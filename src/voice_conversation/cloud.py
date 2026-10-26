"""Bounded Ollama Cloud transport; no session or web-server dependencies."""

import asyncio
import json
import time


async def stream_reply(client, settings, messages, tokens, trace, turn):
    headers = {"Authorization": "Bearer " + settings["api_key"]}
    payload = {
        "model": settings["model"],
        "messages": messages,
        "stream": True,
        "think": settings["think"],
        "options": {
            "temperature": settings["temperature"],
            "num_predict": settings["max_response_tokens"],
        },
    }
    done = False
    async with client.stream(
        "POST",
        settings["base_url"].rstrip("/") + "/api/chat",
        headers=headers,
        json=payload,
    ) as response:
        response.raise_for_status()
        lines = response.aiter_lines().__aiter__()
        deadline = time.monotonic() + settings["first_content_timeout_seconds"]
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Cloud content deadline exceeded")
            try:
                line = await asyncio.wait_for(anext(lines), remaining)
            except StopAsyncIteration:
                break
            if not line:
                continue
            packet = json.loads(line)
            if packet.get("error"):
                raise RuntimeError("Provider stream error")
            content = packet.get("message", {}).get("content", "")
            trace.event(
                "llm_raw",
                turn=turn,
                text=content,
                done=packet.get("done", False),
                done_reason=packet.get("done_reason"),
            )
            if content:
                await tokens.put(content)
                # Local queue backpressure is not a cloud-provider stall.
                deadline = time.monotonic() + settings["idle_content_timeout_seconds"]
            if packet.get("done"):
                trace.event(
                    "llm_usage",
                    turn=turn,
                    input_tokens=packet.get("prompt_eval_count"),
                    output_tokens=packet.get("eval_count"),
                    total_duration_ns=packet.get("total_duration"),
                )
                done = True
                break
    if not done:
        raise RuntimeError("Incomplete provider stream")
    await tokens.put(None)


async def complete_text(
    client, settings, messages, *, think, max_tokens, timeout_seconds
):
    """Bound a small nonstreamed interpretation call without exposing reasoning/headers."""
    payload = {
        "model": settings["model"],
        "messages": messages,
        "stream": False,
        "think": think,
        "options": {"temperature": 0, "num_predict": max_tokens},
    }
    async with asyncio.timeout(timeout_seconds):
        async with client.stream(
            "POST",
            settings["base_url"].rstrip("/") + "/api/chat",
            headers={"Authorization": "Bearer " + settings["api_key"]},
            json=payload,
        ) as response:
            response.raise_for_status()
            await response.aread()
            packet = response.json()
    text = packet.get("message", {}).get("content")
    if not isinstance(text, str) or not text.strip() or packet.get("done") is not True:
        raise RuntimeError("Incomplete interpretation response")
    return text, {
        "input_tokens": packet.get("prompt_eval_count"),
        "output_tokens": packet.get("eval_count"),
    }
