from fastapi import APIRouter, Depends, HTTPException, Path, Request

from server.api.auth import require_student
from server.api.sessions import _ensure_student_session_access
from server.db import SessionLocal
from server.models import Answer, Session
from server.services.answer_feedback import AnswerFeedbackResponse, evaluate_answer


router = APIRouter(
    prefix="/api/sessions",
    tags=["answer-feedback"],
    dependencies=[Depends(require_student)],
)


@router.post("/{sid}/feedback", response_model=AnswerFeedbackResponse)
async def get_answer_feedback(request: Request, sid: int = Path(..., ge=1)):
    _ensure_student_session_access(request, sid)

    with SessionLocal() as db:
        session = db.get(Session, sid)
        if session is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "SESSION_NOT_FOUND", "message": "面试会话不存在"},
            )
        if session.mode != "新生":
            raise HTTPException(
                status_code=403,
                detail={"code": "MODE_FORBIDDEN", "message": "即时练习反馈仅适用于新生模式"},
            )
        if session.status == "answering":
            raise HTTPException(
                status_code=409,
                detail={"code": "ANSWER_IN_PROGRESS", "message": "回答仍在处理中"},
            )

        answer = (
            db.query(Answer)
            .filter(Answer.session_id == sid)
            .order_by(Answer.id.desc())
            .first()
        )
        if answer is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "ANSWER_NOT_FOUND", "message": "请先完成本题回答"},
            )
        answer_id = answer.id
        q_seq = answer.q_seq
        is_followup = answer.is_followup
        question_text = answer.question_text
        answer_text = answer.answer_text

    feedback = await evaluate_answer(
        question_text=question_text,
        answer_text=answer_text,
        is_followup=is_followup,
    )
    return AnswerFeedbackResponse(
        answer_id=answer_id,
        q_seq=q_seq,
        is_followup=is_followup,
        question_text=question_text,
        feedback=feedback,
    )
