import copy
import importlib.util
import os
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]


def load_config():
    spec = importlib.util.spec_from_file_location(
        "voice_user_config", ROOT / "config.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return copy.deepcopy(module.CONFIG)


def load_settings():
    config = load_config()
    secrets = {**dotenv_values(ROOT / ".env"), **os.environ}
    llm = config["llm"]
    for name in ("api_key", "model", "base_url"):
        value = secrets.get(llm[name + "_env"])
        if not value:
            raise ValueError(f"Missing setting: {llm[name + '_env']}")
        llm[name] = value
    if llm["base_url"].rstrip("/") != "https://ollama.com":
        raise ValueError("Cloud credentials may only be sent to https://ollama.com")
    if config["audio"]["input_sample_rate"] != 16000:
        raise ValueError("This implementation requires 16 kHz microphone audio")
    if config["audio"]["frame_samples"] != 512:
        raise ValueError("Silero requires 512-sample frames at 16 kHz")
    if config["audio"]["input_channels"] != 1:
        raise ValueError("Only mono microphone capture is implemented")
    if config["server"]["web_workers"] != 1 or config["workers"]["max_sessions"] != 1:
        raise ValueError("This local version supports one web worker and one session")
    if config["workers"]["start_method"] != "spawn":
        raise ValueError("GPU workers require the spawn start method")
    for key in (
        "stt_processes",
        "tts_processes",
        "tts_queue_max_phrases",
        "playback_queue_max_chunks",
        "llm_token_queue_size",
    ):
        if not isinstance(config["workers"][key], int) or config["workers"][key] < 1:
            raise ValueError(f"workers.{key} must be a positive integer")
    chunk = config["tts"]["chunking"]
    if config["tts"]["device"] == "cuda" and config["workers"]["tts_processes"] != 1:
        raise ValueError("The isolated GPU TTS runtime requires one worker")
    if not 0 < chunk["min_characters"] <= chunk["max_characters"]:
        raise ValueError("Invalid TTS phrase size limits")
    if not 0 < config["vad"]["speech_threshold"] < 1:
        raise ValueError("VAD speech_threshold must be between zero and one")
    for key in ("min_speech_ms", "end_of_turn_silence_ms", "max_utterance_seconds"):
        if config["vad"][key] <= 0:
            raise ValueError(f"vad.{key} must be positive")
    if (
        config["stt"]["partial_interval_ms"] <= 0
        or config["stt"]["window_seconds"] <= 0
        or chunk["flush_timeout_ms"] <= 0
    ):
        raise ValueError("STT intervals and TTS flush timeout must be positive")
    if config["logging"]["record_audio"] or config["logging"]["log_transcripts"]:
        raise ValueError("Live audio/transcript recording is not implemented")
    if not config["workers"]["keep_models_loaded"]:
        raise ValueError("Workers load models once; keep_models_loaded must be True")
    if config["interruptions"]["history_policy"] != "completed_phrases_only":
        raise ValueError("Only completed_phrases_only playback history is implemented")
    return config
