from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import settings

engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
class Base(DeclarativeBase):
    pass

def ensure_schema_upgrades(target_engine=None):
    use_engine = target_engine or engine
    with use_engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(sessions)"))
        cols = {row[1] for row in result.fetchall()}
        if cols:
            if "pending_question_json" not in cols:
                conn.execute(text("ALTER TABLE sessions ADD COLUMN pending_question_json JSON"))
            if "lease_token" not in cols:
                conn.execute(text("ALTER TABLE sessions ADD COLUMN lease_token VARCHAR(64)"))
            if "lease_expires_at" not in cols:
                conn.execute(text("ALTER TABLE sessions ADD COLUMN lease_expires_at DATETIME"))
            if "input_mode" not in cols:
                conn.execute(text("ALTER TABLE sessions ADD COLUMN input_mode VARCHAR(16)"))

        result = conn.execute(text("PRAGMA table_info(reports)"))
        report_cols = {row[1] for row in result.fetchall()}
        if report_cols:
            if "scoring_version" not in report_cols:
                conn.execute(text("ALTER TABLE reports ADD COLUMN scoring_version VARCHAR(16)"))

        conn.commit()

def init_db(target_engine=None):
    from . import models
    use_engine = target_engine or engine
    Base.metadata.create_all(use_engine)
    ensure_schema_upgrades(use_engine)
