"""Persistent isolated GPU voice process with bounded IPC waits and strict provider checks."""

import atexit, base64, json, os, queue, subprocess, threading
from pathlib import Path


class GPUVoiceProcess:
    def __init__(self, settings, root):
        self.settings = settings
        self.root = Path(root)
        self.lock = threading.Lock()
        self.process = None
        self.sequence = 0
        self._start()
        atexit.register(self.close)

    def _start(self):
        runtime = self.root / self.settings["runtime_python"]
        if not runtime.is_file():
            raise RuntimeError("Isolated GPU voice interpreter is missing")
        env = os.environ.copy()
        env.pop("OLLAMA_API_KEY", None)
        env["PYTHONPATH"] = str(self.root / "src") + os.pathsep + str(self.root)
        libraries = [
            str(p)
            for parent in (runtime.parent.parent, self.root / ".venv")
            for p in (parent / "lib").glob("python*/site-packages/nvidia/*/lib")
        ]
        env["LD_LIBRARY_PATH"] = (
            ":".join(libraries) + ":" + env.get("LD_LIBRARY_PATH", "")
        )
        log = self.root / "logs/gpu-voice-worker.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        self.log = os.fdopen(fd, "a")
        self.messages = queue.Queue(maxsize=4)
        self.process = subprocess.Popen(
            [str(runtime), "-m", "scripts.runtime.tts_worker"],
            cwd=self.root,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.log,
            text=True,
            bufsize=1,
        )
        messages = self.messages
        process = self.process

        def read():
            try:
                for line in process.stdout:
                    try:
                        message = json.loads(line)
                    except ValueError:
                        message = {"error": "Invalid voice worker protocol"}
                    messages.put(message)
            finally:
                messages.put({"error": "Voice worker exited"})

        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        try:
            self._write({"root": str(self.root), "settings": self.settings})
            ready = self._receive(self.settings["startup_timeout_seconds"])
            if (
                not ready.get("ready")
                or ready.get("provider") != "CUDAExecutionProvider"
            ):
                raise RuntimeError(
                    "GPU voice worker failed initialization: "
                    + str(ready.get("error", "provider mismatch"))
                )
            self.metadata = ready
        except BaseException:
            self.close()
            raise

    def _write(self, value):
        self.process.stdin.write(json.dumps(value) + "\n")
        self.process.stdin.flush()

    def _receive(self, timeout):
        try:
            return self.messages.get(timeout=timeout)
        except queue.Empty:
            self.close()
            raise TimeoutError("GPU voice worker deadline exceeded") from None

    def synthesize(self, text):
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                self.close()
                self._start()
            self.sequence += 1
            identity = self.sequence
            try:
                self._write({"id": identity, "text": text})
                message = self._receive(self.settings["request_timeout_seconds"])
                if message.get("id") != identity or "error" in message:
                    raise RuntimeError(
                        "GPU voice worker rejected synthesis: "
                        + str(message.get("error", "protocol mismatch"))
                    )
                if message.get("provider") != "CUDAExecutionProvider":
                    raise RuntimeError("GPU voice execution provider changed")
                pcm = base64.b64decode(message["pcm"], validate=True)
                rate = int(message["sample_rate"])
                if not pcm or len(pcm) % 2 or rate <= 0:
                    raise RuntimeError("Invalid PCM audio from voice worker")
                return pcm, rate
            except BaseException:
                self.close()
                raise

    def close(self):
        process = self.process
        self.process = None
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            for stream in (process.stdin, process.stdout):
                if stream:
                    try:
                        stream.close()
                    except OSError:
                        pass
        if getattr(self, "log", None):
            self.log.close()
            self.log = None
