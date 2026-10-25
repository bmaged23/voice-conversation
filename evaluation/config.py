"""Frozen evaluation selection and budgets; keep model tuning in root config.py."""

CONFIG = {
    "seed": 20261025,
    "fleurs": {
        "repository": "google/fleurs",
        "revision": "70bb2e84b976b7e960aa89f1c648e09c59f894dd",
        "language": "en_us",
        "split": "test",
        "license": "CC-BY-4.0",
        "examples_per_gender": 20,
        "validation_per_gender": 10,
        "source_directory": ".evaluation-local/human-inputs-v1",
    },
    "resource_sample_seconds": 0.5,
    "maximum_component_cases": 140,
    "maximum_browser_requests": 30,
    "independent_asr": {
        "repository": "Systran/faster-whisper-large-v3",
        "model_path": "models/evaluation/whisper-large-v3",
        "device": "cuda",
        "compute_type": "int8_float32",
        "beam_size": 5,
    },
}

BROWSER = {
    "port": 8767,
    "startup_timeout_seconds": 180,
    "turn_timeout_ms": 120000,
    "input_timeout_margin_seconds": 15,
    "idle_settle_ms": 400,
    "resource_sample_seconds": 0.5,
}
