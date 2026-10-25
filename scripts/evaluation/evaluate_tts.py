"""Generate fixed English TTS cases and independently score saved audio in a separate stage."""

import argparse, hashlib, json, statistics, time, wave
from pathlib import Path
import numpy as np
from voice_conversation.settings import ROOT, load_config
from evaluation.config import CONFIG
from scripts.evaluation.audio import read, signal
from scripts.evaluation.metrics import score, aggregate
from scripts.evaluation.resources import Resources


def generate(args, folder):
    from voice_conversation.workers import init_tts, synthesize

    cfg = load_config()
    settings = dict(cfg["tts"])
    settings.update(
        device=args.device,
        model_path=cfg["paths"]["tts_model"],
        voices_path=cfg["paths"]["tts_voices"],
    )
    dataset = ROOT / "evaluation/datasets/tts-english-v1.json"
    cases = json.loads(dataset.read_text())["cases"]
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "audio").mkdir()
    (folder / "configuration.json").write_text(
        json.dumps(
            {
                "device": args.device,
                "tts": settings,
                "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
            },
            indent=2,
        )
        + "\n"
    )
    rows = []
    monitor = Resources(folder / "generation-resources.jsonl").start()
    try:
        start = time.monotonic()
        init_tts(settings, ROOT)
        load_seconds = time.monotonic() - start
        synthesize("The voice is ready for a short conversation.")
        with (folder / "generation.jsonl").open("w") as output:
            for case in cases:
                row = dict(case)
                monitor.label = case["case_id"]
                begin = time.monotonic()
                try:
                    pcm, rate = synthesize(case["text"])
                    elapsed = time.monotonic() - begin
                    path = folder / "audio" / (case["case_id"] + ".wav")
                    with wave.open(str(path), "wb") as handle:
                        handle.setnchannels(1)
                        handle.setsampwidth(2)
                        handle.setframerate(rate)
                        handle.writeframes(pcm)
                    audio = np.frombuffer(pcm, "<i2").astype(np.float32) / 32768
                    row.update(
                        audio=str(path.relative_to(ROOT)),
                        audio_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                        signal=signal(audio, rate),
                        seconds=elapsed,
                        rtf=elapsed / (len(audio) / rate),
                    )
                except Exception as error:
                    row["error"] = {
                        "type": type(error).__name__,
                        "message": str(error)[:300],
                    }
                row["resources"] = monitor.summary(begin, time.monotonic())
                rows.append(row)
                output.write(json.dumps(row) + "\n")
                output.flush()
                print(
                    json.dumps(
                        {
                            "case": case["case_id"],
                            "seconds": row.get("seconds"),
                            "error": row.get("error"),
                        }
                    ),
                    flush=True,
                )
    finally:
        monitor.stop()
    valid = [r for r in rows if "seconds" in r]
    summary = {
        "cases": len(rows),
        "failed": len(rows) - len(valid),
        "model_load_seconds": load_seconds,
        "device": args.device,
        "median_seconds": statistics.median(r["seconds"] for r in valid),
        "median_rtf": statistics.median(r["rtf"] for r in valid),
        "resources": monitor.summary(),
        "scope": "Warm serial synthesis of fixed bounded phrases; first model load reported separately. Does not include ASR/cloud/browser playback.",
    }
    (folder / "generation-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )


def audit(args, folder):
    from faster_whisper import WhisperModel

    cases = [
        json.loads(s) for s in (folder / "generation.jsonl").read_text().splitlines()
    ]
    cases = [r for r in cases if "error" not in r]
    target = folder / "audit"
    target.mkdir(exist_ok=False)
    settings = CONFIG["independent_asr"]
    monitor = Resources(target / "resources.jsonl").start()
    rows = []
    try:
        model = WhisperModel(
            str(ROOT / settings["model_path"]),
            device=settings["device"],
            compute_type=settings["compute_type"],
            cpu_threads=2,
            local_files_only=True,
        )
        with (target / "results.jsonl").open("w") as output:
            for case in cases:
                monitor.label = case["case_id"]
                path = ROOT / case["audio"]
                assert (
                    hashlib.sha256(path.read_bytes()).hexdigest()
                    == case["audio_sha256"]
                )
                row = dict(case)
                start = time.monotonic()
                try:
                    segments, _ = model.transcribe(
                        read(path),
                        language="en",
                        beam_size=settings["beam_size"],
                        condition_on_previous_text=False,
                        vad_filter=False,
                    )
                    row["hypothesis"] = " ".join(
                        s.text.strip() for s in segments
                    ).strip()
                    row["metrics"] = score(case["text"], row["hypothesis"])
                    row["audit_seconds"] = time.monotonic() - start
                except Exception as error:
                    row["error"] = {
                        "type": type(error).__name__,
                        "message": str(error)[:300],
                    }
                rows.append(row)
                output.write(json.dumps(row) + "\n")
                output.flush()
                print(
                    json.dumps(
                        {
                            "case": case["case_id"],
                            "wer": row.get("metrics", {}).get("wer"),
                            "error": row.get("error"),
                        }
                    ),
                    flush=True,
                )
    finally:
        monitor.stop()
    summary = {
        "cases": len(rows),
        "failed": sum("error" in r for r in rows),
        "agreement": aggregate(rows),
        "resources": monitor.summary(),
        "scope": "Known-language Whisper large-v3 agreement with synthesis text. Not human listening/MOS, not proof which model caused discrepancies. Literal numbers and abbreviations can differ.",
    }
    (target / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["generate", "audit"], required=True)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    folder = ROOT / args.output
    generate(args, folder) if args.stage == "generate" else audit(args, folder)


if __name__ == "__main__":
    main()
