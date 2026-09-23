import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from server.main import app
from server.db import Base, SessionLocal, ensure_schema_upgrades
from server.models import User, Job, Question, Session, Answer, Report
from server.config import settings
from server.services.scoring import SingleDimensionScore, SingleScoringResult, ScoringUnavailableError


@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch):
    # 文本编排用例不依赖真实 TTS；关闭以避免 edge-tts 可用时 audio_url 非 null 破坏契约断言
    monkeypatch.setattr(settings, "tts_enabled", False)
    # conftest.py 已将 DATABASE_URL 指向临时库；整库重建保证每个用例从空库开始
    from server.db import engine
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    ensure_schema_upgrades(engine)

    with SessionLocal() as db:
        # 预置用户
        user = User(id=1, role="student", name_masked="张**", major="车辆工程", grade="大三")
        db.add(user)
        
        # 预置岗位 (智驾测试)
        job = Job(
            id=1,
            family="智驾",
            title="智驾测试",
            jd_digest="负责智驾测试用例设计与总线通信测试",
            terms_json=["CANoe", "CANalyzer", "时间戳", "丢包率"],
            dims_json={"专业匹配度": 0.4, "逻辑结构": 0.3, "岗位素养": 0.3},
        )
        db.add(job)
        
        # 预置 6 道题 (2通用 + 3专业 + 1情景)
        q_types = ["通用", "通用", "专业", "专业", "专业", "情景"]
        for idx, qt in enumerate(q_types, start=1):
            q = Question(
                id=idx,
                job_id=1,
                type=qt,
                text=f"第{idx}题（{qt}）：请回答关于测试的专业问题。",
                followup_hint=f"第{idx}题追问提示",
            )
            db.add(q)
        db.commit()
    yield


