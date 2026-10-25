"""Compare cloud models on captured development failures; never overwrite prior runs."""

import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx

from voice_conversation.settings import ROOT, load_settings


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    folder = ROOT / args.output
    folder.mkdir(parents=True, exist_ok=False)
    settings = load_settings()["llm"]
    source = ROOT / ".evaluation-local/browser-clarification-v2-full/cases"
    ids = [
        "story-input",
        "teaching-difference",
        "teaching-clarification",
        "teaching-examples",
    ]
    inputs = {
        name: json.loads((source / (name + ".json")).read_text())["hypothesis"]
        for name in ids
    }
    (folder / "inputs.json").write_text(json.dumps(inputs, indent=2) + "\n")
    rows = []
    async with httpx.AsyncClient(timeout=30) as client:
        for model in ["nemotron-3-nano:30b", "gemma4:31b"]:
            history = []
            for name in ids:
                if name in ["story-input", "teaching-difference"]:
                    history = [{"role": "system", "content": settings["system_prompt"]}]
                history.append({"role": "user", "content": inputs[name]})
                row = {"model": model, "case_id": name, "input": inputs[name]}
                start = time.monotonic()
                text = ""
                try:
                    async with client.stream(
                        "POST",
                        settings["base_url"] + "/api/chat",
                        headers={"Authorization": "Bearer " + settings["api_key"]},
                        json={
                            "model": model,
                            "messages": history,
                            "stream": True,
                            "think": False,
                            "options": {"temperature": 0, "num_predict": 192},
                        },
                    ) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line:
                                continue
                            packet = json.loads(line)
                            content = packet.get("message", {}).get("content", "")
                            if content and not text:
                                row["first_content_seconds"] = time.monotonic() - start
                            text += content
                            if packet.get("done"):
                                row["input_tokens"] = packet.get("prompt_eval_count")
                                row["output_tokens"] = packet.get("eval_count")
                                break
                    row.update(answer=text, seconds=time.monotonic() - start)
                    history.append({"role": "assistant", "content": text})
                except Exception as error:
                    row["error"] = type(error).__name__
                rows.append(row)
                (folder / "results.json").write_text(json.dumps(rows, indent=2) + "\n")
                print(json.dumps(row), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
