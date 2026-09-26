from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from server.db import SessionLocal
from server.api.auth import require_recruiter
from server.models import Job, Question, Session as InterviewSession
from server.schemas import (
    JobCreateFromJDRequest,
    JobCreateFromJDResponse,
    JobParseRequest,
    JobParseResponse,
    JdQuestionItem,
)
from server.services.jd_parse import JdParseUnavailableError, parse_jd_draft, parse_new_job_draft
from server.services.question_bank import (
    INTERVIEW_QUESTION_COUNTS,
    QuestionBankIncompleteError,
    active_question_ids,
)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

DEFAULT_JOB_DIMS = {
    "labels": ["专业匹配度", "逻辑结构", "表达流畅度", "岗位素养"],
    "weights": {
        "professional_match": 0.25,
        "logic_structure": 0.25,
        "expression_fluency": 0.25,
        "job_competence": 0.25,
    },
}


class QuestionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["通用", "专业", "情景"]
    text: str = Field(..., min_length=5, max_length=500)
    followup_hint: str | None = Field(default=None, max_length=1000)

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("followup_hint", mode="before")
    @classmethod
    def normalize_followup_hint(cls, value):
        return value.strip() or None if isinstance(value, str) else value


class QuestionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(..., min_length=5, max_length=500)
    followup_hint: str | None = Field(default=None, max_length=1000)

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("followup_hint", mode="before")
    @classmethod
    def normalize_followup_hint(cls, value):
        return value.strip() or None if isinstance(value, str) else value


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("")
def list_jobs(db: Session = Depends(get_db)):
    jobs = db.query(Job).order_by(Job.id.asc()).all()
    return {
        "jobs": [
            {
                "id": j.id,
                "family": j.family,
                "title": j.title,
                "jd_digest": j.jd_digest,
            }
            for j in jobs
        ]
    }


@router.post("/parse", response_model=JobParseResponse)
async def parse_job_jd(
    req: JobParseRequest,
    db: Session = Depends(get_db),
    _recruiter=Depends(require_recruiter),
):
    job = db.query(Job).filter(Job.id == req.job_id).first()
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "JOB_NOT_FOUND", "message": "岗位不存在"},
        )

    before_job_count = db.query(Job).count()
    before_q_count = db.query(Question).filter(Question.job_id == job.id).count()
    before_digest = job.jd_digest
    before_terms = job.terms_json
    before_dims = job.dims_json

    try:
        draft = await parse_jd_draft(
            jd_text=req.jd_text,
            job_title=job.title,
            jd_digest=job.jd_digest,
        )
    except JdParseUnavailableError:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "JD_PARSE_UNAVAILABLE",
                "message": "JD 解析服务暂时不可用，请稍后重试",
            },
        )

    db.refresh(job)
    if (
        db.query(Job).count() != before_job_count
        or db.query(Question).filter(Question.job_id == job.id).count() != before_q_count
        or job.jd_digest != before_digest
        or job.terms_json != before_terms
        or job.dims_json != before_dims
    ):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "JD_PARSE_UNAVAILABLE",
                "message": "JD 解析未写库约束被破坏",
            },
        )

    return JobParseResponse(
        job_id=req.job_id,
        job_id_source="request_binding",
        applied=False,
        dims=draft.dims,
        questions=[JdQuestionItem(type=q.type, text=q.text) for q in draft.questions],
        terms=list(draft.terms),
    )


@router.get("/{job_id}/questions")
def list_job_questions(job_id: int = Path(..., ge=1), db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "JOB_NOT_FOUND", "message": "岗位不存在"},
        )

    questions = (
        db.query(Question)
        .filter(Question.job_id == job_id)
        .order_by(Question.id.asc())
        .all()
    )


    try:
        selected_ids = active_question_ids(db, job_id)
    except QuestionBankIncompleteError:
        selected_ids = set()
    return {
        "job_id": job_id,
        "questions": [
            {
                "id": q.id,
                "type": q.type,
                "text": q.text,
                "followup_hint": q.followup_hint,
                "active_for_interview": q.id in selected_ids,
            }
            for q in questions
        ],
    }


def _ensure_job_exists(db: Session, job_id: int) -> Job:
    job = db.query(Job).filter(Job.id == job_id).first()
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "JOB_NOT_FOUND", "message": "岗位不存在"},
        )
    return job


