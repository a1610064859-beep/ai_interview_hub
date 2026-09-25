"""企业端候选聚合：同源 sessions⋈reports，零 LLM。"""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy.orm import Session as DbSession

from server.models import Job, Report, Session, User

DIM_KEYS = (
    "professional_match",
    "logic_structure",
    "expression_fluency",
    "job_competence",
)

ELIGIBILITY = "min_valid_dims_3"
MIN_VALID_DIMS = 3


class JobWeightsInvalid(Exception):
    """jobs.dims_json 缺失或不符合 W2 批准形状。"""


def parse_job_weights(dims_json: Any) -> dict[str, float]:
    """校验并返回四维权重；失败抛 JobWeightsInvalid。"""
    if not isinstance(dims_json, dict):
        raise JobWeightsInvalid("dims_json 必须为对象")
    weights = dims_json.get("weights")
    if not isinstance(weights, dict):
        raise JobWeightsInvalid("dims_json.weights 必须为对象")
    if set(weights.keys()) != set(DIM_KEYS):
        raise JobWeightsInvalid("weights 必须恰好含四维英文键")
    values: dict[str, float] = {}
    total = Decimal("0")
    for key in DIM_KEYS:
        raw = weights[key]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise JobWeightsInvalid(f"权重 {key} 必须为 number")
        val = Decimal(str(raw))
        if val <= 0:
            raise JobWeightsInvalid(f"权重 {key} 必须 > 0")
        values[key] = float(val)
        total += val
    if abs(total - Decimal("1")) > Decimal("0.000001"):
        raise JobWeightsInvalid("权重之和必须为 1.0")
    labels = dims_json.get("labels")
    if labels is not None:
        if not isinstance(labels, list) or len(labels) != 4:
            raise JobWeightsInvalid("labels 若存在长度须为 4")
    return values


def is_valid_dimension_score(score: Any) -> bool:
    """有效维分数：有限 number，且落在 [0, 100]；拒绝 bool / 非数字 / NaN / Inf。"""
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return False
    if not math.isfinite(score):
        return False
    return 0.0 <= float(score) <= 100.0


def valid_dim_count(dimensions: dict | None) -> int:
    if not isinstance(dimensions, dict):
        return 0
    n = 0
    for key in DIM_KEYS:
        cell = dimensions.get(key)
        if isinstance(cell, dict) and is_valid_dimension_score(cell.get("score")):
            n += 1
    return n


