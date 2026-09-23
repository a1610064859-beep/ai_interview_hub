import asyncio
from datetime import datetime, timedelta
import logging
import os
import shutil
import tempfile
from typing import Annotated
from uuid import uuid4
from fastapi import APIRouter, File, Form, HTTPException, Path, UploadFile
from sqlalchemy import and_, func, or_, update

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
from server.services import asr as asr_service
from server.services import audio as audio_service
from server.services import orchestrator, scoring, tts
from server.services.asr import ASRUnavailableError, count_filler_words
from server.services.audio import AudioInvalidError, AudioProcessError
from server.services.scoring import ScoringUnavailableError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _release_lease(db, sid: int, token: str) -> None:
    db.execute(
        update(Session)
        .where(Session.id == sid, Session.lease_token == token)
        .values(status="active", lease_token=None, lease_expires_at=None)
    )
    db.commit()


def _enforce_input_mode(db, sess: Session, sid: int, token: str, expected: str) -> None:
    """会话已锁定输入模式且与当前端点不一致 → 409，释放租约，不推进。"""
    if sess.input_mode is None:
        return
    if sess.input_mode == expected:
        return
    _release_lease(db, sid, token)
    label = "文本" if sess.input_mode == "text" else "语音"
    raise HTTPException(
        status_code=409,
        detail={
            "code": "INPUT_MODE_MISMATCH",
            "message": f"该会话已以{label}模式进行，禁止混用输入模式",
        },
    )


