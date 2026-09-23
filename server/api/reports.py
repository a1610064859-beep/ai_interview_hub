import logging
from fastapi import APIRouter, HTTPException, Path

from server.db import SessionLocal
from server.models import Job, Report, Session
from server.schemas import ReportResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/{sid}", response_model=ReportResponse)
def get_report(sid: int = Path(..., ge=1)):
    with SessionLocal() as db:
        sess = db.query(Session).filter(Session.id == sid).first()
        if not sess:
            raise HTTPException(
                status_code=404,
                detail={"code": "SESSION_NOT_FOUND", "message": "面试会话不存在"},
            )

        report = (
            db.query(Report)
            .filter(Report.session_id == sid)
            .order_by(Report.id.desc())
            .first()
        )
        if not report:
            raise HTTPException(
                status_code=404,
                detail={"code": "REPORT_NOT_FOUND", "message": "报告尚未生成"},
            )

        job = db.query(Job).filter(Job.id == sess.job_id).first()
        job_title = job.title if job else "未知岗位"

        return ReportResponse(
            id=report.id,
            session_id=report.session_id,
            job_title=job_title,
            overall=report.overall,
            dimensions=report.dimensions_json,
            highlights=report.highlights_json or [],
            concerns=report.concerns_json or [],
            improvement=report.improvement_json or [],
        )
