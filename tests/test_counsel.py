from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from server.db import Base, SessionLocal
from server.main import app
from server.models import Job, Report, Session, User
from server.schemas import CounselLlmResponse, CounselResponse


@pytest.fixture(autouse=True)
def counsel_db(monkeypatch):
    import server.db as db_module

    Base.metadata.drop_all(db_module.engine)
    Base.metadata.create_all(db_module.engine)
    with SessionLocal() as db:
        db.add_all([
            User(id=3, role="student", name_masked="王*明", major="车辆工程", grade="大一"),
            User(id=4, role="student", name_masked="李*华", major="汽车电子", grade="大二"),
            Job(id=1, family="智驾", title="智驾测试", jd_digest="jd", terms_json=[], dims_json=[]),
            Job(id=2, family="三电", title="三电系统测试", jd_digest="jd", terms_json=[], dims_json=[]),
        ])
        db.commit()
    yield
    Base.metadata.drop_all(db_module.engine)


def _post(body=None):
    return TestClient(app).post("/api/counsel", json=body or {
        "major": "车辆工程", "grade": "大一", "interests": ["自动驾驶", "传感器"]
    })


def _assert_strict_response(data: dict) -> None:
    parsed = CounselResponse.model_validate(data)
    assert parsed.mode == "新生"
    assert len(parsed.job_map) == 2
    assert {item.job_id for item in parsed.job_map} == {1, 2}
    assert "user_id" not in data
    assert "score" not in data
    assert "overall" not in data
    blob = str(data).lower()
    assert "\"score\"" not in blob
    assert "weighted_score" not in blob
    assert parsed.learning_path.grade in {"大一", "大二", "大三", "大四"}
    assert isinstance(parsed.learning_path.milestones, list)
    for milestone in parsed.learning_path.milestones:
        assert milestone.term
        assert all(isinstance(item, str) and item for item in milestone.items)
    assert parsed.train_hint.mode == "新生"
    assert parsed.train_hint.job_id == parsed.recommended_job_id


def test_counsel_happy_path_two_seed_jobs(monkeypatch):
    llm = AsyncMock(return_value=CounselLlmResponse(
        recommended_job_id=1,
        fit_summaries={"1": "适合智驾验证", "2": "可了解三电测试"},
    ))
    monkeypatch.setattr("server.services.counsel.chat_json", llm)
    response = _post()
    assert response.status_code == 200
    data = response.json()
    _assert_strict_response(data)
    assert data["degraded"] is False
    assert [item["job_id"] for item in data["job_map"]] == [1, 2]
    assert data["train_hint"] == {"job_id": data["recommended_job_id"], "mode": "新生"}
    assert llm.await_args.args[0] == "counsel"
    assert llm.await_args.args[2] is CounselLlmResponse


def test_empty_interests_and_llm_failure_degrade(monkeypatch):
    monkeypatch.setattr("server.services.counsel.chat_json", AsyncMock(side_effect=RuntimeError("offline")))
    response = _post({"major": "车辆工程", "grade": "大二", "interests": []})
    assert response.status_code == 200
    data = response.json()
    assert data["degraded"] is True
    assert data["recommended_job_id"] in {1, 2}
    _assert_strict_response(data)


@pytest.mark.parametrize("body", [
    {"major": "", "grade": "大一", "interests": []},
    {"major": "车辆工程", "grade": "研一", "interests": []},
    {"major": "车辆工程", "grade": "大一", "interests": [""]},
    {"major": "车辆工程", "grade": "大一", "interests": [], "user_id": 3},
])
def test_invalid_request_is_422(body):
    assert _post(body).status_code == 422