def _ensure_question_bank_mutable(db: Session, job_id: int) -> None:
    active_session = (
        db.query(InterviewSession.id)
        .filter(InterviewSession.job_id == job_id, InterviewSession.status == "active")
        .first()
    )
    if active_session:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "QUESTION_BANK_IN_USE",
                "message": "该岗位有正在进行的面试，请结束后再修改题库",
            },
        )


def _question_payload(question: Question, active_ids: set[int]) -> dict:
    return {
        "id": question.id,
        "job_id": question.job_id,
        "type": question.type,
        "text": question.text,
        "followup_hint": question.followup_hint,
        "active_for_interview": question.id in active_ids,
    }


@router.post("/{job_id}/questions", status_code=201)
def add_job_question(
    request: QuestionCreateRequest,
    job_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _recruiter=Depends(require_recruiter),
):
    _ensure_job_exists(db, job_id)
    _ensure_question_bank_mutable(db, job_id)
    question = Question(
        job_id=job_id,
        type=request.type,
        text=request.text,
        followup_hint=request.followup_hint,
    )
    db.add(question)
    db.commit()
    db.refresh(question)
    return _question_payload(question, active_question_ids(db, job_id))


@router.put("/{job_id}/questions/{question_id}")
def update_job_question(
    request: QuestionUpdateRequest,
    job_id: int = Path(..., ge=1),
    question_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _recruiter=Depends(require_recruiter),
):
    _ensure_job_exists(db, job_id)
    _ensure_question_bank_mutable(db, job_id)
    question = (
        db.query(Question)
        .filter(Question.id == question_id, Question.job_id == job_id)
        .first()
    )
    if question is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "QUESTION_NOT_FOUND", "message": "题目不存在"},
        )
    question.text = request.text
    question.followup_hint = request.followup_hint
    db.commit()
    db.refresh(question)
    return _question_payload(question, active_question_ids(db, job_id))


@router.delete("/{job_id}/questions/{question_id}", status_code=204)
def delete_job_question(
    job_id: int = Path(..., ge=1),
    question_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _recruiter=Depends(require_recruiter),
):
    _ensure_job_exists(db, job_id)
    _ensure_question_bank_mutable(db, job_id)
    question = (
        db.query(Question)
        .filter(Question.id == question_id, Question.job_id == job_id)
        .first()
    )
    if question is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "QUESTION_NOT_FOUND", "message": "题目不存在"},
        )
    minimum = INTERVIEW_QUESTION_COUNTS.get(question.type)
    current_count = (
        db.query(Question)
        .filter(Question.job_id == job_id, Question.type == question.type)
        .count()
    )
    if minimum is None or current_count <= minimum:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "QUESTION_BANK_MINIMUM_REQUIRED",
                "message": f"每个岗位至少保留{INTERVIEW_QUESTION_COUNTS.get(question.type, 0)}道{question.type}题",
            },
        )
    db.delete(question)
    db.commit()
    return Response(status_code=204)


@router.post("/create-from-jd", response_model=JobCreateFromJDResponse, status_code=201)
async def create_job_from_jd(
    req: JobCreateFromJDRequest,
    db: Session = Depends(get_db),
    _recruiter=Depends(require_recruiter),
):
    try:
        draft = await parse_new_job_draft(jd_text=req.jd_text)
    except JdParseUnavailableError:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "JD_PARSE_UNAVAILABLE",
                "message": "JD 解析服务暂时不可用，请稍后重试",
            },
        )

    job = Job(
        family=draft.family,
        title=draft.title,
        jd_digest=req.jd_text,
        terms_json=list(draft.terms),
        dims_json=DEFAULT_JOB_DIMS,
    )
    try:
        db.add(job)
        db.flush()
        db.add_all(
            [
                Question(job_id=job.id, type=question.type, text=question.text)
                for question in draft.questions
            ]
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail={
                "code": "JOB_CREATE_FAILED",
                "message": "岗位及题库保存失败，请重试",
            },
        ) from exc

    return JobCreateFromJDResponse(
        job_id=job.id,
        family=job.family,
        title=job.title,
        dims=draft.dims,
        questions=[JdQuestionItem(type=q.type, text=q.text) for q in draft.questions],
        terms=list(draft.terms),
    )
