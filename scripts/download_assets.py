"""Download local speech assets and record revisions and SHA256 hashes."""
import hashlib
import json
from pathlib import Path
import urllib.request
import runpy

from huggingface_hub import HfApi, snapshot_download

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def fetch(url, target, expected=None):
    if target.exists() and expected and sha256(target) == expected:
        return
    temporary = target.with_suffix(target.suffix + ".part")
    print(f"Downloading {target.name}", flush=True)
    with urllib.request.urlopen(url, timeout=120) as source, temporary.open("wb") as output:
        while block := source.read(8 * 1024 * 1024):
            output.write(block)
    if expected and sha256(temporary) != expected:
        raise ValueError(f"Checksum mismatch: {target.name}")
    temporary.replace(target)


def github_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "voice-conversation-research"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def main():
    config = runpy.run_path(str(ROOT / "config.py"))["CONFIG"]
    paths = config["paths"]
    models = ROOT / paths["models"]
    models.mkdir(parents=True, exist_ok=True)
    manifest_path = models / "assets.json"
    reference_path = ROOT / "docs/assets/model-manifest.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text())
    elif reference_path.exists():
        previous = json.loads(reference_path.read_text())
    else:
        previous = {}
    repo = "Systran/faster-whisper-small.en"
    revision = previous.get("whisper_revision") or HfApi().model_info(repo).sha
    snapshot_download(repo, revision=revision, local_dir=ROOT / paths["stt_model"],
                      allow_patterns=["model.bin", "config.json", "tokenizer.json", "vocabulary.*", "preprocessor_config.json"])
    silero_sha = previous.get("silero_revision") or github_json(
        "https://api.github.com/repos/snakers4/silero-vad/commits/master")["sha"]
    silero_url = f"https://raw.githubusercontent.com/snakers4/silero-vad/{silero_sha}/src/silero_vad/data/silero_vad.onnx"
    files = previous.get("files", {})
    fetch(silero_url, ROOT / paths["vad_model"], files.get("silero_vad.onnx", {}).get("sha256"))
    release = github_json("https://api.github.com/repos/thewh1teagle/kokoro-onnx/releases/tags/model-files-v1.1")
    for name in ("kokoro-v1.0.onnx", "voices-v1.0.bin"):
        asset = next(asset for asset in release["assets"] if asset["name"] == name)
        expected = (asset.get("digest") or "").removeprefix("sha256:") or files.get(name, {}).get("sha256")
        destination = ROOT / paths["tts_model" if name.endswith(".onnx") else "tts_voices"]
        fetch(asset["browser_download_url"], destination, expected)
    manifest = {"whisper_repo": repo, "whisper_revision": revision,
                "silero_revision": silero_sha, "kokoro_release": release["tag_name"],
                "files": {str(p.relative_to(models)): {"bytes": p.stat().st_size, "sha256": sha256(p)}
                          for p in models.rglob("*") if p.is_file() and ".cache" not in p.parts
                          and p.name != "assets.json"}}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print("Speech assets ready; revisions and checksums saved to models/assets.json", flush=True)


if __name__ == "__main__":
    main()