def compute_weighted_score(
    dimensions: dict | None, weights: dict[str, float]
) -> float | None:
    if not isinstance(dimensions, dict):
        return None
    parts: list[tuple[Decimal, Decimal]] = []
    for key in DIM_KEYS:
        cell = dimensions.get(key)
        if not isinstance(cell, dict):
            continue
        score = cell.get("score")
        if not is_valid_dimension_score(score):
            continue
        parts.append((Decimal(str(score)), Decimal(str(weights[key]))))
    if not parts:
        return None
    weight_sum = sum(w for _, w in parts)
    if weight_sum == 0:
        return None
    total = sum(s * (w / weight_sum) for s, w in parts)
    return float(total.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _format_started_at(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat(timespec="seconds")
    return str(value)


def list_available_cohorts(db: DbSession, job_id: int) -> list[dict[str, str]]:
    rows = (
        db.query(Session.input_mode, Report.scoring_version)
        .join(Report, Report.session_id == Session.id)
        .join(User, User.id == Session.user_id)
        .filter(
            Session.job_id == job_id,
            Session.status == "completed",
            User.role == "student",
            Session.input_mode.isnot(None),
            Report.scoring_version.isnot(None),
        )
        .distinct()
        .all()
    )
    cohorts = [
        {"input_mode": im, "scoring_version": sv}
        for im, sv in rows
        if im in ("text", "voice") and isinstance(sv, str) and sv
    ]
    cohorts.sort(key=lambda c: (c["input_mode"], c["scoring_version"]))
    return cohorts


def _eligible_reports_for_cohort(
    db: DbSession, job_id: int, input_mode: str, scoring_version: str
) -> list[tuple[Session, Report, User]]:
    return list(
        db.query(Session, Report, User)
        .join(Report, Report.session_id == Session.id)
        .join(User, User.id == Session.user_id)
        .filter(
            Session.job_id == job_id,
            Session.status == "completed",
            User.role == "student",
            Session.input_mode == input_mode,
            Report.scoring_version == scoring_version,
        )
        .order_by(Session.started_at.desc(), Session.id.desc())
        .all()
    )


def pick_latest_eligible_per_user(
    rows: list[tuple[Session, Report, User]],
) -> list[tuple[Session, Report, User]]:
    """按 started_at DESC, id DESC 扫描，每用户取首条 valid_dim_count>=3。"""
    chosen: dict[int, tuple[Session, Report, User]] = {}
    for sess, report, user in rows:
        if user.id in chosen:
            continue
        if valid_dim_count(report.dimensions_json) < MIN_VALID_DIMS:
            continue
        chosen[user.id] = (sess, report, user)
    return list(chosen.values())


def build_candidate_item(
    sess: Session,
    report: Report,
    user: User,
    weights: dict[str, float],
) -> dict:
    raw = report.dimensions_json if isinstance(report.dimensions_json, dict) else {}
    dimensions: dict[str, dict] = {}
    for key in DIM_KEYS:
        cell = raw.get(key)
        if not isinstance(cell, dict):
            dimensions[key] = {
                "score": None,
                "evidence": None,
                "reason": "未评估",
            }
            continue
        score = cell.get("score")
        if not is_valid_dimension_score(score):
            score = None
        evidence = cell.get("evidence")
        if evidence is not None and not isinstance(evidence, str):
            evidence = None
        reason = cell.get("reason")
        if not isinstance(reason, str) or not reason:
            reason = "未评估" if score is None else "—"
        dimensions[key] = {
            "score": float(score) if score is not None else None,
            "evidence": evidence,
            "reason": reason,
        }
    return {
        "user_id": user.id,
        "name_masked": user.name_masked,
        "major": user.major,
        "grade": user.grade,
        "student_no": user.student_no,
        "education_level": user.education_level,
        "session_id": sess.id,
        "report_id": report.id,
        "job_id": sess.job_id,
        "input_mode": sess.input_mode,
        "scoring_version": report.scoring_version,
        "trained_at": _format_started_at(sess.started_at),
        "overall": report.overall,
        "dimensions": dimensions,
        "valid_dim_count": valid_dim_count(raw),
        "weighted_score": compute_weighted_score(raw, weights),
        "report_path": f"/reports/{sess.id}",
    }


def _sort_candidates(candidates: list[dict]) -> list[dict]:
    """§4.4：weighted_score DESC → trained_at DESC → session_id DESC → user_id ASC。"""

    def key(c: dict):
        ws = c["weighted_score"]
        return (
            ws is not None,
            ws if ws is not None else 0.0,
            c["trained_at"] or "",
            c["session_id"],
            -c["user_id"],
        )

    return sorted(candidates, key=key, reverse=True)


def build_candidates_response(
    db: DbSession,
    *,
    job_id: int,
    input_mode: str | None,
    scoring_version: str | None,
) -> dict:
    job = db.query(Job).filter(Job.id == job_id).first()
    if job is None:
        raise LookupError("JOB_NOT_FOUND")

    available = list_available_cohorts(db, job_id)
    weights_error = None
    weights_payload = None
    raw_weights: dict[str, float] | None
    try:
        raw_weights = parse_job_weights(job.dims_json)
        weights_payload = {"scheme": "job_dims_renorm", **raw_weights}
    except JobWeightsInvalid:
        weights_error = "JOB_WEIGHTS_INVALID"
        raw_weights = None

    # 发现模式：仅 job_id
    if input_mode is None and scoring_version is None:
        return {
            "job_id": job.id,
            "job_title": job.title,
            "cohort": None,
            "available_cohorts": available,
            "weights": weights_payload,
            "weights_error": weights_error,
            "eligibility": ELIGIBILITY,
            "candidates": [],
        }

    # 完整模式：权重非法 → 由 API 转为 503
    if raw_weights is None:
        raise JobWeightsInvalid(weights_error or "JOB_WEIGHTS_INVALID")

    rows = _eligible_reports_for_cohort(db, job_id, input_mode, scoring_version)
    picked = pick_latest_eligible_per_user(rows)
    candidates = _sort_candidates(
        [
            build_candidate_item(sess, report, user, raw_weights)
            for sess, report, user in picked
        ]
    )

    return {
        "job_id": job.id,
        "job_title": job.title,
        "cohort": {"input_mode": input_mode, "scoring_version": scoring_version},
        "available_cohorts": available,
        "weights": weights_payload,
        "weights_error": None,
        "eligibility": ELIGIBILITY,
        "candidates": candidates,
    }
