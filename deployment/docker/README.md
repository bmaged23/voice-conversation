# Docker — Voca GPU application

[Main README](../../README.md) · [Public Docker Hub image](https://hub.docker.com/r/bmaged23/voice-conversation) · [API README](../../docs/api/README.md) · [CI/CD README](../../docs/deployment/README.md)

The image includes the FastAPI backend, browser UI, Whisper small.en, Silero VAD,
GPU Kokoro and both pinned Python runtimes. Recognition and synthesis run locally;
Gemma runs on Ollama Cloud using your credentials. Speech assets are already in
the image, so pulling it requires neither a Git clone nor a startup model download.

## Requirements

- Linux x86-64 containers with an NVIDIA GPU exposed to Docker through `--gpus all`.
- On WSL2, working Docker Desktop WSL integration and GPU access.
- Current NVIDIA drivers; the qualified device was a GTX 1660 Ti with 6 GiB VRAM.
- Internet, an Ollama Cloud API key, model access and available account allowance.
- Allow at least 15 GiB free disk for the approximately 3 GB compressed image, unpacking and working headroom.

The published `gpu` tag is a GPU deployment. CPU-only devices and native macOS
containers were not qualified by this release.

## Pull and run — no source checkout needed

Create a private `.env` in any working folder:

```dotenv
OLLAMA_API_KEY=your_own_key
OLLAMA_BASE_URL=https://ollama.com
OLLAMA_MODEL=gemma4:31b
```

```bash
docker pull bmaged23/voice-conversation:gpu
docker run --rm --name voca --gpus all --env-file .env \
  -p 127.0.0.1:8765:8765 \
  bmaged23/voice-conversation:gpu
```

Wait for model warmup, open **http://localhost:8765**, allow microphone access and
start talking. The browser owns microphone capture and playback; audio-device
passthrough is unnecessary. Speak over a reply to interrupt it. Keep the service
on localhost: the application has one conversation session and no authentication.

Stop with Ctrl+C, or run `docker stop voca` from another terminal. `--rm` removes
the stopped container. Live chat history is held in memory and starts fresh with
a new session; no volume is needed for the default application.

## Check readiness and use the API

From another terminal:

```bash
curl --fail http://localhost:8765/health
curl --fail http://localhost:8765/capabilities
docker logs voca
```

Readiness follows speech-model initialization; it does not verify future cloud
quota. The same container serves the UI, HTTP endpoints and `ws://localhost:8765/ws`.
See the [API README](../../docs/api/README.md) for binary audio framing, events,
playback acknowledgements and interruption handling.

If the port is occupied, change the mapping to `-p 127.0.0.1:8768:8765` and use
`http://localhost:8768` instead. If GPU initialization fails, check host GPU and
Docker GPU integration before retrying. A cloud error requires checking your key,
model access, internet connection and allowance.

## Updates and immutable releases

To update, stop the old container, pull `:gpu` again and repeat the run command.
The tag advances only after the candidate's GPU quality gate passes. The workflow
then verifies anonymous public pull and normal startup; details and failure
behavior are in the [CI/CD README](../../docs/deployment/README.md).

To use the qualified 26 October 2026 version explicitly, use this image reference
in both the pull and run commands instead of `:gpu`:

```text
bmaged23/voice-conversation@sha256:9412ef12d312bc2b33a17b63e9acc0247846b941667b7c174764501aca3cf72f
```

The [evaluation report](../../docs/evaluation/README.md) records its 36 offline
tests, 21/21 browser turns, 10/10 interpretation controls, speech error rates and
sampled latency/resource usage. Measurements are from one development setup.

## Build from source

Clone the repository first, then build from its root:

```bash
git clone https://github.com/bmaged23/voice-conversation.git
cd voice-conversation
docker build -f deployment/docker/Dockerfile \
  --build-arg VCS_REF="$(git rev-parse HEAD)" -t voca:local .
docker run --rm --name voca --gpus all --env-file .env \
  -p 127.0.0.1:8765:8765 voca:local
```

Create `.env` in the checkout before the run step. Builds download pinned production
models and install dependencies; an offline-test pass during the build does not
replace the full GPU release qualification. The recipe is [Dockerfile](Dockerfile).
Private `.env` files, recordings and evaluation assets are excluded by
[.dockerignore](../../.dockerignore).
