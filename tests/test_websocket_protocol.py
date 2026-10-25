"""Protocol tests exercise real WebSocket routing without loading speech/cloud models."""

import numpy as np
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from voice_conversation import server
from voice_conversation.settings import load_config


@pytest.fixture
def client(monkeypatch):
    config = load_config()
    config["llm"]["model"] = "synthetic-protocol-test"
    monkeypatch.setattr(server.app.state, "settings", config, raising=False)
    monkeypatch.setattr(server.app.state, "busy", False, raising=False)
    monkeypatch.setattr(
        server.app.state, "diagnostics", {"frames_received": 0}, raising=False
    )
    monkeypatch.setattr(server, "Silero", lambda *args: lambda frame: 0.0)
    # No lifespan context: protocol tests deliberately do not initialize model executors.
    return TestClient(server.app)


def test_invalid_origin_rejected(client):
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect(
            "/ws", headers={"origin": "https://unrelated.example"}
        ):
            pass
    assert error.value.code == 1008


def test_second_session_rejected_without_disrupting_first(client):
    headers = {"origin": "http://testserver"}
    with client.websocket_connect("/ws", headers=headers) as first:
        assert first.receive_json()["type"] == "ready"
        with client.websocket_connect("/ws", headers=headers) as second:
            assert second.receive_json()["type"] == "error"
            with pytest.raises(WebSocketDisconnect):
                second.receive_json()
        first.send_text("not json")
        assert first.receive_json()["type"] == "error"


def test_malformed_controls_and_frames_do_not_close_session(client):
    with client.websocket_connect(
        "/ws", headers={"origin": "http://testserver"}
    ) as socket:
        assert socket.receive_json()["type"] == "ready"
        for value in ["{", "[]", "null"]:
            socket.send_text(value)
            assert socket.receive_json()["type"] == "error"
        socket.send_json({"type": "played", "id": [], "complete": True})
        socket.send_bytes(np.full(512, np.nan, dtype="<f4").tobytes())
        socket.send_bytes(np.zeros(512, dtype="<f4").tobytes())
        socket.send_bytes(b"wrong-size")
        assert socket.receive_json()["type"] == "error"
        assert server.app.state.diagnostics["frames_received"] == 1
