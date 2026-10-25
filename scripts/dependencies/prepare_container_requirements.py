"""Derive exact image pins while sharing the tested CUDA libraries between runtimes."""

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def pins(path):
    result = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line == "-e .":
            continue
        name, version = line.split("==")
        if name in result and result[name] != version:
            raise ValueError(f"Conflicting pins for {name}")
        result[name] = version
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main = pins(ROOT / "requirements.txt")
    voice = pins(ROOT / "requirements/tts-gpu.txt")
    for name in list(voice):
        if name.startswith("nvidia-"):
            if name not in main:
                raise ValueError(
                    f"CUDA dependency not present in application runtime: {name}"
                )
            main[name] = voice.pop(name)
    if "onnxruntime-gpu" in main or "onnxruntime" in voice:
        raise ValueError("CPU and GPU ONNX distributions must remain isolated")
    args.output.mkdir(parents=True, exist_ok=True)
    for name, packages in [("main.txt", main), ("voice.txt", voice)]:
        (args.output / name).write_text(
            "".join(f"{key}=={value}\n" for key, value in sorted(packages.items()))
        )
    print(
        "Derived exact main/voice image pins; voice runtime shares the qualified CUDA library versions."
    )


if __name__ == "__main__":
    main()
