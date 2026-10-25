"""Isolated opt-in tracing and fault injection for synthetic QA, never normal startup."""

import os
from contextlib import asynccontextmanager
import httpx, uvicorn
from fastapi import Request, HTTPException
from voice_conversation import server
from voice_conversation.settings import load_settings


class BudgetClient:
    def __init__(self, client, maximum):
        self.client = client
        self.maximum = maximum
        self.requests = 0
        self.fault = None

    @asynccontextmanager
    async def stream(self, *args, **kwargs):
        if self.requests >= self.maximum:
            raise httpx.RequestError("Evaluation request budget reached")
        self.requests += 1
        fault = self.fault
        self.fault = None
        if fault == "cloud_timeout":
            raise httpx.ReadTimeout("Synthetic evaluation timeout")
        async with self.client.stream(*args, **kwargs) as response:
            yield response


if __name__ == "__main__":
    cfg = load_settings()
    folder = os.environ.get(
        "VOCA_EVALUATION_OUTPUT", ".evaluation-local/browser-evaluation"
    )
    cfg["server"]["port"] = 8767
    cfg["logging"]["pipeline_trace"] = {
        "enabled": True,
        "directory": folder + "/pipeline-traces",
    }
    server.load_settings = lambda: cfg
    original = server.app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        async with original(app):
            app.state.client = BudgetClient(
                app.state.client,
                int(os.environ.get("VOCA_EVALUATION_MAX_REQUESTS", "30")),
            )
            yield

    server.app.router.lifespan_context = lifespan

    @server.app.post("/__qa__/fault")
    async def fault(request: Request):
        kind = (await request.json()).get("kind")
        if kind != "cloud_timeout":
            raise HTTPException(400, "Unknown evaluation fault")
        server.app.state.client.fault = kind
        return {"armed": kind}

    @server.app.get("/__qa__/usage")
    async def usage():
        c = server.app.state.client
        return {"requests": c.requests, "maximum": c.maximum}

    uvicorn.run(
        server.app,
        host=os.environ.get("VOCA_EVALUATION_HOST", "127.0.0.1"),
        port=8767,
        access_log=False,
    )
