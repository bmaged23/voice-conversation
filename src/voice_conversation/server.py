import asyncio
import base64
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager
import json
import multiprocessing as mp
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import httpx
import numpy as np

from .core import Endpoint, PhraseBuffer
from .settings import ROOT, load_config, load_settings
from .workers import Silero, init_stt, init_tts, ready, synthesize, transcribe, warmup_stt, warmup_tts


@asynccontextmanager
async def lifespan(app):
    settings = load_settings()
    context = mp.get_context(settings["workers"]["start_method"])
    settings["stt"]["model_path"] = settings["paths"]["stt_model"]
    settings["tts"]["model_path"] = settings["paths"]["tts_model"]
    settings["tts"]["voices_path"] = settings["paths"]["tts_voices"]
    app.state.settings = settings
    app.state.busy = False
    app.state.stt = ProcessPoolExecutor(settings["workers"]["stt_processes"], mp_context=context, initializer=init_stt,
                                      initargs=(settings["stt"], str(ROOT)))
    app.state.tts = ProcessPoolExecutor(settings["workers"]["tts_processes"], mp_context=context, initializer=init_tts,
                                      initargs=(settings["tts"], str(ROOT)))
    try:
        loop = asyncio.get_running_loop()
        await asyncio.gather(loop.run_in_executor(app.state.stt, ready),
                             loop.run_in_executor(app.state.tts, ready))
        if settings["workers"].get("warm_up_models", True):
            await asyncio.gather(loop.run_in_executor(app.state.stt, warmup_stt),
                                 loop.run_in_executor(app.state.tts, warmup_tts))
        async with httpx.AsyncClient(timeout=settings["llm"]["request_timeout_seconds"]) as client:
            app.state.client = client
            yield
    finally:
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
    return {"ready": True, "model": app.state.settings["llm"]["model"],
            "stt_device": app.state.settings["stt"]["device"], "tts_device": "cpu"}


