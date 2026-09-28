import json
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


class AnswerFeedbackResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer_id: int
    q_seq: int
    is_followup: bool
    question_text: str
    feedback: AnswerFeedbackLlmResponse


_SYSTEM_PROMPT = """你是面向智能汽车岗位新生的面试练习教练。只分析本题回答内容，不评估语速、停顿、口音、声音或其他语音表现。
给出 0-100 的单题练习分；它只是练习反馈，不是正式面试报告分数。评分参考切题度、专业准确性、逻辑结构、具体行动与结果；约 50 分表示有回应但内容笼统，70 分表示基本切题且有做法，85 分以上要求准确、具体并有清楚依据。指出回答中具体的问题和一条可执行的改进建议。
evidence_quote 必须是回答原文中连续且完全一致的 1-25 个字符；无法找到可靠原文依据时 practice_score 和 evidence_quote 都返回 null，并给出通用学习提示。
learning_topic 只能使用 hear、star、intro、followup、unknown、review 之一：分别表示理解题意、STAR结构、自我介绍、追问应答、暂无法分类、复盘。
对文本转写不可推断语速、停顿、口头表达流畅度。不要重复题目，不要编造回答中没有的经历或事实。"""


def _fallback(is_followup: bool) -> AnswerFeedbackLlmResponse:
    topic: LearningTopic = "followup" if is_followup else "unknown"
    return AnswerFeedbackLlmResponse(
        practice_score=None,
        problem_analysis="暂无法可靠评价本题回答。建议先确认回答直接回应了题目，并整理出关键做法与结果。",
        evidence_quote=None,
        improvement_suggestion="用一两句话说明你采取的行动和可验证的结果，再尝试回答本题。",
        learning_topic=topic,
    )


async def evaluate_answer(
    *, question_text: str, answer_text: str, is_followup: bool
) -> AnswerFeedbackLlmResponse:
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
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            AnswerFeedbackLlmResponse,
        )
    except Exception:
        return _fallback(is_followup)

    quote = result.evidence_quote
    reliable_quote = bool(
        quote and 1 <= len(quote) <= 25 and quote in answer_text
    )
    if result.practice_score is None or not reliable_quote:
        return _fallback(is_followup)
    return result
