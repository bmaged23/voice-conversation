"""Opt-in local evaluation traces; normal sessions do not record content/audio."""

import json, time, wave
from pathlib import Path


class PipelineTrace:
    def __init__(self, settings, root, identity):
        self.enabled = settings.get("enabled", False)
        self.started = time.monotonic()
        if self.enabled:
            self.folder = Path(root) / settings["directory"] / identity
            self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.path = self.folder / "events.jsonl"
            self.path.touch(mode=0o600)

    def event(self, kind, **payload):
        if self.enabled:
            with self.path.open("a") as handle:
                handle.write(
                    json.dumps(
                        {
                            "seconds": round(time.monotonic() - self.started, 6),
                            "monotonic_seconds": time.monotonic(),
                            "event": kind,
                            **payload,
                        }
                    )
                    + "\n"
                )

    def audio(self, identity, pcm, rate, event="tts_audio", **payload):
        if not self.enabled:
            return
        path = self.folder / (identity.replace(":", "-") + ".wav")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes(pcm)
        path.chmod(0o600)
        self.event(
            event,
            id=identity,
            audio=path.name,
            sample_rate=rate,
            audio_seconds=len(pcm) / 2 / rate,
            **payload,
        )