def test_happy_path_full_text_interview():
    client = TestClient(app)
    
    # 1. 创建会话 POST /api/sessions
    resp = client.post("/api/sessions", json={"job_id": 1, "user_id": 1, "mode": "毕业生"})
    assert resp.status_code == 200
    data = resp.json()
    assert "sid" in data
    sid = data["sid"]
    assert data["question"]["seq"] == 1
    assert data["question"]["audio_url"] is None
    assert "第1题" in data["question"]["text"]

    # 验证数据库中初始状态
    with SessionLocal() as db:
        sess = db.query(Session).filter(Session.id == sid).first()
        assert sess is not None
        assert sess.mode == "毕业生"
        assert sess.status == "active"
        assert sess.pending_question_json["seq"] == 1
        assert sess.pending_question_json["is_followup"] is False

    # 2. 第 1 题触发追问
    with patch("server.services.orchestrator.evaluate_followup", AsyncMock(return_value="请展开说明如何使用CANoe排查总线？")):
        ans_resp = client.post(
            f"/api/sessions/{sid}/answers/text",
            json={"answer_text": "在测试中我经常使用CANoe分析报文丢包率。"},
        )
        assert ans_resp.status_code == 200
        ans_data = ans_resp.json()
        assert ans_data["type"] == "followup"
        assert ans_data["question"]["seq"] == 1
        assert ans_data["question"]["audio_url"] is None
        assert ans_data["question"]["text"] == "请展开说明如何使用CANoe排查总线？"

    # 验证 DB: answers 存了一条主问题作答，当前待答是追问
    with SessionLocal() as db:
        ans_list = db.query(Answer).filter(Answer.session_id == sid).all()
        assert len(ans_list) == 1
        assert ans_list[0].q_seq == 1
        assert ans_list[0].is_followup is False
        assert ans_list[0].filler_cnt == 0
        assert ans_list[0].duration_s is None
        sess = db.query(Session).filter(Session.id == sid).first()
        assert sess.pending_question_json["seq"] == 1
        assert sess.pending_question_json["is_followup"] is True

    # 3. 回答追问，应该推进到第 2 题 (下一题，type=next, seq=2)
    ans_resp = client.post(
        f"/api/sessions/{sid}/answers/text",
        json={"answer_text": "那个...首先看Trace窗口的时间戳，然后过滤错误帧。"},
    )
    assert ans_resp.status_code == 200
    ans_data = ans_resp.json()
    assert ans_data["type"] == "next"
    assert ans_data["question"]["seq"] == 2
    assert ans_data["question"]["audio_url"] is None

    # 验证填充词识别 (那个, 然后)
    with SessionLocal() as db:
        ans_list = db.query(Answer).filter(Answer.session_id == sid).all()
        assert len(ans_list) == 2
        assert ans_list[1].is_followup is True
        assert ans_list[1].filler_cnt == 2

    # 4. 连续回答第 2~5 题 (不再追问)
    with patch("server.services.orchestrator.evaluate_followup", AsyncMock(return_value=None)):
        for expected_next_seq in [3, 4, 5, 6]:
            ans_resp = client.post(
                f"/api/sessions/{sid}/answers/text",
                json={"answer_text": f"这是对前一道题目的详细技术回答，展示专业能力。"},
            )
            assert ans_resp.status_code == 200
            ans_data = ans_resp.json()
            assert ans_data["type"] == "next"
            assert ans_data["question"]["seq"] == expected_next_seq

    # 5. 回答第 6 题 (最后一题，触发终面评分落库)
    mock_scoring_result = {
        "dimensions": {
            "professional_match": {"score": 88.0, "evidence": "使用CANoe分析报文", "reason": "熟练"},
            "logic_structure": {"score": 82.5, "evidence": "首先看Trace窗口", "reason": "清晰"},
            "expression_fluency": {"score": None, "evidence": None, "reason": "文本模式，未评估语音流畅度"},
            "job_competence": {"score": 83.5, "evidence": "过滤错误帧", "reason": "规范"},
        },
        "highlights": ["总线分析能力强"],
        "concerns": ["需加强自动化脚本"],
        "improvement": ["建议学习CAPL"],
        "overall": 84.7,
        "scoring_version": "v1",
    }

    with patch("server.services.orchestrator.evaluate_followup", AsyncMock(return_value=None)), \
         patch("server.services.scoring.score_interview", AsyncMock(return_value=mock_scoring_result)):
        ans_resp = client.post(
            f"/api/sessions/{sid}/answers/text",
            json={"answer_text": "在面对量产前重大Bug时，必须阻断发布并组织评审，过滤错误帧。"},
        )
        assert ans_resp.status_code == 200
        ans_data = ans_resp.json()
        assert ans_data["type"] == "done"
        assert "report_id" in ans_data
        report_id = ans_data["report_id"]

    # 6. 查询报告 GET /api/reports/{sid}
    rep_resp = client.get(f"/api/reports/{sid}")
    assert rep_resp.status_code == 200
    rep_data = rep_resp.json()
    assert rep_data["id"] == report_id
    assert rep_data["session_id"] == sid
    assert rep_data["job_title"] == "智驾测试"
    assert rep_data["overall"] == 84.7
    assert rep_data["dimensions"]["expression_fluency"]["score"] is None
    assert rep_data["dimensions"]["expression_fluency"]["reason"] == "文本模式，未评估语音流畅度"
    assert rep_data["dimensions"]["professional_match"]["score"] == 88.0
    assert rep_data["highlights"] == ["总线分析能力强"]

    with SessionLocal() as db:
        stored = db.query(Report).filter(Report.id == report_id).one()
        assert stored.scoring_version == "v1"


@pytest.mark.anyio
async def test_concurrency_scenario_1_a_processing_b_returns_409():
    """场景 1：A 处理中，B 提交返回 409 ANSWER_IN_PROGRESS"""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/sessions", json={"job_id": 1, "user_id": 1, "mode": "毕业生"})
        sid = resp.json()["sid"]

        a_entered = asyncio.Event()
        a_can_proceed = asyncio.Event()

        async def mock_slow_followup(*args, **kwargs):
            a_entered.set()
            await a_can_proceed.wait()
            return None

        with patch("server.services.orchestrator.evaluate_followup", mock_slow_followup):
            task_a = asyncio.create_task(
                client.post(f"/api/sessions/{sid}/answers/text", json={"answer_text": "A回答"})
            )
            await a_entered.wait()

            # B 提交，应被 409 ANSWER_IN_PROGRESS 拦截
            resp_b = await client.post(f"/api/sessions/{sid}/answers/text", json={"answer_text": "B回答"})
            assert resp_b.status_code == 409
            assert resp_b.json()["detail"]["code"] == "ANSWER_IN_PROGRESS"

            # 放行 A
            a_can_proceed.set()
            resp_a = await task_a
            assert resp_a.status_code == 200


