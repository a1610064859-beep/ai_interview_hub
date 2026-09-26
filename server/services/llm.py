import json
import asyncio
import time
import logging
from pathlib import Path
from typing import Type, TypeVar
from pydantic import BaseModel, ValidationError
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

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
            except Exception as e:
                logger.warning(
                    "Failed to write LLM usage log to %s: %s",
                    log_path,
                    type(e).__name__,
                )

    def _chain(self, stage: str):
        chain = [
            ("flagship", getattr(self.settings, "flagship_model", None), getattr(self.settings, "flagship_base_url", None), getattr(self.settings, "flagship_api_key", None)),
            ("flash", getattr(self.settings, "flash_model", None), getattr(self.settings, "flash_base_url", None), getattr(self.settings, "flash_api_key", None)),
            ("local", getattr(self.settings, "local_model", None), getattr(self.settings, "local_base_url", None), getattr(self.settings, "local_api_key", None)),
        ]
        return [entry for entry in chain if entry[1] and entry[2]]

    def _timeout(self, stage: str) -> float:
        if stage in {"scoring", "jd", "jd_parse"}:
            return float(getattr(self.settings, "llm_scoring_timeout_s", getattr(self.settings, "scoring_timeout_s", 60.0)))
        return float(getattr(self.settings, "llm_orchestration_timeout_s", getattr(self.settings, "orchestration_timeout_s", 6.0)))

    async def chat_json(self, stage: str, messages: list, response_model: Type[T]) -> T:
        budget = self._timeout(stage)
        try:
            async with asyncio.timeout(budget):
                return await self._attempts(stage, messages, response_model, time.monotonic() + budget)
        except TimeoutError as exc:
            raise LLMError("llm stage deadline exceeded") from exc

    async def _attempts(self, stage, messages, response_model, deadline):
        last = None
        chain = self._chain(stage)
        for index, (name, model, url, key) in enumerate(chain):
            for retry in range(2):
                started = time.monotonic()
                record = {
                    "stage": stage,
                    "model": model,
                    "success": False,
                    "ttft_ms": None,
                    "total_tokens": None,
                    "error": None,
                    "total_ms": 0.0,
                }
                if not url or not model:
                    record["error"] = "missing_config"
                    self._save_record(record)
                    last = LLMError(f"missing config for {name}")
                    break

                client = None
                try:
                    remaining = deadline - time.monotonic()
                    attempt_timeout = remaining
                    if index < len(chain) - 1:
                        # 仅为已配置的后续模型保留时间，空配置不能占用当前 API 的预算。
                        shares_by_count = {
                            1: (1.0,),
                            2: (2 / 3, 1 / 3),
                            3: (0.5, 1 / 3, 1 / 6),
                        }
                        shares = shares_by_count[len(chain)]
                        total_budget = self._timeout(stage)
                        fallback_reserve = total_budget * sum(shares[index + 1:])
                        attempt_timeout = min(total_budget * shares[index], remaining - fallback_reserve)
                    attempt_timeout = max(0.001, attempt_timeout)
                    response_format = {"type": "json_object"}
                    if name == "local":
                        response_format = {
                            "type": "json_schema",
                            "json_schema": {
                                "name": response_model.__name__,
                                "strict": True,
                                "schema": response_model.model_json_schema(),
                            },
                        }
                    client = AsyncOpenAI(base_url=url, api_key=key, max_retries=0)
                    resp = await asyncio.wait_for(client.chat.completions.create(
                        model=model,
                        messages=messages,
                        response_format=response_format,
                        timeout=attempt_timeout,
                    ), timeout=attempt_timeout)
                    # Non-streaming client: this is the first point at which response content is available.
                    record["ttft_ms"] = round((time.monotonic() - started) * 1000, 1)
                    usage = getattr(resp, "usage", None)
                    record["total_tokens"] = getattr(usage, "total_tokens", None)
                    record["prompt_tokens"] = getattr(usage, "prompt_tokens", None)
                    record["completion_tokens"] = getattr(usage, "completion_tokens", None)
                    data = resp.choices[0].message.content
                    result = response_model.model_validate_json(data)
                    record["success"] = True
                    return result
                except ValidationError as e:
                    last = e
                    record["error"] = "validation_error"
                    if retry == 0:
                        continue
                except asyncio.CancelledError:
                    record["error"] = "stage_deadline_or_cancelled"
                    raise
                except Exception as e:
                    last = e
                    record["error"] = type(e).__name__
                    break
                finally:
                    record["total_ms"] = round((time.monotonic() - started) * 1000, 1)
                    self._save_record(record)
                    if client is not None and hasattr(client, "close"):
                        try:
                            await asyncio.wait_for(client.close(), timeout=0.25)
                        except (Exception, asyncio.CancelledError):
                            pass
        raise LLMError("all llm attempts failed") from last

async def chat_json(stage: str, messages: list, response_model):
    from server.config import settings
    return await LLMClient(settings).chat_json(stage, messages, response_model)

