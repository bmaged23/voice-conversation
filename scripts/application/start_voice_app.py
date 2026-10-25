"""Start localhost server with project-local CUDA libraries on Linux."""

import os
from pathlib import Path
import sys
import runpy

ROOT = Path(__file__).resolve().parents[2]

if __name__ == "__main__":
    config = runpy.run_path(str(ROOT / "config.py"))["CONFIG"]
    env = os.environ.copy()
    env["HF_HOME"] = str(ROOT / config["paths"]["cache"])
    # The isolated voice interpreter owns its compatible CUDA/cuDNN versions.
    # Shared libraries missing there are supplied by the application environment.
    roots = list(dict.fromkeys([Path(sys.prefix), ROOT / ".venv"]))
    libraries = [
        p
        for runtime in roots
        for p in (runtime / "lib").glob("python*/site-packages/nvidia/*/lib")
    ]
    env["LD_LIBRARY_PATH"] = (
        ":".join(str(p) for p in libraries) + ":" + env.get("LD_LIBRARY_PATH", "")
    )
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "voice_conversation.server:app",
        "--host",
        config["server"]["host"],
        "--port",
        str(config["server"]["port"]),
        "--workers",
        str(config["server"]["web_workers"]),
        "--log-level",
        config["logging"]["level"].lower(),
        "--ws-max-size",
        str(config["audio"]["max_websocket_message_bytes"]),
        "--no-access-log",
    ]
    if len(sys.argv) > 1:
        command = [sys.executable, *sys.argv[1:]]
    os.chdir(ROOT)
    # Preserve SIGTERM/SIGINT delivery when this launcher is container PID 1.
    os.execvpe(command[0], command, env)
