"""Test normal image startup and confirm evaluation-only routes are absent."""

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    name = "voca-public-startup"
    subprocess.run(
        ["docker", "rm", "-f", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-d",
                "--gpus",
                "all",
                "--name",
                name,
                "-p",
                "127.0.0.1::8765",
                "-e",
                "OLLAMA_API_KEY",
                "-e",
                "OLLAMA_BASE_URL",
                "-e",
                "OLLAMA_MODEL",
                args.image,
            ],
            check=True,
        )
        mapping = subprocess.check_output(
            ["docker", "port", name, "8765/tcp"], text=True
        ).strip()
        port = int(mapping.rsplit(":", 1)[1])
        base = f"http://127.0.0.1:{port}"
        for _ in range(180):
            try:
                with urllib.request.urlopen(base + "/health", timeout=2) as response:
                    health = json.load(response)
                assert health["stt_device"] == health["tts_device"] == "cuda"
                break
            except OSError:
                time.sleep(1)
        else:
            raise TimeoutError("Public container readiness deadline")
        with urllib.request.urlopen(base + "/", timeout=5) as response:
            assert b"Voca" in response.read()
        try:
            urllib.request.urlopen(base + "/__qa__/usage", timeout=5)
        except urllib.error.HTTPError as error:
            assert error.code == 404
        else:
            raise AssertionError("Evaluation-only route exposed in normal startup")
        print(
            json.dumps(
                {"normal_gpu_startup": "passed", "health": health, "image": args.image}
            )
        )
    finally:
        subprocess.run(
            ["docker", "rm", "-f", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


if __name__ == "__main__":
    main()
