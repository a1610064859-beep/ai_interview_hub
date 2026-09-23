"""T5 语音答题链路测试。

默认全部使用测试夹具（假 ffprobe/ffmpeg/ASR）；涉及真实 ffmpeg 的损坏样本用例
依赖本机 ffmpeg/ffprobe（T5-P0 已预检在位），且样本先经 ffprobe 预验"必须解析失败"。
真实模型验收（B/H）以 ASR_ACCEPTANCE_REAL=1 门控，默认跳过——测试夹具与真实模型实测明确区分。
"""
import asyncio
import os
import re
import subprocess
import tempfile
import threading
import time
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from server.main import app
from server.db import SessionLocal, ensure_schema_upgrades, Base
from server.models import User, Job, Question, Session, Answer, Report
from server.config import settings
from server.services import asr as asr_module
from server.services import audio as audio_module
from server.services import orchestrator
from server.services import scoring as scoring_module
from server.services.asr import ASRUnavailableError, normalize_asr_text


@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch):
    # conftest.py 已将 DATABASE_URL 指向临时库；整库重建保证每个用例从空库开始
    from server.db import engine
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    ensure_schema_upgrades(engine)

    with SessionLocal() as db:
        db.add(User(id=1, role="student", name_masked="张**", major="车辆工程", grade="大三"))
        db.add(Job(
            id=1, family="智驾", title="智驾测试",
            jd_digest="负责智驾测试用例设计与总线通信测试",
            terms_json=["CANoe", "CANalyzer"],
            dims_json={"专业匹配度": 0.4, "逻辑结构": 0.3, "岗位素养": 0.3},
        ))
        q_types = ["通用", "通用", "专业", "专业", "专业", "情景"]
        for idx, qt in enumerate(q_types, start=1):
            db.add(Question(
                id=idx, job_id=1, type=qt,
                text=f"第{idx}题（{qt}）：请回答关于测试的专业问题。",
                followup_hint=f"第{idx}题追问提示",
            ))
        db.commit()

    # 测试内关闭 TTS 网络合成，避免夹具外呼
    monkeypatch.setattr(settings, "tts_enabled", False)
    yield


