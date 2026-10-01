"""企业端学生档案导入与简历查看。"""

import csv
import io
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Path as ApiPath, UploadFile
from fastapi.responses import FileResponse, Response

from server.config import settings
from server.api.auth import require_recruiter
from server.db import SessionLocal
from server.models import User
from server.schemas import StudentImportResponse, StudentProfileResponse
from server.services.student_roster import (
    HEADERS,
    MAX_CSV_BYTES,
    MAX_RESUME_BYTES,
    ResumeUpload,
    ResumeReadError,
    RosterImportError,
    extract_docx_paragraphs,
    extract_docx_images,
    import_roster,
    parse_roster_csv,
    student_detail,
)

router = APIRouter(
    prefix="/api/recruiter/students",
    tags=["student-roster"],
    dependencies=[Depends(require_recruiter)],
)


def _error(exc: RosterImportError) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message})


@router.get("/template.csv")
def roster_template():
    stream = io.StringIO()
    csv.writer(stream).writerow(HEADERS)
    return Response(
        content=stream.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="student_roster_template.csv"'},
    )


@router.post("/import", response_model=StudentImportResponse)
async def upload_roster(csv_file: UploadFile = File(...), resumes: list[UploadFile] | None = File(None)):
    if not csv_file.filename or Path(csv_file.filename).suffix.lower() != ".csv":
        raise _error(RosterImportError("INVALID_CSV", "请选择 .csv 名单文件"))
    try:
        rows = parse_roster_csv(await csv_file.read(MAX_CSV_BYTES + 1))
        files: list[ResumeUpload] = []
        total_resume_bytes = 0
        for upload in resumes or []:
            data = await upload.read(MAX_RESUME_BYTES + 1)
            total_resume_bytes += len(data)
            if total_resume_bytes > 50 * 1024 * 1024:
                raise RosterImportError("INVALID_RESUME", "本次简历文件总量不能超过 50 MB")
            files.append(ResumeUpload(filename=upload.filename or "", data=data))
        with SessionLocal() as db:
            return import_roster(db, rows, files, settings.resume_upload_dir)
    except RosterImportError as exc:
        raise _error(exc) from exc


@router.get("/{student_id}", response_model=StudentProfileResponse)
def get_student_profile(student_id: int = ApiPath(..., ge=1)):
    with SessionLocal() as db:
        user = db.query(User).filter(User.id == student_id, User.role == "student").first()
        if user is None:
            raise HTTPException(status_code=404, detail={"code": "USER_NOT_FOUND", "message": "学生档案不存在"})
        return student_detail(user)


@router.get("/{student_id}/resume")
def get_student_resume(student_id: int = ApiPath(..., ge=1)):
    with SessionLocal() as db:
        user = db.query(User).filter(User.id == student_id, User.role == "student").first()
        if user is None or not user.resume_storage_key:
            raise HTTPException(status_code=404, detail={"code": "RESUME_NOT_FOUND", "message": "简历不存在"})
        directory = Path(settings.resume_upload_dir).resolve()
        file_path = (directory / user.resume_storage_key).resolve()
        if not file_path.is_relative_to(directory) or not file_path.is_file():
            raise HTTPException(status_code=404, detail={"code": "RESUME_NOT_FOUND", "message": "简历不存在"})
        is_pdf = file_path.suffix.lower() == ".pdf"
        return FileResponse(
            file_path,
            media_type="application/pdf" if is_pdf else "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=user.resume_original_name or file_path.name,
            content_disposition_type="inline" if is_pdf else "attachment",
        )


@router.get("/{student_id}/resume/text")
def get_student_resume_text(student_id: int = ApiPath(..., ge=1), include_images: bool = False):
    with SessionLocal() as db:
        user = db.query(User).filter(User.id == student_id, User.role == "student").first()
        if user is None or not user.resume_storage_key:
            raise HTTPException(status_code=404, detail={"code": "RESUME_NOT_FOUND", "message": "简历不存在"})
        directory = Path(settings.resume_upload_dir).resolve()
        file_path = (directory / user.resume_storage_key).resolve()
        if not file_path.is_relative_to(directory) or not file_path.is_file():
            raise HTTPException(status_code=404, detail={"code": "RESUME_NOT_FOUND", "message": "简历不存在"})
        if file_path.suffix.lower() != ".docx":
            raise HTTPException(
                status_code=415,
                detail={"code": "RESUME_FORMAT_UNSUPPORTED", "message": "网页文字读取目前仅支持 DOCX 格式"},
            )
        try:
            resume_data = file_path.read_bytes()
            paragraphs = extract_docx_paragraphs(resume_data)
        except (ResumeReadError, OSError):
            raise HTTPException(
                status_code=422,
                detail={"code": "INVALID_DOCX", "message": "DOCX 简历无法读取，请下载原文件检查"},
            ) from None
        result = {
            "student_id": user.id,
            "filename": user.resume_original_name or file_path.name,
            "paragraphs": paragraphs,
            "text": "\n".join(paragraphs),
        }
        if include_images:
            result["images"] = extract_docx_images(resume_data)
        return result
