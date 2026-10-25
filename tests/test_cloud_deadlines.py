"""Provider keepalives must not leave a session thinking indefinitely."""

import asyncio
from contextlib import asynccontextmanager

import pytest

from voice_conversation import server


class Socket:
    async def send_json(self, packet):
        pass


class Response:
    def raise_for_status(self):
        pass

    async def aiter_lines(self):
        while True:
            await asyncio.sleep(0.002)
            yield '{"message":{"content":""}}'


class Client:
    @asynccontextmanager
    async def stream(self, *args, **kwargs):
        yield Response()


@pytest.mark.asyncio
async def test_empty_keepalives_do_not_extend_first_content_deadline(monkeypatch):
    settings = {
        "llm": {
            "api_key": "synthetic-test",
            "base_url": "https://ollama.com",
            "model": "synthetic-test",
            "think": False,
            "temperature": 0,
            "max_response_tokens": 10,
            "first_content_timeout_seconds": 0.03,
            "idle_content_timeout_seconds": 0.03,
        }
    }
    monkeypatch.setattr(server.app.state, "settings", settings, raising=False)
    monkeypatch.setattr(server.app.state, "client", Client(), raising=False)
    session = server.Session(Socket())
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(session.stream_llm([], asyncio.Queue()), 0.5)