@pytest.mark.anyio
async def test_concurrency_scenario_2_a_expired_b_takes_over_a_late_commit_rolled_back():
    """场景 2：A 过期，B 接管。A 迟到的写入失败（回滚，不污染 DB）"""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/sessions", json={"job_id": 1, "user_id": 1, "mode": "毕业生"})
        sid = resp.json()["sid"]

        a_entered = asyncio.Event()
        a_can_proceed = asyncio.Event()

        async def mock_hanging_followup(*args, **kwargs):
            a_entered.set()
            await a_can_proceed.wait()
            return None

        with patch("server.services.orchestrator.evaluate_followup", mock_hanging_followup):
            task_a = asyncio.create_task(
                client.post(f"/api/sessions/{sid}/answers/text", json={"answer_text": "A回答"})
            )
            await a_entered.wait()

            # 模拟 A 租约已超时过期
            with SessionLocal() as db:
                sess = db.query(Session).filter(Session.id == sid).first()
                sess.lease_expires_at = datetime.utcnow() - timedelta(seconds=10)
                db.commit()

            # 请求 B 抢占租约并成功完成
            with patch("server.services.orchestrator.evaluate_followup", AsyncMock(return_value=None)):
                resp_b = await client.post(f"/api/sessions/{sid}/answers/text", json={"answer_text": "B回答"})
                assert resp_b.status_code == 200

            # 放行 A，A 恢复执行后尝试提交事务 3，因 lease_token 已变更而失败
            a_can_proceed.set()
            resp_a = await task_a
            assert resp_a.status_code == 409
            assert resp_a.json()["detail"]["code"] == "ANSWER_IN_PROGRESS"

            # 检查数据库：只有 B 的回答，绝无 A 的残留
            with SessionLocal() as db:
                ans_list = db.query(Answer).filter(Answer.session_id == sid).all()
                assert len(ans_list) == 1
                assert ans_list[0].answer_text == "B回答"


@pytest.mark.anyio
async def test_concurrency_scenario_3_a_late_exception_does_not_unlock_b():
    """场景 3：A 迟到的异常清理不释放 B 的有效租约"""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/sessions", json={"job_id": 1, "user_id": 1, "mode": "毕业生"})
        sid = resp.json()["sid"]

        a_entered = asyncio.Event()
        a_fail_event = asyncio.Event()
        b_entered = asyncio.Event()
        b_can_proceed = asyncio.Event()

        async def mock_a_hang_and_fail(*args, **kwargs):
            a_entered.set()
            await a_fail_event.wait()
            raise RuntimeError("A crashed")

        async def mock_b_hang(*args, **kwargs):
            b_entered.set()
            await b_can_proceed.wait()
            return None

        # 启动 A
        with patch("server.services.orchestrator.evaluate_followup", mock_a_hang_and_fail):
            task_a = asyncio.create_task(
                client.post(f"/api/sessions/{sid}/answers/text", json={"answer_text": "A回答"})
            )
            await a_entered.wait()

            # 让 A 租约过期
            with SessionLocal() as db:
                sess = db.query(Session).filter(Session.id == sid).first()
                sess.lease_expires_at = datetime.utcnow() - timedelta(seconds=10)
                db.commit()

            # 启动 B，B 接管持有新租约
            with patch("server.services.orchestrator.evaluate_followup", mock_b_hang):
                task_b = asyncio.create_task(
                    client.post(f"/api/sessions/{sid}/answers/text", json={"answer_text": "B回答"})
                )
                await b_entered.wait()

                # 此时 B 正持有锁。触发 A 报错并执行 finally 清理
                a_fail_event.set()
                with pytest.raises(Exception):
                    await task_a

                # 验证 B 的租约未被 A 误解除
                with SessionLocal() as db:
                    sess = db.query(Session).filter(Session.id == sid).first()
                    assert sess.status == "answering"
                    assert sess.lease_token is not None

                # 放行 B，B 正常完成
                b_can_proceed.set()
                resp_b = await task_b
                assert resp_b.status_code == 200



