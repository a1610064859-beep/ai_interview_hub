import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from server.services.llm import chat_json


LearningTopic = Literal["hear", "star", "intro", "followup", "unknown", "review"]


class AnswerFeedbackLlmResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    practice_score: int | None = Field(default=None, ge=0, le=100)
    problem_analysis: str = Field(min_length=1, max_length=1000)
    evidence_quote: str | None = Field(default=None, max_length=25)
    improvement_suggestion: str = Field(min_length=1, max_length=1000)
    learning_topic: LearningTopic


class AnswerFeedbackResult(AnswerFeedbackLlmResponse):
    evidence_quote: str | None = Field(default=None, max_length=5000)
    basis: Literal["ai", "rule"]


class AnswerFeedbackResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer_id: int
    q_seq: int
    is_followup: bool
    question_text: str
    feedback: AnswerFeedbackResult


_SYSTEM_PROMPT = """你是面向智能汽车岗位新生的面试练习教练。只输出 JSON 对象，不要 Markdown 或额外文字。只分析本题回答内容，不评估语速、停顿、口音、声音或其他语音表现。
JSON 必须且只能包含这 5 个字段：practice_score、problem_analysis、evidence_quote、improvement_suggestion、learning_topic。格式示例：{"practice_score": 50, "problem_analysis": "具体问题", "evidence_quote": "回答中的连续原话", "improvement_suggestion": "一条具体建议", "learning_topic": "intro"}。示例值不能照抄，禁止输出 strengths、issues、improvement 或其他字段。
给出 0-100 的单题练习分；它只是练习反馈，不是正式面试报告分数。评分参考切题度、专业准确性、逻辑结构、具体行动与结果；约 50 分表示有回应但内容笼统，70 分表示基本切题且有做法，85 分以上要求准确、具体并有清楚依据。指出回答中具体的问题和一条可执行的改进建议。
evidence_quote 必须是回答原文中连续且完全一致的 1-25 个字符，可以从 quote_candidate 截取；无法找到可靠原文依据时 practice_score 和 evidence_quote 都返回 null，并给出通用学习提示。
learning_topic 只能使用 hear、star、intro、followup、unknown、review 之一：分别表示理解题意、STAR结构、自我介绍、追问应答、暂无法分类、复盘。
对文本转写不可推断语速、停顿、口头表达流畅度。不要重复题目，不要编造回答中没有的经历或事实。"""


def _complete_evidence_quote(answer_text: str, fragment: str | None) -> str | None:
    """Expand a verified fragment to its containing original sentence."""
    if not fragment:
        return None
    fragment = fragment.strip()
    if not fragment:
        return None
    hit = answer_text.find(fragment)
    if hit < 0:
        return None

    sentence_marks = "。！？\n"
    start = max(answer_text.rfind(mark, 0, hit) for mark in sentence_marks) + 1
    ends = [answer_text.find(mark, hit + len(fragment) - 1) for mark in sentence_marks]
    ends = [position for position in ends if position >= 0]
    end = min(ends) + 1 if ends else len(answer_text)
    quote = answer_text[start:end].strip().strip('“”"‘’')
    return quote if quote and quote in answer_text else fragment


def _fallback(question_text: str, answer_text: str, is_followup: bool) -> AnswerFeedbackResult:
    """Give a bounded structure check when the model cannot assess the answer."""
    answer = answer_text.strip()
    is_intro = any(word in question_text for word in ("介绍", "专业背景", "为什么想"))
    topic: LearningTopic = "followup" if is_followup else ("intro" if is_intro else "star")
    if len(answer) < 8:
        return AnswerFeedbackResult(
            practice_score=None,
            problem_analysis="AI评分暂不可用，且本题回答过短，无法做可靠的结构估分。",
            evidence_quote=None,
            improvement_suggestion="先直接回答题目，再补充一项你亲自完成的行动和结果。",
            learning_topic=topic,
            basis="rule",
        )

    has_background = bool(re.search(r"专业|学校|课程|项目|实习|经历|背景", answer))
    has_action = bool(re.search(r"参与|负责|设计|开发|调试|定位|分析|实现|验证|修复|搭建|优化|解决|复跑|测试了|测试过|进行.{0,4}测试", answer))
    has_result = bool(re.search(r"结果|最终|完成|通过|发现|降低|提高|提升了|减少|准确率|成功|\d+(?:\.\d+)?%", answer))
    has_reason = bool(re.search(r"因为|因此|所以|希望|想从事|感兴趣", answer))
    score = min(75, 30 + 10 * (len(answer) >= 20) + 10 * (len(answer) >= 60)
                + 10 * has_background + 10 * has_action + 10 * has_result + 5 * has_reason)
    quote = _complete_evidence_quote(answer_text, answer[:25]) or answer[:25]
    missing = []
    if is_intro and not has_background:
        missing.append("专业或学习背景")
    if not has_action:
        missing.append("亲自采取的行动")
    if not has_result:
        missing.append("可以验证的结果")
    analysis = "AI评分暂不可用；以下仅按回答文字检查结构，不判断专业内容是否正确。"
    analysis += "目前还缺少" + "、".join(missing) + "。" if missing else "回答已包含背景、行动和结果。"
    suggestion = (
        "按“专业背景→相关经历→个人行动→结果→岗位动机”补充一个具体例子。"
        if is_intro else "按“直接结论→个人行动→结果或验证方式”重述本题，尽量给出具体事实。"
    )
    return AnswerFeedbackResult(
        practice_score=score,
        problem_analysis=analysis,
        evidence_quote=quote,
        improvement_suggestion=suggestion,
        learning_topic=topic,
        basis="rule",
    )


async def evaluate_answer(
    *, question_text: str, answer_text: str, is_followup: bool
) -> AnswerFeedbackResult:
    """Return an ephemeral practice assessment; it is never written to reports."""
    try:
        result = await chat_json(
            "answer_feedback",
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "question": question_text,
                            "answer": answer_text,
                            "is_followup": is_followup,
                            "quote_candidate": answer_text.strip()[:25],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            AnswerFeedbackLlmResponse,
        )
    except Exception:
        return _fallback(question_text, answer_text, is_followup)

    quote = _complete_evidence_quote(answer_text, result.evidence_quote)
    reliable_quote = bool(quote and quote in answer_text)
    if result.practice_score is None or not reliable_quote:
        return _fallback(question_text, answer_text, is_followup)
    return AnswerFeedbackResult(
        **result.model_dump(exclude={"evidence_quote"}),
        evidence_quote=quote,
        basis="ai",
    )
