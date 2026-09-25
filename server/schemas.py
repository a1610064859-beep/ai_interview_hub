from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator


class QuestionResponse(BaseModel):
    text: str
    audio_url: str | None = None
    seq: int


class SessionStateResponse(BaseModel):
    sid: int
    status: str
    answer_count: int
    question: QuestionResponse | None
    is_followup: bool
    report_id: int | None


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
    student_no: str | None = None
    education_level: str | None = None
    has_resume: bool = False


class StudentListResponse(BaseModel):
    students: list[StudentItem]


class StudentProfileResponse(StudentItem):
    internship_experience: str | None = None
    awards: str | None = None
    resume_filename: str | None = None


class StudentImportResponse(BaseModel):
    created: int
    updated: int
    total: int


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
    student_no: str | None = None
    education_level: str | None = None
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
class CounselRequest(BaseModel):
    major: str = Field(..., min_length=1, max_length=64)
    grade: Literal["大一", "大二", "大三", "大四"]
    interests: list[str] = Field(..., min_length=0, max_length=8)
    model_config = ConfigDict(extra="forbid")

    @field_validator("major")
    @classmethod
    def clean_major(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("major must not be blank")
        return value

    @field_validator("interests")
    @classmethod
    def clean_interests(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value or len(value) > 32 for value in cleaned):
            raise ValueError("each interest must contain 1-32 characters")
        return cleaned


class CounselJobMapItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: int = Field(..., ge=1)
    family: str = Field(..., min_length=1, max_length=32)
    title: str = Field(..., min_length=1, max_length=64)
    chain_role: str = Field(..., min_length=1, max_length=128)
    core_skills: list[str] = Field(..., min_length=1, max_length=12)
    fit_summary: str = Field(..., min_length=1, max_length=200)

    @field_validator("core_skills")
    @classmethod
    def clean_core_skills(cls, values: list[str]) -> list[str]:
        cleaned = [v.strip() for v in values]
        if any(not v or len(v) > 64 for v in cleaned):
            raise ValueError("each core_skill must contain 1-64 characters")
        return cleaned


class CounselGapItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: int = Field(..., ge=1)
    skill: str = Field(..., min_length=1, max_length=64)
    current_hint: str = Field(..., min_length=1, max_length=200)
    target_hint: str = Field(..., min_length=1, max_length=200)
    suggested_action: str = Field(..., min_length=1, max_length=200)


class CounselMilestone(BaseModel):
    model_config = ConfigDict(extra="forbid")
    term: str = Field(..., min_length=1, max_length=32)
    items: list[str] = Field(..., min_length=1, max_length=8)

    @field_validator("items")
    @classmethod
    def clean_items(cls, values: list[str]) -> list[str]:
        cleaned = [v.strip() for v in values]
        if any(not v or len(v) > 64 for v in cleaned):
            raise ValueError("each milestone item must contain 1-64 characters")
        return cleaned


class CounselNextGrade(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grade: Literal["大一", "大二", "大三", "大四"]
    focus: str = Field(..., min_length=1, max_length=128)


class CounselLearningPath(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grade: Literal["大一", "大二", "大三", "大四"]
    theme: str = Field(..., min_length=1, max_length=128)
    milestones: list[CounselMilestone] = Field(..., min_length=0, max_length=8)
    next_grades: list[CounselNextGrade] = Field(default_factory=list, max_length=4)


class CounselTrainHint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: int = Field(..., ge=1)
    mode: Literal["新生"]


class CounselLlmResponse(BaseModel):
    """LLM 仅允许受控措辞字段；学习路径一律由静态包构造，不接受 LLM 结构。"""

    model_config = ConfigDict(extra="forbid")
    recommended_job_id: int = Field(..., ge=1)
    fit_summaries: dict[str, str] = Field(default_factory=dict)

    @field_validator("fit_summaries")
    @classmethod
    def clean_fit_summaries(cls, values: dict[str, str]) -> dict[str, str]:
        cleaned: dict[str, str] = {}
        for key, value in values.items():
            text = value.strip()
            if not text:
                continue
            cleaned[str(key)] = text[:200]
        return cleaned


class CounselResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["新生"]
    degraded: bool
    job_map: list[CounselJobMapItem] = Field(..., min_length=2, max_length=2)
    gaps: list[CounselGapItem] = Field(..., min_length=0, max_length=16)
    learning_path: CounselLearningPath
    recommended_job_id: int = Field(..., ge=1)
    train_hint: CounselTrainHint
