"""Internal JSON-lines GPU voice worker. Credentials are not needed or printed."""

import base64, json, os, sys
from voice_conversation import workers


def emit(value):
    print(json.dumps(value), flush=True)


def main():
    try:
        initial = json.loads(sys.stdin.readline())
        settings = initial["settings"]
        if settings["device"] != "cuda":
            raise ValueError("GPU worker requires cuda")
        workers.init_tts_model(settings, initial["root"])
        workers.warmup_tts()
        provider = workers._model.sess.session.get_providers()[0]
        if provider != "CUDAExecutionProvider":
            raise RuntimeError("CUDA provider unavailable")
        emit({"ready": True, "provider": provider, "pid": os.getpid()})
    except Exception as error:
        emit({"ready": False, "error": type(error).__name__})
        return 1
    for line in sys.stdin:
        identity = None
        try:
            request = json.loads(line)
            identity = request["id"]
            text = request["text"]
            if not isinstance(text, str) or not text.strip():
                raise ValueError("Empty voice request")
            pcm, rate = workers.synthesize(text)
            emit(
                {
                    "id": identity,
                    "provider": workers._model.sess.session.get_providers()[0],
                    "sample_rate": rate,
                    "pcm": base64.b64encode(pcm).decode(),
                }
            )
        except Exception as error:
            emit({"id": identity, "error": type(error).__name__})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
