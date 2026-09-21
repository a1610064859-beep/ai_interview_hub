import asyncio
from datetime import datetime, timedelta
import logging
from uuid import uuid4
from fastapi import APIRouter, HTTPException, Path
from sqlalchemy import and_, or_, update

from server.config import settings
from server.db import SessionLocal
from server.models import Answer, Job, Question, Report, Session, User
from server.schemas import (
    AnswerResponse,
    DoneAnswerResponse,
    FollowupAnswerResponse,
    NextAnswerResponse,
    QuestionResponse,
    SessionCreateRequest,
    SessionCreateResponse,
    TextAnswerRequest,
)
from server.services.asr import count_filler_words
from server.services import orchestrator, scoring
from server.services.scoring import ScoringUnavailableError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("", response_model=SessionCreateResponse)
def create_session(req: SessionCreateRequest):
    with SessionLocal() as db:
        job = db.query(Job).filter(Job.id == req.job_id).first()
        if not job:
            raise HTTPException(
                status_code=404,
                detail={"code": "JOB_NOT_FOUND", "message": "岗位不存在"},
            )

        # 确保默认学生用户存在
        user = db.query(User).filter(User.id == 1).first()
        if not user:
            user = User(
                id=1,
                role="student",
                name_masked="演示学生",
                major="车辆工程",
                grade="大三",
            )
            db.add(user)
            db.commit()

        # 读取岗位第一题
        questions = (
            db.query(Question)
            .filter(Question.job_id == req.job_id)
            .order_by(Question.id.asc())
            .all()
        )
        if not questions:
            raise HTTPException(
                status_code=404,
                detail={"code": "JOB_NOT_FOUND", "message": "岗位题库未初始化"},
            )

        q1 = questions[0]
        pending_q = {
            "seq": 1,
            "text": q1.text,
            "audio_url": None,
            "is_followup": False,
        }

        session = Session(
            user_id=1,
            job_id=req.job_id,
            mode="毕业生",
            started_at=datetime.utcnow(),
            status="active",
            pending_question_json=pending_q,
            lease_token=None,
            lease_expires_at=None,
        )
        db.add(session)
        db.commit()
        db.refresh(session)

        return SessionCreateResponse(
            sid=session.id,
            question=QuestionResponse(text=q1.text, audio_url=None, seq=1),
        )