def test_third_job_is_clamped_and_counsel_writes_nothing(monkeypatch):
    monkeypatch.setattr(
        "server.services.counsel.chat_json",
        AsyncMock(return_value={
            "recommended_job_id": 999,
            "fit_summaries": {"999": "飞行汽车工程师"},
        }),
    )
    with SessionLocal() as db:
        users_before = [(u.id, u.major, u.grade) for u in db.query(User).order_by(User.id)]
    data = _post().json()
    _assert_strict_response(data)
    assert [j["title"] for j in data["job_map"]] == ["智驾测试", "三电系统测试"]
    assert data["recommended_job_id"] in {1, 2}
    assert data["degraded"] is True
    with SessionLocal() as db:
        assert [(u.id, u.major, u.grade) for u in db.query(User).order_by(User.id)] == users_before
        assert db.query(Session).count() == 0
        assert db.query(Report).count() == 0


def test_malformed_llm_payload_is_degraded_or_clamped(monkeypatch):
    """恶意/畸形 LLM：score、user_id、错误 milestones、第三岗信息 → 降级或钳制，结构仍合法。"""
    monkeypatch.setattr(
        "server.services.counsel.chat_json",
        AsyncMock(return_value={
            "recommended_job_id": 1,
            "fit_summaries": {"1": "ok"},
            "score": 88,
            "user_id": 3,
            "overall": 90,
            "learning_path": {
                "grade": "大一",
                "theme": "伪造路径",
                "milestones": "not-a-list",
                "score": 77,
            },
            "job_map": [{
                "job_id": 999,
                "family": "航天",
                "title": "第三岗位",
                "chain_role": "x",
                "core_skills": ["x"],
                "fit_summary": "y",
                "score": 99,
            }],
        }),
    )
    response = _post()
    assert response.status_code == 200
    data = response.json()
    _assert_strict_response(data)
    # extra 字段导致 CounselLlmResponse 校验失败 → 静态降级
    assert data["degraded"] is True
    assert [j["title"] for j in data["job_map"]] == ["智驾测试", "三电系统测试"]
    assert data["learning_path"]["theme"] == "打基础：编程、汽车构造与电路认知"
    assert isinstance(data["learning_path"]["milestones"], list)
    assert all(isinstance(m.get("items"), list) for m in data["learning_path"]["milestones"])


def test_a15_counsel_stage_always_via_chat_json(monkeypatch):
    """A15：counsel 必经 chat_json('counsel', ...)；成败均由该封装承接（usage 由 LLMClient 记账）。"""
    stages: list[str] = []

    async def ok(stage, messages, response_model):
        stages.append(stage)
        assert response_model is CounselLlmResponse
        return CounselLlmResponse(recommended_job_id=1, fit_summaries={"1": "ok"})

    monkeypatch.setattr("server.services.counsel.chat_json", ok)
    assert _post().status_code == 200
    assert stages == ["counsel"]

    stages.clear()

    async def fail(stage, messages, response_model):
        stages.append(stage)
        assert stage == "counsel"
        assert response_model is CounselLlmResponse
        raise RuntimeError("offline")

    monkeypatch.setattr("server.services.counsel.chat_json", fail)
    degraded = _post().json()
    assert stages == ["counsel"]
    assert degraded["degraded"] is True
    _assert_strict_response(degraded)


