"""Actual Silero/endpoint clip detection on frozen speech and nonspeech probes."""

import argparse
import hashlib
import json
from pathlib import Path
import time
import numpy as np

from scripts.evaluation.audio import read
from voice_conversation.core import Endpoint
from voice_conversation.settings import ROOT, load_config
from voice_conversation.workers import Silero


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    folder = ROOT / args.output
    folder.mkdir(parents=True, exist_ok=False)
    cfg = load_config()
    source = ROOT / ".evaluation-local/component-inputs-v1/inputs.json"
    cases = json.loads(source.read_text())["cases"]
    settings = dict(cfg["vad"])
    settings["min_speech_ms"] = max(
        settings["min_speech_ms"], cfg["interruptions"]["min_speech_ms"]
    )
    rows = []
    for case in cases:
        path = ROOT / case["audio"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == case["audio_sha256"]
        audio = read(path)
        audio = np.pad(audio, (0, (-len(audio)) % 512 + 16000))
        vad = Silero(ROOT / cfg["paths"]["vad_model"], settings)
        endpoint = Endpoint(settings)
        starts = 0
        probabilities = []
        started = time.monotonic()
        for offset in range(0, len(audio) - 511, 512):
            frame = audio[offset : offset + 512]
            probability = vad(frame)
            probabilities.append(probability)
            starts += sum(
                kind == "start" for kind, _ in endpoint.feed(frame, probability)
            )
        expected = case["kind"] != "nonspeech"
        rows.append(
            {
                "case_id": case["case_id"],
                "kind": case["kind"],
                "expected_speech": expected,
                "detected_speech": starts > 0,
                "turn_starts": starts,
                "peak_probability": max(probabilities),
                "seconds": time.monotonic() - started,
            }
        )
    tp = sum(r["expected_speech"] and r["detected_speech"] for r in rows)
    fn = sum(r["expected_speech"] and not r["detected_speech"] for r in rows)
    fp = sum(not r["expected_speech"] and r["detected_speech"] for r in rows)
    tn = sum(not r["expected_speech"] and not r["detected_speech"] for r in rows)
    summary = {
        "cases": len(rows),
        "true_positive": tp,
        "false_negative": fn,
        "false_positive": fp,
        "true_negative": tn,
        "clip_recall": tp / (tp + fn),
        "clip_precision": tp / max(tp + fp, 1),
        "clip_specificity": tn / (tn + fp),
        "settings": settings,
        "input_manifest_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "scope": "Clip-level speech activation only; no human frame/boundary labels, so no frame accuracy or endpoint latency claim. Six nonspeech probes are small synthetic checks. Derived stress variants are not independent speakers.",
    }
    (folder / "results.json").write_text(json.dumps(rows, indent=2) + "\n")
    (folder / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