def test_concurrency_scenario_4_crash_recovery_expired_lease_taken_over():
    """场景 4：崩溃恢复（后续请求成功接管过期租约）"""
    client = TestClient(app)
    resp = client.post("/api/sessions", json={"job_id": 1, "user_id": 1, "mode": "毕业生"})
    sid = resp.json()["sid"]

    # 模拟系统崩溃硬重启后遗留的状态
    with SessionLocal() as db:
        sess = db.query(Session).filter(Session.id == sid).first()
        sess.status = "answering"
        sess.lease_token = "crashed_dead_token"
        sess.lease_expires_at = datetime.utcnow() - timedelta(seconds=60)
        db.commit()

    # 新请求提交，能够顺利接管
    with patch("server.services.orchestrator.evaluate_followup", AsyncMock(return_value=None)):
        ans_resp = client.post(f"/api/sessions/{sid}/answers/text", json={"answer_text": "接管作答"})
        assert ans_resp.status_code == 200
        assert ans_resp.json()["type"] == "next"

    with SessionLocal() as db:
        sess = db.query(Session).filter(Session.id == sid).first()
        assert sess.status == "active"
        assert sess.lease_token is None


def test_concurrency_scenario_5_scoring_503_rollback_and_retry():
    """场景 5：评分 503 失败后状态正确回滚，后续提交可重试"""
    client = TestClient(app)
    resp = client.post("/api/sessions", json={"job_id": 1, "user_id": 1, "mode": "毕业生"})
    sid = resp.json()["sid"]

    # 将进度调整到最后一题 (seq=6)
    with SessionLocal() as db:
        sess = db.query(Session).filter(Session.id == sid).first()
        sess.pending_question_json = {"seq": 6, "text": "情景题", "audio_url": None, "is_followup": True}
        # 填充前 5 题及第 6 题主答
        for i in range(1, 6):
            db.add(Answer(session_id=sid, q_seq=i, question_text="q", answer_text="a", is_followup=False, is_retry=False))
        db.add(Answer(session_id=sid, q_seq=6, question_text="q6", answer_text="a6", is_followup=False, is_retry=False))
        db.commit()

    # 模拟评分模型全挂抛 503
    with patch("server.services.scoring.score_interview", AsyncMock(side_effect=ScoringUnavailableError("model down"))):
        ans_resp = client.post(f"/api/sessions/{sid}/answers/text", json={"answer_text": "第6题作答"})
        assert ans_resp.status_code == 503
        assert ans_resp.json()["detail"]["code"] == "SCORING_UNAVAILABLE"

    # 断言会话回滚为 active，未插入新的第 6 题 answer，未生成 report
    with SessionLocal() as db:
        sess = db.query(Session).filter(Session.id == sid).first()
        assert sess.status == "active"
        assert sess.lease_token is None
        assert db.query(Report).filter(Report.session_id == sid).count() == 0
        ans_count = db.query(Answer).filter(Answer.session_id == sid).count()
        assert ans_count == 6  # 还是原来的 6 条，未新增

    # 恢复评分模型，重试提交第 6 题追问回答，成功完成并生成报告
    mock_rep = {
        "dimensions": {
            "professional_match": {"score": 85.0, "evidence": "第6题作答", "reason": "好"},
            "logic_structure": {"score": 80.0, "evidence": "第6题作答", "reason": "清晰"},
            "expression_fluency": {"score": None, "evidence": None, "reason": "文本模式，未评估语音流畅度"},
            "job_competence": {"score": 85.0, "evidence": "第6题作答", "reason": "素养良好"},
        },
        "highlights": ["表现优秀"],
        "concerns": [],
        "improvement": ["继续保持"],
        "overall": 83.3,
        "scoring_version": "v1",
    }
    with patch("server.services.scoring.score_interview", AsyncMock(return_value=mock_rep)):
        retry_resp = client.post(f"/api/sessions/{sid}/answers/text", json={"answer_text": "第6题重试作答"})
        assert retry_resp.status_code == 200
        assert retry_resp.json()["type"] == "done"

    with SessionLocal() as db:
        assert db.query(Report).filter(Report.session_id == sid).count() == 1


def test_database_upgrade_and_historical_session_reset():
    """测试数据库升级及无待答快照历史会话明确返回 409 SESSION_RESET_REQUIRED"""
    client = TestClient(app)

    # 1. 模拟旧版本数据库历史会话（pending_question_json 为 NULL）
    with SessionLocal() as db:
        old_sess = Session(
            id=999,
            user_id=1,
            job_id=1,
            mode="毕业生",
            status="active",
            pending_question_json=None,
            lease_token=None,
            lease_expires_at=None,
        )
        db.add(old_sess)
        db.commit()

    # 2. 提交答案，应明确拒绝并提示重新开始
    resp = client.post("/api/sessions/999/answers/text", json={"answer_text": "测试旧会话作答"})
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "SESSION_RESET_REQUIRED"


