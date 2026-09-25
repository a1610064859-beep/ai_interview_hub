from sqlalchemy.orm import Session

from server.models import Question


INTERVIEW_QUESTION_COUNTS = {"通用": 2, "专业": 3, "情景": 1}


class QuestionBankIncompleteError(ValueError):
    pass


def get_interview_questions(db: Session, job_id: int) -> list[Question]:
    """Pick the most recently maintained questions while preserving the 2/3/1 flow."""
    selected: list[Question] = []
    missing: dict[str, int] = {}
    for question_type, required_count in INTERVIEW_QUESTION_COUNTS.items():
        newest = (
            db.query(Question)
            .filter(Question.job_id == job_id, Question.type == question_type)
            .order_by(Question.id.desc())
            .limit(required_count)
            .all()
        )
        if len(newest) < required_count:
            missing[question_type] = required_count - len(newest)
        selected.extend(reversed(newest))

    if missing:
        details = "、".join(f"{kind}缺少{count}题" for kind, count in missing.items())
        raise QuestionBankIncompleteError(details)
    return selected


def active_question_ids(db: Session, job_id: int) -> set[int]:
    return {question.id for question in get_interview_questions(db, job_id)}
