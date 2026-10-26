# Configuration reference

Generated from `config.py`. Restart the application after editing.

Credentials are loaded from `.env`; no credential values appear here.

## language

| Parameter | Default |
| --- | --- |
| `language` | `en` |

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
| `max_queued_frames` | `125` |
| `transport_poll_ms` | `8` |
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
| `beam_size` | `3` |
| `language` | `en` |
| `cpu_threads` | `2` |
| `preview_beam_size` | `1` |
| `preview_max_tokens` | `48` |

## llm

| Parameter | Default |
| --- | --- |
| `provider` | `ollama_cloud` |
| `base_url_env` | `OLLAMA_BASE_URL` |
| `api_key_env` | `OLLAMA_API_KEY` |
| `model_env` | `OLLAMA_MODEL` |
| `stream` | `True` |
| `temperature` | `0` |
| `max_response_tokens` | `192` |
| `history_max_turns` | `12` |
| `request_timeout_seconds` | `60` |
| `first_content_timeout_seconds` | `15` |
| `idle_content_timeout_seconds` | `15` |
| `system_prompt` | `You are a friendly English voice companion. Answer the latest request directly. Use plain spoken prose without markdown or lists. Usually use one to three short sentences, but include all requested facts even when that takes longer. In summaries preserve people, places, times, numbers, causes and negations; do not replace an event with a different event. A follow-up question does not change earlier facts. Recognize questions from wording even without punctuation. The input comes from speech recognition and may contain homophones. Spelling in the transcript is not authoritative. When the user supplies a definition, use that definition to identify the intended word and explain any likely transcription error. If a requested word comparison repeats the same spelling, explain that the transcription may be ambiguous and ask which spellings the user means; you may suggest a likely intended pair, clearly as a question. Keep corrections and constraints consistent across turns. Follow exact-repeat requests exactly. Never claim to perform actions without confirming tools.` |
| `think` | `False` |

## interpretation

| Parameter | Default |
| --- | --- |
| `enabled` | `True` |
| `think` | `True` |
| `max_response_tokens` | `1024` |
| `timeout_seconds` | `8` |
| `max_input_characters` | `1600` |
| `max_word_edits` | `4` |
| `spelling_question` | `Could you spell the words you mean so I can explain the right distinction?` |
| `system_prompt` | `First check whether each observed word already has the supplied part of speech and meaning, including less common dictionary senses. If it does, leave it unchanged. Do not substitute a more common homophone for a valid source sense. You repair word identity in automatic English speech transcripts after the speaker supplies a meaning or spelling. Treat the supplied meaning as the intended meaning, not as a mistake to lecture about. If a recognized word conflicts with that meaning, identify the intended English word. Preserve legitimate noun/verb senses of the same word. Make only minimal single-word substitutions. Never change definitions, numbers, names, or other instructions. Do not guess without evidence. Return only JSON: {"edits":[{"token_index":0,"source":"heardword","replacement":"intendedword"}],"needs_clarification":false}. Indices refer to the provided indexed word tokens. Empty edits means no spelling repair. If intent is genuinely unresolved, set needs_clarification true. No explanations or markdown.` |

## tts

| Parameter | Default |
| --- | --- |
| `provider` | `kokoro_onnx` |
| `model` | `hexgrad/Kokoro-82M` |
| `device` | `cuda` |
| `runtime_python` | `.venv-tts-gpu/bin/python` |
| `startup_timeout_seconds` | `180` |
| `request_timeout_seconds` | `30` |
| `cuda.gpu_mem_limit` | `805306368` |
| `cuda.arena_extend_strategy` | `kSameAsRequested` |
| `cuda.cudnn_conv_algo_search` | `HEURISTIC` |
| `cuda.do_copy_in_default_stream` | `True` |
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
| `pipeline_trace.enabled` | `False` |
| `pipeline_trace.directory` | `.evaluation-local/pipeline-traces` |

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

- One web worker and one session; GPU TTS requires one dedicated worker.
- 512 samples at 16 kHz means 32 ms per microphone frame.
- Speech start uses the greater of the VAD and interruption minimums.
- Only completed playback phrases enter assistant history.
- Whisper previews are rolling-window decoding, not a native streaming decoder.
- CPU TTS is available by setting `tts.device` to `cpu`.
- Trace capture is opt-in; normal sessions do not record content.
- More workers load more model copies and do not guarantee lower latency.
