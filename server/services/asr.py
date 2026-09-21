"""ASR Service (M1 Mock Implementation).
Full FunASR / Paraformer / ffmpeg integration will be implemented in M2 (T5).
"""
import re


def count_filler_words(text: str) -> int:
    """统计填充词（嗯|那个|就是|然后|这个）频次"""
    pattern = r"(嗯|那个|就是|然后|这个)"
    return len(re.findall(pattern, text))


async def transcribe(audio_bytes: bytes) -> str:
    """Mock转写接口"""
    return "Mock ASR 转写文本"
