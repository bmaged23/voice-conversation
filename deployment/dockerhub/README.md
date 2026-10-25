# Voca — English Speech-to-Speech Conversation

[GitHub source, demo, animated pipeline and full documentation](https://github.com/bmaged23/voice-conversation)

Speak English into your browser microphone. Whisper small.en recognizes speech locally,
Ollama Cloud Gemma 4 generates streamed replies, and GPU Kokoro speaks ordered
phrases. Silero VAD controls turn timing and voice interruption. Conversation history
keeps completed playback phrases; opening a new session starts fresh history.

## Pull and run

Requires Linux x86-64 NVIDIA GPU containers, current NVIDIA drivers, internet access
and your own Ollama Cloud allowance. Development GPU: GTX 1660 Ti with 6 GiB VRAM.
The image contains production speech models and both pinned runtime environments;
no Git clone or first-run model download is required.

Create `.env` locally:

```dotenv
OLLAMA_API_KEY=your_own_key
OLLAMA_BASE_URL=https://ollama.com
OLLAMA_MODEL=gemma4:31b
```

```bash
docker pull bmaged23/voice-conversation:gpu
docker run --rm --gpus all --env-file .env \
  -p 127.0.0.1:8765:8765 \
  bmaged23/voice-conversation:gpu
```

Wait for model warmup, open **http://localhost:8765**, allow microphone access and
start talking. Your browser owns the microphone and speakers; no audio device
passthrough is required. Speak over a reply to interrupt. Stop with Ctrl+C.

This is a localhost, single-session application. Final text and recent conversation
history go to Ollama Cloud; recognition and synthesis use the local GPU, with CPU VAD.
The cloud LLM is not included in the image, and its hardware is excluded from local
resource measurements. No API keys, private recordings or personal memory are bundled.

## Streaming API

The FastAPI application exposes `/health`, `/client-config`, `/diagnostics` and
`WS /ws` for framed microphone audio, STT text, cloud tokens, PCM speech and playback
acknowledgements. See the [API guide](https://github.com/bmaged23/voice-conversation/blob/main/docs/api/README.md).
This is not an authenticated multi-user hosted service.

## Evaluation and release

The pipeline stages a hosted build, evaluates its exact digest on a trusted GPU
runner, and publishes only after the explicit regression gate passes. The GPU gate
runs container tests, 64 ASR recordings, 32 TTS phrases with independent local
Whisper large-v3 recognition, and 21 connected browser turns. Publication is followed
by an anonymous public pull and normal GPU startup check.

See [measured results and release evidence](https://github.com/bmaged23/voice-conversation/blob/main/docs/evaluation/README.md)
and the [release policy](https://github.com/bmaged23/voice-conversation/blob/main/evaluation/release_policy.json).
Three affect/effect teaching turns are known quality limitations: small English ASR
can collapse both spellings, and the cloud model may misinterpret clarification.
These failures remain in scores. The gate requires all 18 other dialogue cases and
at least 18/21 overall; this is not a perfect language-understanding claim.

Native component benchmarks: paired CPU/GPU Kokoro generation medians were 2.093/0.418
seconds on 32 phrases. Independent recognition transcripts were identical across the
paired outputs, with WER/CER agreement 8.52%/7.10%; this is not human MOS. The original
40-recording beam-1 STT baseline was 6.60% WER/2.80% CER; current beam-3 container
results are reported separately. Component speedups are not whole-conversation speedups.

Models and speech runtimes retain their [upstream notices](https://github.com/bmaged23/voice-conversation/blob/main/docs/notices/README.md).

## Qualified release measurements

[Passing release and immutable evidence](https://github.com/bmaged23/voice-conversation/actions/runs/40223674458):
source `9ac91404ee1634c512f46e03b263fedb737277c8`, image
`bmaged23/voice-conversation@sha256:60fe05514e98ac477de8a4a9935f2ab61c6d9f880fd25c37c6c5fda94bfdc7f3`.

The final container passed 8/8 reasoning cases, VAD clip checks, 64/64 ASR executions,
32/32 TTS generations and independent audits, and 19/21 connected browser turns.
Human ASR WER/CER: **6.60%/2.64%**. TTS recognition agreement WER/CER:
**8.52%/7.10%**, a proxy rather than human listening scores.

Median first audio after recording ended: **1.99 s**; p95 **6.18 s** over 19
voice-producing turns. Sampled backend memory peak: **1,828 MiB**; whole-device VRAM
peak: **1,747 MiB**. CPU mean/peak: **110%/351%**, with 100% representing one logical
core. Cloud hardware is excluded. Measurements are from one GTX 1660 Ti setup.

Docker's reported local size is **8.51 GB**, approximately 28.5% below the earlier
11.9 GB image. Allow at least **15 GiB free disk space** for pulling/unpacking and
working headroom. This local size is distinct from compressed registry download size.
