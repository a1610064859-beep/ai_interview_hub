from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.api.auth import get_db
from server.db import Base
from server.main import app
from server.models import AuthSession, User
from server.config import settings


@pytest.fixture
def auth_db(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = testing_session_local()
    db.add(User(id=1, role="student", name_masked="王**", major="车辆工程", grade="大三", student_no="STU001"))
    db.commit()
    monkeypatch.setattr(settings, "auth_required", True)
    try:
        yield db, testing_session_local
    finally:
        db.close()


@pytest.fixture
def auth_client(auth_db):
    _, testing_session_local = auth_db

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


def test_student_registration_login_and_logout_use_hashed_credentials(auth_client, auth_db):
    db, _ = auth_db
    register = auth_client.post(
        "/api/auth/register/student",
        json={"email": "student@example.cn", "name": "王小明", "major": "车辆工程", "grade": "大三", "password": "safe-passphrase-2026"},
    )
    assert register.status_code == 201
    assert register.json()["user"]["role"] == "student"
    assert "httponly" in register.headers["set-cookie"].lower()
    assert "samesite=strict" in register.headers["set-cookie"].lower()

    stored_user = db.query(User).filter(User.login_email == "student@example.cn").one()
    assert stored_user.name_masked == "王**"
    assert stored_user.major == "车辆工程"
    assert stored_user.password_hash != "safe-passphrase-2026"
    assert stored_user.password_hash.startswith("pbkdf2_sha256$")
    raw_token = auth_client.cookies.get("aihub_session")
    stored_session = db.query(AuthSession).one()
    assert raw_token and stored_session.token_hash != raw_token

    auth_client.cookies.clear()
    login = auth_client.post(
        "/api/auth/login/student",
        json={"email": "student@example.cn", "password": "safe-passphrase-2026"},
    )
    assert login.status_code == 200
    assert auth_client.get("/api/auth/me").json()["user"]["login_email"] == "student@example.cn"
    assert auth_client.post("/api/auth/logout").status_code == 200
    assert auth_client.get("/api/auth/me").json()["authenticated"] is False


def test_student_registration_rejects_duplicate_email_and_injection(auth_client):
    created = auth_client.post(
        "/api/auth/register/student",
        json={"email": "same@example.cn", "name": "李同学", "major": "车辆工程", "grade": "大三", "password": "safe-passphrase-2026"},
    )
    assert created.status_code == 201
    duplicate = auth_client.post(
        "/api/auth/register/student",
        json={"email": "same@example.cn", "name": "李同学", "major": "车辆工程", "grade": "大三", "password": "another-safe-passphrase"},
    )
    assert duplicate.status_code == 400

    injection = auth_client.post(
        "/api/auth/login/student",
        json={"email": "x'OR'1'='1--@example.cn", "password": "anything-long-enough"},
    )
    assert injection.status_code == 401


def test_protected_routes_require_authentication(auth_client):
    assert auth_client.get("/api/recruiter/candidates?job_id=1").status_code == 401
    assert auth_client.get("/api/students").status_code == 401
    assert auth_client.post("/api/sessions", json={"job_id": 1, "user_id": 1}).status_code == 401


def test_recruiter_registration_and_role_protection(auth_client):
    register = auth_client.post(
        "/api/auth/register/recruiter",
        json={
            "email": "hr@example.cn",
            "organization_name": "示例汽车科技",
            "contact_name": "招聘负责人",
            "password": "secure-company-passphrase",
        },
    )
    assert register.status_code == 201
    assert register.json()["user"]["role"] == "recruiter"
    assert auth_client.post(
        "/api/sessions",
        json={"job_id": 1, "user_id": 1, "mode": "毕业生"},
    ).status_code == 403


def test_student_cannot_open_enterprise_apis_or_another_students_growth(auth_client):
    register = auth_client.post(
        "/api/auth/register/student",
        json={"email": "student2@example.cn", "name": "赵同学", "major": "车辆工程", "grade": "大三", "password": "safe-passphrase-2026"},
    )
    assert register.status_code == 201
    assert auth_client.get("/api/recruiter/candidates?job_id=1").status_code == 403
    assert auth_client.get("/api/growth/1/history").status_code == 404
