"""成长追踪纯查询服务：历史 / 趋势 / 可比性判定；零 LLM。"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy.orm import Session as DbSession

from server.models import Job, Report, Session, User

DIMENSION_KEYS = (
    "professional_match",
    "logic_structure",
    "expression_fluency",
    "job_competence",
)

REASON_MESSAGES = {
    "NO_RECORDS": "该岗位暂无已完成的训练记录",
    "SINGLE_RECORD": "仅一次训练，暂无可比较的两次记录",
    "OVERALL_MISSING": "最近两次 overall 存在缺失，不可直接比较",
    "INPUT_MODE_MISMATCH": "文本与语音训练评分口径不同，overall 不可直接比较",
    "SCORING_VERSION_MISMATCH": "评分版本不同，overall 不可直接比较",
    "INPUT_MODE_UNKNOWN": "存在未标识输入模式的存量记录，overall 不可直接比较",
    "SCORING_VERSION_UNKNOWN": "存在未标识评分版本的存量记录，overall 不可直接比较",
    "DIMENSION_SET_MISMATCH": "两次训练的有效评分维度集合不同，overall 不直接比较",
    "EMPTY_DIMENSION_SET": "最近两次均无有效评分维度，overall 不可直接比较",
}


def require_student(db: DbSession, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user or user.role != "student":
        raise LookupError("USER_NOT_FOUND")
    return user


def require_job(db: DbSession, job_id: int) -> Job:
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise LookupError("JOB_NOT_FOUND")
    return job


def list_students(db: DbSession) -> list[User]:
    return (
        db.query(User)
        .filter(User.role == "student")
        .order_by(User.id.asc())
        .all()
    )


def _score_map(dimensions_json: dict | None) -> dict[str, float | None]:
    raw = dimensions_json or {}
    out: dict[str, float | None] = {}
    for key in DIMENSION_KEYS:
        cell = raw.get(key) if isinstance(raw, dict) else None
        if isinstance(cell, dict):
            score = cell.get("score")
            out[key] = score if isinstance(score, (int, float)) else None
        else:
            out[key] = None
    return out


def _effective_dims(score_map: dict[str, float | None]) -> set[str]:
    return {k for k, v in score_map.items() if v is not None}


def _format_started_at(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat(timespec="seconds")
    return str(value)


def _round1(value: float) -> float:
    return float(
        Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    )


def iter_qualified(
    db: DbSession,
    user_id: int,
    job_id: int | None = None,
) -> list[tuple[Session, Report, Job]]:
    """completed 且有 report 的会话，按 started_at、session.id 升序。"""
    q = (
        db.query(Session, Report, Job)
        .join(Report, Report.session_id == Session.id)
        .join(Job, Job.id == Session.job_id)
        .filter(Session.user_id == user_id, Session.status == "completed")
    )
    if job_id is not None:
        q = q.filter(Session.job_id == job_id)
    rows = q.order_by(Session.started_at.asc(), Session.id.asc()).all()
    return list(rows)


def build_history(
    db: DbSession,
    user_id: int,
    job_id: int | None = None,
) -> dict:
    require_student(db, user_id)
    if job_id is not None:
        require_job(db, job_id)

    records = []
    for sess, report, job in iter_qualified(db, user_id, job_id):
        improvement = report.improvement_json
        if not isinstance(improvement, list):
            improvement = []
        records.append(
            {
                "session_id": sess.id,
                "report_id": report.id,
                "job_id": sess.job_id,
                "job_title": job.title,
                "started_at": _format_started_at(sess.started_at),
                "mode": sess.mode,
                "input_mode": sess.input_mode,
                "scoring_version": report.scoring_version,
                "overall": report.overall,
                "dimensions": _score_map(report.dimensions_json),
                "improvement": [str(x) for x in improvement],
            }
        )
    return {"user_id": user_id, "job_id": job_id, "records": records}


def _aggregate_input_mode(modes: list[str | None]) -> str | None:
    if not modes:
        return None
    known = {m for m in modes if m is not None}
    # 含 NULL 或多种已知模式 → mixed；全部同一已知模式 → 该模式
    if None in modes or len(known) != 1:
        return "mixed"
    return next(iter(known))


def _compare_overall(prev: Session, prev_r: Report, curr: Session, curr_r: Report) -> dict:
    reasons: list[str] = []
    prev_scores = _score_map(prev_r.dimensions_json)
    curr_scores = _score_map(curr_r.dimensions_json)
    prev_eff = _effective_dims(prev_scores)
    curr_eff = _effective_dims(curr_scores)

    if prev_r.overall is None or curr_r.overall is None:
        reasons.append("OVERALL_MISSING")

    if prev.input_mode is None or curr.input_mode is None:
        reasons.append("INPUT_MODE_UNKNOWN")
    elif prev.input_mode != curr.input_mode:
        reasons.append("INPUT_MODE_MISMATCH")

    if prev_r.scoring_version is None or curr_r.scoring_version is None:
        reasons.append("SCORING_VERSION_UNKNOWN")
    elif prev_r.scoring_version != curr_r.scoring_version:
        reasons.append("SCORING_VERSION_MISMATCH")

    if not prev_eff and not curr_eff:
        reasons.append("EMPTY_DIMENSION_SET")
    elif prev_eff != curr_eff:
        reasons.append("DIMENSION_SET_MISMATCH")

    comparable = len(reasons) == 0
    delta = None
    if comparable:
        delta = _round1(float(curr_r.overall) - float(prev_r.overall))

    message = None
    if reasons:
        # 优先使用首个原因的标准文案；维度集合不同用规格示例语气
        if "DIMENSION_SET_MISMATCH" in reasons:
            message = REASON_MESSAGES["DIMENSION_SET_MISMATCH"]
        else:
            message = REASON_MESSAGES.get(reasons[0])

    return {
        "comparable": comparable,
        "reasons": reasons,
        "message": message,
        "previous": {"session_id": prev.id, "overall": prev_r.overall},
        "current": {"session_id": curr.id, "overall": curr_r.overall},
        "delta": delta,
    }


def _dimension_changes(prev_r: Report, curr_r: Report) -> dict[str, dict | None]:
    prev_scores = _score_map(prev_r.dimensions_json)
    curr_scores = _score_map(curr_r.dimensions_json)
    out: dict[str, dict | None] = {}
    for key in DIMENSION_KEYS:
        p = prev_scores[key]
        c = curr_scores[key]
        if p is None or c is None:
            out[key] = None
        else:
            out[key] = {
                "previous": float(p),
                "current": float(c),
                "delta": _round1(float(c) - float(p)),
            }
    return out


def build_trend(db: DbSession, user_id: int, job_id: int) -> dict:
    require_student(db, user_id)
    job = require_job(db, job_id)
    rows = iter_qualified(db, user_id, job_id)

    points = []
    for sess, report, _job in rows:
        points.append(
            {
                "session_id": sess.id,
                "report_id": report.id,
                "started_at": _format_started_at(sess.started_at),
                "overall": report.overall,
                "dimensions": _score_map(report.dimensions_json),
            }
        )

    modes = [sess.input_mode for sess, _r, _j in rows]
    top_mode = _aggregate_input_mode(modes)

    if len(rows) == 0:
        comparison = {
            "comparable": False,
            "reasons": ["NO_RECORDS"],
            "message": REASON_MESSAGES["NO_RECORDS"],
            "previous": None,
            "current": None,
            "delta": None,
        }
        dim_changes = {k: None for k in DIMENSION_KEYS}
    elif len(rows) == 1:
        comparison = {
            "comparable": False,
            "reasons": ["SINGLE_RECORD"],
            "message": REASON_MESSAGES["SINGLE_RECORD"],
            "previous": None,
            "current": None,
            "delta": None,
        }
        dim_changes = {k: None for k in DIMENSION_KEYS}
    else:
        prev_s, prev_r, _ = rows[-2]
        curr_s, curr_r, _ = rows[-1]
        comparison = _compare_overall(prev_s, prev_r, curr_s, curr_r)
        dim_changes = _dimension_changes(prev_r, curr_r)

    return {
        "user_id": user_id,
        "job_id": job_id,
        "job_title": job.title,
        "input_mode": top_mode,
        "sessions_count": len(rows),
        "points": points,
        "overall_comparison": comparison,
        "dimension_changes": dim_changes,
    }
