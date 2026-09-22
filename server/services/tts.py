"""TTS Service for AI Interview Hub.
Provides edge-tts integration, concurrent prefetching for fixed questions,
pre-generation and rotation of transition phrases, dynamic followup synthesis,
and robust graceful degradation to null.
"""

import asyncio
import logging
from pathlib import Path

import os
from uuid import uuid4

from server.config import settings

logger = logging.getLogger(__name__)


async def synthesize_to_file(text: str, output_path: Path) -> bool:
    """使用 edge-tts 将文本合成为 MP3 音频文件并原子落盘。
    写入临时文件，成功后原子替换目标文件；
    任何异常（网络中断、403、超时等）立即删除临时文件，杜绝非零残片污染或被误复用。
    """
    if not settings.tts_enabled:
        return False

    stripped_text = text.strip() if text else ""
    if not stripped_text:
        return False

    try:
        import edge_tts
    except ImportError:
        logger.warning("edge-tts 库未安装，无法进行语音合成")
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(f".tmp_{uuid4().hex}_{output_path.name}")

    try:
        communicate = edge_tts.Communicate(stripped_text, voice=settings.tts_voice)
        await asyncio.wait_for(
            communicate.save(str(temp_path)),
            timeout=settings.tts_timeout_s,
        )
        if temp_path.is_file() and temp_path.stat().st_size > 0:
            os.replace(temp_path, output_path)
            return True
        return False
    except Exception as exc:
        logger.warning("TTS 语音合成失败 (text=%s, file=%s): %s", stripped_text[:20], output_path.name, exc)
        return False
    finally:
        if temp_path.is_file():
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass


def get_audio_url_if_exists(filename: str) -> str | None:
    """检查指定音频文件是否存在且有效，返回相对 URL；不存在返回 None"""
    file_path = Path(settings.tts_output_dir) / filename
    if file_path.is_file() and file_path.stat().st_size > 0:
        return f"/audio/{filename}"
    return None


async def prefetch_session_questions(session_id: int, questions: list) -> dict[int, str | None]:
    """会话创建时使用 asyncio.gather 并行预取全部固定主问题的 MP3 音频。
    单条失败不阻塞其他题目与会话创建，每条异常单独捕获并记为 None。
    """
    audio_dir = Path(settings.tts_output_dir)
    results: dict[int, str | None] = {}

    async def _synth_single(seq: int, text: str) -> tuple[int, str | None]:
        filename = f"session_{session_id}_q{seq}.mp3"
        file_path = audio_dir / filename

        # 若文件已存在有效，直接复用
        if file_path.is_file() and file_path.stat().st_size > 0:
            return seq, f"/audio/{filename}"

        try:
            ok = await synthesize_to_file(text, file_path)
            if ok:
                return seq, f"/audio/{filename}"
        except Exception as exc:
            logger.warning("会话 %s 预取题目 %s 异常: %s", session_id, seq, exc)
        return seq, None

    tasks = []
    for seq, item in enumerate(questions, 1):
        text = item if isinstance(item, str) else getattr(item, "text", str(item))
        tasks.append(_synth_single(seq, text))

    if not tasks:
        return results

    gathered = await asyncio.gather(*tasks, return_exceptions=True)
    for item in gathered:
        if isinstance(item, tuple) and len(item) == 2:
            seq, url = item
            results[seq] = url
        elif isinstance(item, Exception):
            logger.warning("预取任务异常: %s", item)

    return results


async def prefetch_session_transitions(session_id: int) -> list[str | None]:
    """会话创建时并行预生成通用过渡语言频（按 session_id 和过渡语索引隔离，禁止不同会话覆盖）。"""
    audio_dir = Path(settings.tts_output_dir)
    transition_lines = settings.transition_lines_list
    if not transition_lines:
        return []

    async def _synth_transition(idx: int, text: str) -> tuple[int, str | None]:
        filename = f"session_{session_id}_trans_{idx}.mp3"
        file_path = audio_dir / filename

        if file_path.is_file() and file_path.stat().st_size > 0:
            return idx, f"/audio/{filename}"

        try:
            ok = await synthesize_to_file(text, file_path)
            if ok:
                return idx, f"/audio/{filename}"
        except Exception as exc:
            logger.warning("会话 %s 预生成过渡语 %s 异常: %s", session_id, idx, exc)
        return idx, None

    tasks = [
        _synth_transition(idx, line)
        for idx, line in enumerate(transition_lines)
    ]

    gathered = await asyncio.gather(*tasks, return_exceptions=True)
    urls: list[str | None] = [None] * len(transition_lines)
    for item in gathered:
        if isinstance(item, tuple) and len(item) == 2:
            idx, url = item
            urls[idx] = url

    return urls


def get_session_transition_url(session_id: int, answer_idx: int) -> str | None:
    """稳定按回答序号轮转获取一条已生成的过渡语音频 URL。
    例如配置3条过渡语时：
    第1次回答 (idx 0) -> trans_0
    第2次回答 (idx 1) -> trans_1
    第3次回答 (idx 2) -> trans_2
    第4次回答 (idx 3) -> trans_0
    """
    transition_lines = settings.transition_lines_list
    if not transition_lines:
        return None

    chosen_idx = answer_idx % len(transition_lines)
    filename = f"session_{session_id}_trans_{chosen_idx}.mp3"
    return get_audio_url_if_exists(filename)


async def synthesize_followup(session_id: int, q_seq: int, text: str) -> str | None:
    """动态追问语音合成：追问为实时生成无法预取，生成追问后再异步合成。
    失败返回 None，绝不中断面试。
    """
    audio_dir = Path(settings.tts_output_dir)
    filename = f"session_{session_id}_q{q_seq}_followup.mp3"
    file_path = audio_dir / filename

    try:
        ok = await synthesize_to_file(text, file_path)
        if ok:
            return f"/audio/{filename}"
    except Exception as exc:
        logger.warning("会话 %s 追问语音合成异常: %s", session_id, exc)

    return None


def get_question_audio_url(session_id: int, q_seq: int, is_followup: bool = False) -> str | None:
    """获取指定题目的音频 URL，若不存在或未预取成功则返回 None。"""
    if is_followup:
        filename = f"session_{session_id}_q{q_seq}_followup.mp3"
    else:
        filename = f"session_{session_id}_q{q_seq}.mp3"
    return get_audio_url_if_exists(filename)
