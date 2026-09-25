"""固定 CSV 学生名单导入；档案与简历不参与评分。"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree

from sqlalchemy.orm import Session as DbSession

from server.models import User

HEADERS = ("学生编号", "姓名（脱敏）", "专业", "年级", "学历", "实习经历", "获奖情况", "简历文件名")
EDUCATION_LEVELS = ("中职", "高职/大专", "本科", "硕士", "博士")
ALLOWED_RESUME_EXTENSIONS = {".docx", ".pdf"}
MAX_CSV_BYTES = 2 * 1024 * 1024
MAX_RESUME_BYTES = 10 * 1024 * 1024
MAX_DOCX_XML_BYTES = 5 * 1024 * 1024
MAX_ROWS = 500
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


class ResumeReadError(ValueError):
    pass


def extract_docx_paragraphs(data: bytes) -> list[str]:
    """Extract readable paragraph text from a DOCX body without external libraries."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            document_info = archive.getinfo("word/document.xml")
            if document_info.file_size > MAX_DOCX_XML_BYTES:
                raise ResumeReadError("简历正文超出可读取大小")
            with archive.open(document_info) as document_file:
                document_xml = document_file.read(MAX_DOCX_XML_BYTES + 1)
            if len(document_xml) > MAX_DOCX_XML_BYTES:
                raise ResumeReadError("简历正文超出可读取大小")
        root = ElementTree.fromstring(document_xml)
    except ResumeReadError:
        raise
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, OSError, RuntimeError) as exc:
        raise ResumeReadError("DOCX 文件损坏或缺少正文") from exc

    paragraphs: list[str] = []
    for paragraph in root.iter(f"{{{_W_NS}}}p"):
        parts: list[str] = []
        for element in paragraph.iter():
            if element.tag == f"{{{_W_NS}}}t":
                parts.append(element.text or "")
            elif element.tag == f"{{{_W_NS}}}tab":
                parts.append("\t")
            elif element.tag in {f"{{{_W_NS}}}br", f"{{{_W_NS}}}cr"}:
                parts.append("\n")
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)
    return paragraphs


class RosterImportError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ResumeUpload:
    filename: str
    data: bytes


def _required(value: str, label: str, row_num: int, limit: int) -> str:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > limit:
        raise RosterImportError("INVALID_ROW", f"第 {row_num} 行的{label}须为 1–{limit} 字符")
    return cleaned


def _optional(value: str, label: str, row_num: int, limit: int) -> str | None:
    cleaned = value.strip()
    if len(cleaned) > limit:
        raise RosterImportError("INVALID_ROW", f"第 {row_num} 行的{label}最多 {limit} 字符")
    return cleaned or None


def parse_roster_csv(content: bytes) -> list[dict[str, str | None]]:
    if not content or len(content) > MAX_CSV_BYTES:
        raise RosterImportError("INVALID_CSV", "CSV 不能为空且不能超过 2 MB")
    try:
        decoded = content.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise RosterImportError("INVALID_CSV", "CSV 必须保存为 UTF-8 编码") from exc
    reader = csv.DictReader(io.StringIO(decoded, newline=""))
    if tuple(reader.fieldnames or ()) != HEADERS:
        raise RosterImportError("INVALID_HEADER", "CSV 表头必须与下载模板完全一致")

    rows: list[dict[str, str | None]] = []
    seen_numbers: set[str] = set()
    for row_num, raw in enumerate(reader, start=2):
        if row_num > MAX_ROWS + 1:
            raise RosterImportError("TOO_MANY_ROWS", f"每次最多导入 {MAX_ROWS} 名学生")
        if None in raw or any(value is None for value in raw.values()):
            raise RosterImportError("INVALID_ROW", f"第 {row_num} 行列数不符合模板")
        student_no = _required(raw["学生编号"], "学生编号", row_num, 64)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", student_no):
            raise RosterImportError("INVALID_ROW", f"第 {row_num} 行学生编号只能用英文字母、数字、_ 或 -")
        if student_no in seen_numbers:
            raise RosterImportError("DUPLICATE_STUDENT_NO", f"第 {row_num} 行学生编号重复：{student_no}")
        seen_numbers.add(student_no)
        education = _required(raw["学历"], "学历", row_num, 32)
        if education not in EDUCATION_LEVELS:
            raise RosterImportError("INVALID_ROW", f"第 {row_num} 行学历须为：{'、'.join(EDUCATION_LEVELS)}")
        rows.append({
            "student_no": student_no,
            "name_masked": _required(raw["姓名（脱敏）"], "姓名（脱敏）", row_num, 128),
            "major": _required(raw["专业"], "专业", row_num, 128),
            "grade": _optional(raw["年级"], "年级", row_num, 64),
            "education_level": education,
            "internship_experience": _optional(raw["实习经历"], "实习经历", row_num, 2000),
            "awards": _optional(raw["获奖情况"], "获奖情况", row_num, 2000),
            "resume_filename": _optional(raw["简历文件名"], "简历文件名", row_num, 255),
        })
    if not rows:
        raise RosterImportError("INVALID_CSV", "CSV 至少需要一行学生数据")
    return rows


