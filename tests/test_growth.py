"""T7-G1-BE：成长追踪后端验收（先写 happy-path，再实现）。"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from scripts.import_seeds import import_seeds, SeedStudentConflictError
from server.db import SessionLocal, ensure_schema_upgrades
from server.db import Base
from server.main import app
from server.models import Answer, Job, Question, Report, Session, User
from server.config import settings


DIM_KEYS = (
    "professional_match",
    "logic_structure",
    "expression_fluency",
    "job_competence",
)


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


@pytest.fixture(autouse=True)
def setup_growth_db(monkeypatch):
    monkeypatch.setattr(settings, "tts_enabled", False)
    from server.db import engine

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
        db.add(
            User(
                id=9,
                role="recruiter",
                name_masked="招聘*员",
                major=None,
                grade=None,
            )
        )

        for jid, title in ((1, "智驾测试"), (2, "三电系统测试")):
            db.add(
                Job(
                    id=jid,
                    family="智驾" if jid == 1 else "三电",
                    title=title,
                    jd_digest=f"{title} JD",
                    terms_json=["CANoe"],
                    dims_json={},
                )
            )
            for qi in range(1, 7):
                db.add(
                    Question(
                        id=(jid - 1) * 6 + qi,
                        job_id=jid,
                        type="专业",
                        text=f"岗位{jid}第{qi}题",
                        followup_hint=None,
                    )
                )
        db.commit()
    yield


def _insert_completed(
    *,
    user_id: int,
    job_id: int,
    started_at: datetime,
    dimensions: dict,
    input_mode: str | None = "text",
    scoring_version: str | None = None,
    mode: str = "毕业生",
    improvement: list[str] | None = None,
) -> tuple[int, int]:
    """测试夹具：直写 completed 会话 + 报告（可显式标 scoring_version，不伪造生产基线）。"""
    overall = _overall_from_dims(dimensions)
    with SessionLocal() as db:
        sess = Session(
            user_id=user_id,
            job_id=job_id,
            mode=mode,
            started_at=started_at,
            status="completed",
            pending_question_json=None,
            input_mode=input_mode,
        )
        db.add(sess)
        db.flush()
        report = Report(
            session_id=sess.id,
            dimensions_json=dimensions,
            highlights_json=["h"],
            concerns_json=["c"],
            improvement_json=improvement or ["保持结论先行"],
            overall=overall,
            scoring_version=scoring_version,
        )
        db.add(report)
        db.commit()
        return sess.id, report.id


def test_happy_path_students_history_trend_isolation():
    """Happy-path：两学生两岗位隔离 + 同人同岗三次可比趋势。"""
    client = TestClient(app)

    # GET /api/students
    stu = client.get("/api/students")
    assert stu.status_code == 200
    body = stu.json()
    assert [s["id"] for s in body["students"]] == [3, 4]
    assert body["students"][0]["name_masked"] == "王*明"
    assert body["students"][1]["name_masked"] == "李*华"

    base = datetime(2026, 9, 20, 10, 0, 0)
    s11, r11 = _insert_completed(
        user_id=3,
        job_id=1,
        started_at=base,
        dimensions=_dims(68.0, 72.0, None, 70.0),
        scoring_version="fixture-a",
        improvement=["回答先给结论再展开"],
    )
    s12, r12 = _insert_completed(
        user_id=4,
        job_id=1,
        started_at=base + timedelta(hours=6),
        dimensions=_dims(71.0, 74.0, None, 72.5),
        scoring_version="fixture-a",
    )
    s13, r13 = _insert_completed(
        user_id=3,
        job_id=1,
        started_at=base + timedelta(hours=6, minutes=1),
        dimensions=_dims(71.0, 74.0, None, 72.5),
        scoring_version="fixture-a",
    )
    s14, r14 = _insert_completed(
        user_id=3,
        job_id=1,
        started_at=base + timedelta(days=1),
        dimensions=_dims(73.0, 76.0, None, 76.0),
        scoring_version="fixture-a",
        improvement=["情景题可加入更多安全兜底思考"],
    )
    # 学生3 在岗位2 一次
    _insert_completed(
        user_id=3,
        job_id=2,
        started_at=base + timedelta(days=2),
        dimensions=_dims(60.0, 60.0, None, 60.0),
        scoring_version="fixture-a",
    )

    hist3 = client.get("/api/growth/3/history", params={"job_id": 1})
    assert hist3.status_code == 200
    h3 = hist3.json()
    assert h3["user_id"] == 3
    assert h3["job_id"] == 1
    assert [r["session_id"] for r in h3["records"]] == [s11, s13, s14]
    assert s12 not in [r["session_id"] for r in h3["records"]]
    assert h3["records"][0]["report_id"] == r11
    assert h3["records"][0]["improvement"] == ["回答先给结论再展开"]
    assert h3["records"][0]["dimensions"]["expression_fluency"] is None
    assert h3["records"][0]["scoring_version"] == "fixture-a"

    hist4 = client.get("/api/growth/4/history", params={"job_id": 1})
    assert [r["session_id"] for r in hist4.json()["records"]] == [s12]
    assert s11 not in [r["session_id"] for r in hist4.json()["records"]]

    hist_all = client.get("/api/growth/3/history")
    assert hist_all.status_code == 200
    assert hist_all.json()["job_id"] is None
    assert len(hist_all.json()["records"]) == 4

    trend = client.get("/api/growth/3/trend", params={"job_id": 1})
    assert trend.status_code == 200
    t = trend.json()
    assert t["user_id"] == 3
    assert t["job_id"] == 1
    assert t["sessions_count"] == 3
    assert t["input_mode"] == "text"
    assert [p["session_id"] for p in t["points"]] == [s11, s13, s14]
    assert s12 not in [p["session_id"] for p in t["points"]]
    assert t["overall_comparison"]["comparable"] is True
    assert t["overall_comparison"]["reasons"] == []
    assert t["overall_comparison"]["previous"]["session_id"] == s13
    assert t["overall_comparison"]["current"]["session_id"] == s14
    assert t["overall_comparison"]["delta"] == 2.5
    assert t["dimension_changes"]["expression_fluency"] is None
    assert t["dimension_changes"]["professional_match"]["delta"] == 2.0


def test_zero_and_single_record_states():
    client = TestClient(app)

    zero = client.get("/api/growth/3/trend", params={"job_id": 1})
    assert zero.status_code == 200
    z = zero.json()
    assert z["sessions_count"] == 0
    assert z["points"] == []
    assert z["input_mode"] is None
    assert z["overall_comparison"]["comparable"] is False
    assert z["overall_comparison"]["reasons"] == ["NO_RECORDS"]
    assert z["overall_comparison"]["delta"] is None
    assert all(z["dimension_changes"][k] is None for k in DIM_KEYS)

    hist = client.get("/api/growth/3/history", params={"job_id": 1})
    assert hist.json()["records"] == []

    _insert_completed(
        user_id=3,
        job_id=2,
        started_at=datetime(2026, 9, 20, 10, 0, 0),
        dimensions=_dims(),
        scoring_version="fixture-a",
    )
    single = client.get("/api/growth/3/trend", params={"job_id": 2})
    s = single.json()
    assert s["sessions_count"] == 1
    assert s["overall_comparison"]["reasons"] == ["SINGLE_RECORD"]
    assert s["overall_comparison"]["delta"] is None
    assert all(s["dimension_changes"][k] is None for k in DIM_KEYS)


def test_missing_dimension_no_zero_fill():
    client = TestClient(app)
    base = datetime(2026, 9, 20, 10, 0, 0)
    _insert_completed(
        user_id=3,
        job_id=1,
        started_at=base,
        dimensions=_dims(68.0, 72.0, None, 70.0),
        scoring_version="fixture-a",
    )
    _insert_completed(
        user_id=3,
        job_id=1,
        started_at=base + timedelta(hours=1),
        dimensions=_dims(66.0, None, None, 70.0),
        scoring_version="fixture-a",
    )
    _insert_completed(
        user_id=3,
        job_id=1,
        started_at=base + timedelta(hours=2),
        dimensions=_dims(73.0, 76.0, None, 76.0),
        scoring_version="fixture-a",
    )

    t = client.get("/api/growth/3/trend", params={"job_id": 1}).json()
    assert t["points"][1]["dimensions"]["logic_structure"] is None
    assert "0" not in str(t["points"][1]["dimensions"]["logic_structure"])
    assert t["overall_comparison"]["comparable"] is False
    assert "DIMENSION_SET_MISMATCH" in t["overall_comparison"]["reasons"]
    assert t["overall_comparison"]["delta"] is None
    assert t["dimension_changes"]["logic_structure"] is None
    assert t["dimension_changes"]["professional_match"]["delta"] == 7.0


def test_text_voice_incomparable_and_scoring_version_mismatch():
    client = TestClient(app)
    base = datetime(2026, 9, 20, 10, 0, 0)
    _insert_completed(
        user_id=3,
        job_id=1,
        started_at=base,
        dimensions=_dims(73.0, 76.0, None, 76.0),
        input_mode="text",
        scoring_version="fixture-a",
    )
    _insert_completed(
        user_id=3,
        job_id=1,
        started_at=base + timedelta(hours=1),
        dimensions=_dims(75.0, 78.0, 82.0, 77.0),
        input_mode="voice",
        scoring_version="fixture-a",
    )
    t = client.get("/api/growth/3/trend", params={"job_id": 1}).json()
    assert t["input_mode"] == "mixed"
    assert "INPUT_MODE_MISMATCH" in t["overall_comparison"]["reasons"]
    assert t["overall_comparison"]["delta"] is None
    # 单维：两次均有效仍可算
    assert t["dimension_changes"]["professional_match"]["delta"] == 2.0
    assert t["dimension_changes"]["expression_fluency"] is None

    with SessionLocal() as db:
        db.query(Report).delete()
        db.query(Session).delete()
        db.commit()

    _insert_completed(
        user_id=3,
        job_id=1,
        started_at=base,
        dimensions=_dims(),
        scoring_version="fixture-a",
    )
    _insert_completed(
        user_id=3,
        job_id=1,
        started_at=base + timedelta(hours=1),
        dimensions=_dims(72.0, 74.0, None, 73.0),
        scoring_version="fixture-b",
    )
    t2 = client.get("/api/growth/3/trend", params={"job_id": 1}).json()
    assert "SCORING_VERSION_MISMATCH" in t2["overall_comparison"]["reasons"]
    assert t2["overall_comparison"]["delta"] is None


def test_legacy_null_scoring_version_unknown():
    client = TestClient(app)
    base = datetime(2026, 9, 20, 10, 0, 0)
    _insert_completed(
        user_id=3,
        job_id=1,
        started_at=base,
        dimensions=_dims(),
        scoring_version=None,
    )
    _insert_completed(
        user_id=3,
        job_id=1,
        started_at=base + timedelta(hours=1),
        dimensions=_dims(72.0, 74.0, None, 73.0),
        scoring_version="fixture-a",
    )
    t = client.get("/api/growth/3/trend", params={"job_id": 1}).json()
    assert "SCORING_VERSION_UNKNOWN" in t["overall_comparison"]["reasons"]
    assert t["overall_comparison"]["comparable"] is False
    hist = client.get("/api/growth/3/history", params={"job_id": 1}).json()
    assert hist["records"][0]["scoring_version"] is None


def test_user_not_found_and_session_create_validation():
    client = TestClient(app)

    assert client.get("/api/growth/999/history").status_code == 404
    assert client.get("/api/growth/999/history").json()["detail"]["code"] == "USER_NOT_FOUND"
    assert client.get("/api/growth/9/history").json()["detail"]["code"] == "USER_NOT_FOUND"

    old = client.post("/api/sessions", json={"job_id": 1})
    assert old.status_code == 422

    missing_mode = client.post("/api/sessions", json={"job_id": 1, "user_id": 3})
    assert missing_mode.status_code == 422

    bad_user = client.post(
        "/api/sessions",
        json={"job_id": 1, "user_id": 999, "mode": "毕业生"},
    )
    assert bad_user.status_code == 404
    assert bad_user.json()["detail"]["code"] == "USER_NOT_FOUND"

    recruiter = client.post(
        "/api/sessions",
        json={"job_id": 1, "user_id": 9, "mode": "毕业生"},
    )
    assert recruiter.status_code == 404
    assert recruiter.json()["detail"]["code"] == "USER_NOT_FOUND"

    ok = client.post(
        "/api/sessions",
        json={"job_id": 1, "user_id": 3, "mode": "毕业生"},
    )
    assert ok.status_code == 200
    sid = ok.json()["sid"]
    with SessionLocal() as db:
        sess = db.query(Session).filter(Session.id == sid).one()
        assert sess.user_id == 3
        assert sess.mode == "毕业生"
        assert sess.input_mode is None
        assert db.query(User).filter(User.id == 1).first() is None


def test_input_mode_mismatch_409():
    client = TestClient(app)
    create = client.post(
        "/api/sessions",
        json={"job_id": 1, "user_id": 3, "mode": "新生"},
    )
    assert create.status_code == 200
    sid = create.json()["sid"]

    with patch(
        "server.services.orchestrator.evaluate_followup",
        AsyncMock(return_value=None),
    ):
        r1 = client.post(
            f"/api/sessions/{sid}/answers/text",
            json={"answer_text": "第一次文本作答，锁定 text 模式。"},
        )
    assert r1.status_code == 200
    with SessionLocal() as db:
        assert db.query(Session).filter(Session.id == sid).one().input_mode == "text"
        before_answers = db.query(Answer).filter(Answer.session_id == sid).count()
        before_pending = db.query(Session).filter(Session.id == sid).one().pending_question_json
        before_status = db.query(Session).filter(Session.id == sid).one().status

    from io import BytesIO

    with patch.object(settings, "asr_enabled", True):
        with patch("server.services.audio.validate_upload"):
            resp = client.post(
                f"/api/sessions/{sid}/answers",
                files={"audio": ("a.webm", BytesIO(b"\x1a\x45\xdf\xa3fake"), "audio/webm")},
                data={"duration_s": "1.0", "pause_cnt": "0"},
            )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "INPUT_MODE_MISMATCH"

    with SessionLocal() as db:
        assert db.query(Answer).filter(Answer.session_id == sid).count() == before_answers
        sess = db.query(Session).filter(Session.id == sid).one()
        assert sess.input_mode == "text"
        assert sess.pending_question_json == before_pending
        assert sess.status == before_status
        assert sess.lease_token is None


def test_input_mode_mismatch_voice_then_text(monkeypatch):
    """反向混用：voice 首答成功后再调 text → 409，不落答、不推进、租约释放。"""
    from io import BytesIO

    from server.services import asr as asr_module
    from server.services import audio as audio_module
    from server.services import orchestrator as orch_module

    monkeypatch.setattr(settings, "asr_enabled", True)
    monkeypatch.setattr(audio_module, "validate_upload", lambda _b: None)
    monkeypatch.setattr(audio_module, "probe_webm", lambda _p: None)

    def _fake_transcode(_webm, wav_path):
        with open(wav_path, "wb") as f:
            f.write(b"RIFF-fake-wav")

    monkeypatch.setattr(audio_module, "transcode_to_16k_wav", _fake_transcode)

    async def _fake_asr(_path):
        return "语音首答锁定 voice 模式"

    monkeypatch.setattr(asr_module, "transcribe_wav", _fake_asr)
    monkeypatch.setattr(orch_module, "evaluate_followup", AsyncMock(return_value=None))

    client = TestClient(app)
    create = client.post(
        "/api/sessions",
        json={"job_id": 1, "user_id": 3, "mode": "毕业生"},
    )
    assert create.status_code == 200
    sid = create.json()["sid"]

    voice = client.post(
        f"/api/sessions/{sid}/answers",
        files={"audio": ("a.webm", BytesIO(b"\x1a\x45\xdf\xa3fake"), "audio/webm")},
        data={"duration_s": "1.5", "pause_cnt": "0"},
    )
    assert voice.status_code == 200, voice.text
    assert voice.json()["type"] in ("followup", "next")

    with SessionLocal() as db:
        sess = db.query(Session).filter(Session.id == sid).one()
        assert sess.input_mode == "voice"
        before_answers = db.query(Answer).filter(Answer.session_id == sid).count()
        before_pending = dict(sess.pending_question_json)
        before_status = sess.status
        assert before_answers == 1
        assert sess.lease_token is None

    text = client.post(
        f"/api/sessions/{sid}/answers/text",
        json={"answer_text": "试图改用文本作答，应被拒绝。"},
    )
    assert text.status_code == 409
    assert text.json()["detail"]["code"] == "INPUT_MODE_MISMATCH"

    with SessionLocal() as db:
        sess = db.query(Session).filter(Session.id == sid).one()
        assert sess.input_mode == "voice"
        assert db.query(Answer).filter(Answer.session_id == sid).count() == before_answers
        assert sess.pending_question_json == before_pending
        assert sess.status == before_status
        assert sess.lease_token is None


def test_only_completed_with_report_in_history():
    client = TestClient(app)
    with SessionLocal() as db:
        db.add(
            Session(
                user_id=3,
                job_id=1,
                mode="毕业生",
                started_at=datetime(2026, 9, 20, 9, 0, 0),
                status="active",
                input_mode="text",
            )
        )
        db.add(
            Session(
                user_id=3,
                job_id=1,
                mode="毕业生",
                started_at=datetime(2026, 9, 20, 9, 30, 0),
                status="completed",
                input_mode="text",
            )
        )
        db.commit()
    _insert_completed(
        user_id=3,
        job_id=1,
        started_at=datetime(2026, 9, 20, 10, 0, 0),
        dimensions=_dims(),
        scoring_version="fixture-a",
    )
    hist = client.get("/api/growth/3/history", params={"job_id": 1}).json()
    assert len(hist["records"]) == 1


def test_growth_queries_invoke_zero_llm_calls(monkeypatch):
    calls = {"n": 0}

    async def boom(*args, **kwargs):
        calls["n"] += 1
        raise AssertionError("growth 路径禁止调用 LLM")

    monkeypatch.setattr("server.services.llm.chat_json", boom)
    monkeypatch.setattr("server.services.scoring.chat_json", boom)
    monkeypatch.setattr("server.services.orchestrator.chat_json", boom)

    _insert_completed(
        user_id=3,
        job_id=1,
        started_at=datetime(2026, 9, 20, 10, 0, 0),
        dimensions=_dims(),
        scoring_version="fixture-a",
    )
    client = TestClient(app)
    assert client.get("/api/students").status_code == 200
    assert client.get("/api/growth/3/history").status_code == 200
    assert client.get("/api/growth/3/trend", params={"job_id": 1}).status_code == 200
    assert calls["n"] == 0


def test_seed_students_idempotent_and_conflict():
    with SessionLocal() as db:
        db.query(User).delete()
        db.commit()
        stats1 = import_seeds(db=db)
        assert stats1.get("students_created", 0) >= 2
        u3 = db.query(User).filter(User.id == 3).one()
        assert u3.name_masked == "王*明"
        assert u3.major == "车辆工程"
        assert u3.grade == "大三"
        stats2 = import_seeds(db=db)
        assert stats2.get("students_created", 0) == 0
        assert db.query(User).filter(User.id.in_([3, 4])).count() == 2

        # 冲突：改坏档案后再导入
        u3.name_masked = "冲突*名"
        db.commit()
        with pytest.raises(SeedStudentConflictError):
            import_seeds(db=db)
        db.refresh(u3)
        assert u3.name_masked == "冲突*名"


def test_integration_stub_matrix_and_p8_closed():
    """T7-G1-INTEGRATION 联调 stub：契约形状 + 隔离矩阵 + P8 仍关闭。

    覆盖：两学生/两岗位、0/1/3 次、跨学生/跨岗位隔离、text/voice/legacy 不可比、
    创建三字段、双向 INPUT_MODE_MISMATCH；不启用 SCORING_VERSION=v1。
    """
    from server.services.scoring import SCORING_VERSION

    assert SCORING_VERSION is None

    client = TestClient(app)
    assert client.post("/api/sessions", json={"job_id": 1}).status_code == 422
    created = client.post(
        "/api/sessions",
        json={"job_id": 1, "user_id": 3, "mode": "毕业生"},
    )
    assert created.status_code == 200
    body = created.json()
    assert set(body.keys()) >= {"sid", "question", "transition_audio_urls"}
    assert body["question"]["seq"] == 1

    students = client.get("/api/students").json()["students"]
    assert [s["id"] for s in students] == [3, 4]

    base = datetime(2026, 9, 21, 9, 0, 0)
    # 学生3 岗位1：三次 text 可比
    s1, _ = _insert_completed(
        user_id=3,
        job_id=1,
        started_at=base,
        dimensions=_dims(70.0, 70.0, None, 70.0),
        scoring_version="fixture-a",
    )
    s2, _ = _insert_completed(
        user_id=3,
        job_id=1,
        started_at=base + timedelta(hours=1),
        dimensions=_dims(72.0, 72.0, None, 72.0),
        scoring_version="fixture-a",
    )
    s3, _ = _insert_completed(
        user_id=3,
        job_id=1,
        started_at=base + timedelta(hours=2),
        dimensions=_dims(74.0, 74.0, None, 74.0),
        scoring_version="fixture-a",
    )
    # 学生4 同岗位；学生3 另一岗位
    s4, _ = _insert_completed(
        user_id=4,
        job_id=1,
        started_at=base + timedelta(hours=3),
        dimensions=_dims(80.0, 80.0, None, 80.0),
        scoring_version="fixture-a",
    )
    _insert_completed(
        user_id=3,
        job_id=2,
        started_at=base + timedelta(hours=4),
        dimensions=_dims(60.0, 60.0, None, 60.0),
        scoring_version="fixture-a",
    )

    hist3 = client.get("/api/growth/3/history", params={"job_id": 1}).json()
    assert [r["session_id"] for r in hist3["records"]] == [s1, s2, s3]
    assert s4 not in [r["session_id"] for r in hist3["records"]]

    hist4 = client.get("/api/growth/4/history", params={"job_id": 1}).json()
    assert [r["session_id"] for r in hist4["records"]] == [s4]

    hist_job2 = client.get("/api/growth/3/history", params={"job_id": 2}).json()
    assert len(hist_job2["records"]) == 1
    assert hist_job2["records"][0]["session_id"] != s1

    trend3 = client.get("/api/growth/3/trend", params={"job_id": 1}).json()
    assert trend3["sessions_count"] == 3
    assert trend3["overall_comparison"]["comparable"] is True

    zero = client.get("/api/growth/4/trend", params={"job_id": 2}).json()
    assert zero["sessions_count"] == 0
    assert zero["overall_comparison"]["reasons"] == ["NO_RECORDS"]

    single = client.get("/api/growth/4/trend", params={"job_id": 1}).json()
    assert single["sessions_count"] == 1
    assert single["overall_comparison"]["reasons"] == ["SINGLE_RECORD"]

    with SessionLocal() as db:
        db.query(Report).delete()
        db.query(Session).delete()
        db.commit()

    _insert_completed(
        user_id=3,
        job_id=1,
        started_at=base,
        dimensions=_dims(70.0, 70.0, None, 70.0),
        input_mode="text",
        scoring_version="fixture-a",
    )
    _insert_completed(
        user_id=3,
        job_id=1,
        started_at=base + timedelta(hours=1),
        dimensions=_dims(75.0, 75.0, 80.0, 75.0),
        input_mode="voice",
        scoring_version="fixture-a",
    )
    mixed = client.get("/api/growth/3/trend", params={"job_id": 1}).json()
    assert "INPUT_MODE_MISMATCH" in mixed["overall_comparison"]["reasons"]

    with SessionLocal() as db:
        db.query(Report).delete()
        db.query(Session).delete()
        db.commit()

    _insert_completed(
        user_id=3,
        job_id=1,
        started_at=base,
        dimensions=_dims(),
        scoring_version=None,
    )
    _insert_completed(
        user_id=3,
        job_id=1,
        started_at=base + timedelta(hours=1),
        dimensions=_dims(72.0, 72.0, None, 72.0),
        scoring_version="fixture-a",
    )
    legacy = client.get("/api/growth/3/trend", params={"job_id": 1}).json()
    assert "SCORING_VERSION_UNKNOWN" in legacy["overall_comparison"]["reasons"]