@router.post("", response_model=SessionCreateResponse)
async def create_session(req: SessionCreateRequest):
    with SessionLocal() as db:
        job = db.query(Job).filter(Job.id == req.job_id).first()
        if not job:
            raise HTTPException(
                status_code=404,
                detail={"code": "JOB_NOT_FOUND", "message": "岗位不存在"},
            )

        user = db.query(User).filter(User.id == req.user_id).first()
        if not user or user.role != "student":
            raise HTTPException(
                status_code=404,
                detail={"code": "USER_NOT_FOUND", "message": "学生档案不存在"},
            )

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

        q1_text = questions[0].text
        question_texts = [q.text for q in questions[:6]]
        pending_q = {
            "seq": 1,
            "text": q1_text,
            "audio_url": None,
            "is_followup": False,
        }

        session = Session(
            user_id=req.user_id,
            job_id=req.job_id,
            mode=req.mode,
            started_at=datetime.utcnow(),
            status="active",
            pending_question_json=pending_q,
            lease_token=None,
            lease_expires_at=None,
            input_mode=None,
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        sid = session.id

    # 在会话创建后并行预取固定题和过渡语音频
    prefetch_results, transition_urls = await asyncio.gather(
        tts.prefetch_session_questions(sid, question_texts),
        tts.prefetch_session_transitions(sid),
    )
    q1_audio_url = prefetch_results.get(1) if isinstance(prefetch_results, dict) else None

    # 若首题预取成功，更新持久化待答状态中的 audio_url
    if q1_audio_url:
        with SessionLocal() as db_update:
            sess_obj = db_update.query(Session).filter(Session.id == sid).first()
            if sess_obj and sess_obj.pending_question_json:
                pending_updated = dict(sess_obj.pending_question_json)
                pending_updated["audio_url"] = q1_audio_url
                sess_obj.pending_question_json = pending_updated
                db_update.commit()

    valid_trans_urls = [u for u in transition_urls if u is not None] if isinstance(transition_urls, list) else []

    return SessionCreateResponse(
        sid=sid,
        question=QuestionResponse(text=q1_text, audio_url=q1_audio_url, seq=1),
        transition_audio_urls=valid_trans_urls,
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

        _enforce_input_mode(db, sess, sid, my_token, "text")

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
        answer_count_before = len(current_answers)

    transition_audio_url = tts.get_session_transition_url(sid, answer_count_before)

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

    async def _execute_business():
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

        if followup_text:
            followup_audio = await tts.synthesize_followup(sid, current_seq, followup_text)
            next_type = "followup"
            next_q = {
                "seq": current_seq,
                "text": followup_text,
                "audio_url": followup_audio,
                "is_followup": True,
            }
            next_status = "active"
            report_data = None
        else:
            if current_seq < 6:
                next_main_q = questions[current_seq]
                next_main_audio = tts.get_question_audio_url(sid, current_seq + 1, is_followup=False)
                next_type = "next"
                next_q = {
                    "seq": current_seq + 1,
                    "text": next_main_q.text,
                    "audio_url": next_main_audio,
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

        return (
            next_type,
            next_q,
            next_status,
            report_data,
            current_seq,
            current_q_text,
            is_followup,
            filler_cnt,
        )

    biz_task = asyncio.create_task(_execute_business())
    cancel_task = asyncio.create_task(cancel_event.wait())

    try:
        done, pending = await asyncio.wait(
            [biz_task, cancel_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        if cancel_task in done:
            # 失去租约所有权！立即取消业务任务并等待结束
            biz_task.cancel()
            try:
                await biz_task
            except (asyncio.CancelledError, Exception):
                pass
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "ANSWER_IN_PROGRESS",
                    "message": "答题租约已被后续请求接管",
                },
            )

        cancel_task.cancel()
        try:
            await cancel_task
        except asyncio.CancelledError:
            pass

        (
            next_type,
            next_q,
            next_status,
            report_data,
            current_seq,
            current_q_text,
            is_followup,
            filler_cnt,
        ) = biz_task.result()

    except HTTPException:
        raise
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
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass

    # 事务 3：所有权校验与原子落库（含首次 input_mode=text）
    with SessionLocal() as db:
        res = db.execute(
            update(Session)
            .where(Session.id == sid, Session.lease_token == my_token)
            .values(
                status=next_status,
                pending_question_json=next_q,
                lease_token=None,
                lease_expires_at=None,
                input_mode=func.coalesce(Session.input_mode, "text"),
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
                scoring_version=report_data.get("scoring_version"),
            )
            db.add(new_report)

        db.commit()
        if new_report:
            db.refresh(new_report)

    if next_type == "followup":
        return FollowupAnswerResponse(
            question=QuestionResponse(**next_q),
            transition_audio_url=transition_audio_url,
        )
    elif next_type == "next":
        return NextAnswerResponse(
            question=QuestionResponse(**next_q),
            transition_audio_url=transition_audio_url,
        )
    else:
        return DoneAnswerResponse(
            report_id=new_report.id,
            transition_audio_url=transition_audio_url,
        )


def _compute_wpm(answer_text: str, duration_s: float) -> float | None:
    """语速=去空白字数/时长×60（AGENTS §6.3）；时长非法时置空，不虚构。"""
    if duration_s <= 0:
        return None
    chars = len("".join(answer_text.split()))
    return round(chars / duration_s * 60, 1)


@router.post("/{sid}/answers", response_model=AnswerResponse)
async def submit_audio_answer(
    sid: Annotated[int, Path(ge=1)],
    audio: Annotated[UploadFile, File()],
    duration_s: Annotated[float, Form(ge=0.1, le=600.0)],
    pause_cnt: Annotated[int, Form(ge=0, le=10000)],
):
    """语音答题（T5）：multipart 提交 webm/opus，服务端转码+ASR 后按文本链路推进。

    错误契约见 docs/asr-implementation-spec.md §5.4（阶段判定）。
    上传校验（大小/魔数）在租约前完成；探测/转码/ASR 在租约持有的业务阶段执行，
    任一失败不产生 Answer、不推进状态，仅释放租约回 active。
    """
    if not settings.asr_enabled:
        raise HTTPException(
            status_code=503,
            detail={"code": "ASR_UNAVAILABLE", "message": "ASR 服务未启用"},
        )

    max_bytes = settings.asr_max_upload_mb * 1024 * 1024
    # 最多读取 上限+1 字节：足以判定超限，又不把超大文件整体读入内存
    audio_bytes = await audio.read(max_bytes + 1)
    if len(audio_bytes) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail={"code": "AUDIO_TOO_LARGE", "message": "音频文件超过大小限制"},
        )
    try:
        audio_service.validate_upload(audio_bytes)
    except AudioInvalidError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "AUDIO_INVALID", "message": str(exc)},
        )

    temp_dir = tempfile.mkdtemp(prefix="asr_", dir=settings.asr_temp_dir or None)
    try:
        webm_path = os.path.join(temp_dir, "input.webm")
        wav_path = os.path.join(temp_dir, "input.wav")
        with open(webm_path, "wb") as f:
            f.write(audio_bytes)

        my_token = uuid4().hex
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=settings.lease_duration_seconds)

        # 事务 1：原子抢占与租约判定（与文本端点同语义）
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
                    detail={"code": "ANSWER_IN_PROGRESS", "message": "当前回答正在处理中，请勿重复提交"},
                )

            sess = db.query(Session).filter(Session.id == sid).first()
            pending_q = sess.pending_question_json
            if not pending_q or not isinstance(pending_q, dict):
                db.execute(
                    update(Session)
                    .where(Session.id == sid, Session.lease_token == my_token)
                    .values(status="active", lease_token=None, lease_expires_at=None)
                )
                db.commit()
                raise HTTPException(
                    status_code=409,
                    detail={"code": "SESSION_RESET_REQUIRED", "message": "该会话缺少待答题目快照，请重新开始新面试"},
                )

            _enforce_input_mode(db, sess, sid, my_token, "voice")

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
            answer_count_before = len(current_answers)

        transition_audio_url = tts.get_session_transition_url(sid, answer_count_before)

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

        async def _execute_business():
            # 探测→转码→ASR：持租约执行，失败统一释放租约，不产生 Answer
            audio_service.probe_webm(webm_path)
            audio_service.transcode_to_16k_wav(webm_path, wav_path)
            answer_text = await asr_service.transcribe_wav(wav_path)
            if not answer_text.strip():
                raise ASRUnavailableError("转写结果为空，疑似无效音频")

            filler_cnt = count_filler_words(answer_text)
            wpm = _compute_wpm(answer_text, duration_s)
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
                    current_q_text, answer_text, followup_hint, job_info
                )

            if followup_text:
                followup_audio = await tts.synthesize_followup(sid, current_seq, followup_text)
                next_type = "followup"
                next_q = {
                    "seq": current_seq,
                    "text": followup_text,
                    "audio_url": followup_audio,
                    "is_followup": True,
                }
                next_status = "active"
                report_data = None
            elif current_seq < 6:
                next_main_q = questions[current_seq]
                next_main_audio = tts.get_question_audio_url(
                    sid, current_seq + 1, is_followup=False
                )
                next_type = "next"
                next_q = {
                    "seq": current_seq + 1,
                    "text": next_main_q.text,
                    "audio_url": next_main_audio,
                    "is_followup": False,
                }
                next_status = "active"
                report_data = None
            else:
                all_answers = [a.answer_text for a in current_answers] + [answer_text]
                job_info = {
                    "title": job.title,
                    "jd_digest": job.jd_digest,
                    "terms": job.terms_json,
                }
                # 声学数据：历史语音回答取自 DB Answer 记录（文本回答无完整声学字段，自动排除）；
                # 本次待提交回答尚未落库，其声学数据显式追加，保证评分输入完整。
                acoustic_samples = [
                    {
                        "duration_s": a.duration_s,
                        "wpm": a.wpm,
                        "pause_cnt": a.pause_cnt,
                        "filler_cnt": a.filler_cnt,
                    }
                    for a in current_answers
                    if a.duration_s is not None and a.wpm is not None
                ]
                acoustic_samples.append(
                    {
                        "duration_s": duration_s,
                        "wpm": wpm,
                        "pause_cnt": pause_cnt,
                        "filler_cnt": filler_cnt,
                    }
                )
                report_data = await scoring.score_interview(
                    answers=all_answers,
                    job_info=job_info,
                    mode="voice",
                    acoustic_samples=acoustic_samples,
                )
                next_type = "done"
                next_q = None
                next_status = "completed"

            return (
                next_type,
                next_q,
                next_status,
                report_data,
                current_seq,
                current_q_text,
                is_followup,
                filler_cnt,
                wpm,
                answer_text,
            )

        biz_task = asyncio.create_task(_execute_business())
        cancel_task = asyncio.create_task(cancel_event.wait())

        try:
            done, pending = await asyncio.wait(
                [biz_task, cancel_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            if cancel_task in done:
                biz_task.cancel()
                try:
                    await biz_task
                except (asyncio.CancelledError, Exception):
                    pass
                raise HTTPException(
                    status_code=409,
                    detail={"code": "ANSWER_IN_PROGRESS", "message": "答题租约已被后续请求接管"},
                )

            cancel_task.cancel()
            try:
                await cancel_task
            except asyncio.CancelledError:
                pass

            (
                next_type,
                next_q,
                next_status,
                report_data,
                current_seq,
                current_q_text,
                is_followup,
                filler_cnt,
                wpm,
                answer_text,
            ) = biz_task.result()

        except HTTPException:
            raise
        except AudioInvalidError as exc:
            with SessionLocal() as db_clean:
                db_clean.execute(
                    update(Session)
                    .where(Session.id == sid, Session.lease_token == my_token)
                    .values(status="active", lease_token=None, lease_expires_at=None)
                )
                db_clean.commit()
            raise HTTPException(
                status_code=422,
                detail={"code": "AUDIO_INVALID", "message": str(exc)},
            )
        except (AudioProcessError, ASRUnavailableError) as exc:
            with SessionLocal() as db_clean:
                db_clean.execute(
                    update(Session)
                    .where(Session.id == sid, Session.lease_token == my_token)
                    .values(status="active", lease_token=None, lease_expires_at=None)
                )
                db_clean.commit()
            code = (
                "AUDIO_PROCESS_FAILED"
                if isinstance(exc, AudioProcessError)
                else "ASR_UNAVAILABLE"
            )
            raise HTTPException(status_code=503, detail={"code": code, "message": str(exc)})
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
                detail={"code": "SCORING_UNAVAILABLE", "message": "评分服务暂时不可用，请稍后重试"},
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
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

        # 事务 3：所有权校验与原子落库（含首次 input_mode=voice）
        with SessionLocal() as db:
            res = db.execute(
                update(Session)
                .where(Session.id == sid, Session.lease_token == my_token)
                .values(
                    status=next_status,
                    pending_question_json=next_q,
                    lease_token=None,
                    lease_expires_at=None,
                    input_mode=func.coalesce(Session.input_mode, "voice"),
                )
            )
            if res.rowcount == 0:
                db.rollback()
                raise HTTPException(
                    status_code=409,
                    detail={"code": "ANSWER_IN_PROGRESS", "message": "答题租约已被后续请求接管"},
                )

            new_answer = Answer(
                session_id=sid,
                q_seq=current_seq,
                question_text=current_q_text,
                answer_text=answer_text,
                is_followup=is_followup,
                is_retry=False,
                duration_s=duration_s,
                wpm=wpm,
                pause_cnt=pause_cnt,
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
                    scoring_version=report_data.get("scoring_version"),
                )
                db.add(new_report)

            db.commit()
            if new_report:
                db.refresh(new_report)

        if next_type == "followup":
            return FollowupAnswerResponse(
                question=QuestionResponse(**next_q),
                transition_audio_url=transition_audio_url,
            )
        elif next_type == "next":
            return NextAnswerResponse(
                question=QuestionResponse(**next_q),
                transition_audio_url=transition_audio_url,
            )
        else:
            return DoneAnswerResponse(
                report_id=new_report.id,
                transition_audio_url=transition_audio_url,
            )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
