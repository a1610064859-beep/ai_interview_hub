from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import settings

_is_sqlite = make_url(settings.database_url).get_backend_name() == "sqlite"

engine = create_engine(
    settings.database_url,
    future=True,
    connect_args={"timeout": 30} if _is_sqlite else {},
)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
        finally:
            cursor.close()
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
