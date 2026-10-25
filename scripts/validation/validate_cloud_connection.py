"""Short authenticated streaming smoke test; never prints the API key."""

import json
from pathlib import Path
import time
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[2]


def main():
    env = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip("\"'")
    key = env.get("OLLAMA_API_KEY", "")
    if not key:
        raise SystemExit("Missing API key")
    results = []
    for model in ("nemotron-3-nano:30b", "gemma4:31b"):
        payload = {
            "model": model,
            "stream": True,
            "think": False,
            "messages": [
                {
                    "role": "system",
                    "content": "You are an English voice assistant. Respond in plain spoken English in no more than two short sentences.",
                },
                {
                    "role": "user",
                    "content": "I have a meeting at three tomorrow. Remind me half an hour before. What time should the reminder be? Don't actually set a reminder.",
                },
            ],
            "options": {"temperature": 0, "num_predict": 80},
        }
        request = urllib.request.Request(
            env.get("OLLAMA_BASE_URL", "https://ollama.com").rstrip("/") + "/api/chat",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": "Bearer " + key,
                "Content-Type": "application/json",
            },
        )
        start = time.perf_counter()
        first = None
        response_text = ""
        final = {}
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                for line in response:
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise ValueError("Provider returned a streaming error")
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        if first is None:
                            first = time.perf_counter() - start
                        response_text += content
                    if chunk.get("done"):
                        final = chunk
            result = {
                "model": model,
                "ok": bool(final.get("done") and response_text),
                "first_text_seconds": round(first, 3) if first is not None else None,
                "total_seconds": round(time.perf_counter() - start, 3),
                "output_tokens": final.get("eval_count"),
                "input_tokens": final.get("prompt_eval_count"),
                "response": response_text,
            }
        except urllib.error.HTTPError as exc:
            result = {"model": model, "ok": False, "http_status": exc.code}
        except Exception as exc:
            result = {"model": model, "ok": False, "error_type": type(exc).__name__}
        results.append(result)
        print(json.dumps(result), flush=True)
    out = ROOT / "logs/ollama-smoke-test.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
