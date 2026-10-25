# Local conversation API

Start the application with `python -m scripts.application.start_voice_app`, then use
`http://127.0.0.1:8765`. This API serves one browser conversation at a time.
It has no authentication and should remain bound to localhost.

| Endpoint | Purpose |
| --- | --- |
| `GET /` | Microphone conversation interface |
| `GET /health` | Readiness, configured cloud model and STT/TTS devices |
| `GET /client-config` | Browser audio framing and capture settings |
| `GET /diagnostics` | Current session flag and received frame count; no transcripts or credentials |
| `WS /ws` | Bidirectional microphone, recognition, response and playback stream |

Health becomes available after model initialization and warmup. Its device fields
report the configured devices; it does not test cloud quota or predict future requests.
FastAPI also exposes its generated OpenAPI schema at `/openapi.json`.

## WebSocket protocol

Connect to `ws://127.0.0.1:8765/ws` with an `Origin` matching the HTTP host.
An invalid origin or second active session is rejected. Wait for `ready` before
sending audio. The browser requests echo cancellation and noise suppression.

Input binary messages are exactly **512 little-endian float32 samples**, mono,
16 kHz: 2,048 bytes every 32 ms. Send normalized finite samples in order, paced
in real time. Non-finite frames are discarded; incorrectly sized frames produce
an error. A complete WAV file is not a valid microphone packet.

Input JSON control messages:

```json
{"type":"played","id":"1:1","complete":true}
```

Acknowledge every audio chunk after playback. Send `complete:false` when playback
was interrupted. Completed phrases enter assistant history; unplayed phrases do
not. Missing acknowledgements apply backpressure and can stall further audio.
To end the conversation, send `{"type":"stop"}` or close the connection.

Output JSON types:

| Type | Payload / handling |
| --- | --- |
| `ready` | `model`, `audio`; capture can begin |
| `partial` | `text`; rolling local recognition preview |
| `final` | `text`; finalized user transcript |
| `token` | `text`, `turn`; streamed cloud response text |
| `audio` | `id`, `turn`, `sample_rate`, `pcm`; base64 mono signed little-endian PCM16 |
| `interrupt` | `turn`; immediately stop playback and discard audio from older turns |
| `status` | `text`; interface status |
| `latency` | `seconds`; time from end-of-turn detection to first audio emission |
| `error` | `text`; show failure and permit another turn when the socket remains open |

Decode `audio.pcm` as raw PCM16 at its supplied sample rate, rather than as a WAV
container. Preserve order within a turn, acknowledge actual playback, and ignore
stale turns. The shipped browser implements this protocol.

Finalized text and recent conversation history go to Ollama Cloud. Local speech
models process audio. Normal sessions do not record content; synthetic evaluation
can explicitly enable private traces. This is a local streaming application API,
not a multi-user hosted service or an OpenAI-compatible STT/TTS endpoint.
