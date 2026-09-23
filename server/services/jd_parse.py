"""JD 解析：绑定现有种子岗的受控草案，禁止写库扩岗。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from server.services.llm import LLMError, chat_json


class JdParseUnavailableError(Exception):
    """JD 解析主备链均失败。"""


class JdQuestionDraft(BaseModel):
    type: Literal["通用", "专业", "情景"]
    text: str = Field(..., min_length=1)


class JdParseDraft(BaseModel):
    dims: list[str] = Field(..., min_length=1, max_length=5)
    questions: list[JdQuestionDraft] = Field(..., min_length=8, max_length=11)
    terms: list[str] = Field(default_factory=list)


def _build_messages(jd_text: str, job_title: str, jd_digest: str | None) -> list[dict]:
    system = (
        "你是智能汽车产业招聘专家。请根据给定 JD 文本，为【已存在的种子岗位】生成评估草案 JSON。"
        "不要假设会新建岗位。输出字段：\n"
        "- dims: 评估维度中文名列表，1–5 项\n"
        "- questions: 8–11 道面试题，每题含 type(通用|专业|情景) 与 text\n"
        "- terms: 专业术语字符串列表\n"
        "只输出 JSON 对象。"
    )
    user = (
        f"【绑定岗位】{job_title}\n"
        f"【岗位现有 JD 摘要】{jd_digest or '（无）'}\n\n"
        f"【待解析 JD 文本】\n{jd_text}\n"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


async def parse_jd_draft(
    *,
    jd_text: str,
    job_title: str,
    jd_digest: str | None,
) -> JdParseDraft:
    messages = _build_messages(jd_text, job_title, jd_digest)
    try:
        return await chat_json("jd", messages, JdParseDraft)
    except LLMError as exc:
        raise JdParseUnavailableError(str(exc)) from exc
