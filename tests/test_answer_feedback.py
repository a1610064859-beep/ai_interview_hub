import hashlib
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from server.db import Base, SessionLocal, engine
from server.main import app
from server.config import settings
from server.models import Answer, AuthSession, Job, Report, Session, User


@pytest.fixture(autouse=True)
def setup_feedback_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.add(User(id=1, role="student", name_masked="新**", major="车辆工程", grade="大一"))
        db.add(User(id=2, role="student", name_masked="另**", major="车辆工程", grade="大一"))
        db.add(Job(id=1, family="智驾", title="智驾测试", jd_digest="测试岗位"))
        db.add(
            Session(
                id=1,
                user_id=1,
                job_id=1,
                mode="新生",
                status="active",
                pending_question_json=None,
                input_mode="text",
            )
        )
        db.add(
            Answer(
                id=1,
                session_id=1,
                q_seq=1,
                question_text="请介绍一次你发现并解决问题的项目经历，并说明结果。",
                answer_text="我用CANoe定位了三次报文丢失，修复过滤配置后丢包率从5%降到0.2%。",
                is_followup=False,
                is_retry=False,
                duration_s=None,
                wpm=None,
                pause_cnt=None,
                filler_cnt=0,
            )
        )
        # 追问复用原题 q_seq；接口必须按落库顺序读取最新回答，而非只按 q_seq 判断。
        db.add(
            Answer(
                id=2,
                session_id=1,
                q_seq=1,
                question_text="你如何确认修复有效？",
                answer_text="我复跑同一组用例，确认连续三轮都没有丢包。",
                is_followup=True,
                is_retry=False,
                duration_s=None,
                wpm=None,
                pause_cnt=None,
                filler_cnt=0,
            )
        )
        db.add(Report(id=1, session_id=1, dimensions_json={"professional_match": 70}, overall=70))
        db.add(
            Session(
                id=2,
                user_id=1,
                job_id=1,
                mode="毕业生",
                status="active",
                pending_question_json=None,
                input_mode="text",
            )
        )
        db.add(
            Session(
                id=3,
                user_id=1,
                job_id=1,
                mode="新生",
                status="answering",
                pending_question_json=None,
                input_mode="text",
            )
        )
        db.commit()
    yield


def test_feedback_scores_latest_answer_without_advancing_session(monkeypatch):
    calls = []

    async def fake_chat_json(stage, messages, response_model):
        calls.append((stage, messages, response_model))
        return response_model(
            practice_score=82,
            problem_analysis="结论和验证方法明确，可以补充测试前后的对比依据。",
            evidence_quote="连续三轮都没有丢包",
            improvement_suggestion="按STAR顺序补充任务背景、个人行动和量化结果。",
            learning_topic="star",
        )

    monkeypatch.setattr("server.services.answer_feedback.chat_json", fake_chat_json)
    client = TestClient(app)

    response = client.post("/api/sessions/1/feedback")

    assert response.status_code == 200
    data = response.json()
    assert data == {
        "answer_id": 2,
        "q_seq": 1,
        "is_followup": True,
        "question_text": "你如何确认修复有效？",
        "feedback": {
            "practice_score": 82,
            "problem_analysis": "结论和验证方法明确，可以补充测试前后的对比依据。",
            "evidence_quote": "我复跑同一组用例，确认连续三轮都没有丢包。",
            "improvement_suggestion": "按STAR顺序补充任务背景、个人行动和量化结果。",
            "learning_topic": "star",
            "basis": "ai",
        },
    }
    assert len(calls) == 1
    assert calls[0][0] == "answer_feedback"
    assert calls[0][2].__name__ == "AnswerFeedbackLlmResponse"
    assert "不评估语速" in calls[0][1][0]["content"]
    assert "practice_score" in calls[0][1][0]["content"]
    assert "quote_candidate" in calls[0][1][1]["content"]
    with SessionLocal() as db:
        assert db.query(Answer).filter(Answer.session_id == 1).count() == 2
        assert db.query(Report).filter(Report.session_id == 1).count() == 1
        assert db.get(Session, 1).status == "active"


