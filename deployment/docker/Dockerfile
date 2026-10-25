# syntax=docker/dockerfile:1
FROM python:3.12.15-slim-bookworm AS application
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 HF_HOME=/app/.cache/huggingface \
    PATH=/app/.venv/bin:$PATH
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
COPY requirements/tts-gpu.txt ./requirements/tts-gpu.txt
COPY scripts/__init__.py ./scripts/__init__.py
COPY scripts/dependencies ./scripts/dependencies
# Cache the large environments independently of application/source edits.
RUN python -m scripts.dependencies.prepare_container_requirements --output /tmp/runtime-pins && \
    python -m venv .venv && \
    .venv/bin/python -m pip install --no-cache-dir --no-deps -r /tmp/runtime-pins/main.txt && \
    python -m venv .venv-tts-gpu && \
    .venv-tts-gpu/bin/python -m pip install --no-cache-dir --no-deps -r /tmp/runtime-pins/voice.txt && \
    mkdir -p deployment/runtime-pins && cp /tmp/runtime-pins/*.txt deployment/runtime-pins/
# Only asset provisioning inputs invalidate the production-model layer.
COPY scripts/__init__.py ./scripts/__init__.py
COPY scripts/setup ./scripts/setup
COPY docs/assets/model-manifest.json ./docs/assets/model-manifest.json
RUN .venv/bin/python -m scripts.setup.download_speech_models --models models && \
    rm -rf .cache models/whisper-small.en/.cache
COPY pyproject.toml ./
COPY src ./src
RUN .venv/bin/python -m pip install --no-cache-dir --no-deps -e . && \
    .venv/bin/python -m pip check
COPY config.py ./
COPY scripts ./scripts
COPY web ./web
COPY docs ./docs
COPY evaluation ./evaluation
COPY tests ./tests
RUN useradd --uid 10001 --create-home voca && \
    mkdir -p logs .cache && chown -R voca:voca logs .cache && \
    .venv/bin/python -m pytest -q
# Keep changing revision metadata out of all dependency/model RUN environments.
ARG VCS_REF=development
LABEL org.opencontainers.image.source="https://github.com/bmaged23/voice-conversation" \
      org.opencontainers.image.title="Voca — English speech-to-speech conversation" \
      org.opencontainers.image.revision=$VCS_REF
USER voca
EXPOSE 8765
HEALTHCHECK --interval=15s --timeout=5s --start-period=180s --retries=3 \
    CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=4)"]
ENTRYPOINT ["/app/.venv/bin/python", "-m", "scripts.application.start_voice_app"]
CMD ["-m", "uvicorn", "voice_conversation.server:app", "--host", "0.0.0.0", "--port", "8765", "--workers", "1", "--ws-max-size", "65536", "--no-access-log"]
