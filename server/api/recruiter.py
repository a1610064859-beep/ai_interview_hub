"""企业端 API：同源候选查询。"""
from fastapi import APIRouter, Depends, HTTPException, Query

from server.api.auth import require_recruiter
from server.db import SessionLocal
from server.schemas import CandidatesResponse
from server.services import recruiter as recruiter_service
from server.services.recruiter import JobWeightsInvalid

router = APIRouter(prefix="/api/recruiter", tags=["recruiter"], dependencies=[Depends(require_recruiter)])


@router.get("/candidates", response_model=CandidatesResponse)
def list_candidates(
    job_id: int = Query(..., ge=1),
    input_mode: str | None = Query(None),
    scoring_version: str | None = Query(None),
) -> CandidatesResponse:
    if (input_mode is None) ^ (scoring_version is None):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "COHORT_PAIR_REQUIRED",
                "message": "input_mode 与 scoring_version 必须同时提供或同时省略",
            },
        )
    if input_mode is not None and input_mode not in ("text", "voice"):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_INPUT_MODE",
                "message": "input_mode 只能是 text 或 voice",
            },
        )
    if scoring_version is not None:
        scoring_version = scoring_version.strip()
        if not scoring_version:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "INVALID_SCORING_VERSION",
                    "message": "scoring_version 不能为空",
                },
            )

    with SessionLocal() as db:
        try:
            return recruiter_service.build_candidates_response(
                db,
                job_id=job_id,
                input_mode=input_mode,
                scoring_version=scoring_version,
            )
        except LookupError:
            raise HTTPException(
                status_code=404,
                detail={"code": "JOB_NOT_FOUND", "message": "岗位不存在"},
            )
        except JobWeightsInvalid:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "JOB_WEIGHTS_INVALID",
                    "message": "岗位 dims_json 权重缺失或非法",
                },
            )