def test_feedback_rejects_quote_not_present_in_answer(monkeypatch):
    async def fake_chat_json(stage, messages, response_model):
        return response_model(
            practice_score=91,
            problem_analysis="分析",
            evidence_quote="回答中没有的原话",
            improvement_suggestion="补充依据。",
            learning_topic="star",
        )

    monkeypatch.setattr("server.services.answer_feedback.chat_json", fake_chat_json)
    response = TestClient(app).post("/api/sessions/1/feedback")

    assert response.status_code == 200
    feedback = response.json()["feedback"]
    assert 0 < feedback["practice_score"] <= 75
    assert feedback["evidence_quote"] in "我复跑同一组用例，确认连续三轮都没有丢包。"
    assert feedback["basis"] == "rule"
    assert "结构" in feedback["problem_analysis"]
    assert feedback["improvement_suggestion"]


def test_fragment_expands_to_complete_original_sentence_without_outer_quotes():
    from server.services.answer_feedback import _complete_evidence_quote

    answer = "“在实习期间，我确实深度参与过一起多传感器（相机+激光雷达+毫米波）标定偏差导致的融合异常定位，并且后续在HIL台架与Corner Case中做了闭环验证。"
    fragment = "“在实习期间，我确实深度参与过一起多传感器（相机+"

    quote = _complete_evidence_quote(answer, fragment)

    assert quote == answer[1:]
    assert quote in answer


def test_feedback_degrades_safely_when_llm_fails(monkeypatch):
    async def fail_chat_json(stage, messages, response_model):
        raise RuntimeError("offline")

    monkeypatch.setattr("server.services.answer_feedback.chat_json", fail_chat_json)
    response = TestClient(app).post("/api/sessions/1/feedback")

    assert response.status_code == 200
    feedback = response.json()["feedback"]
    assert 0 < feedback["practice_score"] <= 75
    assert feedback["evidence_quote"] in "我复跑同一组用例，确认连续三轮都没有丢包。"
    assert feedback["basis"] == "rule"
    assert "AI评分暂不可用" in feedback["problem_analysis"]
    assert feedback["learning_topic"] == "followup"


def test_rule_estimate_does_not_treat_job_title_as_completed_action():
    from server.services.answer_feedback import _fallback

    answer = "我是智能车辆工程专业的学生，我想从事驾驶测试工作，因为我想提升专业水平。"
    feedback = _fallback("请介绍专业背景和求职动机。", answer, False)

    assert feedback.basis == "rule"
    assert feedback.practice_score == 55
    assert "亲自采取的行动" in feedback.problem_analysis
    assert feedback.evidence_quote in answer


@pytest.mark.parametrize("sid,expected_status", [(2, 403), (3, 409)])
def test_feedback_only_available_after_new_student_answer_is_committed(sid, expected_status):
    response = TestClient(app).post(f"/api/sessions/{sid}/feedback")

    assert response.status_code == expected_status


def test_feedback_cannot_read_another_students_session(monkeypatch):
    monkeypatch.setattr(settings, "auth_required", True)
    token = "test-session-token-with-enough-length-123456"
    with SessionLocal() as db:
        db.add(
            Session(
                id=4,
                user_id=2,
                job_id=1,
                mode="新生",
                status="active",
                pending_question_json=None,
                input_mode="text",
            )
        )
        db.add(
            Answer(
                id=3,
                session_id=4,
                q_seq=1,
                question_text="请介绍一次项目经历。",
                answer_text="我完成了一个测试项目。",
                is_followup=False,
                is_retry=False,
                duration_s=None,
                wpm=None,
                pause_cnt=None,
                filler_cnt=0,
            )
        )
        db.add(
            AuthSession(
                user_id=1,
                token_hash=hashlib.sha256(token.encode("ascii")).hexdigest(),
                expires_at=datetime.utcnow() + timedelta(hours=1),
            )
        )
        db.commit()

    client = TestClient(app)
    client.cookies.set("aihub_session", token)
    response = client.post("/api/sessions/4/feedback")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "SESSION_NOT_FOUND"
