from pathlib import Path
from unittest.mock import AsyncMock, patch
import os
import pytest
from fastapi.testclient import TestClient

from server.main import app
from server.config import settings
from server.db import Base, SessionLocal, ensure_schema_upgrades
from server.models import Answer, Job, Question, Report, Session, User
from server.services import tts


@pytest.fixture(autouse=True)
def setup_test_environment(tmp_path, monkeypatch):
    """设置测试数据库与隔离的音频输出目录"""
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "tts_output_dir", str(audio_dir))
    monkeypatch.setattr(settings, "tts_enabled", True)
    monkeypatch.setattr(settings, "tts_transition_lines", "嗯，我了解了|请继续|谢谢你的回答")

    from server.db import engine
    Base.metadata.create_all(engine)
    ensure_schema_upgrades(engine)

    with SessionLocal() as db:
        db.query(Report).delete()
        db.query(Answer).delete()
        db.query(Session).delete()
        db.query(Question).delete()
        db.query(Job).delete()
        db.query(User).delete()

        user = User(id=1, role="student", name_masked="张**", major="车辆工程", grade="大三")
        db.add(user)

        job = Job(
            id=1,
            family="智驾",
            title="智驾测试",
            jd_digest="负责智驾测试用例设计与总线通信测试",
            terms_json=["CANoe", "CANalyzer", "时间戳", "丢包率"],
            dims_json={"专业匹配度": 0.4, "逻辑结构": 0.3, "岗位素养": 0.3},
        )
        db.add(job)

        q_types = ["通用", "通用", "专业", "专业", "专业", "情景"]
        for idx, qt in enumerate(q_types, start=1):
            q = Question(
                id=idx,
                job_id=1,
                type=qt,
                text=f"第{idx}题（{qt}）：请回答关于测试的专业问题。",
                followup_hint=f"第{idx}题追问提示",
            )
            db.add(q)
        db.commit()

    yield


