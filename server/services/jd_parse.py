"""Parse JD drafts and create validated question sets for recruiter-created jobs."""
from __future__ import annotations

from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from server.services.llm import LLMError, chat_json


class JdParseUnavailableError(Exception):
    """JD 解析主备链均失败。"""


class JdQuestionDraft(BaseModel):
    type: Literal["通用", "专业", "情景"]
    text: str = Field(..., min_length=1, max_length=500)


class JdParseDraft(BaseModel):
    dims: list[str] = Field(..., min_length=1, max_length=5)
    questions: list[JdQuestionDraft] = Field(..., min_length=8, max_length=11)
    terms: list[str] = Field(default_factory=list)


class JdJobCreateDraft(JdParseDraft):
    family: str = Field(..., min_length=1, max_length=128)
    title: str = Field(..., min_length=1, max_length=128)

    @field_validator("family", "title", mode="before")
    @classmethod
    def normalize_job_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_interview_question_mix(self):
        counts = Counter(question.type for question in self.questions)
        required = {"通用": 2, "专业": 3, "情景": 1}
        if any(counts[kind] < count for kind, count in required.items()):
            raise ValueError("questions 至少需要 2 道通用题、3 道专业题和 1 道情景题")
        if any(len(question.text.strip()) < 5 for question in self.questions):
            raise ValueError("每道面试题至少需要 5 个字符")
        return self


def _build_messages(
    jd_text: str,
    job_title: str | None = None,
    jd_digest: str | None = None,
    *,
    create_job: bool = False,
) -> list[dict]:
    if create_job:
        system = (
            "你是智能汽车产业招聘专家。请根据给定 JD 文本生成一个新岗位及题库草案。输出字段：\n"
            "- family: 岗位所属产业族，简洁中文名称\n"
            "- title: JD 对应的岗位名称，简洁中文名称\n"
            "- dims: JD 建议评估维度中文名列表，1–5 项\n"
            "- questions: 8–11 道面试题，每题含 type(通用|专业|情景) 与 text；至少含 2 道通用题、3 道专业题、1 道情景题\n"
            "- terms: 专业术语字符串列表\n"
            "只输出 JSON 对象。"
        )
    else:
        system = (
            "你是智能汽车产业招聘专家。请根据给定 JD 文本，为【已存在的种子岗位】生成评估草案 JSON。"
            "不要假设会新建岗位。输出字段：\n"
            "- dims: 评估维度中文名列表，1–5 项\n"
            "- questions: 8–11 道面试题，每题含 type(通用|专业|情景) 与 text\n"
            "- terms: 专业术语字符串列表\n"
            "只输出 JSON 对象。"
        )
    context = ""
    if job_title:
        context += f"【可参考岗位】{job_title}\n"
    if jd_digest:
        context += f"【岗位现有 JD 摘要】{jd_digest}\n"
    user = (
        f"{context}\n【待解析 JD 文本】\n{jd_text}\n"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


async def parse_jd_draft(
    *,
    jd_text: str,
    job_title: str | None = None,
    jd_digest: str | None = None,
) -> JdParseDraft:
    messages = _build_messages(jd_text, job_title, jd_digest)
    try:
        return await chat_json("jd", messages, JdParseDraft)
    except LLMError as exc:
        raise JdParseUnavailableError(str(exc)) from exc


async def parse_new_job_draft(*, jd_text: str) -> JdJobCreateDraft:
    messages = _build_messages(jd_text, create_job=True)
    try:
        return await chat_json("jd", messages, JdJobCreateDraft)
    except LLMError as exc:
        raise JdParseUnavailableError(str(exc)) from exc
