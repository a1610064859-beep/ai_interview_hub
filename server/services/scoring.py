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


# 表达流畅度确定性量化规则（T5-FIX；无 LLM 参与）
WPM_NORMAL_LOW = 220.0        # 正常语速区间下限（字/分）
WPM_NORMAL_HIGH = 280.0       # 正常语速区间上限（字/分）
WPM_PENALTY_PER_UNIT = 0.2    # 每偏离 1 字/分 扣 0.2 分
WPM_PENALTY_CAP = 40.0
PAUSE_FREE_PER_MIN = 6.0      # 每分钟停顿 ≤6 次不扣分
PAUSE_PENALTY_PER_UNIT = 2.0  # 超出部分每次扣 2 分（按每分钟归一化）
PAUSE_PENALTY_CAP = 30.0
FILLER_FREE_PER_MIN = 5.0     # 每分钟填充词 ≤5 个不扣分
FILLER_PENALTY_PER_UNIT = 3.0 # 超出部分每个扣 3 分（按每分钟归一化）
FILLER_PENALTY_CAP = 30.0


def compute_acoustic_fluency(samples: list[dict]) -> dict:
    """基于声学特征（语速/停顿/填充词）的确定性表达流畅度评分，可独立单测。

    samples：每条语音回答一条记录 {duration_s, wpm, pause_cnt, filler_cnt}；
    只统计声学字段完整的记录，停顿/填充词按时长归一化为每分钟频率，
    避免长回答天然吃亏；语速按时长加权平均。
    声学数据不足（无完整记录）时 score=None，绝不虚构评分；
    evidence 恒为 None：声学数字不得冒充原文引用，无合法原文引用时按契约置空。
    """
    complete = [
        s for s in (samples or [])
        if s.get("duration_s") is not None and float(s["duration_s"]) > 0
        and s.get("wpm") is not None
        and s.get("pause_cnt") is not None
        and s.get("filler_cnt") is not None
    ]
    if not complete:
        return {
            "score": None,
            "evidence": None,
            "reason": "声学数据不足（缺少时长/语速/停顿/填充词的完整记录），未评估表达流畅度",
        }

    total_duration = sum(Decimal(str(s["duration_s"])) for s in complete)
    wpm = float(
        sum(Decimal(str(s["wpm"])) * Decimal(str(s["duration_s"])) for s in complete)
        / total_duration
    )
    pause_per_min = float(
        sum(Decimal(str(s["pause_cnt"])) for s in complete) * 60 / total_duration
    )
    filler_per_min = float(
        sum(Decimal(str(s["filler_cnt"])) for s in complete) * 60 / total_duration
    )

    wpm_dev = max(0.0, WPM_NORMAL_LOW - wpm, wpm - WPM_NORMAL_HIGH)
    wpm_penalty = min(WPM_PENALTY_CAP, wpm_dev * WPM_PENALTY_PER_UNIT)
    pause_penalty = min(
        PAUSE_PENALTY_CAP, max(0.0, pause_per_min - PAUSE_FREE_PER_MIN) * PAUSE_PENALTY_PER_UNIT
    )
    filler_penalty = min(
        FILLER_PENALTY_CAP, max(0.0, filler_per_min - FILLER_FREE_PER_MIN) * FILLER_PENALTY_PER_UNIT
    )

    score = max(0.0, 100.0 - wpm_penalty - pause_penalty - filler_penalty)
    score = float(Decimal(str(score)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))

    reason = (
        f"语速{wpm:.0f}字/分（正常区间220-280，扣{wpm_penalty:.1f}分），"
        f"停顿{pause_per_min:.1f}次/分（≤6次/分不扣分，扣{pause_penalty:.1f}分），"
        f"填充词{filler_per_min:.1f}个/分（≤5个/分不扣分，扣{filler_penalty:.1f}分），"
        f"共{len(complete)}条有效语音回答"
    )
    return {"score": score, "evidence": None, "reason": reason}


async def call_scoring_llm(messages: list, answers: list[str]) -> SingleScoringResult:
    """单次调用评分模型并按维度校验证据合规性：
    1. 某维度证据无效时发起一次性针对性重试（一次修正请求同时修正全部无效维度）；
    2. 重试后依然不合规的维度置为 None，逐维保留其余有效维度；
    3. 真正底层 LLM 模型调用失败时向外抛出异常。
    """
    for attempt in range(2):
        res = await chat_json("scoring", messages, SingleScoringResult)

        # 逐维核对 evidence 是否合规
        p_valid = bool(res.professional_match and validate_evidence(res.professional_match.evidence, answers))
        l_valid = bool(res.logic_structure and validate_evidence(res.logic_structure.evidence, answers))
        j_valid = bool(res.job_competence and validate_evidence(res.job_competence.evidence, answers))

        invalid_dims = []
        if res.professional_match and not p_valid:
            invalid_dims.append("professional_match(专业匹配度)")
        if res.logic_structure and not l_valid:
            invalid_dims.append("logic_structure(逻辑结构)")
        if res.job_competence and not j_valid:
            invalid_dims.append("job_competence(岗位素养)")

        # 若全部已评分维度的 evidence 均合规，直接返回
        if not invalid_dims:
            return res

        # 首次调用若存在不合规维度，发起一次性针对性修正重试
        if attempt == 0:
            dims_str = "、".join(invalid_dims)
            messages.append({
                "role": "user",
                "content": (
                    f"请注意：以下维度的 evidence 未通过字面原话校验：{dims_str}。\n"
                    "evidence 必须是候选人某一单条回答正文中出现的字面连续子串（必须与候选人原话完全一致，区分空格且不超过25字），"
                    "严禁修改原字词或跨句拼接。请重新输出完整的评分JSON（一次性修正上述维度的证据与评价）。"
                ),
            })
            continue

        # 重试后依然不合规的维度，逐维置 None 保留其余有效维度
        if res.professional_match and not p_valid:
            res.professional_match = None
        if res.logic_structure and not l_valid:
            res.logic_structure = None
        if res.job_competence and not j_valid:
            res.job_competence = None
        return res

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


async def score_interview(
    answers: list[str],
    job_info: dict,
    mode: str = "text",
    acoustic_samples: Optional[list[dict]] = None,
) -> dict:
    """执行双评并仲裁汇总出最终报告数据：
    1. 逐维保留有效结果；某维缺失仅影响该维；
    2. 两次均无有效证据生成全空报告；
    3. 只有当真正模型链不可用（两次调用均抛出异常）时才报 503 ScoringUnavailableError。
    acoustic_samples：语音模式（mode="voice"）下各语音回答的声学记录
    （{duration_s, wpm, pause_cnt, filler_cnt}），表达流畅度据此确定性量化，无第三次 LLM 调用。
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

    # 表达流畅度：文本模式保持 null；语音模式由确定性声学规则量化（数据不足时同样为 null，不虚构）
    if mode == "text":
        fluency_dim = {
            "score": None,
            "evidence": None,
            "reason": "文本模式，未评估语音流畅度",
        }
    else:
        fluency_dim = compute_acoustic_fluency(acoustic_samples or [])

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
