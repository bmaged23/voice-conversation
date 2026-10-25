"""Synthetic microphone WebSocket integration test; one short cloud reply.

Requires the local server and logs/speech-smoke.wav. No real microphone or
speaker is exercised. Acknowledgments simulate completed browser playback.
"""

import asyncio
import json
import time
import wave

import numpy as np
import websockets

from voice_conversation.settings import ROOT, load_settings


async def main():
    config = load_settings()
    port = config["server"]["port"]
    with wave.open(str(ROOT / "logs/speech-smoke.wav"), "rb") as handle:
        rate = handle.getframerate()
        samples = (
            np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2").astype(
                np.float32
            )
            / 32768
        )
    samples = np.interp(
        np.arange(0, len(samples), rate / 16000), np.arange(len(samples)), samples
    ).astype("<f4")
    events = []
    async with websockets.connect(
        f"ws://127.0.0.1:{port}/ws",
        origin=f"http://127.0.0.1:{port}",
        max_size=4 * 1024 * 1024,
    ) as socket:
        ready = json.loads(await socket.recv())
        if ready["type"] != "ready":
            raise ValueError("Session not ready")
        audio = np.concatenate([samples, np.zeros(16000, np.float32)])
        start = time.perf_counter()
        for offset in range(0, len(audio) - 511, 512):
            await socket.send(audio[offset : offset + 512].tobytes())
        async with asyncio.timeout(60):
            async for raw in socket:
                packet = json.loads(raw)
                events.append(packet["type"])
                if packet["type"] == "error":
                    raise ValueError(packet["text"])
                if packet["type"] == "final":
                    print("Final transcript:", packet["text"], flush=True)
                if packet["type"] == "audio":
                    print(
                        "First response audio received after",
                        round(time.perf_counter() - start, 3),
                        "seconds",
                        flush=True,
                    )
                    await socket.send(
                        json.dumps(
                            {"type": "played", "id": packet["id"], "complete": True}
                        )
                    )
                    for offset in range(0, len(samples) - 511, 512):
                        await socket.send(samples[offset : offset + 512].tobytes())
                    break
        async with asyncio.timeout(10):
            async for raw in socket:
                packet = json.loads(raw)
                if packet["type"] == "interrupt":
                    print("Interruption event verified:", packet["turn"], flush=True)
                    break
                if packet["type"] == "error":
                    raise ValueError(packet["text"])
        assert "final" in events and "token" in events and "audio" in events
        await socket.send(json.dumps({"type": "stop"}))
    print(
        "Synthetic audio → STT → Ollama stream → TTS → interruption: PASS", flush=True
    )


if __name__ == "__main__":
    asyncio.run(main())
