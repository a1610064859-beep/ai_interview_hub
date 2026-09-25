from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from server.api.auth import require_student
from server.db import SessionLocal
from server.schemas import CounselRequest, CounselResponse
from server.services.counsel import build_counsel_response


router = APIRouter(prefix="/api", tags=["counsel"], dependencies=[Depends(require_student)])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/counsel", response_model=CounselResponse)
async def counsel(request: CounselRequest, db: Session = Depends(get_db)):
    try:
        return await build_counsel_response(db, request)
    except LookupError:
        raise HTTPException(status_code=503, detail={"code": "SEED_JOBS_UNAVAILABLE", "message": "种子岗位未就绪"})
