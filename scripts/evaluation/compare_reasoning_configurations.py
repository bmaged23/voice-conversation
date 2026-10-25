"""One bounded comparative run over eight frozen arithmetic/time regressions."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import time
import httpx
from voice_conversation.settings import ROOT, load_settings


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    folder = ROOT / args.output
    folder.mkdir(parents=True, exist_ok=False)
    source = ROOT / "evaluation/datasets/reasoning-regressions-v1.json"
    dataset = json.loads(source.read_text())
    settings = load_settings()["llm"]
    rows = []
    async with httpx.AsyncClient(timeout=45) as client:
        for candidate in dataset["candidates"]:
            for case in dataset["cases"]:
                row = {
                    "candidate": candidate,
                    "case_id": case["case_id"],
                    "reference_answer": case["reference_answer"],
                }
                start = time.monotonic()
                text = ""
                done = False
                try:
                    async with asyncio.timeout(45):
                        async with client.stream(
                            "POST",
                            settings["base_url"] + "/api/chat",
                            headers={"Authorization": "Bearer " + settings["api_key"]},
                            json={
                                "model": candidate["model"],
                                "think": candidate["think"],
                                "stream": True,
                                "messages": [
                                    {
                                        "role": "system",
                                        "content": settings["system_prompt"],
                                    },
                                    *case["messages"],
                                ],
                                "options": {
                                    k: candidate[k]
                                    for k in ["temperature", "num_predict"]
                                },
                            },
                        ) as response:
                            response.raise_for_status()
                            async for line in response.aiter_lines():
                                if not line:
                                    continue
                                packet = json.loads(line)
                                content = packet.get("message", {}).get("content", "")
                                if content and not text:
                                    row["first_content_seconds"] = (
                                        time.monotonic() - start
                                    )
                                text += content
                                if packet.get("done"):
                                    done = True
                                    row["input_tokens"] = packet.get(
                                        "prompt_eval_count"
                                    )
                                    row["output_tokens"] = packet.get("eval_count")
                                    break
                    if not done or not text.strip():
                        raise RuntimeError("Incomplete or empty response")
                    row.update(answer=text, seconds=time.monotonic() - start)
                    row["anchor_passed"] = any(
                        x.casefold() in text.casefold() for x in case["expected_any"]
                    )
                except Exception as error:
                    row["error"] = type(error).__name__
                rows.append(row)
                (folder / "results.json").write_text(
                    json.dumps(
                        {
                            "dataset_sha256": hashlib.sha256(
                                source.read_bytes()
                            ).hexdigest(),
                            "rows": rows,
                        },
                        indent=2,
                    )
                    + "\n"
                )
                print(json.dumps(row), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