async def fake_synthesize_to_file(text: str, output_path: Path) -> bool:
    """Fake TTS synthesizer that generates a valid mock MP3 byte payload."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(f"FAKE_AUDIO_DATA_FOR:{text}".encode("utf-8"))
    return True


def test_tts_prefetch_six_fixed_questions_success():
    """A. 6道固定题并行预取成功，创建会话返回时对应6个 MP3 已存在"""
    client = TestClient(app)

    with patch("server.services.tts.synthesize_to_file", side_effect=fake_synthesize_to_file):
        resp = client.post("/api/sessions", json={"job_id": 1})
        assert resp.status_code == 200
        data = resp.json()

        sid = data["sid"]
        assert data["question"]["seq"] == 1
        assert data["question"]["audio_url"] == f"/audio/session_{sid}_q1.mp3"

        # 验证 6 道固定题的 MP3 文件在创建返回时均已存在
        audio_dir = Path(settings.tts_output_dir)
        for seq in range(1, 7):
            expected_file = audio_dir / f"session_{sid}_q{seq}.mp3"
            assert expected_file.is_file(), f"Expected file {expected_file.name} to exist"
            assert expected_file.stat().st_size > 0

        # 回答第1题，验证第2题返回已预取的 audio_url
        with patch("server.services.orchestrator.evaluate_followup", AsyncMock(return_value=None)):
            ans_resp = client.post(
                f"/api/sessions/{sid}/answers/text",
                json={"answer_text": "回答第1题"},
            )
            assert ans_resp.status_code == 200
            ans_data = ans_resp.json()
            assert ans_data["type"] == "next"
            assert ans_data["question"]["seq"] == 2
            assert ans_data["question"]["audio_url"] == f"/audio/session_{sid}_q2.mp3"


def test_tts_prefetch_single_failure_does_not_block():
    """B. 一条固定题失败不阻塞，其 audio_url=null，其余仍成功"""
    client = TestClient(app)

    async def fail_q3_synthesizer(text: str, output_path: Path) -> bool:
        if "_q3.mp3" in output_path.name:
            return False
        return await fake_synthesize_to_file(text, output_path)

    with patch("server.services.tts.synthesize_to_file", side_effect=fail_q3_synthesizer):
        resp = client.post("/api/sessions", json={"job_id": 1})
        assert resp.status_code == 200
        data = resp.json()

        sid = data["sid"]
        assert data["question"]["audio_url"] == f"/audio/session_{sid}_q1.mp3"

        audio_dir = Path(settings.tts_output_dir)
        # q1, q2, q4, q5, q6 存在，q3 不存在
        assert (audio_dir / f"session_{sid}_q1.mp3").is_file()
        assert (audio_dir / f"session_{sid}_q2.mp3").is_file()
        assert not (audio_dir / f"session_{sid}_q3.mp3").is_file()
        assert (audio_dir / f"session_{sid}_q4.mp3").is_file()

        # 推进到第3题，audio_url 降级为 null
        with patch("server.services.orchestrator.evaluate_followup", AsyncMock(return_value=None)):
            # 回答 q1 -> q2
            client.post(f"/api/sessions/{sid}/answers/text", json={"answer_text": "答q1"})
            # 回答 q2 -> q3
            ans_resp3 = client.post(f"/api/sessions/{sid}/answers/text", json={"answer_text": "答q2"})
            assert ans_resp3.status_code == 200
            ans_data3 = ans_resp3.json()
            assert ans_data3["question"]["seq"] == 3
            assert ans_data3["question"]["audio_url"] is None

            # 回答 q3 -> q4，q4 audio_url 正常
            ans_resp4 = client.post(f"/api/sessions/{sid}/answers/text", json={"answer_text": "答q3"})
            assert ans_resp4.status_code == 200
            assert ans_resp4.json()["question"]["audio_url"] == f"/audio/session_{sid}_q4.mp3"


def test_tts_all_failure_graceful_degradation():
    """C. 全部合成失败时创建会话仍成功，首题 audio_url=null，文本流程正常运行"""
    client = TestClient(app)

    async def all_fail_synthesizer(text: str, output_path: Path) -> bool:
        return False

    with patch("server.services.tts.synthesize_to_file", side_effect=all_fail_synthesizer):
        resp = client.post("/api/sessions", json={"job_id": 1})
        assert resp.status_code == 200
        data = resp.json()
        assert data["question"]["audio_url"] is None

        sid = data["sid"]
        with patch("server.services.orchestrator.evaluate_followup", AsyncMock(return_value=None)):
            ans_resp = client.post(f"/api/sessions/{sid}/answers/text", json={"answer_text": "正常文本作答"})
            assert ans_resp.status_code == 200
            assert ans_resp.json()["question"]["audio_url"] is None


def test_tts_transition_audio_rotation():
    """D. 提交回答可得到预生成过渡语 URL，按回答序号轮转"""
    client = TestClient(app)

    with patch("server.services.tts.synthesize_to_file", side_effect=fake_synthesize_to_file):
        resp = client.post("/api/sessions", json={"job_id": 1})
        sid = resp.json()["sid"]

        # 过渡语配置了3条：嗯，我了解了 (0) | 请继续 (1) | 谢谢你的回答 (2)
        with patch("server.services.orchestrator.evaluate_followup", AsyncMock(return_value=None)):
            # 提交第1次回答 -> 轮转到 index 0
            r1 = client.post(f"/api/sessions/{sid}/answers/text", json={"answer_text": "回答1"})
            assert r1.status_code == 200
            assert r1.json()["transition_audio_url"] == f"/audio/session_{sid}_trans_0.mp3"

            # 提交第2次回答 -> 轮转到 index 1
            r2 = client.post(f"/api/sessions/{sid}/answers/text", json={"answer_text": "回答2"})
            assert r2.status_code == 200
            assert r2.json()["transition_audio_url"] == f"/audio/session_{sid}_trans_1.mp3"

            # 提交第3次回答 -> 轮转到 index 2
            r3 = client.post(f"/api/sessions/{sid}/answers/text", json={"answer_text": "回答3"})
            assert r3.status_code == 200
            assert r3.json()["transition_audio_url"] == f"/audio/session_{sid}_trans_2.mp3"

            # 提交第4次回答 -> 轮转回 index 0
            r4 = client.post(f"/api/sessions/{sid}/answers/text", json={"answer_text": "回答4"})
            assert r4.status_code == 200
            assert r4.json()["transition_audio_url"] == f"/audio/session_{sid}_trans_0.mp3"

        # 验证对应的过渡语音频文件均已产生
        audio_dir = Path(settings.tts_output_dir)
        for i in range(3):
            trans_file = audio_dir / f"session_{sid}_trans_{i}.mp3"
            assert trans_file.is_file()


def test_tts_dynamic_followup_failure_handled_gracefully():
    """E. 动态追问合成失败时仍返回 followup，audio_url=null，不中断面试"""
    client = TestClient(app)

    async def fail_followup_synthesizer(text: str, output_path: Path) -> bool:
        if "followup" in output_path.name:
            raise RuntimeError("TTS connection dropped")
        return await fake_synthesize_to_file(text, output_path)

    with patch("server.services.tts.synthesize_to_file", side_effect=fail_followup_synthesizer):
        resp = client.post("/api/sessions", json={"job_id": 1})
        sid = resp.json()["sid"]

        with patch("server.services.orchestrator.evaluate_followup", AsyncMock(return_value="请展开讲讲")):
            ans_resp = client.post(
                f"/api/sessions/{sid}/answers/text",
                json={"answer_text": "我使用CANoe排查"},
            )
            assert ans_resp.status_code == 200
            data = ans_resp.json()
            assert data["type"] == "followup"
            assert data["question"]["text"] == "请展开讲讲"
            assert data["question"]["audio_url"] is None


def test_tts_audio_paths_do_not_collide_across_sessions():
    """F. 音频路径不会跨会话覆盖"""
    client = TestClient(app)

    with patch("server.services.tts.synthesize_to_file", side_effect=fake_synthesize_to_file):
        resp1 = client.post("/api/sessions", json={"job_id": 1})
        sid1 = resp1.json()["sid"]

        resp2 = client.post("/api/sessions", json={"job_id": 1})
        sid2 = resp2.json()["sid"]
        assert sid1 != sid2

        audio_dir = Path(settings.tts_output_dir)
        file1 = audio_dir / f"session_{sid1}_q1.mp3"
        file2 = audio_dir / f"session_{sid2}_q1.mp3"
        assert file1 != file2
        assert file1.is_file()
        assert file2.is_file()

        # 修改 session 1 的文件内容，session 2 保持独立
        file1.write_bytes(b"SESSION_1_OVERWRITTEN")
        assert file2.read_bytes() != b"SESSION_1_OVERWRITTEN"


def test_tts_static_audio_route_serving():
    """G. 静态音频 URL 可请求到对应 MP3，不存在返回 404，越界返回 403"""
    client = TestClient(app)

    with patch("server.services.tts.synthesize_to_file", side_effect=fake_synthesize_to_file):
        resp = client.post("/api/sessions", json={"job_id": 1})
        audio_url = resp.json()["question"]["audio_url"]

        # 请求有效静态音频
        audio_resp = client.get(audio_url)
        assert audio_resp.status_code == 200
        assert "audio/mpeg" in audio_resp.headers.get("content-type", "")
        assert audio_resp.content.startswith(b"FAKE_AUDIO_DATA_FOR:")

        # 请求不存在的音频
        not_found_resp = client.get("/audio/non_existent_file.mp3")
        assert not_found_resp.status_code == 404

        # 路径遍历防护测试
        traversal_resp = client.get("/audio/../config.py")
        assert traversal_resp.status_code in [403, 404]


@pytest.mark.anyio
async def test_tts_atomic_write_and_no_corrupt_fragments_reused(tmp_path):
    """验证写入临时文件且原子替换：网络中断留下非零残片时，临时文件被删除，目标文件不生成且不会被复用"""
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    target_mp3 = audio_dir / "session_99_q1.mp3"

    class FakeCommunicateWithInterruption:
        def __init__(self, text, voice):
            self.text = text
            self.voice = voice

        async def save(self, path):
            # 模拟网络中断：写入非零残片后断开连接
            Path(path).write_bytes(b"CORRUPTED_NON_ZERO_PARTIAL_BYTES")
            raise ConnectionResetError("Connection lost during audio download")

    with patch("edge_tts.Communicate", FakeCommunicateWithInterruption):
        success = await tts.synthesize_to_file("测试断网文本", target_mp3)
        assert success is False
        # 目标文件绝不应该生成
        assert not target_mp3.exists()
        # 临时文件已被清理，目录下无任何残片
        tmp_files = list(audio_dir.glob(".tmp_*"))
        assert len(tmp_files) == 0
        # 绝不被当作有效音频复用
        assert tts.get_audio_url_if_exists(target_mp3.name) is None


@pytest.mark.anyio
async def test_tts_disabled_does_not_reuse_residual_mp3(monkeypatch):
    """TTS 关闭时：磁盘上已有非空目标 MP3 也不得复用；预取与 URL 查询一律 None，且不调用 edge-tts。"""
    audio_dir = Path(settings.tts_output_dir)
    q_file = audio_dir / "session_77_q1.mp3"
    trans_file = audio_dir / "session_77_trans_0.mp3"
    q_file.write_bytes(b"RESIDUAL_QUESTION_MP3_BYTES")
    trans_file.write_bytes(b"RESIDUAL_TRANSITION_MP3_BYTES")
    assert q_file.stat().st_size > 0
    assert trans_file.stat().st_size > 0

    monkeypatch.setattr(settings, "tts_enabled", False)

    def _forbid_real_edge_tts(*args, **kwargs):
        raise AssertionError("tts_enabled=False 时不得调用真实 edge-tts")

    with patch("edge_tts.Communicate", side_effect=_forbid_real_edge_tts):
        q_urls = await tts.prefetch_session_questions(77, ["残留题不应被复用"])
        assert q_urls == {1: None}

        trans_urls = await tts.prefetch_session_transitions(77)
        assert trans_urls == [None] * len(settings.transition_lines_list)

        assert tts.get_audio_url_if_exists(q_file.name) is None
        assert tts.get_audio_url_if_exists(trans_file.name) is None
        assert await tts.synthesize_to_file("也不应合成", q_file) is False


@pytest.mark.skipif(
    os.environ.get("TTS_ACCEPTANCE_REAL") != "1",
    reason="需真实 edge-tts 网络验收",
)
@pytest.mark.anyio
async def test_edge_tts_v7_real_synthesis_and_ffprobe(tmp_path):
    """[T4-FIX] 验证 edge-tts 7.2.8 真实网络合成、生成 MP3 文件大小与 ffprobe 容器格式。"""
    import subprocess
    import edge_tts

    assert edge_tts.__version__ == "7.2.8"

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    test_mp3 = audio_dir / "real_v7_test.mp3"

    # 1. 真实调用 Communicate.save
    comm = edge_tts.Communicate("你好", settings.tts_voice)
    await comm.save(str(test_mp3))

    assert test_mp3.exists()
    assert test_mp3.stat().st_size > 0

    # 2. ffprobe 校验
    res = subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=format_name,duration:stream=codec_name",
        "-of", "default=noprint_wrappers=1",
        str(test_mp3)
    ], capture_output=True, text=True, check=True)

    assert "format_name=mp3" in res.stdout
    assert "codec_name=mp3" in res.stdout
