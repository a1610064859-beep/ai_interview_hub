from collections import defaultdict, deque
from datetime import datetime
import hashlib
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from server.config import settings
from server.db import SessionLocal
from server.models import User
from server.services import auth as auth_service


router = APIRouter(prefix="/api/auth", tags=["auth"])
AUTH_COOKIE_NAME = "aihub_session"
_LOGIN_WINDOW_SECONDS = 15 * 60
_LOGIN_MAX_ATTEMPTS = 8
_login_failures: dict[str, deque[float]] = defaultdict(deque)
_login_failures_lock = Lock()


def _validate_registration_password(value: str) -> str:
    has_letter = any(char.isascii() and char.isalpha() for char in value)
    has_digit = any(char.isascii() and char.isdigit() for char in value)
    if len(value) < 9 or not has_letter or not has_digit:
        raise ValueError("密码至少9位，且必须包含英文字母和数字")
    return value


class StudentRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(..., min_length=3, max_length=254)
    name: str = Field(..., min_length=1, max_length=128)
    major: str = Field(..., min_length=1, max_length=128)
    grade: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=9, max_length=128)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        return auth_service.validate_registration_email(value)

    @field_validator("name", "major", "grade")
    @classmethod
    def normalize_profile(cls, value: str, info) -> str:
        return auth_service.normalize_profile_field(value, info.field_name)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return _validate_registration_password(value)


class RecruiterRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(..., min_length=3, max_length=254)
    organization_name: str = Field(..., min_length=2, max_length=128)
    contact_name: str = Field(..., min_length=2, max_length=128)
    password: str = Field(..., min_length=9, max_length=128)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        return auth_service.validate_registration_email(value)

    @field_validator("organization_name", "contact_name")
    @classmethod
    def normalize_names(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2 or any(ord(char) < 32 for char in normalized):
            raise ValueError("该字段格式不正确")
        return normalized

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return _validate_registration_password(value)


class StudentLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        return auth_service.normalize_email(value)


class RecruiterLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        return auth_service.normalize_email(value)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    if not settings.auth_required:
        return None
    token = request.cookies.get(AUTH_COOKIE_NAME)
    user = auth_service.resolve_auth_session(db, token)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_REQUIRED", "message": "请先登录"},
            headers={"WWW-Authenticate": "Cookie"},
        )
    request.state.current_user = user
    return user


def require_student(user: User | None = Depends(require_current_user)) -> User | None:
    if user is not None and user.role != "student":
        raise HTTPException(status_code=403, detail={"code": "ROLE_FORBIDDEN", "message": "仅学生账号可访问"})
    return user


def require_recruiter(user: User | None = Depends(require_current_user)) -> User | None:
    if user is not None and user.role not in {"recruiter", "admin"}:
        raise HTTPException(status_code=403, detail={"code": "ROLE_FORBIDDEN", "message": "仅企业账号可访问"})
    return user


def require_authenticated(user: User | None = Depends(require_current_user)) -> User | None:
    return user


def _login_key(request: Request, role: str, identifier: str) -> str:
    client_ip = request.client.host if request.client else "unknown"
    identifier_hash = hashlib.sha256(identifier.casefold().encode("utf-8")).hexdigest()
    return f"{client_ip}:{role}:{identifier_hash}"


def _check_login_limit(key: str) -> None:
    now = datetime.utcnow().timestamp()
    with _login_failures_lock:
        attempts = _login_failures[key]
        while attempts and now - attempts[0] >= _LOGIN_WINDOW_SECONDS:
            attempts.popleft()
        if len(attempts) >= _LOGIN_MAX_ATTEMPTS:
            raise HTTPException(
                status_code=429,
                detail={"code": "LOGIN_RATE_LIMITED", "message": "登录尝试过多，请 15 分钟后重试"},
            )


def _record_login_failure(key: str) -> None:
    now = datetime.utcnow().timestamp()
    with _login_failures_lock:
        attempts = _login_failures[key]
        while attempts and now - attempts[0] >= _LOGIN_WINDOW_SECONDS:
            attempts.popleft()
        attempts.append(now)
        if len(_login_failures) > 4096:
            for stale_key in [k for k, values in _login_failures.items() if not values or now - values[-1] >= _LOGIN_WINDOW_SECONDS]:
                _login_failures.pop(stale_key, None)


def _set_auth_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        max_age=settings.auth_session_hours * 60 * 60,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/",
    )


def _session_response(response: Response, request: Request, db: Session, user: User) -> dict:
    auth_service.revoke_auth_session(db, request.cookies.get(AUTH_COOKIE_NAME))
    token, _expires_at = auth_service.create_auth_session(db, user)
    _set_auth_cookie(response, request, token)
    return {"authenticated": True, "user": auth_service.user_summary(user)}


@router.post("/register/student", status_code=201)
def register_student(request: Request, response: Response, body: StudentRegisterRequest, db: Session = Depends(get_db)):
    try:
        user = auth_service.register_student(
            db, body.email, body.name, body.major, body.grade, body.password
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "REGISTRATION_FAILED", "message": str(exc)},
        ) from exc
    return _session_response(response, request, db, user)


@router.post("/register/recruiter", status_code=201)
def register_recruiter(request: Request, response: Response, body: RecruiterRegisterRequest, db: Session = Depends(get_db)):
    try:
        user = auth_service.register_recruiter(
            db,
            body.email,
            body.organization_name,
            body.contact_name,
            body.password,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "REGISTRATION_FAILED", "message": str(exc)},
        ) from exc
    return _session_response(response, request, db, user)


@router.post("/login/student")
def login_student(request: Request, response: Response, body: StudentLoginRequest, db: Session = Depends(get_db)):
    key = _login_key(request, "student", body.email)
    _check_login_limit(key)
    user = auth_service.authenticate_student(db, body.email, body.password)
    if user is None:
        _record_login_failure(key)
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_CREDENTIALS", "message": "邮箱或密码不正确"},
        )
    with _login_failures_lock:
        _login_failures.pop(key, None)
    return _session_response(response, request, db, user)


@router.post("/login/recruiter")
def login_recruiter(request: Request, response: Response, body: RecruiterLoginRequest, db: Session = Depends(get_db)):
    key = _login_key(request, "recruiter", body.email)
    _check_login_limit(key)
    user = auth_service.authenticate_recruiter(db, body.email, body.password)
    if user is None:
        _record_login_failure(key)
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_CREDENTIALS", "message": "邮箱或密码不正确"},
        )
    with _login_failures_lock:
        _login_failures.pop(key, None)
    return _session_response(response, request, db, user)


@router.get("/me")
def auth_me(request: Request, db: Session = Depends(get_db)):
    user = auth_service.resolve_auth_session(db, request.cookies.get(AUTH_COOKIE_NAME))
    if user is None:
        return {"authenticated": False, "user": None}
    return {"authenticated": True, "user": auth_service.user_summary(user)}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    auth_service.revoke_auth_session(db, request.cookies.get(AUTH_COOKIE_NAME))
    response.delete_cookie(
        AUTH_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
    )
    return {"authenticated": False, "user": None}
