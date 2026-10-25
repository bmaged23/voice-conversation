"""Generate machine captions from the actual MP4 audio, also checking audibility."""

import json
from pathlib import Path

from faster_whisper import WhisperModel
from voice_conversation.settings import ROOT, load_settings


def timestamp(seconds):
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}"


if __name__ == "__main__":
    c = load_settings()
    model = WhisperModel(
        str(ROOT / c["paths"]["stt_model"]),
        device=c["stt"]["device"],
        device_index=c["stt"]["device_index"],
        compute_type=c["stt"]["compute_type"],
        local_files_only=True,
    )
    segments, _ = model.transcribe(
        str(ROOT / "docs/demo/conversation-demo.mp4"),
        language="en",
        beam_size=1,
        condition_on_previous_text=False,
        vad_filter=True,
    )
    cues = [
        "WEBVTT",
        "",
        "NOTE Machine-generated captions from the recorded audio.",
        "",
    ]
    plain = []
    for index, segment in enumerate(segments, 1):
        cues += [
            str(index),
            f"{timestamp(segment.start)} --> {timestamp(segment.end)}",
            segment.text.strip(),
            "",
        ]
        plain.append(segment.text.strip())
    if not plain:
        raise SystemExit("No speech detected in the exported video")
    (ROOT / "docs/demo/captions.vtt").write_text("\n".join(cues) + "\n")
    (ROOT / "logs/demo-audio-verification.txt").write_text("\n".join(plain) + "\n")
    print("Machine caption cues:", len(plain))
    print("Recorded audio speech:", " ".join(plain), flush=True)
