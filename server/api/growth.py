from fastapi import APIRouter, HTTPException, Path, Query

from server.db import SessionLocal
from server.schemas import (
    GrowthHistoryResponse,
    GrowthTrendResponse,
    StudentListResponse,
)
from server.services import growth as growth_service

router = APIRouter(tags=["growth"])


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
def list_students():
    with SessionLocal() as db:
        students = growth_service.list_students(db)
        return {
            "students": [
                {
                    "id": u.id,
                    "name_masked": u.name_masked,
                    "major": u.major,
                    "grade": u.grade,
                }
                for u in students
            ]
        }


@router.get(
    "/api/growth/{user_id}/history",
    response_model=GrowthHistoryResponse,
)
def get_growth_history(
    user_id: int = Path(..., ge=1),
    job_id: int | None = Query(default=None, ge=1),
):
    with SessionLocal() as db:
        try:
            return growth_service.build_history(db, user_id, job_id)
        except LookupError as exc:
            raise _http_lookup(exc) from exc


@router.get(
    "/api/growth/{user_id}/trend",
    response_model=GrowthTrendResponse,
)
def get_growth_trend(
    user_id: int = Path(..., ge=1),
    job_id: int = Query(..., ge=1),
):
    with SessionLocal() as db:
        try:
            return growth_service.build_trend(db, user_id, job_id)
        except LookupError as exc:
            raise _http_lookup(exc) from exc