@app.get("/client-config")
async def client_config():
    return app.state.settings["audio"]


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

    async def send(self, kind, **payload):
        async with self.lock:
            await self.ws.send_json({"type": kind, **payload})

    async def interrupt(self):
        self.turn += 1
        if self.response_task and not self.response_task.done():
            self.response_task.cancel()
            await asyncio.gather(self.response_task, return_exceptions=True)
        # A running short ONNX inference cannot be preempted; its result is discarded.
        for _, _, semaphore in self.outstanding.values():
            semaphore.release()
        self.outstanding.clear()
        await self.send("interrupt", turn=self.turn)

    async def close(self):
        for task in (self.response_task, self.partial_task):
            if task:
                task.cancel()
        await asyncio.gather(*(t for t in (self.response_task, self.partial_task) if t),
                             return_exceptions=True)

    async def partial(self, audio, segment):
        try:
            text = await self.loop.run_in_executor(app.state.stt, transcribe, audio)
            if segment == self.segment:
                await self.send("partial", text=text)
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.send("error", text="STT preview failed. Check the server and GPU setup.")

    def acknowledge(self, packet):
        item = self.outstanding.pop(packet.get("id"), None)
        if item is None:
            return
        turn, phrase, semaphore = item
        semaphore.release()
        if packet.get("complete") and turn in self.answers:
            self.answers[turn]["content"] += phrase + " "

    async def response(self, audio, segment, turn):
        try:
            text = await self.loop.run_in_executor(app.state.stt, transcribe, audio)
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
            self.answers = {k: v for k, v in self.answers.items()
                            if any(v is entry for entry in self.history) or k == turn}
            messages = [{"role": "system", "content": self.config["llm"]["system_prompt"]}]
            messages += [dict(entry) for entry in self.history if entry["content"].strip()]
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
            # Do not serialize request headers, secrets, or provider error bodies.
            await self.send("error", text="Response failed. Check network access, Ollama quota, and speech model setup.")

    async def stream_llm(self, messages, tokens):
        settings = self.config["llm"]
        headers = {"Authorization": "Bearer " + settings["api_key"]}
        payload = {"model": settings["model"], "messages": messages, "stream": True,
                   "think": settings["think"],
                   "options": {"temperature": settings["temperature"],
                               "num_predict": settings["max_response_tokens"]}}
        done = False
        async with app.state.client.stream("POST", settings["base_url"].rstrip("/") + "/api/chat",
                                          headers=headers, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                packet = json.loads(line)
                if packet.get("error"):
                    raise RuntimeError("Provider stream error")
                content = packet.get("message", {}).get("content", "")
                if content:
                    await tokens.put(content)
                if packet.get("done"):
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
                text = await asyncio.wait_for(tokens.get(), settings["flush_timeout_ms"] / 1000)
            except asyncio.TimeoutError:
                # Do not split a token in the middle of an unfinished word.
                if len(buffer.text) >= settings["min_characters"] and buffer.text.endswith(" "):
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
        semaphore = asyncio.Semaphore(self.config["workers"]["playback_queue_max_chunks"])
        sequence = 0
        while (phrase := await phrases.get()) is not None:
            await semaphore.acquire()
            pcm, rate = await self.loop.run_in_executor(app.state.tts, synthesize, phrase)
            if turn != self.turn:
                return
            sequence += 1
            chunk_id = f"{turn}:{sequence}"
            self.outstanding[chunk_id] = (turn, phrase, semaphore)
            await self.send("audio", id=chunk_id, turn=turn, sample_rate=rate,
                            pcm=base64.b64encode(pcm).decode())
            if sequence == 1:
                await self.send("latency", seconds=round(time.perf_counter() - self.last_end, 3))

    async def run(self):
        vad = Silero(ROOT / self.config["paths"]["vad_model"], self.config["vad"])
        endpoint_settings = dict(self.config["vad"])
        if self.config["interruptions"]["enabled"]:
            endpoint_settings["min_speech_ms"] = max(endpoint_settings["min_speech_ms"], self.config["interruptions"]["min_speech_ms"])
        endpoint = Endpoint(endpoint_settings)
        await self.send("ready", model=self.config["llm"]["model"], audio=self.config["audio"])
        while True:
            packet = await self.ws.receive()
            if packet["type"] == "websocket.disconnect":
                break
            if packet.get("text"):
                command = json.loads(packet["text"])
                if command.get("type") == "played":
                    self.acknowledge(command)
                elif command.get("type") == "stop":
                    break
                continue
            raw = packet.get("bytes", b"")
            if (not self.config["interruptions"]["enabled"] and
                    ((self.response_task and not self.response_task.done()) or self.outstanding)):
                continue
            if len(raw) != 512 * 4:
                await self.send("error", text="Expected 512 float32 samples per microphone frame")
                continue
            frame = np.frombuffer(raw, dtype="<f4").copy()
            if not np.isfinite(frame).all():
                continue
            frame = np.clip(frame, -1, 1)
            for kind, audio in endpoint.feed(frame, vad(frame)):
                if kind == "start":
                    self.segment += 1
                    await self.interrupt()
                    await self.send("status", text="Listening to you")
                elif kind == "end":
                    self.last_end = time.perf_counter()
                    if self.partial_task:
                        self.partial_task.cancel()
                    self.response_task = asyncio.create_task(self.response(audio, self.segment, self.turn))
            now = time.monotonic()
            if (endpoint.started and (self.partial_task is None or self.partial_task.done()) and
                    now - self.last_partial >= self.config["stt"]["partial_interval_ms"] / 1000):
                self.last_partial = now
                self.partial_task = asyncio.create_task(self.partial(
                    endpoint.snapshot(self.config["stt"]["window_seconds"]), self.segment))


@app.websocket("/ws")
async def websocket(ws: WebSocket):
    # Local browser only; prevents arbitrary websites from opening a credentialed session.
    host = ws.headers.get("host", "")
    if ws.headers.get("origin") not in (f"http://{host}", f"https://{host}"):
        await ws.close(code=1008)
        return
    await ws.accept()
    if app.state.busy:
        await ws.send_json({"type": "error", "text": "Another voice session is active. Stop it first."})
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