@router.post("/{sid}/answers/text", response_model=AnswerResponse)
async def submit_text_answer(
    req: TextAnswerRequest,
    sid: int = Path(..., ge=1),
):
    my_token = uuid4().hex
    now = datetime.utcnow()
    expires_at = now + timedelta(seconds=settings.lease_duration_seconds)

    # 事务 1：原子抢占与租约判定
    with SessionLocal() as db:
        result = db.execute(
            update(Session)
            .where(
                Session.id == sid,
                or_(
                    Session.status == "active",
                    and_(
                        Session.status == "answering",
                        Session.lease_expires_at < now,
                    ),
                ),
            )
            .values(
                status="answering",
                lease_token=my_token,
                lease_expires_at=expires_at,
            )
        )
        db.commit()

        if result.rowcount == 0:
            sess = db.query(Session).filter(Session.id == sid).first()
            if not sess:
                raise HTTPException(
                    status_code=404,
                    detail={"code": "SESSION_NOT_FOUND", "message": "面试会话不存在"},
                )
            if sess.status == "completed":
                raise HTTPException(
                    status_code=409,
                    detail={"code": "SESSION_COMPLETED", "message": "面试已结束"},
                )
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "ANSWER_IN_PROGRESS",
                    "message": "当前回答正在处理中，请勿重复提交",
                },
            )

        sess = db.query(Session).filter(Session.id == sid).first()
        pending_q = sess.pending_question_json
        if not pending_q or not isinstance(pending_q, dict):
            # 缺少待答快照（旧会话），释放锁并明确提示重新开始
            db.execute(
                update(Session)
                .where(Session.id == sid, Session.lease_token == my_token)
                .values(status="active", lease_token=None, lease_expires_at=None)
            )
            db.commit()
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "SESSION_RESET_REQUIRED",
                    "message": "该会话缺少待答题目快照，请重新开始新面试",
                },
            )

        job = db.query(Job).filter(Job.id == sess.job_id).first()
        questions = (
            db.query(Question)
            .filter(Question.job_id == sess.job_id)
            .order_by(Question.id.asc())
            .all()
        )
        current_answers = (
            db.query(Answer)
            .filter(Answer.session_id == sid)
            .order_by(Answer.id.asc())
            .all()
        )

    # 阶段 2：业务执行（带心跳续租与所有权即时中止）
    cancel_event = asyncio.Event()

    async def _heartbeat_renewal():
        while not cancel_event.is_set():
            try:
                await asyncio.sleep(settings.lease_renew_interval_seconds)
            except asyncio.CancelledError:
                break
            try:
                with SessionLocal() as db_inner:
                    res_renew = db_inner.execute(
                        update(Session)
                        .where(Session.id == sid, Session.lease_token == my_token)
                        .values(
                            lease_expires_at=datetime.utcnow()
                            + timedelta(seconds=settings.lease_duration_seconds)
                        )
                    )
                    db_inner.commit()
                    if res_renew.rowcount == 0:
                        cancel_event.set()
                        break
            except Exception:
                pass

    heartbeat_task = asyncio.create_task(_heartbeat_renewal())

    try:
        filler_cnt = count_filler_words(req.answer_text)
        current_seq = pending_q["seq"]
        is_followup = pending_q.get("is_followup", False)
        current_q_text = pending_q["text"]

        orig_q = (
            questions[current_seq - 1]
            if 1 <= current_seq <= len(questions)
            else None
        )
        followup_hint = orig_q.followup_hint if orig_q else None
        has_followup_answered = any(
            a.q_seq == current_seq and a.is_followup for a in current_answers
        )

        followup_text = None
        if not is_followup and not has_followup_answered:
            job_info = {
                "title": job.title,
                "jd_digest": job.jd_digest,
                "terms": job.terms_json,
            }
            followup_text = await orchestrator.evaluate_followup(
                current_q_text, req.answer_text, followup_hint, job_info
            )

        if cancel_event.is_set():
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "ANSWER_IN_PROGRESS",
                    "message": "答题租约已被后续请求接管",
                },
            )

        if followup_text:
            next_type = "followup"
            next_q = {
                "seq": current_seq,
                "text": followup_text,
                "audio_url": None,
                "is_followup": True,
            }
            next_status = "active"
            report_data = None
        else:
            if current_seq < 6:
                next_main_q = questions[current_seq]
                next_type = "next"
                next_q = {
                    "seq": current_seq + 1,
                    "text": next_main_q.text,
                    "audio_url": None,
                    "is_followup": False,
                }
                next_status = "active"
                report_data = None
            else:
                all_answers = [a.answer_text for a in current_answers] + [
                    req.answer_text
                ]
                job_info = {
                    "title": job.title,
                    "jd_digest": job.jd_digest,
                    "terms": job.terms_json,
                }
                report_data = await scoring.score_interview(
                    answers=all_answers, job_info=job_info, mode="text"
                )
                next_type = "done"
                next_q = None
                next_status = "completed"

    except ScoringUnavailableError:
        with SessionLocal() as db_clean:
            db_clean.execute(
                update(Session)
                .where(Session.id == sid, Session.lease_token == my_token)
                .values(status="active", lease_token=None, lease_expires_at=None)
            )
            db_clean.commit()
        raise HTTPException(
            status_code=503,
            detail={
                "code": "SCORING_UNAVAILABLE",
                "message": "评分服务暂时不可用，请稍后重试",
            },
        )
    except Exception:
        with SessionLocal() as db_clean:
            db_clean.execute(
                update(Session)
                .where(Session.id == sid, Session.lease_token == my_token)
                .values(status="active", lease_token=None, lease_expires_at=None)
            )
            db_clean.commit()
        raise
    finally:
        cancel_event.set()
        heartbeat_task.cancel()

    # 事务 3：所有权校验与原子落库
    with SessionLocal() as db:
        res = db.execute(
            update(Session)
            .where(Session.id == sid, Session.lease_token == my_token)
            .values(
                status=next_status,
                pending_question_json=next_q,
                lease_token=None,
                lease_expires_at=None,
            )
        )
        if res.rowcount == 0:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "ANSWER_IN_PROGRESS",
                    "message": "答题租约已被后续请求接管",
                },
            )

        new_answer = Answer(
            session_id=sid,
            q_seq=current_seq,
            question_text=current_q_text,
            answer_text=req.answer_text,
            is_followup=is_followup,
            is_retry=False,
            duration_s=None,
            wpm=None,
            pause_cnt=None,
            filler_cnt=filler_cnt,
        )
        db.add(new_answer)

        new_report = None
        if report_data:
            new_report = Report(
                session_id=sid,
                dimensions_json=report_data["dimensions"],
                highlights_json=report_data["highlights"],
                concerns_json=report_data["concerns"],
                improvement_json=report_data["improvement"],
                overall=report_data["overall"],
            )
            db.add(new_report)

        db.commit()
        if new_report:
            db.refresh(new_report)

    if next_type == "followup":
        return FollowupAnswerResponse(question=QuestionResponse(**next_q))
    elif next_type == "next":
        return NextAnswerResponse(question=QuestionResponse(**next_q))
    else:
        return DoneAnswerResponse(report_id=new_report.id)
