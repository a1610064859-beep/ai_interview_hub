from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from server.db import SessionLocal
from server.models import Job, Question
from server.schemas import JobParseRequest, JobParseResponse, JdQuestionItem
from server.services.jd_parse import JdParseUnavailableError, parse_jd_draft

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


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
async def parse_job_jd(req: JobParseRequest, db: Session = Depends(get_db)):
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
    return {
        "job_id": job_id,
        "questions": [
            {
                "id": q.id,
                "type": q.type,
                "text": q.text,
            }
            for q in questions
        ],
    }
