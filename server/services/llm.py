import time
from dataclasses import dataclass
from typing import Type, TypeVar, Any
from pydantic import BaseModel, ValidationError
from openai import AsyncOpenAI

T = TypeVar("T", bound=BaseModel)

class LLMError(Exception):
    pass

class LLMClient:
    def __init__(self, settings):
        self.settings=settings
        self.records=[]

    def _record(self, stage, model, error=None, usage=None, ttft_ms=None):
        self.records.append({
            "stage": stage,
            "model": model,
            "ttft_ms": ttft_ms,
            "total_tokens": getattr(usage, "total_tokens", None) if usage else None,
            "error": type(error).__name__ if error else None,
        })

    def _chain(self, stage):
        if stage in {"orchestration","followup","new_student"}:
            return [("local", self.settings.local_model, self.settings.local_base_url, self.settings.local_api_key), ("flash", self.settings.flash_model, self.settings.flash_base_url, self.settings.flash_api_key)]
        return [("flagship", self.settings.flagship_model, self.settings.flagship_base_url, self.settings.flagship_api_key), ("local", self.settings.local_model, self.settings.local_base_url, self.settings.local_api_key)]

    async def chat_json(self, stage: str, messages: list, response_model: Type[T]) -> T:
        last=None
        for name, model, url, key in self._chain(stage):
            for retry in range(2):
                try:
                    if not url or not model:
                        raise LLMError(f"missing config for {name}")
                    client=AsyncOpenAI(base_url=url, api_key=key)
                    start=time.perf_counter()
                    resp=await client.chat.completions.create(model=model,messages=messages,response_format={"type":"json_object"},timeout=self.settings.orchestration_timeout_s)
                    usage=getattr(resp,"usage",None)
                    self._record(stage, model, usage=usage, ttft_ms=None)
                    data=resp.choices[0].message.content
                    return response_model.model_validate_json(data)
                except ValidationError as e:
                    last=e
                    self._record(stage, model, error=e)
                    if retry==0: continue
                except Exception as e:
                    last=e
                    self._record(stage, model, error=e)
                    break
        raise LLMError("all llm attempts failed") from last


async def chat_json(stage: str, messages: list, response_model):
    from server.config import settings
    return await LLMClient(settings).chat_json(stage, messages, response_model)