def test_api_error_codes():
    client = TestClient(app)

    # 1. 404 JOB_NOT_FOUND
    r = client.post("/api/sessions", json={"job_id": 99999, "user_id": 1, "mode": "毕业生"})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "JOB_NOT_FOUND"

    # 2. 404 SESSION_NOT_FOUND
    r = client.post("/api/sessions/99999/answers/text", json={"answer_text": "回答"})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "SESSION_NOT_FOUND"

    # 3. 404 REPORT_NOT_FOUND (会话存在但尚未生成报告)
    sess_r = client.post("/api/sessions", json={"job_id": 1, "user_id": 1, "mode": "毕业生"})
    sid = sess_r.json()["sid"]
    rep_r = client.get(f"/api/reports/{sid}")
    assert rep_r.status_code == 404
    assert rep_r.json()["detail"]["code"] == "REPORT_NOT_FOUND"

    # 4. 404 SESSION_NOT_FOUND (报告查询时会话不存在)
    rep_r2 = client.get("/api/reports/88888")
    assert rep_r2.status_code == 404
    assert rep_r2.json()["detail"]["code"] == "SESSION_NOT_FOUND"

    # 5. 422 验证错误
    # 空内容
    r = client.post(f"/api/sessions/{sid}/answers/text", json={"answer_text": "   "})
    assert r.status_code == 422
    # 拒绝额外字段
    r = client.post(f"/api/sessions/{sid}/answers/text", json={"answer_text": "合法内容", "extra": "invalid"})
    assert r.status_code == 422


