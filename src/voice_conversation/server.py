import asyncio
import base64
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager
import json
import multiprocessing as mp
import time
import uuid

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import httpx
import numpy as np

from .core import Endpoint, PhraseBuffer
from .pipeline_trace import PipelineTrace
from .settings import ROOT, load_config, load_settings
from .workers import (
    Silero,
    init_stt,
    init_tts,
    ready,
    synthesize,
    transcribe,
    warmup_stt,
    warmup_tts,
    shutdown_tts,
)


@asynccontextmanager
async def lifespan(app):
    settings = load_settings()
    context = mp.get_context(settings["workers"]["start_method"])
    settings["stt"]["model_path"] = settings["paths"]["stt_model"]
    settings["tts"]["model_path"] = settings["paths"]["tts_model"]
    settings["tts"]["voices_path"] = settings["paths"]["tts_voices"]
    app.state.settings = settings
    app.state.busy = False
    app.state.diagnostics = {"stage": "ready", "frames_received": 0}
    app.state.stt = ProcessPoolExecutor(
        settings["workers"]["stt_processes"],
        mp_context=context,
        initializer=init_stt,
        initargs=(settings["stt"], str(ROOT)),
    )
    app.state.tts = ProcessPoolExecutor(
        settings["workers"]["tts_processes"],
        mp_context=context,
        initializer=init_tts,
        initargs=(settings["tts"], str(ROOT)),
    )
    try:
        loop = asyncio.get_running_loop()
        await asyncio.gather(
            loop.run_in_executor(app.state.stt, ready),
            loop.run_in_executor(app.state.tts, ready),
        )
        if settings["workers"].get("warm_up_models", True):
            await asyncio.gather(
                loop.run_in_executor(app.state.stt, warmup_stt),
                loop.run_in_executor(app.state.tts, warmup_tts),
            )
        async with httpx.AsyncClient(
            timeout=settings["llm"]["request_timeout_seconds"]
        ) as client:
            app.state.client = client
            yield
    finally:
        try:
            await asyncio.get_running_loop().run_in_executor(
                app.state.tts, shutdown_tts
            )
        except Exception:
            pass  # A broken worker pool already terminates its child process.
        app.state.stt.shutdown(wait=True, cancel_futures=True)
        app.state.tts.shutdown(wait=True, cancel_futures=True)


app = FastAPI(lifespan=lifespan)
WEB = ROOT / load_config()["paths"]["web"]
app.mount("/static", StaticFiles(directory=WEB), name="static")
app.mount("/docs", StaticFiles(directory=ROOT / "docs", html=True), name="project-docs")


@app.get("/")
async def index():
    return FileResponse(WEB / "index.html")


@app.get("/health")
async def health():
    return {
        "ready": True,
        "model": app.state.settings["llm"]["model"],
        "stt_device": app.state.settings["stt"]["device"],
        "tts_device": app.state.settings["tts"]["device"],
    }


@app.get("/client-config")
async def client_config():
    return app.state.settings["audio"]


@app.get("/diagnostics")
async def diagnostics():
    return {**app.state.diagnostics, "session_active": app.state.busy}


