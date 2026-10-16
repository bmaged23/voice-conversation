# Configuration reference

Generated from `config.py`. Restart the server after editing it. Credentials remain in `.env`.

## language

`en`

## audio

| Parameter | Default |
| --- | --- |
| `input_sample_rate` | `16000` |
| `input_channels` | `1` |
| `frame_samples` | `512` |
| `input_device_id` | `None` |
| `output_device_id` | `None` |
| `echo_cancellation` | `True` |
| `noise_suppression` | `True` |
| `auto_gain_control` | `True` |
| `max_buffered_bytes` | `65536` |
| `max_websocket_message_bytes` | `65536` |

## vad

| Parameter | Default |
| --- | --- |
| `provider` | `silero` |
| `device` | `cpu` |
| `speech_threshold` | `0.5` |
| `min_speech_ms` | `200` |
| `end_of_turn_silence_ms` | `700` |
| `prefix_buffer_ms` | `300` |
| `max_utterance_seconds` | `30` |
| `intra_op_threads` | `1` |
| `inter_op_threads` | `1` |

## stt

| Parameter | Default |
| --- | --- |
| `provider` | `faster_whisper` |
| `model` | `small.en` |
| `device` | `cuda` |
| `device_index` | `0` |
| `compute_type` | `int8_float32` |
| `mode` | `rolling_window` |
| `partial_interval_ms` | `600` |
| `window_seconds` | `10` |
| `beam_size` | `1` |
| `language` | `en` |
| `cpu_threads` | `2` |

## llm

| Parameter | Default |
| --- | --- |
| `provider` | `ollama_cloud` |
| `base_url_env` | `OLLAMA_BASE_URL` |
| `api_key_env` | `OLLAMA_API_KEY` |
| `model_env` | `OLLAMA_MODEL` |
| `stream` | `True` |
| `temperature` | `0.6` |
| `max_response_tokens` | `192` |
| `history_max_turns` | `12` |
| `request_timeout_seconds` | `60` |
| `system_prompt` | `You are a warm, enthusiastic English voice companion. Speak naturally and build on what the user has already told you. Keep each reply between 25 and 45 words, with two or three complete spoken sentences. Give one practical answer, never a long menu of options. Use plain spoken prose only: no markdown, lists, bullets, headings or asterisks. Remember constraints and maintain consistency. Express excitement through lively wording without repeating praise. Never claim to have performed actions without tools that confirm them.` |
| `think` | `False` |

## tts

| Parameter | Default |
| --- | --- |
| `provider` | `kokoro_onnx` |
| `model` | `hexgrad/Kokoro-82M` |
| `device` | `cpu` |
| `language_code` | `en-us` |
| `voice` | `af_heart` |
| `speed` | `1.05` |
| `chunking.strategy` | `phrase` |
| `chunking.min_characters` | `40` |
| `chunking.max_characters` | `180` |
| `chunking.flush_timeout_ms` | `350` |
| `intra_op_threads` | `2` |
| `inter_op_threads` | `1` |

## interruptions

| Parameter | Default |
| --- | --- |
| `enabled` | `True` |
| `min_speech_ms` | `256` |
| `history_policy` | `completed_phrases_only` |

## workers

| Parameter | Default |
| --- | --- |
| `start_method` | `spawn` |
| `stt_processes` | `1` |
| `tts_processes` | `1` |
| `keep_models_loaded` | `True` |
| `warm_up_models` | `True` |
| `tts_queue_max_phrases` | `3` |
| `playback_queue_max_chunks` | `3` |
| `llm_token_queue_size` | `32` |
| `max_sessions` | `1` |

## logging

| Parameter | Default |
| --- | --- |
| `level` | `INFO` |
| `record_audio` | `False` |
| `log_transcripts` | `False` |

## server

| Parameter | Default |
| --- | --- |
| `host` | `127.0.0.1` |
| `port` | `8765` |
| `web_workers` | `1` |

## paths

| Parameter | Default |
| --- | --- |
| `models` | `models` |
| `web` | `web` |
| `cache` | `.cache/huggingface` |
| `stt_model` | `models/whisper-small.en` |
| `vad_model` | `models/silero_vad.onnx` |
| `tts_model` | `models/kokoro-v1.0.onnx` |
| `tts_voices` | `models/voices-v1.0.bin` |

## Effective behavior

- With barge-in enabled, the effective speech-start threshold is the greater of the VAD and interruption minimums: 256 ms by default.
- Frames are 32 ms long. The 700 ms silence threshold is reached after approximately 704 ms; the 300 ms prefix buffer retains 288 ms.
- The 350 ms phrase timer flushes at a safe word boundary after the minimum phrase length. It is not an end-to-end response deadline.
- Rolling previews cover the latest ten seconds; final STT decodes the complete utterance, capped at 30 seconds by default.
- Only completed assistant playback phrases enter history; a partly played phrase is omitted after interruption.
- One web worker and one session are supported. Increasing speech-process counts loads more model copies and does not automatically reduce latency.
- CPU-only TTS is implemented. Recording/logging, alternative provider adapters, and semantic turn detection are not implemented merely by changing labels.
- Default browser playback volume is 100%; the UI slider changes it for the current page. Browser microphone selection applies next session.
