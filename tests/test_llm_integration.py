import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import BaseModel
from server.services.llm import chat_json


class ProbeResponse(BaseModel):
    ok: bool
    message: str


def test_real_chat_json() -> None:
    result = asyncio.run(
        chat_json(
            stage="scoring",
            messages=[
                {
                    "role": "system",
                    "content": "Return only valid JSON matching the requested schema.",
                },
                {
                    "role": "user",
                    "content": "Set ok to true and message to ready.",
                },
            ],
            response_model=ProbeResponse,
        )
    )

    assert result.ok is True
    assert result.message == "ready"
