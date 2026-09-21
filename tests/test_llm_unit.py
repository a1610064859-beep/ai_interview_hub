import pytest
import asyncio
from types import SimpleNamespace
from pydantic import BaseModel
from server.services.llm import LLMClient, LLMError

class Out(BaseModel):
    value: str

def make_settings():
    return SimpleNamespace(local_model='m',local_base_url='u',local_api_key='k',flash_model='fm',flash_base_url='fu',flash_api_key='fk',flagship_model='sm',flagship_base_url='su',flagship_api_key='sk',orchestration_timeout_s=6)

class FakeResp:
    def __init__(self, text='{\"value\":\"ok\"}', tokens=12):
        self.choices=[SimpleNamespace(message=SimpleNamespace(content=text))]
        self.usage=SimpleNamespace(total_tokens=tokens)

class FakeClient:
    class chat:
        class completions:
            @staticmethod
            async def create(**kwargs):
                return FakeResp()

def test_json_to_model(monkeypatch):
    settings=SimpleNamespace(local_model="m",local_base_url="u",local_api_key="k",flash_model="fm",flash_base_url="fu",flash_api_key="fk",flagship_model="sm",flagship_base_url="su",flagship_api_key="sk",orchestration_timeout_s=6)
    client=LLMClient(settings)
    monkeypatch.setattr("server.services.llm.AsyncOpenAI", lambda **x: FakeClient())
    result=asyncio.run(client.chat_json("orchestration", [{"role":"user","content":"x"}], Out))
    assert result.value == "ok"
    assert client.records[0]["total_tokens"] == 12

def test_all_failed():
    settings=SimpleNamespace(local_model="",local_base_url="",local_api_key="",flash_model="",flash_base_url="",flash_api_key="",flagship_model="",flagship_base_url="",flagship_api_key="",orchestration_timeout_s=6)
    client=LLMClient(settings)
    with pytest.raises(LLMError):
        asyncio.run(client.chat_json("orchestration", [], Out))


def test_retry_and_fallback(monkeypatch):
    calls=[]
    class BadThenGood:
        def __init__(self, url): self.url=url
        class chat:
            class completions:
                @staticmethod
                async def create(**kwargs):
                    calls.append(kwargs.get('model'))
                    if len(calls)==1:
                        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{\"bad\":1}'))], usage=SimpleNamespace(total_tokens=1))
                    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{\"value\":\"ok\"}'))], usage=SimpleNamespace(total_tokens=2))
    monkeypatch.setattr('server.services.llm.AsyncOpenAI', lambda **x: BadThenGood(x))
    c=LLMClient(make_settings())
    assert asyncio.run(c.chat_json('orchestration',[],Out)).value=='ok'
    assert len(calls)==2


def test_timeout_forwarded(monkeypatch):
    seen={}
    class C:
        class chat:
            class completions:
                @staticmethod
                async def create(**kwargs):
                    seen['timeout']=kwargs.get('timeout')
                    return FakeResp('{\"value\":\"ok\"}')
    monkeypatch.setattr('server.services.llm.AsyncOpenAI', lambda **x:C())
    asyncio.run(LLMClient(make_settings()).chat_json('orchestration',[],Out))
    assert seen['timeout']==6


def test_models_nullable_and_create():
    from server.db import Base
    from server.models import User, Job, Question, Session, Answer, Report
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as DBSession
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with DBSession(engine) as s:
        u=User(role='student')
        j=Job(family='ai',title='test')
        s.add_all([u,j]); s.flush()
        se=Session(user_id=u.id,job_id=j.id,mode='graduate',status='active')
        s.add(se); s.flush()
        s.add(Answer(session_id=se.id,q_seq=1,question_text='q',answer_text='a',is_followup=False,is_retry=False))
        s.add(Report(session_id=se.id))
        s.commit()


def test_stage_model_switch_order(monkeypatch):
    calls=[]
    class C:
        class chat:
            class completions:
                @staticmethod
                async def create(**kwargs):
                    calls.append(kwargs["model"])
                    return FakeResp('{"value":"ok"}')
    monkeypatch.setattr('server.services.llm.AsyncOpenAI', lambda **x:C())
    asyncio.run(LLMClient(make_settings()).chat_json('scoring', [], Out))
    assert calls[0] == 'sm'


def test_failure_is_recorded(monkeypatch):
    class C:
        class chat:
            class completions:
                @staticmethod
                async def create(**kwargs):
                    raise TimeoutError('timeout')
    monkeypatch.setattr('server.services.llm.AsyncOpenAI', lambda **x:C())
    c=LLMClient(make_settings())
    with pytest.raises(LLMError):
        asyncio.run(c.chat_json('orchestration', [], Out))
    assert any(r['error']=='TimeoutError' for r in c.records)
