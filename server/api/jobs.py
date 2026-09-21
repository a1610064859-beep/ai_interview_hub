from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from server.db import SessionLocal
from server.models import Job, Question

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
