"""Render measured component comparisons; requires matplotlib only for documentation."""

import json
from pathlib import Path
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]


def main():
    folder = ROOT / "docs/evaluation/measurements"
    stt = json.loads((folder / "stt-gpu-beam1-baseline.json").read_text())
    tts = json.loads((folder / "tts-gpu-adoption.json").read_text())
    plt.rcParams.update(
        {"font.size": 11, "axes.spines.top": False, "axes.spines.right": False}
    )
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.7), constrained_layout=True)
    for axis, title, values in [
        (axes[0], "Whisper decoder · 8 paired recordings", [2.668465, 0.455393]),
        (
            axes[1],
            "Kokoro synthesis · 32 paired phrases",
            [tts["cpu_median_seconds"], tts["gpu_median_seconds"]],
        ),
    ]:
        bars = axis.bar(
            ["CPU", "GPU"], values, color=["#94a3b8", "#0f766e"], width=0.55
        )
        axis.bar_label(bars, labels=[f"{v:.3f} s" for v in values], padding=5)
        axis.set_ylim(0, max(values) * 1.25)
        axis.set_ylabel("Median warm inference time (seconds)")
        axis.set_title(title, fontsize=12)
        axis.grid(axis="y", alpha=0.15)
        axis.set_axisbelow(True)
    fig.suptitle("Voca: measured component inference, CPU versus GPU", fontsize=15)
    fig.supxlabel(
        "GTX 1660 Ti · configurations differ · not whole-conversation speedups",
        fontsize=10,
    )
    target = ROOT / "docs/evaluation/charts"
    target.mkdir(exist_ok=True)
    fig.savefig(target / "component-latency.png", dpi=180)
    fig.savefig(target / "component-latency.svg")
    plt.close(fig)
    fig, axis = plt.subplots(figsize=(10, 5), constrained_layout=True)
    labels = [
        "STT human\n40 recordings",
        "STT stress\n18 derived inputs",
        "TTS CPU / GPU\n32 phrases each",
    ]
    wer = [stt["human"]["wer"], stt["stress"]["wer"], tts["gpu_agreement"]["wer"]]
    cer = [stt["human"]["cer"], stt["stress"]["cer"], tts["gpu_agreement"]["cer"]]
    positions = list(range(3))
    for offset, values, label, color in [
        (-0.18, wer, "WER", "#0f766e"),
        (0.18, cer, "CER", "#64748b"),
    ]:
        bars = axis.bar(
            [x + offset for x in positions],
            [100 * v for v in values],
            width=0.32,
            label=label,
            color=color,
        )
        axis.bar_label(bars, labels=[f"{100 * v:.2f}%" for v in values], padding=4)
    axis.set_xticks(positions, labels)
    axis.set_ylabel("Aggregate error / agreement rate (%)")
    axis.set_ylim(0, 21)
    axis.legend(frameon=False)
    axis.set_title("Baseline recognition and independent TTS recognition agreement")
    axis.grid(axis="y", alpha=0.15)
    axis.set_axisbelow(True)
    fig.supxlabel(
        "STT: beam 1 baseline · TTS: Whisper large-v3 proxy, not human MOS", fontsize=10
    )
    fig.savefig(target / "speech-error-rates.png", dpi=180)
    fig.savefig(target / "speech-error-rates.svg")
    plt.close(fig)
    print("Rendered four measured comparison chart artifacts.")


if __name__ == "__main__":
    main()
