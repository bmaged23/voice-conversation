"""Render public configuration defaults without reading environment credentials."""

from voice_conversation.settings import ROOT, load_config


def main():
    lines = [
        "# Configuration reference",
        "",
        "Generated from `config.py`. Restart the application after editing.",
        "",
        "Credentials are loaded from `.env`; no credential values appear here.",
        "",
    ]
    for group, settings in load_config().items():
        lines += ["## " + group, "", "| Parameter | Default |", "| --- | --- |"]

        def rows(value, prefix=""):
            for key, item in value.items():
                name = prefix + key
                if isinstance(item, dict):
                    rows(item, name + ".")
                else:
                    text = str(item).replace("|", "\\|").replace("\n", " ")
                    lines.append(f"| `{name}` | `{text}` |")

        if isinstance(settings, dict):
            rows(settings)
        else:
            lines.append(f"| `{group}` | `{settings}` |")
        lines.append("")
    lines += [
        "## Effective behavior",
        "",
        "- One web worker and one session; GPU TTS requires one dedicated worker.",
        "- 512 samples at 16 kHz means 32 ms per microphone frame.",
        "- Speech start uses the greater of the VAD and interruption minimums.",
        "- Only completed playback phrases enter assistant history.",
        "- Whisper previews are rolling-window decoding, not a native streaming decoder.",
        "- CPU TTS is available by setting `tts.device` to `cpu`.",
        "- Trace capture is opt-in; normal sessions do not record content.",
        "- More workers load more model copies and do not guarantee lower latency.",
        "",
    ]
    (ROOT / "docs/parameters.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
