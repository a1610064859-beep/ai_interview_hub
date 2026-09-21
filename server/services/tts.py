"""TTS Service (M1 Mock Implementation).
Full edge-tts and prefetching integration will be implemented in M2 (T4).
"""

async def synthesize(text: str) -> str | None:
    """Mock语音合成接口，M1阶段统一返回 None"""
    return None
