"""音频转码与探测服务（T5）：webm/opus → 16kHz 单声道 pcm_s16le wav。

按 docs/asr-implementation-spec.md §5.4 阶段判定，stderr 只记日志、不作为业务分类依据：
①EBML 魔数初筛不符 → AudioInvalidError（422 AUDIO_INVALID）；
②ffprobe 可执行但对文件解析失败（含各类截断/内部损坏）→ AudioInvalidError；
③ffprobe 通过后 ffmpeg 转码失败 → AudioProcessError（503 AUDIO_PROCESS_FAILED）；
④ffprobe/ffmpeg 不存在、无执行权限或启动失败 → AudioProcessError。
"""
import logging
import subprocess

from server.config import settings

logger = logging.getLogger(__name__)

EBML_MAGIC = b"\x1a\x45\xdf\xa3"


class AudioInvalidError(Exception):
    """上传内容不是可解析的 webm/opus 音频 → 422 AUDIO_INVALID"""


class AudioProcessError(Exception):
    """ffmpeg/ffprobe 环境缺失或转码执行失败 → 503 AUDIO_PROCESS_FAILED"""


async def prepare_wav(webm_path: str, wav_path: str) -> None:
    """Keep subprocess waits off the event loop and keep files alive on cancellation."""
    import asyncio
    import time
    def convert():
        begin = time.perf_counter()
        probe_webm(webm_path)
        transcode_to_16k_wav(webm_path, wav_path)
        logger.info("audio stage=prepare total_ms=%.1f", (time.perf_counter() - begin) * 1000)
    task = asyncio.create_task(asyncio.to_thread(convert))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        except Exception:
            pass
        raise


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=settings.audio_process_timeout_s)
    except (FileNotFoundError, PermissionError, OSError) as exc:
        raise AudioProcessError(f"外部工具不可执行: {cmd[0]}: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise AudioProcessError(f"外部工具执行超时: {cmd[0]}") from exc


def validate_upload(audio_bytes: bytes) -> None:
    """阶段①：EBML 魔数初筛。"""
    if len(audio_bytes) < 4 or audio_bytes[:4] != EBML_MAGIC:
        raise AudioInvalidError("不是 webm/opus 音频（EBML 魔数不符）")


def probe_webm(webm_path: str) -> None:
    """阶段②：ffprobe 可执行但解析失败 → AudioInvalidError；不可执行/超时 → AudioProcessError。"""
    result = _run([
        settings.ffprobe_path,
        "-v", "error",
        "-show_entries", "stream=codec_name",
        "-of", "default=nw=1",
        webm_path,
    ])
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace").strip()
        logger.warning("ffprobe 解析失败（AUDIO_INVALID）: %s", stderr[:200])
        raise AudioInvalidError("音频容器无法解析（截断或损坏）")


def transcode_to_16k_wav(webm_path: str, wav_path: str) -> None:
    """阶段③：探测通过后的转码；失败 → AudioProcessError（stderr 仅记日志）。"""
    result = _run([
        settings.ffmpeg_path,
        "-hide_banner", "-loglevel", "error", "-y",
        "-i", webm_path,
        "-ac", "1", "-ar", str(settings.asr_sample_rate),
        "-c:a", "pcm_s16le", wav_path,
    ])
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace").strip()
        logger.warning("ffmpeg 转码失败（AUDIO_PROCESS_FAILED）: %s", stderr[:200])
        raise AudioProcessError("音频转码失败")
