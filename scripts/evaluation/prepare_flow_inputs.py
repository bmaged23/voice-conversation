"""Generate and freeze synthetic microphone inputs before live flow evaluation."""

import argparse, hashlib, json, wave, shutil
from pathlib import Path
import numpy as np
from voice_conversation.settings import ROOT, load_config
from voice_conversation.workers import init_tts, synthesize
from scripts.evaluation.audio import read, write, signal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("evaluation/datasets/conversation-flows-v1.json"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path(".evaluation-local/flow-inputs-v1")
    )
    parser.add_argument("--reuse", type=Path)
    args = parser.parse_args()
    source = ROOT / args.dataset
    dataset = json.loads(source.read_text())
    folder = ROOT / args.output
    folder.mkdir(exist_ok=True)
    if (folder / "inputs.json").exists():
        raise RuntimeError("Preserve frozen flow inputs")
    cfg = load_config()
    settings = dict(
        cfg["tts"],
        device="cpu",
        voice="am_michael",
        model_path=cfg["paths"]["tts_model"],
        voices_path=cfg["paths"]["tts_voices"],
    )
    init_tts(settings, ROOT)
    rows = []
    previous = {}
    if args.reuse:
        previous = {
            r["case_id"]: r
            for r in json.loads((ROOT / args.reuse).read_text())["cases"]
        }
    for session in dataset["sessions"]:
        for case in session["turns"]:
            path = folder / (case["case_id"] + ".wav")
            old = previous.get(case["case_id"])
            if (
                old
                and old["text"] == case["text"]
                and old.get("snr_db") == case.get("snr_db")
            ):
                original = ROOT / old["audio"]
                assert (
                    hashlib.sha256(original.read_bytes()).hexdigest()
                    == old["audio_sha256"]
                )
                shutil.copyfile(original, path)
                rows.append(
                    dict(
                        case,
                        session_id=session["session_id"],
                        audio=str(path.relative_to(ROOT)),
                        audio_sha256=old["audio_sha256"],
                        signal=old["signal"],
                    )
                )
                continue
            if case.get("silence_seconds"):
                write(
                    path, np.zeros(16000 * case["silence_seconds"], np.float32), 16000
                )
            else:
                pcm, rate = synthesize(case["text"])
                with wave.open(str(path), "wb") as handle:
                    handle.setnchannels(1)
                    handle.setsampwidth(2)
                    handle.setframerate(rate)
                    handle.writeframes(pcm)
            if "snr_db" in case:
                audio = read(path)
                noise = np.random.default_rng(20261025).normal(size=len(audio))
                noise = (
                    noise
                    / max(float(np.sqrt(np.mean(noise * noise))), 1e-9)
                    * float(np.sqrt(np.mean(audio * audio)))
                    / (10 ** (case["snr_db"] / 20))
                )
                write(path, audio + noise, 16000)
            rows.append(
                dict(
                    case,
                    session_id=session["session_id"],
                    audio=str(path.relative_to(ROOT)),
                    audio_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    signal=signal(read(path), 16000),
                )
            )
            print("Prepared", case["case_id"], flush=True)
    (folder / "inputs.json").write_text(
        json.dumps(
            {
                "dataset_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "input_voice": "Kokoro am_michael CPU",
                "cases": rows,
                "scope": "Synthetic microphone input. No live human microphone, room echo or accent benchmark. SNR is relative to full recording RMS.",
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
