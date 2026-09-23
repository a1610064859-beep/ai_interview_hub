import json
from pathlib import Path

from sqlalchemy.orm import Session

from server.models import Job
from server.schemas import (
    CounselGapItem,
    CounselJobMapItem,
    CounselLearningPath,
    CounselLlmResponse,
    CounselRequest,
    CounselResponse,
    CounselTrainHint,
)
from server.services.llm import chat_json


STATIC_PATH = Path(__file__).resolve().parents[2] / "data" / "freshman_static.json"
DEFAULT_FIT = "可通过岗位训练进一步了解匹配方向"


def _static_learning_path(static: dict, grade: str) -> CounselLearningPath:
    """学习路径只来自静态包，不接受 LLM 结构。"""
    path = static["paths_by_grade"][grade]
    return CounselLearningPath.model_validate(
        {
            "grade": grade,
            "theme": path["theme"],
            "milestones": path["milestones"],
            "next_grades": path.get("next_grades", []),
        }
    )


def _resolve_fit(result: CounselLlmResponse | None, job_id: int) -> str:
    if result is None:
        return DEFAULT_FIT
    text = result.fit_summaries.get(str(job_id))
    if not text:
        return DEFAULT_FIT
    return text[:200]


async def build_counsel_response(db: Session, request: CounselRequest) -> CounselResponse:
    static = json.loads(STATIC_PATH.read_text(encoding="utf-8"))
    definitions = static["jobs"]
    titles = [item["seed_key"] for item in definitions]
    jobs = db.query(Job).filter(Job.title.in_(titles)).order_by(Job.id).all()
    by_title = {job.title: job for job in jobs}
    if len(jobs) != 2 or any(title not in by_title for title in titles):
        raise LookupError("SEED_JOBS_UNAVAILABLE")

    interest_text = " ".join(request.interests).lower()
    fallback_id = next(
        (
            by_title[item["seed_key"]].id
            for item in definitions
            if any(k.lower() in interest_text for k in item["interest_keywords"])
        ),
        jobs[0].id,
    )

    degraded = False
    result: CounselLlmResponse | None = None
    try:
        raw = await chat_json(
            "counsel",
            [
                {
                    "role": "system",
                    "content": "只在给定两个岗位内组织新生建议，禁止给分或发明岗位。",
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "major": request.major,
                            "grade": request.grade,
                            "interests": request.interests,
                            "jobs": [{"job_id": j.id, "title": j.title} for j in jobs],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            CounselLlmResponse,
        )
        if isinstance(raw, CounselLlmResponse):
            result = raw
        else:
            result = CounselLlmResponse.model_validate(raw)
    except Exception:
        degraded = True
        result = None

    valid_ids = {job.id for job in jobs}
    recommended = (
        result.recommended_job_id
        if result and result.recommended_job_id in valid_ids
        else fallback_id
    )
    if result and result.recommended_job_id not in valid_ids:
        degraded = True

    job_map: list[CounselJobMapItem] = []
    gaps: list[CounselGapItem] = []
    for definition in definitions:
        job = by_title[definition["seed_key"]]
        job_map.append(
            CounselJobMapItem(
                job_id=job.id,
                family=job.family,
                title=job.title,
                chain_role=definition["chain_role"],
                core_skills=definition["core_skills"],
                fit_summary=_resolve_fit(result, job.id),
            )
        )
        for gap in definition["gap_templates"]:
            gaps.append(
                CounselGapItem(
                    job_id=job.id,
                    skill=gap["skill"],
                    current_hint="结合当前课程与项目经历自查",
                    target_hint=gap["target_hint"],
                    suggested_action="完成基础学习后进入面试仓训练并复盘",
                )
            )

    learning_path = _static_learning_path(static, request.grade)
    return CounselResponse(
        mode="新生",
        degraded=degraded,
        job_map=sorted(job_map, key=lambda item: item.job_id),
        gaps=gaps,
        learning_path=learning_path,
        recommended_job_id=recommended,
        train_hint=CounselTrainHint(job_id=recommended, mode="新生"),
    )
