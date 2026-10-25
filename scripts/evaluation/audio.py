"""Decode/resample audio consistently and report simple signal diagnostics."""

from pathlib import Path
import av, numpy as np, wave


def read(path, rate=16000):
    resampler = av.AudioResampler(format="fltp", layout="mono", rate=rate)
    pieces = []
    with av.open(str(path)) as container:
        for frame in container.decode(audio=0):
            pieces.extend(x.to_ndarray().reshape(-1) for x in resampler.resample(frame))
        pieces.extend(x.to_ndarray().reshape(-1) for x in resampler.resample(None))
    return (
        np.concatenate(pieces).astype(np.float32) if pieces else np.zeros(0, np.float32)
    )


def write(path, audio, rate):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())


def signal(audio, rate):
    finite = np.isfinite(audio)
    safe = np.where(finite, audio, 0)
    return {
        "seconds": len(audio) / rate,
        "samples": len(audio),
        "nonfinite_samples": int((~finite).sum()),
        "rms": float(np.sqrt(np.mean(safe * safe))) if len(audio) else 0,
        "peak": float(np.max(np.abs(safe))) if len(audio) else 0,
        "clipped_fraction": float(np.mean(np.abs(safe) >= 0.999)) if len(audio) else 0,
        "near_silence_fraction": float(np.mean(np.abs(safe) < 0.001))
        if len(audio)
        else 1,
    }
