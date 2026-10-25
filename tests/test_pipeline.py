import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import numpy as np
import pytest

from voice_conversation.core import Endpoint, PhraseBuffer
from voice_conversation import server
from voice_conversation.workers import KokoroSession


def test_phrase_stream_preserves_words_and_bounds():
    buffer = PhraseBuffer(12, 35)
    output = []
    message = (
        "This is the first sentence. Here is another longer sentence with more words."
    )
    for offset in range(0, len(message), 3):
        output += buffer.push(message[offset : offset + 3])
    output += buffer.push(flush=True)
    assert " ".join(output) == message
    assert all(len(phrase) <= 35 for phrase in output)


def test_endpoint_keeps_prefix_and_finishes_after_silence():
    endpoint = Endpoint(
        {
            "prefix_buffer_ms": 64,
            "speech_threshold": 0.5,
            "min_speech_ms": 64,
            "end_of_turn_silence_ms": 96,
            "max_utterance_seconds": 30,
        }
    )
    frame = np.ones(512, np.float32)
    assert not endpoint.feed(frame, 0)
    assert not endpoint.feed(frame, 0)
    assert not endpoint.feed(frame, 0.9)
    assert endpoint.feed(frame, 0.9) == [("start", None)]
    assert not endpoint.feed(frame, 0)
    assert not endpoint.feed(frame, 0)
    event, audio = endpoint.feed(frame, 0)[0]
    assert event == "end"
    assert len(audio) == 7 * 512
    assert not endpoint.started


def test_endpoint_discards_short_noise():
    endpoint = Endpoint(
        {
            "prefix_buffer_ms": 64,
            "speech_threshold": 0.5,
            "min_speech_ms": 64,
            "end_of_turn_silence_ms": 64,
            "max_utterance_seconds": 30,
        }
    )
    frame = np.zeros(512, np.float32)
    assert not endpoint.feed(frame, 0.9)
    assert not endpoint.feed(frame, 0)
    assert not endpoint.feed(frame, 0)
    assert endpoint.frames == []


def test_kokoro_speed_uses_graph_dtype_and_preserves_fractional_value():
    class Graph:
        def get_inputs(self):
            return [SimpleNamespace(name="speed", type="tensor(float)")]

        def run(self, outputs, inputs):
            assert inputs["speed"].dtype == np.float32
            assert inputs["speed"][0] == np.float32(1.1)
            return [np.zeros(10)]

    graph = KokoroSession(Graph())
    graph.speed = 1.1
    assert len(graph.run(None, {"speed": np.array([1], dtype=np.int32)})[0]) == 10


class Socket:
    def __init__(self):
        self.messages = []

    async def send_json(self, packet):
        self.messages.append(packet)


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setattr(
        server.app.state,
        "settings",
        {
            "llm": {"history_max_turns": 2, "system_prompt": "Speak English."},
            "workers": {"tts_queue_max_phrases": 1, "playback_queue_max_chunks": 1},
            "tts": {
                "chunking": {
                    "min_characters": 5,
                    "max_characters": 40,
                    "flush_timeout_ms": 20,
                }
            },
        },
        raising=False,
    )


@pytest.mark.asyncio
async def test_interruption_cancels_response_and_discards_unplayed_history(session):
    socket = Socket()
    voice = server.Session(socket)
    answer = {"role": "assistant", "content": ""}
    voice.answers[0] = answer
    slot = asyncio.Semaphore(0)
    voice.outstanding["0:1"] = (0, "Already heard.", slot)
    voice.acknowledge({"id": "0:1", "complete": True})
    voice.outstanding["0:2"] = (0, "Never heard.", slot)
    voice.response_task = asyncio.create_task(asyncio.sleep(60))
    await voice.interrupt()
    assert voice.response_task.cancelled()
    assert answer["content"] == "Already heard. "
    assert voice.outstanding == {}
    voice.acknowledge({"id": "0:2", "complete": True})
    assert "Never" not in answer["content"]
    assert socket.messages[-1] == {"type": "interrupt", "turn": 1}


@pytest.mark.asyncio
async def test_playback_backpressure_and_order(session, monkeypatch):
    socket = Socket()
    voice = server.Session(socket)
    executor = ThreadPoolExecutor(1)
    monkeypatch.setattr(server.app.state, "tts", executor, raising=False)
    monkeypatch.setattr(server, "synthesize", lambda text: (b"\0\0", 24000))
    phrases = asyncio.Queue()
    for value in ("First.", "Second.", None):
        phrases.put_nowait(value)
    task = asyncio.create_task(voice.speak(phrases, 0))
    try:
        for _ in range(100):
            if voice.outstanding:
                break
            await asyncio.sleep(0.005)
        assert list(voice.outstanding) == ["0:1"]
        assert not task.done()
        voice.acknowledge({"id": "0:1", "complete": True})
        await asyncio.wait_for(task, 2)
        assert [p["id"] for p in socket.messages if p["type"] == "audio"] == [
            "0:1",
            "0:2",
        ]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        executor.shutdown()


@pytest.mark.asyncio
async def test_phrase_timer_does_not_lose_cancelled_queue_reads(session):
    voice = server.Session(Socket())
    tokens, phrases = asyncio.Queue(), asyncio.Queue()
    task = asyncio.create_task(voice.chunk_tokens(tokens, phrases))
    await tokens.put("Hello world ")
    assert await asyncio.wait_for(phrases.get(), 1) == "Hello world"
    await tokens.put("Goodbye.")
    await tokens.put(None)
    await asyncio.wait_for(task, 1)
    assert await phrases.get() == "Goodbye."
    assert await phrases.get() is None


@pytest.mark.asyncio
async def test_interrupt_packet_precedes_slow_reply_cleanup(session):
    socket = Socket()
    voice = server.Session(socket)
    cleanup_started = asyncio.Event()
    allow_cleanup = asyncio.Event()

    async def slow_reply():
        try:
            await asyncio.sleep(60)
        finally:
            cleanup_started.set()
            await allow_cleanup.wait()

    voice.response_task = asyncio.create_task(slow_reply())
    await asyncio.sleep(0)
    interruption = asyncio.create_task(voice.interrupt())
    try:
        await asyncio.wait_for(cleanup_started.wait(), 1)
        assert socket.messages == [{"type": "interrupt", "turn": 1}]
        assert not interruption.done()
    finally:
        allow_cleanup.set()
        await asyncio.wait_for(interruption, 1)
