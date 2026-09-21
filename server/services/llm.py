import json
import time
from pathlib import Path
from typing import Type, TypeVar
from pydantic import BaseModel, ValidationError
from openai import AsyncOpenAI

T = TypeVar("T", bound=BaseModel)

class LLMError(Exception):
    pass

class LLMClient:
    def __init__(self, settings):
        self.settings = settings
        self.records = []

    def _save_record(self, record):
        self.records.append(record)
        log_path = getattr(self.settings, "llm_usage_log_path", "logs/llm_usage.jsonl")
        if log_path:
            try:
                path = Path(log_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            except Exception:
                pass

    def _chain(self, stage: str):
        if stage in {"orchestration", "followup", "new_student", "counsel"}:
            return [
                ("local", getattr(self.settings, "local_model", None), getattr(self.settings, "local_base_url", None), getattr(self.settings, "local_api_key", None)),
                ("flash", getattr(self.settings, "flash_model", None), getattr(self.settings, "flash_base_url", None), getattr(self.settings, "flash_api_key", None)),
            ]
        return [
            ("flagship", getattr(self.settings, "flagship_model", None), getattr(self.settings, "flagship_base_url", None), getattr(self.settings, "flagship_api_key", None)),
            ("local", getattr(self.settings, "local_model", None), getattr(self.settings, "local_base_url", None), getattr(self.settings, "local_api_key", None)),
        ]

    def _timeout(self, stage: str) -> float:
        if stage in {"scoring", "jd", "jd_parse"}:
            return float(getattr(self.settings, "llm_scoring_timeout_s", getattr(self.settings, "scoring_timeout_s", 60.0)))
        return float(getattr(self.settings, "llm_orchestration_timeout_s", getattr(self.settings, "orchestration_timeout_s", 6.0)))

    async def chat_json(self, stage: str, messages: list, response_model: Type[T]) -> T:
        last = None
        for name, model, url, key in self._chain(stage):
            for retry in range(2):
                record = {
                    "stage": stage,
                    "model": model,
                    "success": False,
                    "ttft_ms": None,
                    "total_tokens": None,
                    "error": None,
                }
                if not url or not model:
                    record["error"] = "missing_config"
                    self._save_record(record)
                    last = LLMError(f"missing config for {name}")
                    break

                try:
                    client = AsyncOpenAI(base_url=url, api_key=key)
                    start_time = time.perf_counter()
                    resp = await client.chat.completions.create(
                        model=model,
                        messages=messages,
                        response_format={"type": "json_object"},
                        timeout=self._timeout(stage),
                    )
                    record["ttft_ms"] = round((time.perf_counter() - start_time) * 1000, 2)
                    usage = getattr(resp, "usage", None)
                    record["total_tokens"] = getattr(usage, "total_tokens", None)
                    data = resp.choices[0].message.content
                    result = response_model.model_validate_json(data)
                    record["success"] = True
                    self._save_record(record)
                    return result
                except ValidationError as e:
                    last = e
                    record["error"] = "validation_error"
                    self._save_record(record)
                    if retry == 0:
                        continue
                except Exception as e:
                    last = e
                    record["error"] = type(e).__name__
                    self._save_record(record)
                    break
        raise LLMError("all llm attempts failed") from last

async def chat_json(stage: str, messages: list, response_model):
    from server.config import settings
    return await LLMClient(settings).chat_json(stage, messages, response_model)

