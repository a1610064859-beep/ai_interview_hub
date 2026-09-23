from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator


class QuestionResponse(BaseModel):
    text: str
    audio_url: str | None = None
    seq: int


class SessionCreateRequest(BaseModel):
    job_id: int = Field(..., ge=1)
    user_id: int = Field(..., ge=1)
    mode: Literal["毕业生", "新生"]
    model_config = ConfigDict(extra="forbid")


class SessionCreateResponse(BaseModel):
    sid: int
    question: QuestionResponse
    transition_audio_urls: list[str] = Field(default_factory=list)


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
    transition_audio_url: str | None = None


class NextAnswerResponse(BaseModel):
    type: Literal["next"] = "next"
    question: QuestionResponse
    transition_audio_url: str | None = None


class DoneAnswerResponse(BaseModel):
    type: Literal["done"] = "done"
    report_id: int
    transition_audio_url: str | None = None


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


class StudentItem(BaseModel):
    id: int
    name_masked: str | None = None
    major: str | None = None
    grade: str | None = None


class StudentListResponse(BaseModel):
    students: list[StudentItem]


class GrowthHistoryRecord(BaseModel):
    session_id: int
    report_id: int
    job_id: int
    job_title: str
    started_at: str | None = None
    mode: str
    input_mode: str | None = None
    scoring_version: str | None = None
    overall: float | None = None
    dimensions: dict[str, float | None]
    improvement: list[str] = Field(default_factory=list)


class GrowthHistoryResponse(BaseModel):
    user_id: int
    job_id: int | None = None
    records: list[GrowthHistoryRecord]


class GrowthTrendPoint(BaseModel):
    session_id: int
    report_id: int
    started_at: str | None = None
    overall: float | None = None
    dimensions: dict[str, float | None]


class OverallSide(BaseModel):
    session_id: int
    overall: float | None = None


class OverallComparison(BaseModel):
    comparable: bool
    reasons: list[str] = Field(default_factory=list)
    message: str | None = None
    previous: OverallSide | None = None
    current: OverallSide | None = None
    delta: float | None = None


class DimensionChange(BaseModel):
    previous: float
    current: float
    delta: float


class GrowthTrendResponse(BaseModel):
    user_id: int
    job_id: int
    job_title: str
    input_mode: str | None = None
    sessions_count: int
    points: list[GrowthTrendPoint]
    overall_comparison: OverallComparison
    dimension_changes: dict[str, DimensionChange | None]


class JobParseRequest(BaseModel):
    job_id: int = Field(..., ge=1)
    jd_text: str = Field(...)
    model_config = ConfigDict(extra="forbid")

    @field_validator("jd_text")
    @classmethod
    def validate_jd_text(cls, v: str) -> str:
        stripped = v.strip()
        if not (20 <= len(stripped) <= 20000):
            raise ValueError("jd_text 去除首尾空白后长度必须在 20 至 20000 字符之间")
        return stripped


class JdQuestionItem(BaseModel):
    type: Literal["通用", "专业", "情景"]
    text: str


class JobParseResponse(BaseModel):
    job_id: int
    job_id_source: Literal["request_binding"] = "request_binding"
    applied: Literal[False] = False
    dims: list[str]
    questions: list[JdQuestionItem]
    terms: list[str]


class RecruiterCohort(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_mode: Literal["text", "voice"]
    scoring_version: str


class RecruiterWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scheme: Literal["job_dims_renorm"] = "job_dims_renorm"
    professional_match: float
    logic_structure: float
    expression_fluency: float
    job_competence: float


class CandidateDimensionScore(BaseModel):
    model_config = ConfigDict(extra="forbid")
    score: float | None = None
    evidence: str | None = None
    reason: str


class CandidateItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int
    name_masked: str | None = None
    major: str | None = None
    grade: str | None = None
    session_id: int
    report_id: int
    job_id: int
    input_mode: str
    scoring_version: str
    trained_at: str | None = None
    overall: float | None = None
    weighted_score: float | None = None
    valid_dim_count: int = Field(..., ge=0, le=4)
    dimensions: dict[str, CandidateDimensionScore]
    report_path: str


class CandidatesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: int
    job_title: str
    cohort: RecruiterCohort | None = None
    available_cohorts: list[RecruiterCohort]
    weights: RecruiterWeights | None = None
    weights_error: Literal["JOB_WEIGHTS_INVALID"] | None = None
    eligibility: Literal["min_valid_dims_3"]
    candidates: list[CandidateItem]
