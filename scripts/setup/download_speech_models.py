"""Download production speech assets at reviewed revisions and verify every hash."""

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import urllib.request

from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parents[2]


def sha256(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def fetch(url, target, expected):
    if target.exists() and sha256(target) == expected:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    print(f"Downloading {target.name}", flush=True)
    request = urllib.request.Request(url, headers={"User-Agent": "Voca-model-setup"})
    with (
        urllib.request.urlopen(request, timeout=120) as source,
        temporary.open("wb") as output,
    ):
        while block := source.read(8 * 1024 * 1024):
            output.write(block)
    if sha256(temporary) != expected:
        raise ValueError(f"Checksum mismatch: {target.name}")
    temporary.replace(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        type=Path,
        help="Fixed production layout; independent of runtime tuning for image caching",
    )
    args = parser.parse_args()
    reference = json.loads((ROOT / "docs/assets/model-manifest.json").read_text())
    if args.models:
        models = ROOT / args.models
        paths = {
            "stt_model": models / "whisper-small.en",
            "vad_model": models / "silero_vad.onnx",
            "tts_model": models / "kokoro-v1.0.onnx",
            "tts_voices": models / "voices-v1.0.bin",
        }
    else:
        config = runpy.run_path(str(ROOT / "config.py"))["CONFIG"]
        models = ROOT / config["paths"]["models"]
        paths = {
            key: ROOT / config["paths"][key]
            for key in ["stt_model", "vad_model", "tts_model", "tts_voices"]
        }
    models.mkdir(parents=True, exist_ok=True)
    repo = reference["whisper_repo"]
    snapshot_download(
        repo,
        revision=reference["whisper_revision"],
        local_dir=paths["stt_model"],
        allow_patterns=[
            "model.bin",
            "config.json",
            "tokenizer.json",
            "vocabulary.*",
            "preprocessor_config.json",
        ],
    )
    files = reference["files"]
    fetch(
        f"https://raw.githubusercontent.com/snakers4/silero-vad/{reference['silero_revision']}/src/silero_vad/data/silero_vad.onnx",
        paths["vad_model"],
        files["silero_vad.onnx"]["sha256"],
    )
    for name, key in [
        ("kokoro-v1.0.onnx", "tts_model"),
        ("voices-v1.0.bin", "tts_voices"),
    ]:
        fetch(
            f"https://github.com/thewh1teagle/kokoro-onnx/releases/download/{reference['kokoro_release']}/{name}",
            paths[key],
            files[name]["sha256"],
        )
    verified = {}
    for name, metadata in files.items():
        if name.startswith("whisper-small.en/"):
            path = paths["stt_model"] / name.split("/", 1)[1]
        else:
            key = {
                "silero_vad.onnx": "vad_model",
                "kokoro-v1.0.onnx": "tts_model",
                "voices-v1.0.bin": "tts_voices",
            }[name]
            path = paths[key]
        digest = sha256(path)
        if digest != metadata["sha256"]:
            raise ValueError(f"Checksum mismatch: {name}")
        verified[str(path.relative_to(models))] = {
            "bytes": path.stat().st_size,
            "sha256": digest,
        }
    manifest = {**reference, "files": verified}
    (models / "assets.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        "Production speech assets verified against the reviewed manifest.", flush=True
    )


if __name__ == "__main__":
    main()