def test_database_schema_upgrade_lifecycle(tmp_path):
    """测试数据库升级生命周期：
    1. 首次全新建库生成所有表与新列；
    2. 模拟旧版本库（无新列）升级，原数据完整保留；
    3. 重复执行升级保持幂等。
    """
    from server.db import init_db

    # 1. 首次全新建库
    fresh_db_path = tmp_path / "fresh.db"
    fresh_engine = create_engine(f"sqlite:///{fresh_db_path}")
    init_db(fresh_engine)

    with fresh_engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(sessions)")).fetchall()}
        assert "pending_question_json" in cols
        assert "lease_token" in cols
        assert "lease_expires_at" in cols

    # 2. 模拟旧表（仅有旧列），先手工建立旧 sessions 表并插入数据
    legacy_db_path = tmp_path / "legacy.db"
    legacy_engine = create_engine(f"sqlite:///{legacy_db_path}")
    with legacy_engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE sessions (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                job_id INTEGER,
                mode VARCHAR(32),
                started_at DATETIME,
                status VARCHAR(32)
            )
        """))
        conn.execute(text("""
            INSERT INTO sessions (id, user_id, job_id, mode, status)
            VALUES (101, 1, 1, '毕业生', 'active')
        """))
        conn.commit()

    # 执行平滑升级
    ensure_schema_upgrades(legacy_engine)

    # 验证新列成功追加，且原有数据完整保留
    with legacy_engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(sessions)")).fetchall()}
        assert "pending_question_json" in cols
        assert "lease_token" in cols
        assert "lease_expires_at" in cols

        # 检查原数据仍完好
        row = conn.execute(text("SELECT id, user_id, status, pending_question_json FROM sessions WHERE id = 101")).fetchone()
        assert row is not None
        assert row[0] == 101
        assert row[1] == 1
        assert row[2] == "active"
        assert row[3] is None  # 新追加列为 NULL

    # 3. 重复升级保持幂等
    ensure_schema_upgrades(legacy_engine)


@pytest.mark.anyio
async def test_heartbeat_lease_renewal_and_cancellation():
    """测试阶段 2 心跳定期续租与所有权被盗后即时中止"""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/sessions", json={"job_id": 1, "user_id": 1, "mode": "毕业生"})
        sid = resp.json()["sid"]

        # 配置较短的心跳与租约
        with patch.object(settings, "lease_renew_interval_seconds", 0.1), \
             patch.object(settings, "lease_duration_seconds", 2):

            step1_entered = asyncio.Event()
            step1_can_proceed = asyncio.Event()

            async def mock_renewing_followup(*args, **kwargs):
                step1_entered.set()
                # 等待两次心跳（0.25s）
                await asyncio.sleep(0.25)
                # 检查心跳是否续租了
                with SessionLocal() as db:
                    sess = db.query(Session).filter(Session.id == sid).first()
                    # 续约后的 lease_expires_at 应大于当前时间 1 秒
                    assert sess.lease_expires_at > datetime.utcnow()
                await step1_can_proceed.wait()
                return None

            with patch("server.services.orchestrator.evaluate_followup", mock_renewing_followup):
                task1 = asyncio.create_task(
                    client.post(f"/api/sessions/{sid}/answers/text", json={"answer_text": "回答测试续租"})
                )
                await step1_entered.wait()

                # 模拟在此期间被外部请求篡改/抢占了租约 (lease_token 变为他人 token)
                with SessionLocal() as db:
                    sess = db.query(Session).filter(Session.id == sid).first()
                    sess.lease_token = "stolen_by_another_request"
                    db.commit()

                # 等待下一个心跳检测 (0.15s)
                await asyncio.sleep(0.15)
                step1_can_proceed.set()

                # 原任务检测到 cancel_event 被触发，应中止并抛出 409
                resp1 = await task1
                assert resp1.status_code == 409
                assert resp1.json()["detail"]["code"] == "ANSWER_IN_PROGRESS"


@pytest.mark.anyio
async def test_concurrency_stolen_lease_cancels_business_task_without_releasing_barrier():
    """复现阻断 3：失去所有权时竞争取消业务任务；证明无需释放 mock 屏障，旧请求就能退出"""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/sessions", json={"job_id": 1, "user_id": 1, "mode": "毕业生"})
        sid = resp.json()["sid"]

        # 配置极短心跳
        with patch.object(settings, "lease_renew_interval_seconds", 0.05), \
             patch.object(settings, "lease_duration_seconds", 2):

            task_entered = asyncio.Event()
            # 注意：never_released_barrier 永不 set()！
            never_released_barrier = asyncio.Event()

            async def mock_forever_hanging_followup(*args, **kwargs):
                task_entered.set()
                await never_released_barrier.wait()
                return None

            with patch("server.services.orchestrator.evaluate_followup", mock_forever_hanging_followup):
                task = asyncio.create_task(
                    client.post(f"/api/sessions/{sid}/answers/text", json={"answer_text": "回答挂起"})
                )
                await task_entered.wait()

                # 模拟租约被他人夺走
                with SessionLocal() as db:
                    sess = db.query(Session).filter(Session.id == sid).first()
                    sess.lease_token = "stolen_token"
                    db.commit()

                # 在不释放 never_released_barrier 的情况下，等待 task 退出（超时 1.5s）
                resp = await asyncio.wait_for(task, timeout=1.5)
                assert resp.status_code == 409
                assert resp.json()["detail"]["code"] == "ANSWER_IN_PROGRESS"


@pytest.mark.anyio
async def test_orchestrator_prompt_injects_jd_and_terms():
    """复现阻断 4：追问必须注入岗位JD要点与专业术语表"""
    from server.services.orchestrator import evaluate_followup

    captured_messages = []

    async def mock_chat_json(stage, messages, model):
        captured_messages.extend(messages)
        return type("Obj", (), {"need_followup": False, "question": None})()

    job_info = {
        "title": "智驾系统测试工程师",
        "jd_digest": "负责车载以太网与CAN-FD通信总线测试",
        "terms": ["SOME/IP", "DoIP", "CANoe"],
    }

    with patch("server.services.orchestrator.chat_json", mock_chat_json):
        await evaluate_followup(
            question_text="请谈谈通信测试经验",
            answer_text="我做过相关报文解析",
            followup_hint="关注以太网协议",
            job_info=job_info,
        )

    assert len(captured_messages) == 2
    prompt_content = captured_messages[1]["content"]
    assert "智驾系统测试工程师" in prompt_content
    assert "负责车载以太网与CAN-FD通信总线测试" in prompt_content
    assert "SOME/IP" in prompt_content
    assert "DoIP" in prompt_content
