"""Timeout regressions use isolated state, synthetic audio, and no external models."""
import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from server.config import settings
from server.db import Base
from server.main import app
from server.models import Answer, Session
from server.services import asr, audio, llm
from pydantic import BaseModel


def test_session_snapshot_recovers_committed_next_question(monkeypatch):
    from server.api import sessions
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(sessions, "SessionLocal", factory)
    with factory() as db:
        db.add(Session(id=1, user_id=1, job_id=1, mode="毕业生", status="active",
                       pending_question_json={"seq": 2, "text": "下一题", "audio_url": None, "is_followup": False}))
        db.add(Answer(session_id=1, q_seq=1, question_text="第一题", answer_text="回答",
                      is_followup=False, is_retry=False))
        db.commit()
    client = TestClient(app)
    payload = client.get("/api/sessions/1/state").json()
    assert payload["answer_count"] == 1
    assert payload["status"] == "active"
    assert payload["question"]["seq"] == 2
    assert "lease_token" not in payload
    assert client.get("/api/sessions/99/state").status_code == 404
    with factory() as db:
        db.get(Session, 1).status = "answering"
        db.commit()
    assert client.get("/api/sessions/1/state").json()["status"] == "answering"
    engine.dispose()


def test_asr_timeout_keeps_owned_audio_and_refuses_overlapping_inference(monkeypatch, tmp_path):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    observed = []
    def generate(input):
        entered.set()
        try:
            release.wait(2)
            observed.append(Path(input).read_bytes())
            return [{"text": "测 试"}]
        finally:
            finished.set()
    monkeypatch.setattr(asr, "_load_model", lambda: SimpleNamespace(generate=generate))
    monkeypatch.setattr(settings, "asr_timeout_s", 0.04)
    monkeypatch.setattr(settings, "asr_temp_dir", str(tmp_path))
    wav = tmp_path / "request.wav"
    wav.write_bytes(b"owned audio")
    async def scenario():
        with pytest.raises(asr.ASRUnavailableError):
            await asr.transcribe_wav(str(wav))
        assert entered.is_set()
        wav.unlink()
        other = tmp_path / "other.wav"
        other.write_bytes(b"second")
        with pytest.raises(asr.ASRUnavailableError, match="繁忙"):
            await asr.transcribe_wav(str(other))
        release.set()
        await asyncio.to_thread(finished.wait, 2)
    try:
        asyncio.run(scenario())
    finally:
        release.set()
    assert observed == [b"owned audio"]


def test_llm_stage_has_total_deadline_and_no_sdk_retries(monkeypatch):
    seen = []
    class Out(BaseModel):
        value: str
    class Client:
        def __init__(self, **kwargs):
            seen.append(kwargs)
            self.chat = SimpleNamespace(completions=self)
        async def create(self, **kwargs):
            await asyncio.sleep(0.2)
        async def close(self):
            pass
    monkeypatch.setattr(llm, "AsyncOpenAI", Client)
    config = SimpleNamespace(local_model="local", local_base_url="http://unused", local_api_key="x",
                             flash_model="flash", flash_base_url="http://unused", flash_api_key="x",
                             llm_orchestration_timeout_s=0.04)
    client = llm.LLMClient(config)
    monkeypatch.setattr(client, "_save_record", client.records.append)
    begin = time.perf_counter()
    with pytest.raises(llm.LLMError):
        asyncio.run(client.chat_json("orchestration", [], Out))
    assert time.perf_counter() - begin < 0.15
    assert all(item["max_retries"] == 0 for item in seen)
    assert client.records and all("total_ms" in item for item in client.records)
