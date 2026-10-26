# GPU container release process

The image recipe is [`deployment/docker/Dockerfile`](../../deployment/docker/Dockerfile).
It packages both isolated Python environments, production speech models, browser UI,
API and upstream notices. It does not package credentials, user recordings, local
memory or the independent evaluation model.

The [release workflow](../../.github/workflows/release.yml) separates these stages:

1. GitHub-hosted pinned installation and offline tests.
2. GitHub-hosted Linux amd64 image build, staged under an immutable GHCR digest.
3. A trusted `voca-gpu` laptop runner pulls that digest and checks the image revision.
4. The container runs offline tests, eight cloud reasoning cases, actual VAD on
   64 clips, 64 frozen ASR cases and 32 TTS phrases.
   An independent local Whisper large-v3 process scores the saved generated audio.
   Ten explicit speech-interpretation controls check valid repairs and unchanged inputs.
   Chromium runs 21 connected microphone turns against the candidate container.
5. The explicit [release policy](../../evaluation/release_policy.json) assesses
   completeness, STT WER/CER, TTS recognition agreement and conversation behavior.
6. Only after passing, a hosted runner transfers the exact digest to Docker Hub.
7. The GPU runner anonymously pulls the public digest and tests normal startup.

The laptop must be awake, Docker/WSL GPU integration running, and the registered
runner online. GitHub-hosted machines cannot access the laptop's GPU or private
frozen waveforms by themselves. Pull requests run offline tests without cloud keys;
only trusted owner pushes to main or manual releases can reach the GPU pipeline.

## Quality scope

All **21 original conversation turns** must pass, including teaching clarification
and follow-up examples. All **10 interpretation controls** must pass with zero
unwanted changes. A failed case blocks publication; teaching exemptions have been
removed. Raw STT remains unchanged for display and recognition scoring; validated
clarified-word edits alone enter chat memory. These repeatedly exposed development
cases are regression checks, not an untouched benchmark. Thresholds must not be
lowered to make a candidate pass.

Only aggregate `gate-summary.json` is uploaded publicly. Audio, raw dialogues,
provider payloads and private evaluation traces stay on the laptop. Cloud calls
consume the account allowance; a failed quota/network gate prevents publication.
Documentation-only changes run offline CI without rebuilding or republishing an
unchanged image. Workflow-file maintenance requires manual release dispatch if a
new release is needed. Release concurrency queues runs rather than cancelling them.

## Local build (not the prebuilt-image route)

From the repository root, with NVIDIA GPU container support:

```bash
docker build -f deployment/docker/Dockerfile \
  --build-arg VCS_REF="$(git rev-parse HEAD)" -t voca:local .
docker run --rm --gpus all --env-file .env \
  -p 127.0.0.1:8765:8765 voca:local
```

Open `http://localhost:8765`, allow microphone access and wait for readiness.
The cloud key and selected model need valid account access. Stop with Ctrl+C.
Production speech assets download at build time; model initialization happens at
startup. A release is verified only after its public pull/startup evidence exists.

## Image dependency and cache layout

Native installation uses the two exact environment snapshots. The image derives
its exact pins with `scripts.dependencies.prepare_container_requirements`, shares
CUDA/cuDNN versions from the qualified GPU voice snapshot, and keeps CPU/GPU ONNX
in separate interpreters. The generated lists are retained inside the image under
`/app/deployment/runtime-pins`. Sharing avoids duplicate large CUDA libraries;
all speech gates must pass with that image configuration before publication.

Dependency installation and production model downloads have separate cached layers.
Application-only edits no longer invalidate those large setup layers. Model setup
uses pinned revisions, direct release URLs and every reviewed file checksum; it
never silently replaces the human evaluation gold references.

Revision labels are applied after all build-time `RUN` steps so each commit's SHA
cannot invalidate cached dependency/model layers through the build environment.
See [Docker's ARG cache behavior](https://docs.docker.com/reference/dockerfile/#impact-on-build-caching).
The public startup check selects an ephemeral localhost port, so it does not need
to stop an interactive application already using port8765.
