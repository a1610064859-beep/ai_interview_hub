import logging
from typing import Optional
from pydantic import BaseModel, Field

from server.services.llm import chat_json, LLMError

logger = logging.getLogger(__name__)


class FollowupDecision(BaseModel):
    need_followup: bool
    question: Optional[str] = Field(None, description="追问正文，若 need_followup 为 False 则为 None")


async def evaluate_followup(
    question_text: str,
    answer_text: str,
    followup_hint: Optional[str],
    job_info: dict,
) -> Optional[str]:
    """判断是否对当前回答发起追问（每题最多1次，提示词包含严格否定约束）。
    所有异常降级必须静默可用：若 LLM 故障或解析失败，直接返回 None（进入下一题）。
    """
    system_prompt = (
        "你是一名智能汽车产业面试考官。请根据候选人的回答，判断是否需要发起一次深入技术追问。\n"
        "【严格否定约束】\n"
        "1. 禁止评价回答好坏（严禁出现“回答得很好”、“不错”、“欠缺”等评语）；\n"
        "2. 禁止重复原问题；\n"
        "3. 追问正文严格禁止超过一句话；\n"
        "4. 若候选人回答已较完整，或追问价值不大，必须返回 need_followup: false。"
    )
    user_prompt = (
        f"【岗位信息】{job_info.get('title', '')}\n"
        f"【原问题】{question_text}\n"
        f"【追问指引】{followup_hint or '无'}\n"
        f"【候选人回答】{answer_text}\n\n"
        "请判断是否追问，并输出 JSON 格式（need_followup: bool, question: str | null）。"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        decision = await chat_json("followup", messages, FollowupDecision)
        if decision.need_followup and decision.question and decision.question.strip():
            return decision.question.strip()
        return None
    except Exception as e:
        # 所有降级必须静默可用：追问判定失败=直接下一题
        logger.warning("Followup LLM evaluation failed, silently advancing to next question: %s", e)
        return None
