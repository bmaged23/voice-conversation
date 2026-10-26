"""Read-only HTTP API; session audio/text stays on the same-origin WebSocket."""

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request):
    settings = request.app.state.settings
    return {
        "ready": True,
        "model": settings["llm"]["model"],
        "stt_device": settings["stt"]["device"],
        "tts_device": settings["tts"]["device"],
    }


@router.get("/client-config")
async def client_config(request: Request):
    return request.app.state.settings["audio"]


@router.get("/diagnostics")
async def diagnostics(request: Request):
    return {**request.app.state.diagnostics, "session_active": request.app.state.busy}


@router.get("/capabilities")
async def capabilities(request: Request):
    settings = request.app.state.settings
    return {
        "protocol_version": 2,
        "websocket": "/ws",
        "max_sessions": 1,
        "input": {
            "encoding": "float32le",
            "sample_rate": 16000,
            "frame_samples": 512,
            "channels": 1,
        },
        "output": {
            "encoding": "base64-pcm16le",
            "sample_rate_field": "sample_rate",
            "acknowledgements_required": True,
        },
        "interpretation": {
            "enabled": settings.get("interpretation", {}).get("enabled", False),
            "raw_transcript_event": "final",
            "interpretation_event": "interpretation",
            "history_uses_interpreted_text": True,
        },
        "history_policy": settings["interruptions"]["history_policy"],
    }
