"""Qualify the exact container on frozen local inputs before public publication."""

import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.request

from voice_conversation.settings import ROOT


def run(command, **kwargs):
    subprocess.run(command, check=True, **kwargs)


def read(path):
    return json.loads(path.read_text())


def wait_health(port, container):
    for _ in range(180):
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=2
            ) as response:
                health = json.load(response)
            assert health["stt_device"] == health["tts_device"] == "cuda"
            return health
        except (OSError, urllib.error.URLError):
            if (
                subprocess.check_output(
                    ["docker", "inspect", "--format", "{{.State.Running}}", container],
                    text=True,
                ).strip()
                != "true"
            ):
                raise RuntimeError("Container exited before readiness")
            time.sleep(1)
    raise TimeoutError("Container startup deadline")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    policy = read(ROOT / "evaluation/release_policy.json")
    folder = ROOT / ".evaluation-local/image-gate"
    folder.mkdir(parents=True, exist_ok=False)
    output = ".evaluation-local/image-gate"
    image = json.loads(
        subprocess.check_output(["docker", "image", "inspect", args.image], text=True)
    )[0]
    if (
        image["Config"]["Labels"].get("org.opencontainers.image.revision")
        != args.source_sha
    ):
        raise ValueError("Image revision does not match evaluated source")
    if image["Architecture"] != "amd64" or image["Os"] != "linux":
        raise ValueError("Unsupported image platform")
    mounts = ["--mount", f"type=bind,src={folder},dst=/app/{output}"]
    logs = folder / "gpu-worker-logs"
    logs.mkdir()
    mounts += ["--mount", f"type=bind,src={logs},dst=/app/logs"]
    for name in ["human-inputs-v1", "component-inputs-v1"]:
        mounts += [
            "--mount",
            f"type=bind,src={ROOT / '.evaluation-local' / name},dst=/app/.evaluation-local/{name},readonly",
        ]
    base = [
        "docker",
        "run",
        "--rm",
        "--gpus",
        "all",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        *mounts,
    ]
    run([*base, args.image, "-m", "pytest", "-q"])
    run(
        [
            *base,
            "-e",
            "OLLAMA_API_KEY",
            "-e",
            "OLLAMA_BASE_URL",
            "-e",
            "OLLAMA_MODEL",
            args.image,
            "-m",
            "scripts.evaluation.evaluate_llm",
            "--output",
            output + "/llm",
        ]
    )
    run(
        [
            *base,
            args.image,
            "-m",
            "scripts.evaluation.evaluate_vad",
            "--output",
            output + "/vad",
        ]
    )
    run(
        [
            *base,
            args.image,
            "-m",
            "scripts.evaluation.evaluate_stt",
            "--beam-size",
            "3",
            "--output",
            output + "/stt",
        ]
    )
    run(
        [
            *base,
            args.image,
            "-m",
            "scripts.evaluation.evaluate_tts",
            "--stage",
            "generate",
            "--device",
            "cuda",
            "--output",
            output + "/tts",
        ]
    )
    # Recognition of generated speech is independent of the production recognizer.
    run(
        [
            str(ROOT / ".venv/bin/python"),
            "-m",
            "scripts.application.start_voice_app",
            "-m",
            "scripts.evaluation.evaluate_tts",
            "--stage",
            "audit",
            "--output",
            output + "/tts",
        ],
        cwd=ROOT,
    )
    name = "voca-gpu-qualification"
    subprocess.run(
        ["docker", "rm", "-f", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    browser_path = output + "/browser"
    try:
        run(
            [
                *base,
                "--name",
                name,
                "-d",
                "-p",
                "127.0.0.1:8767:8767",
                "-e",
                "OLLAMA_API_KEY",
                "-e",
                "OLLAMA_BASE_URL",
                "-e",
                "OLLAMA_MODEL",
                "-e",
                "VOCA_EVALUATION_HOST=0.0.0.0",
                "-e",
                "VOCA_EVALUATION_OUTPUT=" + browser_path,
                args.image,
                "-m",
                "scripts.validation.start_evaluation_server",
            ]
        )
        wait_health(8767, name)
        browser_command = [
            str(ROOT / ".venv/bin/python"),
            "-m",
            "scripts.evaluation.run_browser_flows",
            "--external-server",
            "--output",
            browser_path,
            "--dataset",
            policy["browser"]["dataset"],
            "--inputs",
            policy["browser"]["inputs"],
        ]
        # Nonzero semantic-test status is assessed against the explicit known-limitations policy below.
        result = subprocess.run(browser_command, cwd=ROOT)
        if result.returncode not in (0, 1):
            raise RuntimeError("Browser harness execution failed")
        (folder / "container.log").write_bytes(
            subprocess.check_output(["docker", "logs", name], stderr=subprocess.STDOUT)
        )
    finally:
        subprocess.run(
            ["docker", "rm", "-f", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    stt = read(folder / "stt/summary.json")
    llm = read(folder / "llm/summary.json")
    vad = read(folder / "vad/summary.json")
    tts = read(folder / "tts/generation-summary.json")
    audit = read(folder / "tts/audit/summary.json")
    browser = read(folder / "browser/summary.json")
    failures = {row["case_id"] for row in browser["failed"]}
    accepted = set(policy["browser"]["known_quality_limitations"])
    checks = {
        "llm_regressions": llm["cases"] == llm["passed"] == policy["llm"]["cases"]
        and llm["execution_errors"] == 0,
        "vad_complete": vad["cases"] == policy["vad"]["cases"],
        "vad_speech_detection": vad["false_negative"]
        <= policy["vad"]["false_negatives_max"],
        "vad_nonspeech_activation": vad["false_positive"]
        <= policy["vad"]["false_positives_max"],
        "stt_complete": stt["completed"] == policy["stt"]["cases"]
        and stt["failed"] == 0,
        "stt_human_wer": stt["human"]["wer"] <= policy["stt"]["human_wer_max"],
        "stt_human_cer": stt["human"]["cer"] <= policy["stt"]["human_cer_max"],
        "stt_stress_wer": stt["stress"]["wer"] <= policy["stt"]["stress_wer_max"],
        "tts_complete": tts["cases"] == audit["cases"] == policy["tts"]["cases"]
        and tts["failed"] == audit["failed"] == 0,
        "tts_agreement_wer": audit["agreement"]["wer"]
        <= policy["tts"]["agreement_wer_max"],
        "tts_agreement_cer": audit["agreement"]["cer"]
        <= policy["tts"]["agreement_cer_max"],
        "browser_complete": browser["completed"]
        == browser["selected"]
        == policy["browser"]["cases"],
        "browser_required_cases": not (failures - accepted),
        "browser_total_floor": browser["passed"]
        >= policy["browser"]["minimum_total_passed"],
        "no_javascript_errors": not browser["javascript_errors"],
    }
    summary = {
        "source_sha": args.source_sha,
        "image": args.image,
        "image_id": image["Id"],
        "policy": policy,
        "checks": checks,
        "passed": all(checks.values()),
        "stt": stt,
        "llm": llm,
        "vad": vad,
        "tts": tts,
        "tts_audit": audit,
        "browser": browser,
        "limitations": "Local synthetic dialogue and small public read-speech development regression. Known homophone failures remain visible. Cloud hardware excluded.",
    }
    (folder / "gate-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({"passed": summary["passed"], "checks": checks}, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
