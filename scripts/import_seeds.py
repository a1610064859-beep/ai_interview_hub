import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.db import SessionLocal, init_db
from server.models import Job, Question, User

SEED_STUDENTS = (
    {
        "id": 3,
        "role": "student",
        "name_masked": "王*明",
        "major": "车辆工程",
        "grade": "大三",
    },
    {
        "id": 4,
        "role": "student",
        "name_masked": "李*华",
        "major": "智能车辆工程",
        "grade": "大二",
    },
)

_WEIGHT_KEYS = (
    "professional_match",
    "logic_structure",
    "expression_fluency",
    "job_competence",
)


class SeedStudentConflictError(RuntimeError):
    """目标学生 ID 已存在但档案字段与演示种子不一致；禁止覆盖。"""


class SeedDimsJsonError(RuntimeError):
    """种子 dims_json 不符合 T8 §5.1 批准形状。"""


def _validate_dims_json(dims_json, title: str) -> None:
    """T8：两岗 dims_json 须为含 weights 的对象；禁止静默接受旧名称数组。"""
    if not isinstance(dims_json, dict):
        raise SeedDimsJsonError(
            f"岗位「{title}」dims_json 必须为对象（含 labels/weights），不能是名称数组"
        )
    weights = dims_json.get("weights")
    if not isinstance(weights, dict) or set(weights.keys()) != set(_WEIGHT_KEYS):
        raise SeedDimsJsonError(
            f"岗位「{title}」dims_json.weights 必须恰好含四维英文键"
        )
    total = 0.0
    for key in _WEIGHT_KEYS:
        val = weights[key]
        if isinstance(val, bool) or not isinstance(val, (int, float)) or val <= 0:
            raise SeedDimsJsonError(f"岗位「{title}」权重 {key} 必须为 >0 的 number")
        total += float(val)
    if abs(total - 1.0) > 1e-6:
        raise SeedDimsJsonError(f"岗位「{title}」权重合计必须为 1.0，当前={total}")
    labels = dims_json.get("labels")
    if labels is not None and (not isinstance(labels, list) or len(labels) != 4):
        raise SeedDimsJsonError(f"岗位「{title}」labels 若存在长度须为 4")


def _ensure_seed_students(db) -> dict:
    created = 0
    existing = 0
    conflicts = []
    for spec in SEED_STUDENTS:
        row = db.query(User).filter(User.id == spec["id"]).first()
        if row is None:
            db.add(User(**spec))
            created += 1
            continue
        mismatched = {
            field: {"expected": spec[field], "actual": getattr(row, field)}
            for field in ("role", "name_masked", "major", "grade")
            if getattr(row, field) != spec[field]
        }
        if mismatched:
            conflicts.append({"id": spec["id"], "mismatched": mismatched})
        else:
            existing += 1
    if conflicts:
        raise SeedStudentConflictError(
            "种子学生档案冲突，拒绝覆盖: " + json.dumps(conflicts, ensure_ascii=False)
        )
    return {"students_created": created, "students_existing": existing}


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
        "students_created": 0,
        "students_existing": 0,
    }

    try:
        student_stats = _ensure_seed_students(db)
        stats.update(student_stats)

        for item in data:
            family = item["family"]
            title = item["title"]
            jd_digest = item.get("jd_digest")
            terms_json = item.get("terms_json")
            dims_json = item.get("dims_json")
            _validate_dims_json(dims_json, title)

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
    except Exception:
        db.rollback()
        raise
    finally:
        if close_db_when_done:
            db.close()


if __name__ == "__main__":
    try:
        result = import_seeds()
    except (SeedStudentConflictError, SeedDimsJsonError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"Seeds imported successfully: {result}")