def test_a9_train_entry_creates_session_as_freshman(monkeypatch):
    """A9 stub：咨询后按 deep-link 契约创建会话，body 含 user_id/job_id/mode=新生。"""
    monkeypatch.setattr(
        "server.services.counsel.chat_json",
        AsyncMock(return_value=CounselLlmResponse(recommended_job_id=1, fit_summaries={})),
    )
    # stub TTS prefetch so session create does not need network
    async def _empty_prefetch(*_args, **_kwargs):
        return {}

    async def _empty_transitions(*_args, **_kwargs):
        return []

    monkeypatch.setattr("server.services.tts.prefetch_session_questions", _empty_prefetch)
    monkeypatch.setattr("server.services.tts.prefetch_session_transitions", _empty_transitions)

    with SessionLocal() as db:
        from server.models import Question

        if db.query(Question).filter(Question.job_id == 1).count() == 0:
            db.add(Question(job_id=1, type="通用", text="Q1", followup_hint="h"))
            db.commit()

    counsel = _post().json()
    job_id = counsel["recommended_job_id"]
    user_id = 3
    # mirrors web/app/counsel href: /?user_id=&job_id=&mode=新生
    assert counsel["train_hint"] == {"job_id": job_id, "mode": "新生"}
    create = TestClient(app).post(
        "/api/sessions",
        json={"user_id": user_id, "job_id": job_id, "mode": "新生"},
    )
    assert create.status_code == 200, create.text
    sid = create.json()["sid"]
    with SessionLocal() as db:
        sess = db.query(Session).filter(Session.id == sid).one()
        assert sess.user_id == user_id
        assert sess.job_id == job_id
        assert sess.mode == "新生"


def test_a2_two_students_isolation_after_freshman_sessions(monkeypatch):
    """A2：两名学生各自新生会话互不混入成长 history。"""
    monkeypatch.setattr(
        "server.services.counsel.chat_json",
        AsyncMock(return_value=CounselLlmResponse(recommended_job_id=1, fit_summaries={})),
    )

    async def _empty_prefetch(*_args, **_kwargs):
        return {}

    async def _empty_transitions(*_args, **_kwargs):
        return []

    monkeypatch.setattr("server.services.tts.prefetch_session_questions", _empty_prefetch)
    monkeypatch.setattr("server.services.tts.prefetch_session_transitions", _empty_transitions)

    # Session create needs at least one question per job
    with SessionLocal() as db:
        from server.models import Question

        db.add_all([
            Question(job_id=1, type="通用", text="Q1", followup_hint="h"),
            Question(job_id=1, type="通用", text="Q2", followup_hint="h"),
            Question(job_id=1, type="专业", text="Q3", followup_hint="h"),
            Question(job_id=1, type="专业", text="Q4", followup_hint="h"),
            Question(job_id=1, type="专业", text="Q5", followup_hint="h"),
            Question(job_id=1, type="情景", text="Q6", followup_hint="h"),
        ])
        db.commit()

    client = TestClient(app)
    sids: dict[int, int] = {}
    for user_id in (3, 4):
        created = client.post(
            "/api/sessions",
            json={"user_id": user_id, "job_id": 1, "mode": "新生"},
        )
        assert created.status_code == 200, created.text
        sid = created.json()["sid"]
        sids[user_id] = sid
        with SessionLocal() as db:
            sess = db.query(Session).filter(Session.id == sid).one()
            sess.status = "completed"
            sess.input_mode = "text"
            db.add(
                Report(
                    session_id=sid,
                    dimensions_json={
                        "professional_match": {"score": 70.0, "evidence": "a", "reason": "r"},
                        "logic_structure": {"score": 70.0, "evidence": "a", "reason": "r"},
                        "expression_fluency": {
                            "score": None,
                            "evidence": None,
                            "reason": "文本模式，未评估语音流畅度",
                        },
                        "job_competence": {"score": 70.0, "evidence": "a", "reason": "r"},
                    },
                    highlights_json=[],
                    concerns_json=[],
                    improvement_json=["复盘一次"],
                    overall=70.0,
                    scoring_version="v1",
                )
            )
            db.commit()

    hist3 = client.get("/api/growth/3/history?job_id=1").json()
    hist4 = client.get("/api/growth/4/history?job_id=1").json()
    assert [r["session_id"] for r in hist3["records"]] == [sids[3]]
    assert [r["session_id"] for r in hist4["records"]] == [sids[4]]
    assert sids[3] != sids[4]


def test_seed_jobs_unavailable(monkeypatch):
    with SessionLocal() as db:
        db.query(Job).filter(Job.id == 2).delete()
        db.commit()
    response = _post()
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "SEED_JOBS_UNAVAILABLE"
