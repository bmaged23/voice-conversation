# Included speech assets and upstream notices

Production speech assets are downloaded at build time using the pinned
[model manifest](../assets/model-manifest.json). The evaluation-only Whisper large-v3
model and human evaluation waveforms are not included in the public image.

| Component | Upstream source | Notice |
| --- | --- | --- |
| Whisper small.en / CTranslate2 conversion | [OpenAI Whisper](https://github.com/openai/whisper), [Systran conversion](https://huggingface.co/Systran/faster-whisper-small.en) | [MIT](licenses/whisper-MIT.txt) |
| Silero VAD | [Silero](https://github.com/snakers4/silero-vad) | [MIT](licenses/silero-MIT.txt) |
| Kokoro 82M model and voices | [Hexgrad model card](https://huggingface.co/hexgrad/Kokoro-82M), [ONNX assets](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.1) | [Apache 2.0](licenses/kokoro-Apache-2.0.txt) |
| kokoro-onnx adapter | [Source](https://github.com/thewh1teagle/kokoro-onnx) | [MIT](licenses/kokoro-onnx-MIT.txt) |
| eSpeak NG phonemization runtime | [Corresponding source and releases](https://github.com/espeak-ng/espeak-ng) | [GPL 3.0](licenses/espeak-ng-GPL-3.0.txt); see installed distribution metadata for the packaged runtime version |

Python wheels retain their upstream distribution metadata and license files inside
both environments. CUDA/cuDNN libraries are supplied by their pinned NVIDIA wheels;
their included notices and terms remain applicable. Debian runtime packages retain
notices under `/usr/share/doc`. These notices do not change upstream licenses or
confer rights to third-party recordings, cloud accounts or trademarks.

The FLEURS dataset is used only in local evaluation, under CC-BY-4.0; its source and
pinned revision are documented in the [evaluation report](../evaluation/README.md).
