"""Model instances live in separate spawned processes, never reloaded per turn."""
import os
from pathlib import Path

import numpy as np

_model = None
_settings = None


class KokoroSession:
    """kokoro-onnx 0.4.9 assumes integer speed for input_ids exports.

    The pinned v1.1 graph instead declares float speed. Respect the graph's
    schema without changing third-party code or truncating fractional speeds.
    """
    def __init__(self, session):
        self.session = session
        speed = next(item for item in session.get_inputs() if item.name == "speed")
        self.speed_dtype = {"tensor(float)": np.float32, "tensor(int32)": np.int32}[speed.type]

    def __getattr__(self, name):
        return getattr(self.session, name)

    def run(self, outputs, inputs):
        inputs = dict(inputs)
        # Pass through the caller's intended speed; see synthesize().
        inputs["speed"] = np.asarray([self.speed], dtype=self.speed_dtype)
        return self.session.run(outputs, inputs)


def init_stt(settings, root):
    global _model, _settings
    from faster_whisper import WhisperModel
    _settings = settings
    _model = WhisperModel(str(Path(root) / settings["model_path"]),
                         device=settings["device"], device_index=settings["device_index"],
                         compute_type=settings["compute_type"], cpu_threads=settings["cpu_threads"],
                         local_files_only=True)


def transcribe(audio):
    segments, _ = _model.transcribe(audio, language="en", beam_size=_settings["beam_size"],
                                    vad_filter=False, condition_on_previous_text=False)
    return " ".join(s.text.strip() for s in segments).strip()


def init_tts(settings, root):
    global _model, _settings
    import onnxruntime as ort
    from kokoro_onnx import Kokoro
    _settings = settings
    options = ort.SessionOptions()
    options.intra_op_num_threads = settings["intra_op_threads"]
    options.inter_op_num_threads = settings["inter_op_threads"]
    providers = ["CPUExecutionProvider"]
    if settings["device"] != "cpu":
        raise ValueError("This build uses CPU Kokoro; GPU TTS needs a separate ONNX GPU environment")
    root = Path(root)
    session = ort.InferenceSession(str(root / settings["model_path"]), options, providers=providers)
    _model = Kokoro.from_session(session, str(root / settings["voices_path"]))
    _model.sess = KokoroSession(session)
    _model.sess.speed = settings["speed"]


def synthesize(text):
    audio, sample_rate = _model.create(text, voice=_settings["voice"],
                                       speed=_settings["speed"], lang=_settings["language_code"])
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
    return pcm, sample_rate


def ready():
    return _model is not None


def warmup_stt():
    transcribe(np.zeros(16000, dtype=np.float32))
    return True


def warmup_tts():
    synthesize("Ready.")
    return True


class Silero:
    """ONNX recurrent state for one 16 kHz microphone stream (512 samples/call)."""
    def __init__(self, path, settings=None):
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = (settings or {}).get("intra_op_threads", 1)
        options.inter_op_num_threads = (settings or {}).get("inter_op_threads", 1)
        self.session = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.context = np.zeros((1, 64), dtype=np.float32)

    def __call__(self, frame):
        audio = np.concatenate((self.context, frame.reshape(1, 512)), axis=1)
        output, self.state = self.session.run(None, {"input": audio,
                    "state": self.state, "sr": np.array(16000, dtype=np.int64)})
        self.context = audio[:, -64:]
        return float(output[0][0])
