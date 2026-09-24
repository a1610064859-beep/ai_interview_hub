import asyncio
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.config import Settings
from server.services.llm import LLMClient, LLMError


class Out(BaseModel):
    value: str


def make_settings(**kwargs):
    defaults = {
        "local_model": "local_m",
        "local_base_url": "http://local:11434/v1",
        "local_api_key": "ollama",
        "flash_model": "flash_m",
        "flash_base_url": "https://dashscope.example.com/v1",
        "flash_api_key": "flash_key",
        "flagship_model": "flagship_m",
        "flagship_base_url": "https://dashscope.example.com/v1",
        "flagship_api_key": "flagship_key",
        "llm_orchestration_timeout_s": 6.0,
        "llm_scoring_timeout_s": 60.0,
        "llm_usage_log_path": "logs/test_llm_usage.jsonl",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class FakeResp:
    def __init__(self, text='{"value":"ok"}', tokens=12):
        self.choices = [SimpleNamespace(message=SimpleNamespace(content=text))]
        self.usage = SimpleNamespace(total_tokens=tokens)


class FakeClient:
    def __init__(self, resp=None):
        self._resp = resp or FakeResp()

    class chat:
        class completions:
            @staticmethod
            async def create(**kwargs):
                return FakeResp()


# A. JSON -> Pydantic 转换测试（非流式模式记录首个可用响应耗时）
def test_json_to_pydantic(monkeypatch):
    settings = make_settings()
    client = LLMClient(settings)
    monkeypatch.setattr("server.services.llm.AsyncOpenAI", lambda **x: FakeClient())

    result = asyncio.run(client.chat_json("orchestration", [{"role": "user", "content": "x"}], Out))

    assert result.value == "ok"
    assert len(client.records) == 1
    rec = client.records[0]
    assert rec["stage"] == "orchestration"
    assert rec["model"] == "local_m"
    assert rec["success"] is True
    assert rec["error"] is None
    assert rec["total_tokens"] == 12
    # 非流式模式无法测量真实首字时延，按规约为 None (JSON null)
    assert rec["ttft_ms"] >= 0


# B. ValidationError retry 一次测试（第1次校验失败重试，第2次成功）
def test_validation_error_retry_once(monkeypatch):
    calls = []

    class BadThenGood:
        def __init__(self, **kwargs):
            pass

        class chat:
            class completions:
                @staticmethod
                async def create(**kwargs):
                    calls.append(kwargs.get("model"))
                    if len(calls) == 1:
                        # 缺失必要字段 value，触发 ValidationError
                        return FakeResp('{"bad_key": 123}', tokens=5)
                    return FakeResp('{"value": "retry_ok"}', tokens=8)

    monkeypatch.setattr("server.services.llm.AsyncOpenAI", lambda **x: BadThenGood(**x))
    client = LLMClient(make_settings())

    result = asyncio.run(client.chat_json("orchestration", [], Out))
    assert result.value == "retry_ok"
    # 同一模型 local_m 调用了2次（初始+1次重试）
    assert calls == ["local_m", "local_m"]
    # 恰好产生 2 条调用记录，无重复记录（Astra 反馈 4）
    assert len(client.records) == 2
    assert client.records[0]["success"] is False
    assert client.records[0]["error"] == "validation_error"
    assert client.records[0]["total_tokens"] == 5
    assert client.records[0]["ttft_ms"] >= 0
    assert client.records[1]["success"] is True
    assert client.records[1]["error"] is None
    assert client.records[1]["total_tokens"] == 8
    assert client.records[1]["ttft_ms"] >= 0


# C1. Fallback 成功：编排模式 local 失败重试1次后仍失败，fallback flash 成功
def test_fallback_orchestration_local_to_flash(monkeypatch):
    calls = []

    class LocalFailFlashSuccess:
        def __init__(self, **kwargs):
            pass

        class chat:
            class completions:
                @staticmethod
                async def create(**kwargs):
                    m = kwargs.get("model")
                    calls.append(m)
                    if m == "local_m":
                        # local 两次都返回非法结构
                        return FakeResp('{"wrong": 1}', tokens=3)
                    # flash 返回合法数据
                    return FakeResp('{"value": "flash_ok"}', tokens=15)

    monkeypatch.setattr("server.services.llm.AsyncOpenAI", lambda **x: LocalFailFlashSuccess(**x))
    client = LLMClient(make_settings())

    result = asyncio.run(client.chat_json("orchestration", [], Out))
    assert result.value == "flash_ok"
    # local 失败 -> retry 1次 -> fallback flash 成功
    assert calls == ["local_m", "local_m", "flash_m"]
    assert len(client.records) == 3
    assert client.records[0]["model"] == "local_m" and client.records[0]["success"] is False
    assert client.records[1]["model"] == "local_m" and client.records[1]["success"] is False
    assert client.records[2]["model"] == "flash_m" and client.records[2]["success"] is True


# C2. Fallback 成功：评分模式 flagship 优先，flagship 失败，local 接管成功
def test_scoring_flagship_first_and_local_fallback(monkeypatch):
    calls = []

    class FlagshipFailLocalSuccess:
        def __init__(self, **kwargs):
            pass

        class chat:
            class completions:
                @staticmethod
                async def create(**kwargs):
                    m = kwargs.get("model")
                    calls.append(m)
                    if m == "flagship_m":
                        raise RuntimeError("flagship service unavailable")
                    return FakeResp('{"value": "local_fallback_ok"}', tokens=20)

    monkeypatch.setattr("server.services.llm.AsyncOpenAI", lambda **x: FlagshipFailLocalSuccess(**x))
    client = LLMClient(make_settings())

    result = asyncio.run(client.chat_json("scoring", [], Out))
    assert result.value == "local_fallback_ok"
    # flagship 优先尝试，失败后 local 接管
    assert calls == ["flagship_m", "local_m"]
    assert len(client.records) == 2
    assert client.records[0]["model"] == "flagship_m" and client.records[0]["success"] is False
    assert client.records[0]["error"] == "RuntimeError"
    assert client.records[1]["model"] == "local_m" and client.records[1]["success"] is True


# D. 分阶段 timeout 边界与选择测试
def test_timeout_forwarded_and_stage_selection(monkeypatch):
    seen_timeouts = {}

    class TimeoutRecorder:
        def __init__(self, **kwargs):
            pass

        class chat:
            class completions:
                @staticmethod
                async def create(**kwargs):
                    model = kwargs.get("model")
                    seen_timeouts[model] = kwargs.get("timeout")
                    return FakeResp('{"value": "ok"}')

    monkeypatch.setattr("server.services.llm.AsyncOpenAI", lambda **x: TimeoutRecorder(**x))
    client = LLMClient(make_settings(llm_orchestration_timeout_s=6.0, llm_scoring_timeout_s=60.0))

    # 单次请求使用剩余阶段预算；外层 deadline 负责总超时，SDK 禁止隐式重试
    asyncio.run(client.chat_json("orchestration", [], Out))
    assert seen_timeouts["local_m"] == pytest.approx(6.0, abs=0.1)

    # scoring 主模型最多占用一半阶段预算，给本地兜底留出时间
    asyncio.run(client.chat_json("scoring", [], Out))
    assert seen_timeouts["flagship_m"] == pytest.approx(30.0, abs=0.1)


def test_local_uses_json_schema_response_format(monkeypatch, tmp_path):
    formats = []

    class FormatRecorder:
        def __init__(self, **kwargs):
            pass

        class chat:
            class completions:
                @staticmethod
                async def create(**kwargs):
                    formats.append(kwargs["response_format"])
                    return FakeResp('{"value": "ok"}')

    monkeypatch.setattr("server.services.llm.AsyncOpenAI", lambda **x: FormatRecorder(**x))
    client = LLMClient(make_settings(llm_usage_log_path=str(tmp_path / "usage.jsonl")))

    result = asyncio.run(client.chat_json("followup", [], Out))

    assert result.value == "ok"
    assert formats == [
        {
            "type": "json_schema",
            "json_schema": {
                "name": "Out",
                "strict": True,
                "schema": Out.model_json_schema(),
            },
        }
    ]


def test_scoring_primary_timeout_still_reaches_local_fallback(monkeypatch, tmp_path):
    calls = []

    class SlowFlagship:
        def __init__(self, **kwargs):
            pass

        class chat:
            class completions:
                @staticmethod
                async def create(**kwargs):
                    calls.append(kwargs["model"])
                    if kwargs["model"] == "flagship_m":
                        await asyncio.sleep(1)
                    return FakeResp('{"value": "local_fallback_ok"}')

    monkeypatch.setattr("server.services.llm.AsyncOpenAI", lambda **x: SlowFlagship(**x))
    client = LLMClient(make_settings(
        llm_scoring_timeout_s=0.2,
        llm_usage_log_path=str(tmp_path / "usage.jsonl"),
    ))

    result = asyncio.run(client.chat_json("scoring", [], Out))

    assert result.value == "local_fallback_ok"
    assert calls == ["flagship_m", "local_m"]


# E. 全链失败产生明确 LLMError
def test_all_failed_raises_llmerror(monkeypatch):
    class AlwaysFail:
        def __init__(self, **kwargs):
            pass

        class chat:
            class completions:
                @staticmethod
                async def create(**kwargs):
                    raise TimeoutError("connection timed out")

    monkeypatch.setattr("server.services.llm.AsyncOpenAI", lambda **x: AlwaysFail(**x))
    client = LLMClient(make_settings())

    with pytest.raises(LLMError, match="all llm attempts failed"):
        asyncio.run(client.chat_json("orchestration", [], Out))


# F & G. 内存捕获验证写入成功路径（替换读取日志文件验证，检查字段完整性与无敏感信息）
def test_usage_logging_fields_and_persistence_memory_success(monkeypatch):
    written_lines = []

    class MockFile:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def write(self, text):
            written_lines.append(text)

    def fake_open(self, mode="r", encoding=None):
        return MockFile()

    monkeypatch.setattr(Path, "open", fake_open)
    settings = make_settings(llm_usage_log_path="logs/usage_test.jsonl")

    class MixedOutcome:
        def __init__(self, **kwargs):
            pass

        class chat:
            class completions:
                @staticmethod
                async def create(**kwargs):
                    m = kwargs.get("model")
                    if m == "local_m":
                        raise TimeoutError("timeout on local")
                    return FakeResp('{"value": "ok"}', tokens=42)

    monkeypatch.setattr("server.services.llm.AsyncOpenAI", lambda **x: MixedOutcome(**x))
    client = LLMClient(settings)

    result = asyncio.run(client.chat_json("orchestration", [], Out))
    assert result.value == "ok"

    # 1. 验证 in-memory records
    assert len(client.records) == 2
    fail_rec, succ_rec = client.records[0], client.records[1]

    for r in [fail_rec, succ_rec]:
        assert "stage" in r
        assert "model" in r
        assert "success" in r
        assert "ttft_ms" in r
        assert "total_tokens" in r
        assert "error" in r
        assert "api_key" not in r
        assert "content" not in r
        assert "messages" not in r

    assert fail_rec["success"] is False
    assert fail_rec["error"] == "TimeoutError"
    assert fail_rec["ttft_ms"] is None
    assert succ_rec["success"] is True
    assert succ_rec["total_tokens"] == 42
    assert succ_rec["ttft_ms"] >= 0

    # 2. 内存捕获验证写入内容（无磁盘读取）
    assert len(written_lines) == 2
    loaded = [json.loads(line) for line in written_lines]
    assert loaded[0]["model"] == "local_m" and loaded[0]["success"] is False
    assert loaded[0]["ttft_ms"] is None
    assert loaded[1]["model"] == "flash_m" and loaded[1]["success"] is True
    assert loaded[1]["ttft_ms"] >= 0
    assert loaded[1]["total_tokens"] == 42
    for item in loaded:
        assert "api_key" not in item
        assert "content" not in item
        assert "messages" not in item


# G2. 内存捕获验证写入失败路径（可观察告警，不含敏感信息，业务不中断且内存记账完整）
def test_usage_logging_write_failure_warning(monkeypatch, caplog):
    def fake_open_fail(self, mode="r", encoding=None):
        raise OSError("Simulated disk error on logs/usage_fail.jsonl")

    monkeypatch.setattr(Path, "open", fake_open_fail)
    settings = make_settings(llm_usage_log_path="logs/usage_fail.jsonl")
    client = LLMClient(settings)
    monkeypatch.setattr("server.services.llm.AsyncOpenAI", lambda **x: FakeClient())

    with caplog.at_level(logging.WARNING):
        result = asyncio.run(client.chat_json("orchestration", [{"role": "user", "content": "x"}], Out))

    # 业务正常完成，不抛出异常
    assert result.value == "ok"

    # 内存捕获验证告警已记录
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    warn_text = caplog.text
    assert "Failed to write LLM usage log to logs/usage_fail.jsonl" in warn_text
    assert "OSError" in warn_text
    # 验证告警绝不泄露敏感信息
    assert "api_key" not in warn_text.lower()
    assert "ollama" not in warn_text
    assert "flash_key" not in warn_text
    assert "flagship_key" not in warn_text

    # 内存记账依然完整
    assert len(client.records) == 1
    assert client.records[0]["success"] is True
    assert client.records[0]["ttft_ms"] >= 0


# Astra 审查项 1: Settings Pydantic alias 映射验证
def test_settings_reads_llm_env_aliases(monkeypatch):
    monkeypatch.setenv("LLM_LOCAL_MODEL", "custom-local-qwen")
    monkeypatch.setenv("LLM_FLASH_MODEL", "custom-flash-qwen")
    monkeypatch.setenv("LLM_FLAGSHIP_MODEL", "custom-flagship-qwen")
    monkeypatch.setenv("LLM_ORCHESTRATION_TIMEOUT_S", "7.5")
    monkeypatch.setenv("LLM_SCORING_TIMEOUT_S", "45.0")
    monkeypatch.setenv("LLM_USAGE_LOG_PATH", "logs/custom_usage.jsonl")

    s = Settings()
    assert s.local_model == "custom-local-qwen"
    assert s.flash_model == "custom-flash-qwen"
    assert s.flagship_model == "custom-flagship-qwen"
    assert s.llm_orchestration_timeout_s == 7.5
    assert s.orchestration_timeout_s == 7.5
    assert s.llm_scoring_timeout_s == 45.0
    assert s.scoring_timeout_s == 45.0
    assert s.llm_usage_log_path == "logs/custom_usage.jsonl"


# Astra 审查项 4: 配置缺失时不产生重复日志
def test_missing_config_no_duplicate_records():
    settings = SimpleNamespace(
        local_model=None,
        local_base_url=None,
        local_api_key=None,
        flash_model=None,
        flash_base_url=None,
        flash_api_key=None,
        llm_orchestration_timeout_s=6.0,
        llm_usage_log_path="logs/missing_cfg.jsonl",
    )
    client = LLMClient(settings)

    with pytest.raises(LLMError, match="all llm attempts failed"):
        asyncio.run(client.chat_json("orchestration", [], Out))

    # local 和 flash 各产生 1 条 missing_config 记录，绝不重复
    assert len(client.records) == 2
    assert [r["error"] for r in client.records] == ["missing_config", "missing_config"]
    assert all(r["ttft_ms"] is None for r in client.records)


# 数据库与模型可空性测试
def test_models_nullable_and_create():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as DBSession
    from server.db import Base
    from server.models import Answer, Job, Question, Report, Session, User

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with DBSession(engine) as s:
        u = User(role="student")
        j = Job(family="ai", title="test")
        s.add_all([u, j])
        s.flush()
        se = Session(user_id=u.id, job_id=j.id, mode="graduate", status="active")
        s.add(se)
        s.flush()
        s.add(Answer(session_id=se.id, q_seq=1, question_text="q", answer_text="a", is_followup=False, is_retry=False))
        s.add(Report(session_id=se.id))
        s.commit()
