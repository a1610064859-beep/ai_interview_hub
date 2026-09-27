"""Authentication helpers: password hashes, profile registration, and opaque DB sessions."""

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta

from sqlalchemy.orm import Session as DbSession

from server.config import settings
from server.models import AuthSession, User


_PASSWORD_ITERATIONS = 600_000
_EMAIL_LOCAL_PATTERN = re.compile(r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}\Z", re.IGNORECASE)
_DOMAIN_LABEL_PATTERN = re.compile(r"[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\Z", re.IGNORECASE)
_SUPPORTED_EMAIL_TLDS = frozenset({
    "aero", "ai", "app", "asia", "biz", "cat", "cloud", "co", "com", "coop",
    "dev", "edu", "email", "gov", "info", "int", "io", "jobs", "me", "mil",
    "mobi", "museum", "name", "net", "online", "org", "post", "pro", "shop",
    "site", "store", "tech", "tel", "top", "travel", "tv", "vip", "wiki", "work",
    "xyz", "xxx",
})


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PASSWORD_ITERATIONS, dklen=32
    )
    return f"pbkdf2_sha256${_PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


_DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(48))


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        scheme, rounds_text, salt_text, expected = encoded.split("$", 3)
        rounds = int(rounds_text)
        salt = bytes.fromhex(salt_text)
        expected_bytes = bytes.fromhex(expected)
    except (ValueError, TypeError):
        return False
    if scheme != "pbkdf2_sha256" or not 100_000 <= rounds <= 1_000_000 or len(salt) != 16:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds, dklen=32)
    return hmac.compare_digest(actual, expected_bytes)


def normalize_email(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) > 254 or normalized.count("@") != 1:
        raise ValueError("邮箱格式不正确")
    local, domain = normalized.split("@", 1)
    labels = domain.split(".")
    if (
        not _EMAIL_LOCAL_PATTERN.fullmatch(local)
        or local.startswith(".")
        or local.endswith(".")
        or ".." in local
        or len(domain) > 253
        or len(labels) < 2
        or any(not _DOMAIN_LABEL_PATTERN.fullmatch(label) for label in labels)
        or len(labels[-1]) < 2
        or not labels[-1].isascii()
        or not labels[-1].isalpha()
    ):
        raise ValueError("邮箱格式不正确")
    return normalized


def validate_registration_email(value: str) -> str:
    normalized = normalize_email(value)
    tld = normalized.rsplit(".", 1)[-1]
    if len(tld) != 2 and tld not in _SUPPORTED_EMAIL_TLDS:
        raise ValueError("邮箱域名后缀暂不支持，请检查后使用常见邮箱后缀")
    return normalized


def normalize_profile_field(value: str, label: str) -> str:
    normalized = value.strip()
    if len(normalized) < 1 or any(ord(char) < 32 for char in normalized):
        raise ValueError(f"{label}格式不正确")
    return normalized


def register_student(
    db: DbSession, email: str, name: str, major: str, grade: str, password: str
) -> User:
    email = normalize_email(email)
    if db.query(User.id).filter(User.login_email == email, User.role == "student").first() is not None:
        raise ValueError("注册信息无效或邮箱已注册")
    name = normalize_profile_field(name, "姓名")
    major = normalize_profile_field(major, "专业")
    grade = normalize_profile_field(grade, "年级")
    name_masked = name[0] + "*" * max(1, len(name) - 1)
    user = User(
        role="student",
        login_email=email,
        password_hash=hash_password(password),
        name_masked=name_masked,
        major=major,
        grade=grade,
    )
    db.add(user)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise ValueError("注册信息无效或邮箱已注册") from None
    db.refresh(user)
    return user


def register_recruiter(
    db: DbSession,
    email: str,
    organization_name: str,
    contact_name: str,
    password: str,
) -> User:
    email = normalize_email(email)
    if db.query(User.id).filter(User.login_email == email, User.role == "recruiter").first() is not None:
        raise ValueError("注册信息无效或邮箱已注册")
    user = User(
        role="recruiter",
        login_email=email,
        password_hash=hash_password(password),
        organization_name=organization_name.strip(),
        contact_name=contact_name.strip(),
    )
    db.add(user)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise ValueError("注册信息无效或邮箱已注册") from None
    db.refresh(user)
    return user


def authenticate_student(db: DbSession, email: str, password: str) -> User | None:
    email = normalize_email(email)
    user = db.query(User).filter(User.login_email == email, User.role == "student").first()
    encoded = user.password_hash if user and user.password_hash else _DUMMY_PASSWORD_HASH
    if user is None or not verify_password(password, encoded):
        return None
    return user


def authenticate_recruiter(db: DbSession, email: str, password: str) -> User | None:
    email = normalize_email(email)
    user = db.query(User).filter(User.login_email == email, User.role == "recruiter").first()
    encoded = user.password_hash if user and user.password_hash else _DUMMY_PASSWORD_HASH
    if user is None or not verify_password(password, encoded):
        return None
    return user


def create_auth_session(db: DbSession, user: User) -> tuple[str, datetime]:
    now = datetime.utcnow()
    expires_at = now + timedelta(hours=settings.auth_session_hours)
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    db.query(AuthSession).filter(AuthSession.expires_at <= now).delete(synchronize_session=False)
    db.add(AuthSession(user_id=user.id, token_hash=token_hash, created_at=now, expires_at=expires_at))
    db.commit()
    return token, expires_at


def resolve_auth_session(db: DbSession, token: str | None) -> User | None:
    if not token or not 32 <= len(token) <= 128:
        return None
    token_hash = hashlib.sha256(token.encode("ascii", errors="ignore")).hexdigest()
    session = (
        db.query(AuthSession)
        .filter(AuthSession.token_hash == token_hash, AuthSession.expires_at > datetime.utcnow())
        .first()
    )
    if session is None:
        return None
    return db.query(User).filter(User.id == session.user_id).first()


def revoke_auth_session(db: DbSession, token: str | None) -> None:
    if not token or not 32 <= len(token) <= 128:
        return
    token_hash = hashlib.sha256(token.encode("ascii", errors="ignore")).hexdigest()
    db.query(AuthSession).filter(AuthSession.token_hash == token_hash).delete(synchronize_session=False)
    db.commit()


def user_summary(user: User) -> dict:
    return {
        "id": user.id,
        "role": user.role,
        "name_masked": user.name_masked,
        "major": user.major,
        "grade": user.grade,
        "student_no": user.student_no,
        "login_email": user.login_email,
        "organization_name": user.organization_name,
        "contact_name": user.contact_name,
    }