def _validate_resume_name(filename: str) -> None:
    if (not filename or len(filename) > 255 or filename in (".", "..")
            or "/" in filename or "\\" in filename or "\x00" in filename
            or Path(filename).suffix.lower() not in ALLOWED_RESUME_EXTENSIONS):
        raise RosterImportError("INVALID_RESUME", f"简历文件名无效或格式不支持：{filename}")


def validate_resumes(rows: list[dict[str, str | None]], uploads: list[ResumeUpload]) -> dict[str, ResumeUpload]:
    referenced = {row["resume_filename"] for row in rows if row["resume_filename"]}
    files: dict[str, ResumeUpload] = {}
    for upload in uploads:
        _validate_resume_name(upload.filename)
        if upload.filename in files:
            raise RosterImportError("DUPLICATE_RESUME", f"重复选择了简历文件：{upload.filename}")
        if not upload.data or len(upload.data) > MAX_RESUME_BYTES:
            raise RosterImportError("INVALID_RESUME", f"简历文件为空或超过 10 MB：{upload.filename}")
        if upload.filename.lower().endswith(".pdf") and not upload.data.startswith(b"%PDF-"):
            raise RosterImportError("INVALID_RESUME", f"PDF 文件格式不正确：{upload.filename}")
        if upload.filename.lower().endswith(".docx") and not upload.data.startswith(b"PK\x03\x04"):
            raise RosterImportError("INVALID_RESUME", f"Word 文件格式不正确：{upload.filename}")
        files[upload.filename] = upload
    if set(files) != referenced:
        missing = sorted(referenced - set(files))
        extra = sorted(set(files) - referenced)
        raise RosterImportError("RESUME_MISMATCH", f"简历文件与 CSV 不匹配；缺少：{missing}；未引用：{extra}")
    return files


def import_roster(
    db: DbSession,
    rows: list[dict[str, str | None]],
    uploads: list[ResumeUpload],
    upload_dir: str,
) -> dict[str, int]:
    files = validate_resumes(rows, uploads)
    numbers = [str(row["student_no"]) for row in rows]
    existing = {user.student_no: user for user in db.query(User).filter(User.student_no.in_(numbers)).all()}
    directory = Path(upload_dir).resolve()
    created_paths: list[Path] = []
    replaced_keys: list[str] = []
    created = 0
    updated = 0
    try:
        for row in rows:
            student_no = str(row["student_no"])
            user = existing.get(student_no)
            if user is None:
                user = User(role="student", student_no=student_no)
                db.add(user)
                created += 1
            else:
                if user.role != "student":
                    raise RosterImportError("STUDENT_NO_CONFLICT", f"编号 {student_no} 已用于非学生账号")
                updated += 1
            for field in ("name_masked", "major", "grade", "education_level", "internship_experience", "awards"):
                setattr(user, field, row[field])
            filename = row["resume_filename"]
            if filename:
                upload = files[filename]
                directory.mkdir(parents=True, exist_ok=True)
                key = f"{uuid4().hex}{Path(filename).suffix.lower()}"
                destination = directory / key
                destination.write_bytes(upload.data)
                created_paths.append(destination)
                if user.resume_storage_key:
                    replaced_keys.append(user.resume_storage_key)
                user.resume_storage_key = key
                user.resume_original_name = filename
        db.commit()
    except Exception:
        db.rollback()
        for path in created_paths:
            path.unlink(missing_ok=True)
        raise
    for key in replaced_keys:
        old_path = (directory / key).resolve()
        if old_path.is_relative_to(directory):
            try:
                old_path.unlink(missing_ok=True)
            except OSError:
                pass
    return {"created": created, "updated": updated, "total": len(rows)}


def student_detail(user: User) -> dict:
    return {
        "id": user.id,
        "student_no": user.student_no,
        "name_masked": user.name_masked,
        "major": user.major,
        "grade": user.grade,
        "education_level": user.education_level,
        "internship_experience": user.internship_experience,
        "awards": user.awards,
        "has_resume": bool(user.resume_storage_key),
        "resume_filename": user.resume_original_name,
    }
