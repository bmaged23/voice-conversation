"""Measure the deployed English recognizer on frozen human recordings and stress probes."""

import argparse, hashlib, json, statistics, time
from pathlib import Path
import numpy as np
from faster_whisper import WhisperModel
from voice_conversation.settings import ROOT, load_config
from evaluation.config import CONFIG
from scripts.evaluation.audio import read, write, signal
from scripts.evaluation.metrics import score, aggregate
from scripts.evaluation.resources import Resources


def inputs():
    target = ROOT / ".evaluation-local/component-inputs-v1"
    target.mkdir(parents=True, exist_ok=True)
    manifest = target / "inputs.json"
    if manifest.exists():
        return json.loads(manifest.read_text())["cases"]
    human = json.loads(
        (ROOT / CONFIG["fleurs"]["source_directory"] / "inputs.json").read_text()
    )["cases"]
    cases = [dict(r, kind="human") for r in human]
    for i, row in enumerate([r for r in human if r["split"] == "development"][:6]):
        audio = read(ROOT / row["audio"])
        rms = float(np.sqrt(np.mean(audio * audio)))
        noise = (
            np.random.default_rng(CONFIG["seed"] + i)
            .normal(size=len(audio))
            .astype(np.float32)
        )
        noise /= max(float(np.sqrt(np.mean(noise * noise))), 1e-9)
        for condition in ("noise20", "noise10", "quiet"):
            modified = (
                audio * 0.15
                if condition == "quiet"
                else audio + noise * rms / (10 ** (int(condition[5:]) / 20))
            )
            identity = row["case_id"] + "-" + condition
            path = target / (identity + ".wav")
            write(path, modified, 16000)
            cases.append(
                dict(
                    row,
                    case_id=identity,
                    kind="stress",
                    condition=condition,
                    audio=str(path.relative_to(ROOT)),
                    audio_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                )
            )
    rng = np.random.default_rng(CONFIG["seed"])
    count = 5 * 16000
    for identity, audio in [
        ("silence-short", np.zeros(16000)),
        ("silence-long", np.zeros(count)),
        ("quiet-constant", np.full(count, 1e-6)),
        ("white-noise-quiet", rng.normal(0, 0.001, count)),
        ("white-noise", rng.normal(0, 0.02, count)),
        ("tone", 0.05 * np.sin(2 * np.pi * 440 * np.arange(count) / 16000)),
    ]:
        path = target / (identity + ".wav")
        write(path, audio, 16000)
        cases.append(
            {
                "case_id": identity,
                "reference": "",
                "kind": "nonspeech",
                "split": "development",
                "audio": str(path.relative_to(ROOT)),
                "audio_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    manifest.write_text(
        json.dumps(
            {
                "source_sha256": hashlib.sha256(
                    (ROOT / "evaluation/datasets/human-english-v1.json").read_bytes()
                ).hexdigest(),
                "cases": cases,
                "noise_scope": "SNR computed against entire source-recording RMS, including source silence.",
            },
            indent=2,
        )
        + "\n"
    )
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--human-only", action="store_true")
    parser.add_argument("--beam-size", type=int, default=1)
    parser.add_argument(
        "--split", choices=["all", "development", "validation"], default="all"
    )
    args = parser.parse_args()
    folder = ROOT / args.output
    folder.mkdir(parents=True, exist_ok=False)
    cfg = load_config()
    cases = inputs()
    if args.human_only:
        cases = [r for r in cases if r["kind"] == "human"]
    if args.split != "all":
        cases = [r for r in cases if r["split"] == args.split]
    if args.limit:
        cases = cases[: args.limit]
    assert 0 < len(cases) <= CONFIG["maximum_component_cases"]
    (folder / "configuration.json").write_text(
        json.dumps(
            {
                "device": args.device,
                "beam_size": args.beam_size,
                "app_stt": cfg["stt"],
                "cases": [r["case_id"] for r in cases],
            },
            indent=2,
        )
        + "\n"
    )
    monitor = Resources(
        folder / "resources.jsonl", CONFIG["resource_sample_seconds"]
    ).start()
    rows = []
    try:
        begin = time.perf_counter()
        model = WhisperModel(
            str(ROOT / cfg["paths"]["stt_model"]),
            device=args.device,
            compute_type="int8_float32" if args.device == "cuda" else "int8",
            cpu_threads=cfg["stt"]["cpu_threads"],
            local_files_only=True,
        )
        load_seconds = time.perf_counter() - begin
        segments, _ = model.transcribe(
            np.zeros(16000, np.float32),
            language="en",
            beam_size=args.beam_size,
            condition_on_previous_text=False,
            vad_filter=False,
        )
        list(segments)
        with (folder / "results.jsonl").open("w") as output:
            for case in cases:
                path = ROOT / case["audio"]
                assert (
                    hashlib.sha256(path.read_bytes()).hexdigest()
                    == case["audio_sha256"]
                )
                audio = read(path)
                monitor.label = case["case_id"]
                start = time.monotonic()
                row = dict(case, signal=signal(audio, 16000))
                try:
                    segments, info = model.transcribe(
                        audio,
                        language="en",
                        beam_size=args.beam_size,
                        condition_on_previous_text=False,
                        vad_filter=False,
                    )
                    segments = list(segments)
                    row["hypothesis"] = " ".join(
                        s.text.strip() for s in segments
                    ).strip()
                    row["seconds"] = time.monotonic() - start
                    row["rtf"] = row["seconds"] / max(len(audio) / 16000, 1e-9)
                    row["metrics"] = score(case["reference"], row["hypothesis"])
                    row["segments"] = [
                        {
                            "text": s.text,
                            "start": s.start,
                            "end": s.end,
                            "avg_logprob": s.avg_logprob,
                            "no_speech_prob": s.no_speech_prob,
                        }
                        for s in segments
                    ]
                except Exception as error:
                    row["error"] = {
                        "type": type(error).__name__,
                        "message": str(error)[:300],
                    }
                row["resources"] = monitor.summary(start, time.monotonic())
                rows.append(row)
                output.write(json.dumps(row) + "\n")
                output.flush()
                print(
                    json.dumps(
                        {
                            "case": case["case_id"],
                            "wer": row.get("metrics", {}).get("wer"),
                            "seconds": row.get("seconds"),
                            "error": row.get("error"),
                        }
                    ),
                    flush=True,
                )
    finally:
        monitor.stop()
    speech = [r for r in rows if r["reference"] and "metrics" in r]
    summary = {
        "selected": len(cases),
        "completed": len(rows),
        "failed": sum("error" in r for r in rows),
        "model_load_seconds": load_seconds,
        "device": args.device,
        "human": aggregate([r for r in rows if r["kind"] == "human"]),
        "development_human": aggregate(
            [r for r in rows if r["kind"] == "human" and r["split"] == "development"]
        ),
        "validation_human": aggregate(
            [r for r in rows if r["kind"] == "human" and r["split"] == "validation"]
        ),
        "stress": aggregate([r for r in rows if r["kind"] == "stress"]),
        "nonspeech": aggregate([r for r in rows if r["kind"] == "nonspeech"]),
        "median_decode_seconds": statistics.median(r["seconds"] for r in speech),
        "median_rtf": statistics.median(r["rtf"] for r in speech),
        "resources": monitor.summary(),
        "scope": "Offline whole-recording final decode, not real-time endpoint/preview/cloud/TTS latency. Nonspeech probes bypass VAD and are not automatically live user turns. Stress variants are not independent recordings. WER/CER use lowercase NFKC and punctuation-to-space normalization with literal number spellings.",
    }
    (folder / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
