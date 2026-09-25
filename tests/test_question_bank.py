from pathlib import Path
import sys
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.import_seeds import import_seeds
from server.api.jobs import get_db
from server.db import Base
from server.main import app
from server.models import Job, Question, Session, User
from server.services.question_bank import get_interview_questions


@pytest.fixture
def bank_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = testing_session_local()
    try:
        seed_path = Path(__file__).resolve().parent.parent / "data" / "jobs_seed.json"
        import_seeds(seed_path=seed_path, db=db)
        yield db, testing_session_local
    finally:
        db.close()


@pytest.fixture
def bank_client(bank_db):
    _, testing_session_local = bank_db

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_custom_question_enters_fixed_interview_slots(bank_client, bank_db):
    db, _ = bank_db
    job_id = db.query(Job).order_by(Job.id.asc()).first().id

    response = bank_client.post(
        f"/api/jobs/{job_id}/questions",
        json={
            "type": "专业",
            "text": "如何设计一套覆盖边界工况的自定义测试用例？",
            "followup_hint": "请说明验证方法",
        },
    )
    assert response.status_code == 201
    custom_id = response.json()["id"]

    questions = get_interview_questions(db, job_id)
    assert len(questions) == 6
    assert [question.type for question in questions] == [
        "通用", "通用", "专业", "专业", "专业", "情景"
    ]
    assert custom_id in {question.id for question in questions}

    listed = bank_client.get(f"/api/jobs/{job_id}/questions").json()["questions"]
    assert len(listed) == 7
    assert sum(question["active_for_interview"] for question in listed) == 6
    assert next(question for question in listed if question["id"] == custom_id)["active_for_interview"]


def test_new_session_starts_with_recently_added_general_questions(bank_client, bank_db, monkeypatch):
    db, testing_session_local = bank_db
    job_id = db.query(Job).order_by(Job.id.asc()).first().id
    db.add(User(id=901, role="student", name_masked="测试同学", major="汽车", grade="大三"))
    db.commit()
    custom_texts = [
        "请分享一次你主动发现并解决技术问题的经历。",
        "你如何把一次团队协作经验迁移到岗位工作中？",
    ]
    for text in custom_texts:
        response = bank_client.post(
            f"/api/jobs/{job_id}/questions",
            json={"type": "通用", "text": text},
        )
        assert response.status_code == 201

    monkeypatch.setattr("server.api.sessions.SessionLocal", testing_session_local)
    question_tts_mock = AsyncMock(return_value={})
    monkeypatch.setattr("server.api.sessions.tts.prefetch_session_questions", question_tts_mock)
    monkeypatch.setattr("server.api.sessions.tts.prefetch_session_transitions", AsyncMock(return_value=[]))
    response = bank_client.post(
        "/api/sessions",
        json={"job_id": job_id, "user_id": 901, "mode": "毕业生"},
    )
    assert response.status_code == 200
    assert response.json()["question"]["text"] == custom_texts[0]
    assert question_tts_mock.await_args.args[1][:2] == custom_texts


def test_custom_question_can_be_edited_and_removed_without_breaking_slots(bank_client, bank_db):
    db, _ = bank_db
    job_id = db.query(Job).order_by(Job.id.asc()).first().id
    create_response = bank_client.post(
        f"/api/jobs/{job_id}/questions",
        json={"type": "通用", "text": "请描述一次你主动解决问题的经历。"},
    )
    custom_id = create_response.json()["id"]

    update_response = bank_client.put(
        f"/api/jobs/{job_id}/questions/{custom_id}",
        json={"text": "请说明一次你主动定位并解决问题的经历。", "followup_hint": "具体做法是什么"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["text"] == "请说明一次你主动定位并解决问题的经历。"

    assert bank_client.delete(f"/api/jobs/{job_id}/questions/{custom_id}").status_code == 204
    assert db.query(Question).filter(Question.job_id == job_id).count() == 6


def test_question_bank_preserves_minimum_counts_and_locks_during_active_sessions(bank_client, bank_db):
    db, _ = bank_db
    job_id = db.query(Job).order_by(Job.id.asc()).first().id
    original = db.query(Question).filter(Question.job_id == job_id).first()
    assert bank_client.delete(f"/api/jobs/{job_id}/questions/{original.id}").status_code == 409

    db.add(Session(user_id=999, job_id=job_id, mode="毕业生", status="active"))
    db.commit()
    response = bank_client.post(
        f"/api/jobs/{job_id}/questions",
        json={"type": "专业", "text": "如何验证新增的故障诊断逻辑？"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "QUESTION_BANK_IN_USE"


def test_question_bank_rejects_invalid_input_and_unknown_job(bank_client):
    invalid = bank_client.post(
        "/api/jobs/1/questions",
        json={"type": "闲聊", "text": "太短"},
    )
    assert invalid.status_code == 422
    missing = bank_client.post(
        "/api/jobs/99999/questions",
        json={"type": "专业", "text": "如何验证新增的故障诊断逻辑？"},
    )
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "JOB_NOT_FOUND"