@pytest.fixture()
def valid_webm_bytes():
    """用本机 ffmpeg 生成 1s 正弦 webm/opus（真实容器样本）。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "gen.webm")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
             "-ac", "1", "-ar", "48000", "-c:a", "libopus", "-b:a", "32k", path],
            check=True, capture_output=True,
        )
        with open(path, "rb") as f:
            yield f.read()


def _fake_pipeline(monkeypatch, transcribe_text="那个 就是 我们 用 CANoe 做 测试", transcribe_side_effect=None):
    """夹具替换 ASR 三件套（探测/转码直通、转写固定文本），并禁用真实追问 LLM。"""
    monkeypatch.setattr(audio_module, "probe_webm", lambda path: None)

    def _fake_transcode(webm_path, wav_path):
        with open(wav_path, "wb") as f:
            f.write(b"RIFF-fake-wav")

    monkeypatch.setattr(audio_module, "transcode_to_16k_wav", _fake_transcode)

    if transcribe_side_effect is not None:
        async def _fake_transcribe(wav_path):
            raise transcribe_side_effect
    else:
        async def _fake_transcribe(wav_path):
            # 与生产 transcribe_wav 一致：返回前做 CJK 间空白折叠
            return normalize_asr_text(transcribe_text)
    monkeypatch.setattr(asr_module, "transcribe_wav", _fake_transcribe)
    monkeypatch.setattr(orchestrator, "evaluate_followup", AsyncMock(return_value=None))


def test_normalize_asr_text_cjk_and_latin_mixed():
    """T5-FIX：仅折叠 CJK–CJK 之间空白，保留英文/数字侧空格。"""
    assert normalize_asr_text("超 声 波 雷 达") == "超声波雷达"
    assert normalize_asr_text("使 用 CANoe 进 行 总 线 测 试") == "使用 CANoe 进行总线测试"
    assert normalize_asr_text("CANoe bus test") == "CANoe bus test"
    assert normalize_asr_text("ISO 26262 功 能 安 全") == "ISO 26262 功能安全"
    assert normalize_asr_text("超\n\n声   波") == "超声波"
    assert normalize_asr_text("") == ""
    assert normalize_asr_text("已经连续中文无空格") == "已经连续中文无空格"


def test_audio_answer_persists_normalized_asr_text(monkeypatch, valid_webm_bytes):
    """规范化发生在落库前；wpm/filler 基于同一规范化文本。"""
    spaced = "使 用 CANoe 进 行 总 线 测 试"
    _fake_pipeline(monkeypatch, transcribe_text=spaced)
    client = TestClient(app)
    sid = _create_session(client)
    resp = _post_audio(client, sid, valid_webm_bytes)
    assert resp.status_code == 200, resp.text

    expected = "使用 CANoe 进行总线测试"
    with SessionLocal() as db:
        ans = db.query(Answer).filter(Answer.session_id == sid).one()
        assert ans.answer_text == expected
        # "".join(expected.split()) 字数与去全部空白一致 → wpm 稳定
        char_n = len("".join(expected.split()))
        assert ans.wpm == round(char_n / 8.0 * 60, 1)
        assert ans.filler_cnt == 0


def _post_audio(client, sid, audio_bytes, duration_s="8.0", pause_cnt="2", filename="answer.webm"):
    return client.post(
        f"/api/sessions/{sid}/answers",
        files={"audio": (filename, audio_bytes, "audio/webm")},
        data={"duration_s": duration_s, "pause_cnt": pause_cnt},
    )


def _create_session(client):
    resp = client.post("/api/sessions", json={"job_id": 1, "user_id": 1, "mode": "毕业生"})
    assert resp.status_code == 200
    return resp.json()["sid"]


def test_audio_answer_next_with_acoustic_values(monkeypatch, valid_webm_bytes):
    """C：成功路径 + duration_s/wpm/pause_cnt/filler_cnt 正确落库。"""
    _fake_pipeline(monkeypatch)
    client = TestClient(app)
    sid = _create_session(client)

    resp = _post_audio(client, sid, valid_webm_bytes)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["type"] == "next"
    assert data["question"]["seq"] == 2

    with SessionLocal() as db:
        answers = db.query(Answer).filter(Answer.session_id == sid).all()
        assert len(answers) == 1
        ans = answers[0]
        assert ans.duration_s == 8.0
        assert ans.pause_cnt == 2
        # 规范化后："那个就是我们用 CANoe 做测试"；去全部空白仍 15 字 → wpm=112.5
        assert ans.wpm == 112.5
        assert ans.filler_cnt == 2  # 那个 + 就是
        assert ans.answer_text == "那个就是我们用 CANoe 做测试"
        assert "CANoe" in ans.answer_text
        sess = db.query(Session).filter(Session.id == sid).first()
        assert sess.status == "active"
        assert sess.lease_token is None


def _ffprobe_rejects(data: bytes) -> bool:
    """构造样本后先经真实 ffprobe 预验：必须解析失败才作为 422 用例样本。"""
    fd, path = tempfile.mkstemp(suffix=".webm")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name",
             "-of", "default=nw=1", path],
            capture_output=True,
        )
        return result.returncode != 0
    finally:
        os.unlink(path)


def test_corrupted_webm_variants_422(valid_webm_bytes):
    """D（真 ffprobe）：两种不同截断方式，样本先经 ffprobe 预验失败，再断言接口稳定 422。"""
    client = TestClient(app)
    sid = _create_session(client)

    samples = {
        "EBML头后接垃圾（容器解析失败）": valid_webm_bytes[:32] + os.urandom(512),
        "EBML头内截断（保留前20字节，魔数完整但头元素越过EOF）": valid_webm_bytes[:20],
    }
    for name, data in samples.items():
        assert _ffprobe_rejects(data), f"样本构造失败：{name} 应被 ffprobe 拒绝"
        resp = _post_audio(client, sid, data)
        assert resp.status_code == 422, (name, resp.status_code, resp.text)
        assert resp.json()["detail"]["code"] == "AUDIO_INVALID"

    with SessionLocal() as db:
        assert db.query(Answer).filter(Answer.session_id == sid).count() == 0
        sess = db.query(Session).filter(Session.id == sid).first()
        assert sess.status == "active"
        assert sess.pending_question_json["seq"] == 1


def test_bad_magic_rejected_422_without_advance(monkeypatch):
    """D①：魔数非法 → 422 AUDIO_INVALID，不推进会话。"""
    _fake_pipeline(monkeypatch)
    client = TestClient(app)
    sid = _create_session(client)

    resp = _post_audio(client, sid, b"NOTWEBM-NOT-AUDIO-0000")
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "AUDIO_INVALID"

    with SessionLocal() as db:
        assert db.query(Answer).filter(Answer.session_id == sid).count() == 0
        sess = db.query(Session).filter(Session.id == sid).first()
        assert sess.status == "active"
        assert sess.pending_question_json["seq"] == 1


def test_real_webm_end_to_end_with_fake_asr(monkeypatch, valid_webm_bytes):
    """A（真实转码路径）+ G（临时清理）：真 ffprobe/ffmpeg 成功转码，ASR 打桩。"""
    async def _fake_transcribe(wav_path):
        return "那个 就是 我们 用 CANoe 做 测试"

    monkeypatch.setattr(asr_module, "transcribe_wav", _fake_transcribe)
    monkeypatch.setattr(orchestrator, "evaluate_followup", AsyncMock(return_value=None))

    client = TestClient(app)
    sid = _create_session(client)
    resp = _post_audio(client, sid, valid_webm_bytes)
    assert resp.status_code == 200, resp.text
    assert resp.json()["type"] == "next"

    # G：请求结束后系统临时目录不得残留 asr_* 工作目录
    leftovers = [d for d in os.listdir(tempfile.gettempdir()) if d.startswith("asr_")]
    assert leftovers == []


def test_asr_failure_503_no_answer_no_advance(monkeypatch, valid_webm_bytes):
    """E：ASR 异常 → 503 ASR_UNAVAILABLE，不产生 Answer，会话回 active。"""
    _fake_pipeline(monkeypatch, transcribe_side_effect=ASRUnavailableError("模型加载失败"))
    client = TestClient(app)
    sid = _create_session(client)

    resp = _post_audio(client, sid, valid_webm_bytes)
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "ASR_UNAVAILABLE"

    with SessionLocal() as db:
        assert db.query(Answer).filter(Answer.session_id == sid).count() == 0
        sess = db.query(Session).filter(Session.id == sid).first()
        assert sess.status == "active"
        assert sess.lease_token is None
        assert sess.pending_question_json["seq"] == 1


def test_concurrent_duplicate_request_no_double_advance(monkeypatch, valid_webm_bytes):
    """F：并发重复请求 → 第二请求 409，answers 恰 +1。"""
    release = threading.Event()

    async def _slow_transcribe(wav_path):
        # 等主线程发出第二个请求后再放行，制造真实并发窗口
        await asyncio.to_thread(release.wait, 10)
        return "那个 就是 我们 用 CANoe 做 测试"

    monkeypatch.setattr(audio_module, "probe_webm", lambda path: None)
    monkeypatch.setattr(audio_module, "transcode_to_16k_wav", lambda w, v: None)
    monkeypatch.setattr(asr_module, "transcribe_wav", _slow_transcribe)
    monkeypatch.setattr(orchestrator, "evaluate_followup", AsyncMock(return_value=None))

    client = TestClient(app)
    sid = _create_session(client)

    results = {}

    def _first():
        results["first"] = _post_audio(client, sid, valid_webm_bytes)

    worker = threading.Thread(target=_first)
    worker.start()
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            with SessionLocal() as db:
                sess = db.query(Session).filter(Session.id == sid).first()
                if sess.status == "answering" and sess.lease_token:
                    break
            time.sleep(0.05)

        second = _post_audio(client, sid, valid_webm_bytes)
        assert second.status_code == 409
        assert second.json()["detail"]["code"] == "ANSWER_IN_PROGRESS"
    finally:
        release.set()
        worker.join(15)

    assert results["first"].status_code == 200, results["first"].text
    with SessionLocal() as db:
        assert db.query(Answer).filter(Answer.session_id == sid).count() == 1


def test_audio_too_large_413(monkeypatch, valid_webm_bytes):
    monkeypatch.setattr(settings, "asr_max_upload_mb", 0)
    client = TestClient(app)
    sid = _create_session(client)
    resp = _post_audio(client, sid, valid_webm_bytes)
    assert resp.status_code == 413
    assert resp.json()["detail"]["code"] == "AUDIO_TOO_LARGE"


def test_asr_disabled_503(monkeypatch, valid_webm_bytes):
    monkeypatch.setattr(settings, "asr_enabled", False)
    client = TestClient(app)
    sid = _create_session(client)
    resp = _post_audio(client, sid, valid_webm_bytes)
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "ASR_UNAVAILABLE"


def test_missing_duration_s_422(monkeypatch, valid_webm_bytes):
    client = TestClient(app)
    sid = _create_session(client)
    resp = client.post(
        f"/api/sessions/{sid}/answers",
        files={"audio": ("a.webm", valid_webm_bytes, "audio/webm")},
        data={"pause_cnt": "1"},
    )
    assert resp.status_code == 422


def _make_chinese_speech_webm(tmpdir: str) -> str:
    """用 Windows SAPI（Huihui, zh-CN）离线合成中文语音并转 webm/opus（真实中文语音样本，§7-B）。"""
    wav = os.path.join(tmpdir, "tts.wav")
    webm = os.path.join(tmpdir, "tts.webm")
    ps = (
        "Add-Type -AssemblyName System.Speech;"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$s.SelectVoice('Microsoft Huihui Desktop');"
        "$s.SetOutputToWaveFile('" + wav + "', "
        "(New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,"
        "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,"
        "[System.Speech.AudioFormat.AudioChannel]::Mono)));"
        "$s.Speak('我们使用CANoe进行智能汽车总线通信测试');"
        "$s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True, timeout=60)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-i", wav, "-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "32k", webm],
        check=True, capture_output=True,
    )
    return webm


@pytest.mark.skipif(
    os.environ.get("ASR_ACCEPTANCE_REAL") != "1",
    reason="真实模型验收：需已安装 funasr 并完成 paraformer-zh 缓存（§7-B/H 门控）",
)
def test_real_model_transcribe_chinese(monkeypatch):
    """B/H（真实模型，手动门控）：真实中文语音 → 真实转码 + 真实 ASR → 非空中文转写。"""
    monkeypatch.setattr(orchestrator, "evaluate_followup", AsyncMock(return_value=None))
    with tempfile.TemporaryDirectory() as tmp:
        webm = _make_chinese_speech_webm(tmp)
        with open(webm, "rb") as f:
            audio_bytes = f.read()

    client = TestClient(app)
    sid = _create_session(client)
    resp = _post_audio(client, sid, audio_bytes, duration_s="4.0", pause_cnt="0")
    assert resp.status_code == 200, resp.text

    with SessionLocal() as db:
        ans = db.query(Answer).filter(Answer.session_id == sid).first()
        assert ans is not None
        assert ans.answer_text.strip() != ""
        assert re.search(r"[\u4e00-\u9fff]", ans.answer_text), f"转写非中文: {ans.answer_text!r}"
        # T5-FIX：落库文本不得再含 CJK–CJK 间空白（已在 transcribe_wav 内规范化）
        assert ans.answer_text == normalize_asr_text(ans.answer_text)
        assert not re.search(
            r"[\u4e00-\u9fff][ \t\r\n\u3000]+[\u4e00-\u9fff]",
            ans.answer_text,
        ), f"仍含汉字间空格: {ans.answer_text!r}"


def test_oversize_rejected_before_probe_lease_and_asr(monkeypatch, valid_webm_bytes):
    """上传限流：最多读上限+1字节；超限 413 且不进入探测/转码/ASR/租约阶段。"""
    monkeypatch.setattr(settings, "asr_max_upload_mb", 0)
    called = {"probe": 0, "transcode": 0, "asr": 0}

    def _probe(path):
        called["probe"] += 1
        return None

    def _transcode(w, v):
        called["transcode"] += 1

    async def _asr(wav_path):
        called["asr"] += 1
        return "文本"

    monkeypatch.setattr(audio_module, "probe_webm", _probe)
    monkeypatch.setattr(audio_module, "transcode_to_16k_wav", _transcode)
    monkeypatch.setattr(asr_module, "transcribe_wav", _asr)

    client = TestClient(app)
    sid = _create_session(client)
    resp = _post_audio(client, sid, valid_webm_bytes)
    assert resp.status_code == 413
    assert resp.json()["detail"]["code"] == "AUDIO_TOO_LARGE"
    assert called == {"probe": 0, "transcode": 0, "asr": 0}
    with SessionLocal() as db:
        sess = db.query(Session).filter(Session.id == sid).first()
        assert sess.status == "active"  # 从未进入租约阶段
        assert sess.lease_token is None
        assert db.query(Answer).filter(Answer.session_id == sid).count() == 0


def test_full_voice_flow_feeds_acoustics_to_scoring(monkeypatch, valid_webm_bytes):
    """D：6 题语音流程——评分引擎收到本次+全部历史语音回答的声学字段，报告 fluency 非 null。"""
    _fake_pipeline(monkeypatch)  # 探测/转码直通 + ASR 固定文本 + 无追问

    captured = {}
    canned_report = {
        "dimensions": {
            "professional_match": {"score": 88.0, "evidence": "CANoe", "reason": "熟练"},
            "logic_structure": {"score": 82.5, "evidence": "CANoe", "reason": "清晰"},
            "expression_fluency": {"score": 88.0, "evidence": None, "reason": "声学量化"},
            "job_competence": {"score": 83.5, "evidence": "CANoe", "reason": "规范"},
        },
        "highlights": [], "concerns": [], "improvement": ["继续"],
        "overall": 85.5,
    }

    async def _capture_scoring(*args, **kwargs):
        captured.update(kwargs)
        return canned_report

    monkeypatch.setattr(scoring_module, "score_interview", _capture_scoring)

    client = TestClient(app)
    sid = _create_session(client)
    for i in range(6):
        resp = _post_audio(client, sid, valid_webm_bytes, duration_s="6.0", pause_cnt="1")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        if i < 5:
            assert data["type"] == "next"
    assert data["type"] == "done"

    assert captured["mode"] == "voice"
    samples = captured["acoustic_samples"]
    assert len(samples) == 6  # 5 条历史（DB）+ 1 条本次（显式追加）
    for s in samples:
        assert s["duration_s"] == 6.0
        assert s["wpm"] is not None
        assert s["pause_cnt"] == 1
        assert s["filler_cnt"] is not None

    rep = client.get(f"/api/reports/{sid}")
    assert rep.status_code == 200
    assert rep.json()["dimensions"]["expression_fluency"]["score"] == 88.0  # 不再固定 null


def test_text_flow_scoring_keeps_acoustics_absent(monkeypatch):
    """D 回归：文本端点评分调用无声学参数，报告 fluency 保持 null 与原 reason。"""
    captured = {}
    canned_report = {
        "dimensions": {
            "professional_match": {"score": 88.0, "evidence": "专业能力", "reason": "熟练"},
            "logic_structure": {"score": 82.5, "evidence": "专业能力", "reason": "清晰"},
            "expression_fluency": {"score": None, "evidence": None, "reason": "文本模式，未评估语音流畅度"},
            "job_competence": {"score": 83.5, "evidence": "专业能力", "reason": "规范"},
        },
        "highlights": [], "concerns": [], "improvement": [],
        "overall": 84.7,
    }

    async def _capture_scoring(*args, **kwargs):
        captured.update(kwargs)
        return canned_report

    monkeypatch.setattr(scoring_module, "score_interview", _capture_scoring)
    monkeypatch.setattr(orchestrator, "evaluate_followup", AsyncMock(return_value=None))

    client = TestClient(app)
    sid = _create_session(client)
    for i in range(6):
        resp = client.post(
            f"/api/sessions/{sid}/answers/text",
            json={"answer_text": "这是展示专业能力的详细技术回答，包含专业能力关键词。"},
        )
        assert resp.status_code == 200
        data = resp.json()
    assert data["type"] == "done"
    assert captured["mode"] == "text"
    assert captured.get("acoustic_samples") is None

    rep = client.get(f"/api/reports/{sid}")
    assert rep.status_code == 200
    fluency = rep.json()["dimensions"]["expression_fluency"]
    assert fluency["score"] is None
    assert fluency["reason"] == "文本模式，未评估语音流畅度"
