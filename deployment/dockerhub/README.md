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

The FastAPI application exposes `/health`, `/client-config`, `/diagnostics`, `/capabilities` and
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
Explicit speech clarifications use a bounded interpretation request before chat.
The raw transcript remains visible; validated word edits enter conversation memory.
Unresolved cases ask for spelling. Valid same-word meanings and literal requests are
protected by regression controls. The gate requires all 21 original dialogue turns
and all ten interpretation controls before this version can be published.

Native component benchmarks: paired CPU/GPU Kokoro generation medians were 2.093/0.418
seconds on 32 phrases. Independent recognition transcripts were identical across the
paired outputs, with WER/CER agreement 8.52%/7.10%; this is not human MOS. The original
40-recording beam-1 STT baseline was 6.60% WER/2.80% CER; current beam-3 container
results are reported separately. Component speedups are not whole-conversation speedups.

Models and speech runtimes retain their [upstream notices](https://github.com/bmaged23/voice-conversation/blob/main/docs/notices/README.md).


## Verified release — 26 October 2026

[Passing build, GPU gate, publication and public startup](https://github.com/bmaged23/voice-conversation/actions/runs/40248465601).
Immutable image: `bmaged23/voice-conversation@sha256:9412ef12d312bc2b33a17b63e9acc0247846b941667b7c174764501aca3cf72f`.

The exact container passed **36 offline tests**, **10/10 interpretation controls**,
**8/8 reasoning cases**, **64/64 STT recordings**, **32/32 TTS generations/audits**
and **21/21 browser turns**, with zero JavaScript errors. Both previous teaching
regressions pass; all original turns are mandatory.
Human STT WER/CER: **6.60%/2.64%**. Independent TTS recognition agreement:
**8.52%/7.10%** (a proxy, not human listening quality).
First audio after recording ended: **1.75 s median / 3.72 s p95** over 19 turns.
Sampled container RAM peaked at **1,390 MiB**, whole-device VRAM at **1,375 MiB**;
CPU averaged **97%**, peaked at **288%**, where 100% is one core. Cloud hardware is excluded.
Explicit interpretation adds a separate cloud call only for matching clarifications:
six active controls took **1.68 s median**, while four controls skipped the call.
Small exposed development suites and sampled peaks are not universal guarantees.
See the linked evaluation report for historical failures, method and raw-transcript policy.
