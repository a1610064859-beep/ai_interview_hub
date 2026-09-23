import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.import_seeds import import_seeds, SeedStudentConflictError
from server.api.jobs import get_db
from server.db import Base
from server.main import app
from server.models import Job, Question, User


@pytest.fixture
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestingSessionLocal()
    try:
        yield db, TestingSessionLocal
    finally:
        db.close()


@pytest.fixture
def client(test_db):
    _, TestingSessionLocal = test_db

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# 1. 题库导入与幂等性测试（重复导入不重复建题）
def test_import_seeds_idempotent(test_db):
    db, TestingSessionLocal = test_db
    seed_path = Path(__file__).resolve().parent.parent / "data" / "jobs_seed.json"

    # 首次导入
    stats1 = import_seeds(seed_path=seed_path, db=db)
    assert stats1["jobs_created"] == 2
    assert stats1["questions_created"] == 12

    assert db.query(Job).count() == 2
    assert db.query(Question).count() == 12

    # 二次导入，验证不重复插入
    stats2 = import_seeds(seed_path=seed_path, db=db)
    assert stats2["jobs_created"] == 0
    assert stats2["questions_created"] == 0

    assert db.query(Job).count() == 2
    assert db.query(Question).count() == 12


# 2. GET /api/jobs 空列表测试
def test_get_jobs_empty(client):
    response = client.get("/api/jobs")
    assert response.status_code == 200
    assert response.json() == {"jobs": []}


# 3. GET /api/jobs 正常列表测试（按 id 升序）
def test_get_jobs_success(client, test_db):
    db, _ = test_db
    seed_path = Path(__file__).resolve().parent.parent / "data" / "jobs_seed.json"
    import_seeds(seed_path=seed_path, db=db)

    response = client.get("/api/jobs")
    assert response.status_code == 200
    data = response.json()
    assert "jobs" in data
    assert len(data["jobs"]) == 2

    job1, job2 = data["jobs"][0], data["jobs"][1]
    assert job1["id"] < job2["id"]
    assert job1["family"] in ["智驾", "三电"]
    assert "title" in job1
    assert "jd_digest" in job1


# 4. GET /api/jobs/{job_id}/questions 正常获取测试（按 id 升序）
def test_get_job_questions_success(client, test_db):
    db, _ = test_db
    seed_path = Path(__file__).resolve().parent.parent / "data" / "jobs_seed.json"
    import_seeds(seed_path=seed_path, db=db)

    first_job = db.query(Job).order_by(Job.id.asc()).first()
    assert first_job is not None

    response = client.get(f"/api/jobs/{first_job.id}/questions")
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == first_job.id
    assert "questions" in data
    assert len(data["questions"]) == 6

    # 验证题目按 id 升序且结构符合契约
    ids = [q["id"] for q in data["questions"]]
    assert ids == sorted(ids)
    for q in data["questions"]:
        assert "id" in q
        assert q["type"] in ["通用", "专业", "情景"]
        assert len(q["text"]) > 0


# 5. GET /api/jobs/{job_id}/questions 岗位不存在 404 测试
def test_get_job_questions_not_found(client):
    response = client.get("/api/jobs/99999/questions")
    assert response.status_code == 404
    err = response.json()
    assert err["detail"]["code"] == "JOB_NOT_FOUND"
    assert "不存在" in err["detail"]["message"]


# 6. GET /api/jobs/{job_id}/questions 非正整数 ID 422 测试
def test_get_job_questions_invalid_id(client):
    # 非法数字（0 或负数）
    res_zero = client.get("/api/jobs/0/questions")
    assert res_zero.status_code == 422

    res_neg = client.get("/api/jobs/-1/questions")
    assert res_neg.status_code == 422

    # 非法非数字字符串
    res_str = client.get("/api/jobs/not-an-id/questions")
    assert res_str.status_code == 422


# 7. 种子学生幂等与冲突即失败
def test_seed_students_idempotent_and_conflict(test_db):
    db, _ = test_db
    seed_path = Path(__file__).resolve().parent.parent / "data" / "jobs_seed.json"

    stats1 = import_seeds(seed_path=seed_path, db=db)
    assert stats1["students_created"] == 2
    u3 = db.query(User).filter(User.id == 3).one()
    u4 = db.query(User).filter(User.id == 4).one()
    assert u3.name_masked == "王*明"
    assert u4.name_masked == "李*华"

    stats2 = import_seeds(seed_path=seed_path, db=db)
    assert stats2["students_created"] == 0
    assert stats2["students_existing"] == 2

    u3.name_masked = "冲突*名"
    db.commit()
    with pytest.raises(SeedStudentConflictError):
        import_seeds(seed_path=seed_path, db=db)
    db.refresh(u3)
    assert u3.name_masked == "冲突*名"

