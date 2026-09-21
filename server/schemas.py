from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator


class QuestionResponse(BaseModel):
    text: str
    audio_url: str | None = None
    seq: int


class SessionCreateRequest(BaseModel):
    job_id: int = Field(..., ge=1)
    model_config = ConfigDict(extra="forbid")


class SessionCreateResponse(BaseModel):
    sid: int
    question: QuestionResponse


class TextAnswerRequest(BaseModel):
    answer_text: str = Field(...)
    model_config = ConfigDict(extra="forbid")

    @field_validator("answer_text")
    @classmethod
    def validate_answer_text(cls, v: str) -> str:
        stripped = v.strip()
        if not (1 <= len(stripped) <= 5000):
            raise ValueError("answer_text 去除首尾空白后长度必须在 1 至 5000 字符之间")
        return stripped


class FollowupAnswerResponse(BaseModel):
    type: Literal["followup"] = "followup"
    question: QuestionResponse


class NextAnswerResponse(BaseModel):
    type: Literal["next"] = "next"
    question: QuestionResponse


class DoneAnswerResponse(BaseModel):
    type: Literal["done"] = "done"
    report_id: int


AnswerResponse = Annotated[
    Union[FollowupAnswerResponse, NextAnswerResponse, DoneAnswerResponse],
    Field(discriminator="type"),
]


class DimensionScore(BaseModel):
    score: float | None = None
    evidence: str | None = None
    reason: str


class ReportResponse(BaseModel):
    id: int
    session_id: int
    job_title: str
    overall: float | None = None
    dimensions: dict[str, DimensionScore]
    highlights: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    improvement: list[str] = Field(default_factory=list)
