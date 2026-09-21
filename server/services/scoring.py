import asyncio
from decimal import Decimal, ROUND_HALF_UP
import logging
from typing import Optional
from pydantic import BaseModel, Field

from server.services.llm import chat_json, LLMError

logger = logging.getLogger(__name__)


class ScoringUnavailableError(Exception):
    """评分基础设施（主备模型链）全部不可用"""
    pass


class SingleDimensionScore(BaseModel):
    score: float = Field(..., ge=0.0, le=100.0)
    evidence: str = Field(..., min_length=1, max_length=25)
    reason: str


class SingleScoringResult(BaseModel):
    professional_match: Optional[SingleDimensionScore] = None
    logic_structure: Optional[SingleDimensionScore] = None
    job_competence: Optional[SingleDimensionScore] = None
    highlights: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    improvement: list[str] = Field(default_factory=list)


def validate_evidence(evidence: Optional[str], answers: list[str]) -> bool:
    """严格校验引用原话证据：
    1. 空白判断可以使用 strip，但长度及子串匹配必须针对最终返回的原字符串；
    2. 长度在 1..25 之间；
    3. 必须为候选人某一单条回答正文的原文字面连续子串（禁止跨回答拼接，禁止虚构）。
    """
    if not evidence or not isinstance(evidence, str):
        return False
    if not evidence.strip():
        return False
    if not (1 <= len(evidence) <= 25):
        return False
    return any(evidence in ans for ans in answers if ans)


def calculate_dimension_average(
    d1: Optional[SingleDimensionScore],
    d2: Optional[SingleDimensionScore],
) -> tuple[Optional[float], Optional[str], str]:
    """双评均值计算与字段继承：
    1. 两次均有效时，转 Decimal 计算等权均值并 ROUND_HALF_UP 保留 1 位小数；
    2. 固定继承第 1 次调用的 evidence 与 reason；
    3. 任一次无效时，置 score=None, evidence=None, reason="未获得通过校验的双次评分"。
    """
    if d1 is None or d2 is None:
        return None, None, "未获得通过校验的双次评分"

    s1 = Decimal(str(d1.score))
    s2 = Decimal(str(d2.score))
    mean = ((s1 + s2) / Decimal("2")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(mean), d1.evidence, d1.reason


def calculate_overall(dimensions: dict[str, dict]) -> Optional[float]:
    """计算 overall：对所有有效维度等权平均并四舍五入保留 1 位小数；全缺失则返回 None"""
    valid_scores = [
        Decimal(str(d["score"]))
        for d in dimensions.values()
        if d.get("score") is not None
    ]
    if not valid_scores:
        return None

    total = sum(valid_scores)
    mean = (total / Decimal(str(len(valid_scores)))).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    return float(mean)


async def call_scoring_llm(messages: list, answers: list[str]) -> SingleScoringResult:
    """单次调用评分模型并按维度校验证据合规性：
    逐维保留有效结果，某维证据不合规仅置该维为 None，不丢弃整次评分；
    真正底层 LLM 模型调用失败时向外抛出异常。
    """
    res = await chat_json("scoring", messages, SingleScoringResult)
    if res.professional_match and not validate_evidence(res.professional_match.evidence, answers):
        res.professional_match = None
    if res.logic_structure and not validate_evidence(res.logic_structure.evidence, answers):
        res.logic_structure = None
    if res.job_competence and not validate_evidence(res.job_competence.evidence, answers):
        res.job_competence = None
    return res



def build_scoring_prompt(answers: list[str], job_info: dict) -> list[dict]:
    answers_text = "\n".join([f"回答{i+1}: {a}" for i, a in enumerate(answers)])
    system_prompt = (
        "你是一名严谨的智能汽车产业面试考官。请对候选人的全部面试回答进行多维评分，并输出JSON。\n"
        "评分维度包含：\n"
        "1. professional_match (专业匹配度, 0-100)\n"
        "2. logic_structure (逻辑结构, 0-100)\n"
        "3. job_competence (岗位素养, 0-100)\n"
        "每个维度必须提供：\n"
        "- score: 分数 (0-100)\n"
        "- evidence: 引用候选人原话，必须为候选人某一单条回答中的字面连续子串，不超过25字\n"
        "- reason: 详细评价原因\n"
        "此外还需提供 highlights (亮点列表, list[str]), concerns (顾虑点列表, list[str]), improvement (改进建议列表, list[str])。"
    )
    user_content = (
        f"【岗位信息】\n岗位名称: {job_info.get('title', '')}\n"
        f"岗位JD要点: {job_info.get('jd_digest', '')}\n"
        f"专业术语表: {job_info.get('terms', [])}\n\n"
        f"【候选人作答记录】\n{answers_text}\n\n"
        "请严格依据事实打分并输出结构化评分结果。"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


async def score_interview(answers: list[str], job_info: dict, mode: str = "text") -> dict:
    """执行双评并仲裁汇总出最终报告数据：
    1. 逐维保留有效结果；某维缺失仅影响该维；
    2. 两次均无有效证据生成全空报告；
    3. 只有当真正模型链不可用（两次调用均抛出异常）时才报 503 ScoringUnavailableError。
    """
    messages_1 = build_scoring_prompt(answers, job_info)
    messages_2 = build_scoring_prompt(answers, job_info)

    # 尝试并行进行两次独立调用
    results = await asyncio.gather(
        call_scoring_llm(messages_1, answers),
        call_scoring_llm(messages_2, answers),
        return_exceptions=True,
    )

    # 只有底层模型基础设施调用均抛出异常，才判定为基础设施不可用 (503)
    if isinstance(results[0], Exception) and isinstance(results[1], Exception):
        raise ScoringUnavailableError(f"所有评分模型均不可用: {results[0]}, {results[1]}")

    res1 = results[0] if not isinstance(results[0], Exception) else None
    res2 = results[1] if not isinstance(results[1], Exception) else None


    # 计算各维度双评均值
    prof_score, prof_ev, prof_reason = calculate_dimension_average(
        res1.professional_match if res1 else None,
        res2.professional_match if res2 else None,
    )
    logic_score, logic_ev, logic_reason = calculate_dimension_average(
        res1.logic_structure if res1 else None,
        res2.logic_structure if res2 else None,
    )
    comp_score, comp_ev, comp_reason = calculate_dimension_average(
        res1.job_competence if res1 else None,
        res2.job_competence if res2 else None,
    )

    # 表达流畅度在文本模式置为 None
    if mode == "text":
        fluency_dim = {
            "score": None,
            "evidence": None,
            "reason": "文本模式，未评估语音流畅度",
        }
    else:
        fluency_dim = {
            "score": None,
            "evidence": None,
            "reason": "未评估",
        }

    dimensions = {
        "professional_match": {"score": prof_score, "evidence": prof_ev, "reason": prof_reason},
        "logic_structure": {"score": logic_score, "evidence": logic_ev, "reason": logic_reason},
        "expression_fluency": fluency_dim,
        "job_competence": {"score": comp_score, "evidence": comp_ev, "reason": comp_reason},
    }

    overall = calculate_overall(dimensions)

    primary_res = res1 or res2
    highlights = primary_res.highlights if primary_res else []
    concerns = primary_res.concerns if primary_res else []
    improvement = primary_res.improvement if primary_res else []

    return {
        "dimensions": dimensions,
        "highlights": highlights,
        "concerns": concerns,
        "improvement": improvement,
        "overall": overall,
    }
