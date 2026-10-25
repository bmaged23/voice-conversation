# Historical dependency lock

`uv-original.lock` preserves the repository's earlier single-environment lock.
It predates the isolated GPU TTS runtime and is not used for current installation,
CI or container builds. Use the root `requirements.txt` and `requirements/tts-gpu.txt`.
