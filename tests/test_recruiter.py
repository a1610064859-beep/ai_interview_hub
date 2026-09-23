"""T8：企业端同源候选闭环验收（先写 happy-path，再实现）。R1–R14。"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from scripts.import_seeds import import_seeds
from server.config import settings
from server.db import Base, SessionLocal, ensure_schema_upgrades, engine
from server.main import app
from server.models import Answer, Job, Question, Report, Session, User

DIM_KEYS = (
    "professional_match",
    "logic_structure",
    "expression_fluency",
    "job_competence",
)

APPROVED_WEIGHTS = {
    "professional_match": 0.30,
    "logic_structure": 0.25,
    "expression_fluency": 0.20,
    "job_competence": 0.25,
}

APPROVED_DIMS_JSON = {
    "labels": ["专业匹配度", "逻辑结构", "表达流畅度", "岗位素养"],
    "weights": dict(APPROVED_WEIGHTS),
}


def _dims(
    professional_match=70.0,
    logic_structure=72.0,
    expression_fluency=None,
    job_competence=71.0,
):
    return {
        "professional_match": {
            "score": professional_match,
            "evidence": "证据甲" if professional_match is not None else None,
            "reason": "r" if professional_match is not None else "未评估",
        },
        "logic_structure": {
            "score": logic_structure,
            "evidence": "证据乙" if logic_structure is not None else None,
            "reason": "r" if logic_structure is not None else "未评估",
        },
        "expression_fluency": {
            "score": expression_fluency,
            "evidence": None,
            "reason": "文本模式，未评估语音流畅度"
            if expression_fluency is None
            else "声学",
        },
        "job_competence": {
            "score": job_competence,
            "evidence": "证据丙" if job_competence is not None else None,
            "reason": "r" if job_competence is not None else "未评估",
        },
    }


def _overall_from_dims(dimensions: dict) -> float | None:
    scores = [
        Decimal(str(dimensions[k]["score"]))
        for k in DIM_KEYS
        if dimensions[k]["score"] is not None
    ]
    if not scores:
        return None
    return float(
        (sum(scores) / Decimal(str(len(scores)))).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )
    )


def _expected_weighted(dimensions: dict, weights: dict[str, float]) -> float | None:
    parts = []
    for k in DIM_KEYS:
        score = dimensions[k]["score"]
        if score is None:
            continue
        parts.append((Decimal(str(score)), Decimal(str(weights[k]))))
    if not parts:
        return None
    s = sum(w for _, w in parts)
    if s == 0:
        return None
    total = sum(score * (w / s) for score, w in parts)
    return float(total.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _insert_completed(
    *,
    user_id: int,
    job_id: int,
    started_at: datetime,
    dimensions: dict,
    input_mode: str | None = "text",
    scoring_version: str | None = "v1",
    status: str = "completed",
    with_report: bool = True,
) -> tuple[int, int | None]:
    overall = _overall_from_dims(dimensions)
    with SessionLocal() as db:
        sess = Session(
            user_id=user_id,
            job_id=job_id,
            mode="毕业生",
            started_at=started_at,
            status=status,
            pending_question_json=None,
            input_mode=input_mode,
        )
        db.add(sess)
        db.flush()
        rid = None
        if with_report and status == "completed":
            report = Report(
                session_id=sess.id,
                dimensions_json=dimensions,
                highlights_json=["h"],
                concerns_json=["c"],
                improvement_json=["i"],
                overall=overall,
                scoring_version=scoring_version,
            )
            db.add(report)
            db.flush()
            rid = report.id
        db.commit()
        return sess.id, rid


@pytest.fixture(autouse=True)
def setup_recruiter_db(monkeypatch):
    monkeypatch.setattr(settings, "tts_enabled", False)
    Base.metadata.create_all(engine)
    ensure_schema_upgrades(engine)

    with SessionLocal() as db:
        db.query(Report).delete()
        db.query(Answer).delete()
        db.query(Session).delete()
        db.query(Question).delete()
        db.query(Job).delete()
        db.query(User).delete()

        db.add(
            User(
                id=3,
                role="student",
                name_masked="王*明",
                major="车辆工程",
                grade="大三",
            )
        )
        db.add(
            User(
                id=4,
                role="student",
                name_masked="李*华",
                major="智能车辆工程",
                grade="大二",
            )
        )
        for jid, title in ((1, "智驾测试"), (2, "三电系统测试")):
            db.add(
                Job(
                    id=jid,
                    family="智驾" if jid == 1 else "三电",
                    title=title,
                    jd_digest="digest",
                    terms_json=["t"],
                    dims_json=dict(APPROVED_DIMS_JSON),
                )
            )
            for i in range(6):
                db.add(
                    Question(
                        job_id=jid,
                        type="通用" if i < 2 else ("情景" if i == 5 else "专业"),
                        text=f"岗位{jid}题{i+1}",
                        followup_hint=None,
                    )
                )
        db.commit()


def test_happy_path_r1_two_students_same_job_同源():
    """R1 happy-path：两学生同岗 text/v1，候选同源且加权正确。"""
    client = TestClient(app)
    base = datetime(2026, 9, 20, 10, 0, 0)
    dims_a = _dims(73.0, 76.0, None, 76.0)
    dims_b = _dims(71.0, 74.0, None, 72.5)
    s_a, r_a = _insert_completed(
        user_id=3, job_id=1, started_at=base + timedelta(hours=1), dimensions=dims_a
    )
    s_b, r_b = _insert_completed(
        user_id=4, job_id=1, started_at=base, dimensions=dims_b
    )

    resp = client.get(
        "/api/recruiter/candidates",
        params={"job_id": 1, "input_mode": "text", "scoring_version": "v1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == 1
    assert body["cohort"] == {"input_mode": "text", "scoring_version": "v1"}
    assert body["weights_error"] is None
    assert body["weights"]["scheme"] == "job_dims_renorm"
    assert body["eligibility"] == "min_valid_dims_3"
    assert len(body["candidates"]) == 2

    by_uid = {c["user_id"]: c for c in body["candidates"]}
    assert set(by_uid) == {3, 4}
    ca, cb = by_uid[3], by_uid[4]
    assert ca["session_id"] == s_a and ca["report_id"] == r_a
    assert cb["session_id"] == s_b and cb["report_id"] == r_b
    assert ca["job_id"] == 1 and cb["job_id"] == 1
    assert ca["name_masked"] == "王*明" and cb["name_masked"] == "李*华"
    assert ca["overall"] == _overall_from_dims(dims_a)
    assert cb["overall"] == _overall_from_dims(dims_b)
    assert ca["dimensions"]["expression_fluency"]["score"] is None
    assert ca["weighted_score"] == _expected_weighted(dims_a, APPROVED_WEIGHTS)
    assert cb["weighted_score"] == _expected_weighted(dims_b, APPROVED_WEIGHTS)
    # 本夹具下加权≠等权，证明未以 overall 冒充 weighted_score
    assert ca["weighted_score"] != ca["overall"]
    assert cb["weighted_score"] != cb["overall"]
    assert ca["report_path"] == f"/reports/{s_a}"
    assert cb["report_path"] == f"/reports/{s_b}"
    # A 更晚训练且加权更高或时间更新 → 排在前面（本例 A weighted 更高）
    assert body["candidates"][0]["user_id"] == 3


def test_r2_job_isolation():
    client = TestClient(app)
    base = datetime(2026, 9, 20, 10, 0, 0)
    s1, _ = _insert_completed(
        user_id=3, job_id=1, started_at=base, dimensions=_dims()
    )
    s2, _ = _insert_completed(
        user_id=3, job_id=2, started_at=base + timedelta(hours=1), dimensions=_dims()
    )
    j1 = client.get(
        "/api/recruiter/candidates",
        params={"job_id": 1, "input_mode": "text", "scoring_version": "v1"},
    ).json()
    j2 = client.get(
        "/api/recruiter/candidates",
        params={"job_id": 2, "input_mode": "text", "scoring_version": "v1"},
    ).json()
    assert [c["session_id"] for c in j1["candidates"]] == [s1]
    assert [c["session_id"] for c in j2["candidates"]] == [s2]
    assert s2 not in [c["session_id"] for c in j1["candidates"]]
    assert s1 not in [c["session_id"] for c in j2["candidates"]]


def test_r3_retrain_updates_no_duplicate():
    client = TestClient(app)
    base = datetime(2026, 9, 20, 10, 0, 0)
    _insert_completed(user_id=3, job_id=1, started_at=base, dimensions=_dims(70, 70, None, 70))
    s_b, r_b = _insert_completed(
        user_id=4, job_id=1, started_at=base + timedelta(minutes=1), dimensions=_dims(71, 71, None, 71)
    )
    s_a2, r_a2 = _insert_completed(
        user_id=3,
        job_id=1,
        started_at=base + timedelta(hours=2),
        dimensions=_dims(80, 80, None, 80),
    )
    body = client.get(
        "/api/recruiter/candidates",
        params={"job_id": 1, "input_mode": "text", "scoring_version": "v1"},
    ).json()
    assert len(body["candidates"]) == 2
    by_uid = {c["user_id"]: c for c in body["candidates"]}
    assert by_uid[3]["session_id"] == s_a2 and by_uid[3]["report_id"] == r_a2
    assert by_uid[4]["session_id"] == s_b and by_uid[4]["report_id"] == r_b


def test_r4_incomplete_or_no_report_excluded():
    client = TestClient(app)
    base = datetime(2026, 9, 20, 10, 0, 0)
    _insert_completed(
        user_id=3,
        job_id=1,
        started_at=base,
        dimensions=_dims(),
        status="active",
        with_report=False,
    )
    _insert_completed(
        user_id=4,
        job_id=1,
        started_at=base,
        dimensions=_dims(),
        status="completed",
        with_report=False,
    )
    body = client.get(
        "/api/recruiter/candidates",
        params={"job_id": 1, "input_mode": "text", "scoring_version": "v1"},
    ).json()
    assert body["candidates"] == []


def test_r5_legacy_null_excluded_from_candidates_and_cohorts():
    client = TestClient(app)
    base = datetime(2026, 9, 20, 10, 0, 0)
    _insert_completed(
        user_id=3,
        job_id=1,
        started_at=base,
        dimensions=_dims(),
        input_mode=None,
        scoring_version="v1",
    )
    _insert_completed(
        user_id=4,
        job_id=1,
        started_at=base + timedelta(hours=1),
        dimensions=_dims(),
        input_mode="text",
        scoring_version=None,
    )
    _insert_completed(
        user_id=3,
        job_id=1,
        started_at=base + timedelta(hours=2),
        dimensions=_dims(),
        input_mode="text",
        scoring_version="v1",
    )
    discover = client.get("/api/recruiter/candidates", params={"job_id": 1}).json()
    assert discover["candidates"] == []
    assert discover["available_cohorts"] == [
        {"input_mode": "text", "scoring_version": "v1"}
    ]
    full = client.get(
        "/api/recruiter/candidates",
        params={"job_id": 1, "input_mode": "text", "scoring_version": "v1"},
    ).json()
    assert [c["user_id"] for c in full["candidates"]] == [3]


def test_r6_null_dim_no_zero_and_w2_renorm():
    client = TestClient(app)
    dims = _dims(80.0, 70.0, None, 60.0)
    _insert_completed(user_id=3, job_id=1, started_at=datetime(2026, 9, 20), dimensions=dims)
    body = client.get(
        "/api/recruiter/candidates",
        params={"job_id": 1, "input_mode": "text", "scoring_version": "v1"},
    ).json()
    c = body["candidates"][0]
    assert c["dimensions"]["expression_fluency"]["score"] is None
    assert "0" not in str(c["dimensions"]["expression_fluency"]["score"])
    assert c["weighted_score"] == _expected_weighted(dims, APPROVED_WEIGHTS)
    # 剔除流畅度后 0.30+0.25+0.25=0.8 重归一 → 70.6
    assert c["weighted_score"] == 70.6


def test_r7_e1_fallback_to_previous_eligible():
    client = TestClient(app)
    base = datetime(2026, 9, 20, 10, 0, 0)
    s_old, r_old = _insert_completed(
        user_id=3,
        job_id=1,
        started_at=base,
        dimensions=_dims(70, 70, None, 70),
    )
    # 最新报告仅 2 有效维 → 不合格
    _insert_completed(
        user_id=3,
        job_id=1,
        started_at=base + timedelta(hours=1),
        dimensions=_dims(90, None, None, 90),
    )
    body = client.get(
        "/api/recruiter/candidates",
        params={"job_id": 1, "input_mode": "text", "scoring_version": "v1"},
    ).json()
    assert len(body["candidates"]) == 1
    assert body["candidates"][0]["session_id"] == s_old
    assert body["candidates"][0]["report_id"] == r_old
    assert body["candidates"][0]["valid_dim_count"] == 3


def test_r7b_anomaly_scores_rejected_from_valid_dim_count():
    """非数字 / 非有限 / 越界分数不计有效维；布尔 True 不得冒充 1 分。"""
    from server.services.recruiter import (
        compute_weighted_score,
        is_valid_dimension_score,
        valid_dim_count,
    )

    assert is_valid_dimension_score(0) is True
    assert is_valid_dimension_score(100) is True
    assert is_valid_dimension_score(75.5) is True
    assert is_valid_dimension_score(None) is False
    assert is_valid_dimension_score(True) is False
    assert is_valid_dimension_score(False) is False
    assert is_valid_dimension_score("80") is False
    assert is_valid_dimension_score(float("nan")) is False
    assert is_valid_dimension_score(float("inf")) is False
    assert is_valid_dimension_score(float("-inf")) is False
    assert is_valid_dimension_score(-0.1) is False
    assert is_valid_dimension_score(100.1) is False

    junk = {
        "professional_match": {"score": "80", "evidence": "x", "reason": "r"},
        "logic_structure": {"score": float("nan"), "evidence": "x", "reason": "r"},
        "expression_fluency": {"score": 150, "evidence": "x", "reason": "r"},
        "job_competence": {"score": True, "evidence": "x", "reason": "r"},
    }
    assert valid_dim_count(junk) == 0
    assert compute_weighted_score(junk, APPROVED_WEIGHTS) is None

    mixed = _dims(70.0, float("inf"), -1.0, 80.0)
    assert valid_dim_count(mixed) == 2
    # 仅 70 与 80 参与重归一：0.30+0.25=0.55 → 74.5
    assert compute_weighted_score(mixed, APPROVED_WEIGHTS) == 74.5

    client = TestClient(app)
    base = datetime(2026, 9, 20, 10, 0, 0)
    s_ok, r_ok = _insert_completed(
        user_id=3, job_id=1, started_at=base, dimensions=_dims(70, 70, None, 70)
    )
    # 表面四维均有 score，但含异常值 → 有效维 < 3，回退到旧报告
    anomaly = {
        "professional_match": {"score": 90.0, "evidence": "好", "reason": "r"},
        "logic_structure": {"score": float("nan"), "evidence": "坏", "reason": "r"},
        "expression_fluency": {"score": 999.0, "evidence": "坏", "reason": "r"},
        "job_competence": {"score": "88", "evidence": "坏", "reason": "r"},
    }
    with SessionLocal() as db:
        sess = Session(
            user_id=3,
            job_id=1,
            mode="毕业生",
            started_at=base + timedelta(hours=1),
            status="completed",
            pending_question_json=None,
            input_mode="text",
        )
        db.add(sess)
        db.flush()
        db.add(
            Report(
                session_id=sess.id,
                dimensions_json=anomaly,
                highlights_json=[],
                concerns_json=[],
                improvement_json=[],
                overall=90.0,
                scoring_version="v1",
            )
        )
        db.commit()

    body = client.get(
        "/api/recruiter/candidates",
        params={"job_id": 1, "input_mode": "text", "scoring_version": "v1"},
    ).json()
    assert len(body["candidates"]) == 1
    assert body["candidates"][0]["session_id"] == s_ok
    assert body["candidates"][0]["report_id"] == r_ok
    assert body["candidates"][0]["valid_dim_count"] == 3


def test_r8_cohort_no_mix_and_discovery_and_half_params():
    client = TestClient(app)
    base = datetime(2026, 9, 20, 10, 0, 0)
    _insert_completed(
        user_id=3,
        job_id=1,
        started_at=base,
        dimensions=_dims(),
        input_mode="text",
        scoring_version="v1",
    )
    _insert_completed(
        user_id=3,
        job_id=1,
        started_at=base + timedelta(hours=1),
        dimensions=_dims(75, 75, 80, 75),
        input_mode="voice",
        scoring_version="v1",
    )
    text = client.get(
        "/api/recruiter/candidates",
        params={"job_id": 1, "input_mode": "text", "scoring_version": "v1"},
    ).json()
    assert len(text["candidates"]) == 1
    assert text["candidates"][0]["input_mode"] == "text"
    voice = client.get(
        "/api/recruiter/candidates",
        params={"job_id": 1, "input_mode": "voice", "scoring_version": "v1"},
    ).json()
    assert voice["candidates"][0]["input_mode"] == "voice"

    discover = client.get("/api/recruiter/candidates", params={"job_id": 1})
    assert discover.status_code == 200
    d = discover.json()
    assert d["candidates"] == []
    assert d["cohort"] is None
    assert d["available_cohorts"] == [
        {"input_mode": "text", "scoring_version": "v1"},
        {"input_mode": "voice", "scoring_version": "v1"},
    ]

    half = client.get(
        "/api/recruiter/candidates",
        params={"job_id": 1, "input_mode": "text"},
    )
    assert half.status_code == 422


def test_r9_stable_sort_tie_breakers():
    client = TestClient(app)
    base = datetime(2026, 9, 20, 10, 0, 0)
    # 相同加权：相同分数维
    dims = _dims(70, 70, None, 70)
    s_early, _ = _insert_completed(
        user_id=4, job_id=1, started_at=base, dimensions=dims
    )
    s_late, _ = _insert_completed(
        user_id=3, job_id=1, started_at=base + timedelta(hours=1), dimensions=dims
    )
    body1 = client.get(
        "/api/recruiter/candidates",
        params={"job_id": 1, "input_mode": "text", "scoring_version": "v1"},
    ).json()
    body2 = client.get(
        "/api/recruiter/candidates",
        params={"job_id": 1, "input_mode": "text", "scoring_version": "v1"},
    ).json()
    # weighted 相同 → trained_at DESC → user 3 在前
    assert [c["user_id"] for c in body1["candidates"]] == [3, 4]
    assert [c["session_id"] for c in body1["candidates"]] == [s_late, s_early]
    assert [c["user_id"] for c in body2["candidates"]] == [3, 4]


def test_r10_report_path_opens_same_report_id():
    client = TestClient(app)
    sid, rid = _insert_completed(
        user_id=3, job_id=1, started_at=datetime(2026, 9, 20), dimensions=_dims()
    )
    cand = client.get(
        "/api/recruiter/candidates",
        params={"job_id": 1, "input_mode": "text", "scoring_version": "v1"},
    ).json()["candidates"][0]
    assert cand["report_path"] == f"/reports/{sid}"
    report = client.get(f"/api/reports/{sid}")
    assert report.status_code == 200
    assert report.json()["id"] == rid
    assert report.json()["session_id"] == sid


def test_r11_parse_no_job_expansion(monkeypatch):
    client = TestClient(app)

    class FakeDraft:
        dims = ["专业匹配度", "逻辑结构", "表达流畅度", "岗位素养"]
        questions = [{"type": "通用", "text": f"草案题{i}"} for i in range(8)]
        terms = ["感知融合", "标定"]

        def model_dump(self):
            return {
                "dims": self.dims,
                "questions": self.questions,
                "terms": self.terms,
            }

    async def fake_chat_json(stage, messages, response_model):
        assert stage in {"jd", "jd_parse"}
        return response_model.model_validate(FakeDraft().model_dump())

    monkeypatch.setattr("server.services.jd_parse.chat_json", fake_chat_json)

    with SessionLocal() as db:
        before_jobs = {(j.id, j.family, j.title) for j in db.query(Job).all()}
        before_q = db.query(Question).count()
        before_digest = db.query(Job).filter(Job.id == 1).one().jd_digest

    jd = "x" * 20 + "智能驾驶测试岗位职责说明与技能要求"
    resp = client.post("/api/jobs/parse", json={"job_id": 1, "jd_text": jd})
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == 1
    assert body["job_id_source"] == "request_binding"
    assert body["applied"] is False
    assert len(body["dims"]) <= 5
    assert 8 <= len(body["questions"]) <= 11

    with SessionLocal() as db:
        after_jobs = {(j.id, j.family, j.title) for j in db.query(Job).all()}
        assert after_jobs == before_jobs
        assert db.query(Question).count() == before_q
        assert db.query(Job).filter(Job.id == 1).one().jd_digest == before_digest

    assert client.post("/api/jobs/parse", json={"jd_text": jd}).status_code == 422
    assert (
        client.post("/api/jobs/parse", json={"job_id": 999, "jd_text": jd}).status_code
        == 404
    )
    assert (
        client.post(
            "/api/jobs/parse", json={"job_id": 1, "jd_text": "too-short", "extra": 1}
        ).status_code
        == 422
    )


def test_r12_no_candidate_table_and_no_static_board():
    from sqlalchemy import inspect

    insp = inspect(engine)
    tables = set(insp.get_table_names())
    assert "candidates" not in tables
    assert "recruiter_board" not in tables
    assert "leaderboard" not in tables


def test_r13_candidates_zero_llm_calls(monkeypatch):
    calls = {"n": 0}

    async def boom(*args, **kwargs):
        calls["n"] += 1
        raise AssertionError("candidates 路径禁止调用 LLM")

    monkeypatch.setattr("server.services.llm.chat_json", boom)
    _insert_completed(
        user_id=3, job_id=1, started_at=datetime(2026, 9, 20), dimensions=_dims()
    )
    client = TestClient(app)
    assert (
        client.get(
            "/api/recruiter/candidates",
            params={"job_id": 1, "input_mode": "text", "scoring_version": "v1"},
        ).status_code
        == 200
    )
    assert (
        client.get("/api/recruiter/candidates", params={"job_id": 1}).status_code == 200
    )
    assert calls["n"] == 0


def test_r14_invalid_weights_and_job_not_found():
    client = TestClient(app)
    _insert_completed(
        user_id=3, job_id=1, started_at=datetime(2026, 9, 20), dimensions=_dims()
    )
    with SessionLocal() as db:
        job = db.query(Job).filter(Job.id == 1).one()
        job.dims_json = ["专业匹配度", "逻辑结构", "表达流畅度", "岗位素养"]
        db.commit()

    full = client.get(
        "/api/recruiter/candidates",
        params={"job_id": 1, "input_mode": "text", "scoring_version": "v1"},
    )
    assert full.status_code == 503
    assert full.json()["detail"]["code"] == "JOB_WEIGHTS_INVALID"

    discover = client.get("/api/recruiter/candidates", params={"job_id": 1})
    assert discover.status_code == 200
    d = discover.json()
    assert d["candidates"] == []
    assert d["weights"] is None
    assert d["weights_error"] == "JOB_WEIGHTS_INVALID"
    assert d["available_cohorts"] == [
        {"input_mode": "text", "scoring_version": "v1"}
    ]

    assert (
        client.get(
            "/api/recruiter/candidates",
            params={"job_id": 999, "input_mode": "text", "scoring_version": "v1"},
        ).status_code
        == 404
    )


def test_parse_unavailable_503(monkeypatch):
    from server.services.llm import LLMError

    async def fail(*args, **kwargs):
        raise LLMError("all failed")

    monkeypatch.setattr("server.services.jd_parse.chat_json", fail)
    client = TestClient(app)
    resp = client.post(
        "/api/jobs/parse",
        json={"job_id": 1, "jd_text": "x" * 25 + "智能驾驶测试岗位描述"},
    )
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "JD_PARSE_UNAVAILABLE"


def test_seed_dims_json_upgrade_idempotent():
    """种子升级后 dims_json 为 §5.1 形状；重复导入不建第三岗。"""
    with SessionLocal() as db:
        db.query(Question).delete()
        db.query(Job).delete()
        db.query(User).delete()
        db.commit()
        stats1 = import_seeds(db=db)
        jobs = db.query(Job).order_by(Job.id.asc()).all()
        assert len(jobs) == 2
        for job in jobs:
            dims = job.dims_json
            assert isinstance(dims, dict)
            assert set(dims["weights"].keys()) == set(DIM_KEYS)
            assert abs(sum(dims["weights"].values()) - 1.0) <= 1e-6
        q_count = db.query(Question).count()
        stats2 = import_seeds(db=db)
        assert db.query(Job).count() == 2
        assert db.query(Question).count() == q_count
        assert stats2["jobs_created"] == 0
        assert stats1["jobs_created"] == 2
