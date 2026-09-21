import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.db import SessionLocal, init_db
from server.models import Job, Question


def import_seeds(seed_path=None, db=None) -> dict:
    if seed_path is None:
        seed_path = Path(__file__).resolve().parent.parent / "data" / "jobs_seed.json"
    else:
        seed_path = Path(seed_path)

    with open(seed_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    close_db_when_done = False
    if db is None:
        init_db()
        db = SessionLocal()
        close_db_when_done = True

    stats = {
        "jobs_created": 0,
        "jobs_updated": 0,
        "questions_created": 0,
        "questions_updated": 0,
    }

    try:
        for item in data:
            family = item["family"]
            title = item["title"]
            jd_digest = item.get("jd_digest")
            terms_json = item.get("terms_json")
            dims_json = item.get("dims_json")

            job = db.query(Job).filter(Job.family == family, Job.title == title).first()
            if job is None:
                job = Job(
                    family=family,
                    title=title,
                    jd_digest=jd_digest,
                    terms_json=terms_json,
                    dims_json=dims_json,
                )
                db.add(job)
                db.flush()
                stats["jobs_created"] += 1
            else:
                job.jd_digest = jd_digest
                job.terms_json = terms_json
                job.dims_json = dims_json
                stats["jobs_updated"] += 1

            for q_data in item.get("questions", []):
                q_type = q_data["type"]
                q_text = q_data["text"]
                followup_hint = q_data.get("followup_hint")

                question = (
                    db.query(Question)
                    .filter(Question.job_id == job.id, Question.text == q_text)
                    .first()
                )
                if question is None:
                    question = Question(
                        job_id=job.id,
                        type=q_type,
                        text=q_text,
                        followup_hint=followup_hint,
                    )
                    db.add(question)
                    stats["questions_created"] += 1
                else:
                    question.type = q_type
                    question.followup_hint = followup_hint
                    stats["questions_updated"] += 1

        db.commit()
        return stats
    finally:
        if close_db_when_done:
            db.close()


if __name__ == "__main__":
    result = import_seeds()
    print(f"Seeds imported successfully: {result}")
