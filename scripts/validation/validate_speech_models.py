"""Exercise real local TTS, Silero VAD and STT; no cloud calls."""

import json
import time
import wave

import numpy as np

from voice_conversation.settings import ROOT, load_settings
from voice_conversation.workers import (
    Silero,
    init_stt,
    init_tts,
    synthesize,
    transcribe,
)

if __name__ == "__main__":
    c = load_settings()
    c["tts"]["model_path"] = c["paths"]["tts_model"]
    c["tts"]["voices_path"] = c["paths"]["tts_voices"]
    c["stt"]["model_path"] = c["paths"]["stt_model"]
    init_tts(c["tts"], ROOT)
    start = time.perf_counter()
    pcm, rate = synthesize("Hello, can you help me plan my day?")
    synthesis = time.perf_counter() - start
    output = ROOT / "logs/speech-smoke.wav"
    output.parent.mkdir(exist_ok=True)
    with wave.open(str(output), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(pcm)
    audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
    resampled = np.interp(
        np.arange(0, len(audio), rate / 16000), np.arange(len(audio)), audio
    ).astype(np.float32)
    vad = Silero(ROOT / c["paths"]["vad_model"], c["vad"])
    scores = [vad(resampled[i : i + 512]) for i in range(0, len(resampled) - 511, 512)]
    init_stt(c["stt"], ROOT)
    start = time.perf_counter()
    text = transcribe(resampled)
    report = {
        "tts_seconds": round(synthesis, 3),
        "audio_seconds": len(audio) / rate,
        "vad_max_probability": max(scores),
        "stt_seconds": round(time.perf_counter() - start, 3),
        "stt_device": c["stt"]["device"],
        "transcript": text,
    }
    print(json.dumps(report, indent=2), flush=True)
    if not text or max(scores) < 0.5:
        raise SystemExit("Speech smoke test failed")
    (ROOT / "logs/speech-smoke.json").write_text(json.dumps(report, indent=2) + "\n")