class Session:
    def __init__(self, ws):
        self.ws = ws
        self.config = app.state.settings
        self.loop = asyncio.get_running_loop()
        self.lock = asyncio.Lock()
        self.turn = 0
        self.segment = 0
        self.history = []
        self.answers = {}
        self.outstanding = {}
        self.response_task = None
        self.partial_task = None
        self.last_partial = 0
        self.last_end = time.perf_counter()
        self.trace = PipelineTrace(
            self.config.get("logging", {}).get("pipeline_trace", {"enabled": False}),
            ROOT,
            uuid.uuid4().hex,
        )

    async def send(self, kind, **payload):
        async with self.lock:
            await self.ws.send_json({"type": kind, **payload})

    async def interrupt(self):
        self.trace.event("interrupt", turn=self.turn)
        self.turn += 1
        await self.send("interrupt", turn=self.turn)
        if self.response_task and not self.response_task.done():
            self.response_task.cancel()
            await asyncio.gather(self.response_task, return_exceptions=True)
        # A running short ONNX inference cannot be preempted; its result is discarded.
        for _, _, semaphore in self.outstanding.values():
            semaphore.release()
        self.outstanding.clear()

    async def close(self):
        for task in (self.response_task, self.partial_task):
            if task:
                task.cancel()
        await asyncio.gather(
            *(t for t in (self.response_task, self.partial_task) if t),
            return_exceptions=True,
        )

    async def partial(self, audio, segment):
        try:
            text = await self.loop.run_in_executor(app.state.stt, transcribe, audio)
            if segment == self.segment:
                self.trace.event("stt_partial", text=text, turn=self.turn)
                await self.send("partial", text=text)
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.send(
                "error", text="STT preview failed. Check the server and GPU setup."
            )

    def acknowledge(self, packet):
        identity = packet.get("id")
        complete = packet.get("complete")
        if not isinstance(identity, str) or not isinstance(complete, bool):
            return
        self.trace.event("playback_ack", id=identity, complete=complete)
        item = self.outstanding.pop(identity, None)
        if item is None:
            return
        turn, phrase, semaphore = item
        semaphore.release()
        if complete and turn in self.answers:
            self.answers[turn]["content"] += phrase + " "

    async def response(self, audio, segment, turn):
        try:
            self.trace.audio(
                "input-" + str(turn),
                (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes(),
                16000,
                event="stt_input",
                turn=turn,
            )
            started = time.perf_counter()
            text = await self.loop.run_in_executor(app.state.stt, transcribe, audio)
            self.trace.event(
                "stt_final",
                turn=turn,
                text=text,
                queue_and_decode_seconds=time.perf_counter() - started,
            )
            if segment != self.segment or turn != self.turn:
                return
            await self.send("final", text=text)
            if not text:
                await self.send("status", text="Listening")
                return
            self.history.append({"role": "user", "content": text})
            answer = {"role": "assistant", "content": ""}
            self.answers[turn] = answer
            limit = self.config["llm"]["history_max_turns"] * 2
            self.history = self.history[-limit:]
            self.answers = {
                k: v
                for k, v in self.answers.items()
                if any(v is entry for entry in self.history) or k == turn
            }
            messages = [
                {"role": "system", "content": self.config["llm"]["system_prompt"]}
            ]
            messages += [
                dict(entry) for entry in self.history if entry["content"].strip()
            ]
            self.trace.event("llm_messages", turn=turn, messages=messages)
            self.history.append(answer)
            phrases = asyncio.Queue(self.config["workers"]["tts_queue_max_phrases"])
            tokens = asyncio.Queue(self.config["workers"]["llm_token_queue_size"])
            await self.send("status", text="Thinking")
            async with asyncio.TaskGroup() as group:
                group.create_task(self.stream_llm(messages, tokens))
                group.create_task(self.chunk_tokens(tokens, phrases))
                group.create_task(self.speak(phrases, turn))
            await self.send("status", text="Listening", turn=turn)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.trace.event("reply_error", turn=turn)
            # Do not serialize request headers, secrets, or provider error bodies.
            await self.send(
                "error",
                text="Response failed. Check network access, Ollama quota, and speech model setup.",
            )

    async def stream_llm(self, messages, tokens):
        settings = self.config["llm"]
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
        async with app.state.client.stream(
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
                self.trace.event(
                    "llm_raw",
                    turn=self.turn,
                    text=content,
                    done=packet.get("done", False),
                    done_reason=packet.get("done_reason"),
                )
                if content:
                    await tokens.put(content)
                    # Local queue backpressure is not a cloud-provider stall.
                    deadline = (
                        time.monotonic() + settings["idle_content_timeout_seconds"]
                    )
                if packet.get("done"):
                    self.trace.event(
                        "llm_usage",
                        turn=self.turn,
                        input_tokens=packet.get("prompt_eval_count"),
                        output_tokens=packet.get("eval_count"),
                        total_duration_ns=packet.get("total_duration"),
                    )
                    done = True
                    break
        if not done:
            raise RuntimeError("Incomplete provider stream")
        await tokens.put(None)

    async def chunk_tokens(self, tokens, phrases):
        settings = self.config["tts"]["chunking"]
        buffer = PhraseBuffer(settings["min_characters"], settings["max_characters"])
        while True:
            try:
                text = await asyncio.wait_for(
                    tokens.get(), settings["flush_timeout_ms"] / 1000
                )
            except asyncio.TimeoutError:
                # Do not split a token in the middle of an unfinished word.
                if len(buffer.text) >= settings[
                    "min_characters"
                ] and buffer.text.endswith(" "):
                    for phrase in buffer.push(flush=True):
                        await phrases.put(phrase)
                continue
            if text is None:
                for phrase in buffer.push(flush=True):
                    await phrases.put(phrase)
                await phrases.put(None)
                return
            await self.send("token", text=text, turn=self.turn)
            for phrase in buffer.push(text):
                await phrases.put(phrase)

    async def speak(self, phrases, turn):
        semaphore = asyncio.Semaphore(
            self.config["workers"]["playback_queue_max_chunks"]
        )
        sequence = 0
        while (phrase := await phrases.get()) is not None:
            await semaphore.acquire()
            self.trace.event("tts_input", turn=turn, text=phrase)
            started = time.perf_counter()
            pcm, rate = await self.loop.run_in_executor(
                app.state.tts, synthesize, phrase
            )
            self.trace.event(
                "tts_complete", turn=turn, seconds=time.perf_counter() - started
            )
            if turn != self.turn:
                return
            sequence += 1
            chunk_id = f"{turn}:{sequence}"
            self.trace.audio(chunk_id, pcm, rate, turn=turn, text=phrase, language="en")
            self.outstanding[chunk_id] = (turn, phrase, semaphore)
            await self.send(
                "audio",
                id=chunk_id,
                turn=turn,
                sample_rate=rate,
                pcm=base64.b64encode(pcm).decode(),
            )
            if sequence == 1:
                await self.send(
                    "latency", seconds=round(time.perf_counter() - self.last_end, 3)
                )

    async def run(self):
        vad = Silero(ROOT / self.config["paths"]["vad_model"], self.config["vad"])
        endpoint_settings = dict(self.config["vad"])
        if self.config["interruptions"]["enabled"]:
            endpoint_settings["min_speech_ms"] = max(
                endpoint_settings["min_speech_ms"],
                self.config["interruptions"]["min_speech_ms"],
            )
        endpoint = Endpoint(endpoint_settings)
        await self.send(
            "ready", model=self.config["llm"]["model"], audio=self.config["audio"]
        )
        while True:
            packet = await self.ws.receive()
            if packet["type"] == "websocket.disconnect":
                break
            if packet.get("text"):
                try:
                    command = json.loads(packet["text"])
                    if not isinstance(command, dict):
                        raise ValueError("Expected control object")
                except (ValueError, TypeError):
                    await self.send("error", text="Expected a JSON control object")
                    continue
                if command.get("type") == "played":
                    self.acknowledge(command)
                elif command.get("type") == "stop":
                    break
                continue
            raw = packet.get("bytes", b"")
            if not self.config["interruptions"]["enabled"] and (
                (self.response_task and not self.response_task.done())
                or self.outstanding
            ):
                continue
            if len(raw) != 512 * 4:
                await self.send(
                    "error", text="Expected 512 float32 samples per microphone frame"
                )
                continue
            frame = np.frombuffer(raw, dtype="<f4").copy()
            if not np.isfinite(frame).all():
                continue
            frame = np.clip(frame, -1, 1)
            app.state.diagnostics["frames_received"] += 1
            for kind, audio in endpoint.feed(frame, vad(frame)):
                if kind == "start":
                    self.segment += 1
                    await self.interrupt()
                    await self.send("status", text="Listening to you")
                elif kind == "end":
                    self.last_end = time.perf_counter()
                    if self.partial_task:
                        self.partial_task.cancel()
                    self.response_task = asyncio.create_task(
                        self.response(audio, self.segment, self.turn)
                    )
            now = time.monotonic()
            if (
                endpoint.started
                and (self.partial_task is None or self.partial_task.done())
                and now - self.last_partial
                >= self.config["stt"]["partial_interval_ms"] / 1000
            ):
                self.last_partial = now
                self.partial_task = asyncio.create_task(
                    self.partial(
                        endpoint.snapshot(self.config["stt"]["window_seconds"]),
                        self.segment,
                    )
                )


@app.websocket("/ws")
async def websocket(ws: WebSocket):
    # Local browser only; prevents arbitrary websites from opening a credentialed session.
    host = ws.headers.get("host", "")
    if ws.headers.get("origin") not in (f"http://{host}", f"https://{host}"):
        await ws.close(code=1008)
        return
    await ws.accept()
    if app.state.busy:
        await ws.send_json(
            {"type": "error", "text": "Another voice session is active. Stop it first."}
        )
        await ws.close(code=1008)
        return
    app.state.busy = True
    session = Session(ws)
    try:
        await session.run()
    except WebSocketDisconnect:
        pass
    finally:
        await session.close()
        app.state.busy = False
