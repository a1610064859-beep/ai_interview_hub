from datetime import datetime
from sqlalchemy import Integer, String, Text, JSON, Boolean, Float, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

class User(Base):
    __tablename__="users"
    id: Mapped[int]=mapped_column(Integer, primary_key=True)
    role: Mapped[str]=mapped_column(String(32))
    name_masked: Mapped[str|None]=mapped_column(String(128), nullable=True)
    major: Mapped[str|None]=mapped_column(String(128), nullable=True)
    grade: Mapped[str|None]=mapped_column(String(64), nullable=True)
    student_no: Mapped[str|None]=mapped_column(String(64), nullable=True, unique=True)
    education_level: Mapped[str|None]=mapped_column(String(32), nullable=True)
    internship_experience: Mapped[str|None]=mapped_column(Text, nullable=True)
    awards: Mapped[str|None]=mapped_column(Text, nullable=True)
    resume_storage_key: Mapped[str|None]=mapped_column(String(80), nullable=True)
    resume_original_name: Mapped[str|None]=mapped_column(String(255), nullable=True)
class Job(Base):
    __tablename__="jobs"
    id: Mapped[int]=mapped_column(Integer, primary_key=True)
    family: Mapped[str]=mapped_column(String(128)); title: Mapped[str]=mapped_column(String(128))
    jd_digest: Mapped[str|None]=mapped_column(Text, nullable=True); terms_json: Mapped[dict|None]=mapped_column(JSON); dims_json: Mapped[dict|None]=mapped_column(JSON)
class Question(Base):
    __tablename__="questions"
    id: Mapped[int]=mapped_column(Integer, primary_key=True); job_id: Mapped[int]=mapped_column(Integer)
    type: Mapped[str]=mapped_column(String(32)); text: Mapped[str]=mapped_column(Text); followup_hint: Mapped[str|None]=mapped_column(Text, nullable=True)
class Session(Base):
    __tablename__="sessions"
    id: Mapped[int]=mapped_column(Integer, primary_key=True); user_id: Mapped[int]=mapped_column(Integer); job_id: Mapped[int]=mapped_column(Integer)
    mode: Mapped[str]=mapped_column(String(32)); started_at: Mapped[datetime|None]=mapped_column(DateTime, nullable=True); status: Mapped[str]=mapped_column(String(32))
    pending_question_json: Mapped[dict|None]=mapped_column(JSON, nullable=True)
    lease_token: Mapped[str|None]=mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime|None]=mapped_column(DateTime, nullable=True)
    input_mode: Mapped[str|None]=mapped_column(String(16), nullable=True)
class Answer(Base):
    __tablename__="answers"
    id: Mapped[int]=mapped_column(Integer, primary_key=True); session_id: Mapped[int]=mapped_column(Integer); q_seq: Mapped[int]=mapped_column(Integer)
    question_text: Mapped[str]=mapped_column(Text); answer_text: Mapped[str]=mapped_column(Text); is_followup: Mapped[bool]=mapped_column(Boolean)
    is_retry: Mapped[bool]=mapped_column(Boolean); duration_s: Mapped[float|None]=mapped_column(Float, nullable=True); wpm: Mapped[float|None]=mapped_column(Float, nullable=True); pause_cnt: Mapped[int|None]=mapped_column(Integer, nullable=True); filler_cnt: Mapped[int|None]=mapped_column(Integer, nullable=True)
class Report(Base):
    __tablename__="reports"
    id: Mapped[int]=mapped_column(Integer, primary_key=True); session_id: Mapped[int]=mapped_column(Integer)
    dimensions_json: Mapped[dict|None]=mapped_column(JSON); highlights_json: Mapped[dict|None]=mapped_column(JSON); concerns_json: Mapped[dict|None]=mapped_column(JSON); improvement_json: Mapped[dict|None]=mapped_column(JSON); overall: Mapped[float|None]=mapped_column(Float, nullable=True)
    scoring_version: Mapped[str|None]=mapped_column(String(16), nullable=True)
