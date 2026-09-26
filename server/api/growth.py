from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from server.api.auth import require_current_user, require_student
from server.config import settings
from server.db import SessionLocal
from server.schemas import (
    GrowthHistoryResponse,
    GrowthTrendResponse,
    StudentListResponse,
)
from server.services import growth as growth_service

router = APIRouter(tags=["growth"], dependencies=[Depends(require_current_user)])


def _ensure_growth_owner(request: Request, user_id: int) -> None:
    if not settings.auth_required:
        return
    current_user = getattr(request.state, "current_user", None)
    if current_user is None or current_user.role != "student":
        raise HTTPException(status_code=403, detail={"code": "ROLE_FORBIDDEN", "message": "仅学生可查看成长记录"})
    if current_user.id != user_id:
        raise HTTPException(status_code=404, detail={"code": "USER_NOT_FOUND", "message": "学生档案不存在"})


def _http_lookup(err: LookupError) -> HTTPException:
    code = str(err)
    if code == "USER_NOT_FOUND":
        return HTTPException(
            status_code=404,
            detail={"code": "USER_NOT_FOUND", "message": "学生档案不存在"},
        )
    if code == "JOB_NOT_FOUND":
        return HTTPException(
            status_code=404,
            detail={"code": "JOB_NOT_FOUND", "message": "岗位不存在"},
        )
    return HTTPException(status_code=404, detail={"code": code, "message": code})


@router.get("/api/students", response_model=StudentListResponse)
def list_students(request: Request):
    with SessionLocal() as db:
        current_user = getattr(request.state, "current_user", None)
        students = (
            [current_user]
            if settings.auth_required and current_user is not None and current_user.role == "student"
            else growth_service.list_students(db)
        )
        return {
            "students": [
                {
                    "id": u.id,
                    "name_masked": u.name_masked,
                    "major": u.major,
                    "grade": u.grade,
                    "student_no": u.student_no,
                    "education_level": u.education_level,
                    "school_tier": u.school_tier,
                    "has_resume": bool(u.resume_storage_key),
                }
                for u in students
            ]
        }


@router.get(
    "/api/growth/{user_id}/history",
    response_model=GrowthHistoryResponse,
    dependencies=[Depends(require_student)],
)
def get_growth_history(
    request: Request,
    user_id: int = Path(..., ge=1),
    job_id: int | None = Query(default=None, ge=1),
):
    _ensure_growth_owner(request, user_id)
    with SessionLocal() as db:
        try:
            return growth_service.build_history(db, user_id, job_id)
        except LookupError as exc:
            raise _http_lookup(exc) from exc


@router.get(
    "/api/growth/{user_id}/trend",
    response_model=GrowthTrendResponse,
    dependencies=[Depends(require_student)],
)
def get_growth_trend(
    request: Request,
    user_id: int = Path(..., ge=1),
    job_id: int = Query(..., ge=1),
):
    _ensure_growth_owner(request, user_id)
    with SessionLocal() as db:
        try:
            return growth_service.build_trend(db, user_id, job_id)
        except LookupError as exc:
            raise _http_lookup(exc) from exc
