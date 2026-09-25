"""CSV 名单导入、档案查看与简历下载的端到端契约。"""

import csv
import io
import zipfile
from xml.sax.saxutils import escape

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from server.config import settings
from server.db import Base, SessionLocal, engine, init_db
from server.main import app
from server.models import User


client = TestClient(app)
HEADERS = ["学生编号", "姓名（脱敏）", "专业", "年级", "学历", "实习经历", "获奖情况", "简历文件名"]


@pytest.fixture(autouse=True)
def empty_roster(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "resume_upload_dir", str(tmp_path / "resumes"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def csv_file(*rows):
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(HEADERS)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


def make_docx(*paragraphs: str) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>" for text in paragraphs)
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def test_import_csv_roster_and_open_student_resume():
    template = client.get("/api/recruiter/students/template.csv")
    assert template.status_code == 200
    assert template.content.startswith(b"\xef\xbb\xbf")
    assert "学生编号" in template.content.decode("utf-8-sig")

    data = csv_file(
        ["S1001", "王*明", "车辆工程", "大三", "本科", "整车测试实习三个月", "校级一等奖", "wang.docx"],
        ["S1002", "李*华", "汽车电子", "大二", "高职/大专", "", "", ""],
    )
    docx = make_docx("实习经历：整车测试", "项目经历：读取传感器数据")
    imported = client.post(
        "/api/recruiter/students/import",
        files=[
            ("csv_file", ("students.csv", data, "text/csv")),
            ("resumes", ("wang.docx", docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
        ],
    )
    assert imported.status_code == 200, imported.text
    assert imported.json() == {"created": 2, "updated": 0, "total": 2}

    students = client.get("/api/students").json()["students"]
    assert [student["student_no"] for student in students] == ["S1001", "S1002"]
    student_id = students[0]["id"]
    detail = client.get(f"/api/recruiter/students/{student_id}")
    assert detail.status_code == 200
    assert detail.json()["internship_experience"] == "整车测试实习三个月"
    assert detail.json()["awards"] == "校级一等奖"
    assert detail.json()["education_level"] == "本科"
    assert detail.json()["has_resume"] is True
    resume = client.get(f"/api/recruiter/students/{student_id}/resume")
    assert resume.status_code == 200
    assert resume.content == docx
    assert "attachment" in resume.headers["content-disposition"]
    readable = client.get(f"/api/recruiter/students/{student_id}/resume/text")
    assert readable.status_code == 200
    assert readable.json() == {
        "student_id": student_id,
        "filename": "wang.docx",
        "paragraphs": ["实习经历：整车测试", "项目经历：读取传感器数据"],
        "text": "实习经历：整车测试\n项目经历：读取传感器数据",
    }

    with SessionLocal() as db:
        assert db.query(User).filter(User.role == "student").count() == 2


def test_resume_text_endpoint_handles_invalid_docx_and_pdf():
    malformed_csv = csv_file(["S1003", "周*宁", "汽车电子", "大二", "本科", "", "", "broken.docx"])
    malformed_import = client.post(
        "/api/recruiter/students/import",
        files=[
            ("csv_file", ("students.csv", malformed_csv, "text/csv")),
            ("resumes", ("broken.docx", b"PK\x03\x04not-a-docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
        ],
    )
    assert malformed_import.status_code == 200
    malformed_id = client.get("/api/students").json()["students"][0]["id"]
    malformed = client.get(f"/api/recruiter/students/{malformed_id}/resume/text")
    assert malformed.status_code == 422
    assert malformed.json()["detail"]["code"] == "INVALID_DOCX"

    pdf_csv = csv_file(["S1004", "吴*杰", "汽车电子", "大二", "本科", "", "", "resume.pdf"])
    pdf_import = client.post(
        "/api/recruiter/students/import",
        files=[("csv_file", ("students.csv", pdf_csv, "text/csv")), ("resumes", ("resume.pdf", b"%PDF-sample", "application/pdf"))],
    )
    assert pdf_import.status_code == 200
    pdf_id = next(student["id"] for student in client.get("/api/students").json()["students"] if student["student_no"] == "S1004")
    unsupported = client.get(f"/api/recruiter/students/{pdf_id}/resume/text")
    assert unsupported.status_code == 415
    assert unsupported.json()["detail"]["code"] == "RESUME_FORMAT_UNSUPPORTED"


def test_reimport_updates_same_student_without_losing_identity():
    initial = csv_file(["S1001", "王*明", "车辆工程", "大三", "本科", "一段实习", "无", ""])
    assert client.post("/api/recruiter/students/import", files={"csv_file": ("students.csv", initial)}).status_code == 200
    original_id = client.get("/api/students").json()["students"][0]["id"]

    revised = csv_file(["S1001", "王*明", "车辆工程", "大四", "本科", "两段实习", "省级二等奖", ""])
    response = client.post("/api/recruiter/students/import", files={"csv_file": ("students.csv", revised)})
    assert response.status_code == 200, response.text
    assert response.json() == {"created": 0, "updated": 1, "total": 1}
    students = client.get("/api/students").json()["students"]
    assert len(students) == 1
    assert students[0]["id"] == original_id
    detail = client.get(f"/api/recruiter/students/{original_id}").json()
    assert detail["grade"] == "大四"
    assert detail["awards"] == "省级二等奖"


def test_invalid_row_rolls_back_entire_import():
    data = csv_file(
        ["S1001", "王*明", "车辆工程", "大三", "本科", "", "", ""],
        ["S1002", "李*华", "汽车电子", "大二", "未知学历", "", "", ""],
    )
    response = client.post("/api/recruiter/students/import", files={"csv_file": ("students.csv", data)})
    assert response.status_code == 422
    assert client.get("/api/students").json()["students"] == []


def test_existing_sqlite_students_survive_schema_upgrade(tmp_path):
    legacy = create_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    with legacy.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, role VARCHAR(32), name_masked VARCHAR(128), major VARCHAR(128), grade VARCHAR(64))"))
        conn.execute(text("INSERT INTO users (id, role, name_masked, major, grade) VALUES (3, 'student', '王*明', '车辆工程', '大三')"))
    init_db(legacy)
    with legacy.connect() as conn:
        row = conn.execute(text("SELECT id, name_masked, student_no, education_level FROM users WHERE id=3")).one()
        assert tuple(row) == (3, "王*明", None, None)
