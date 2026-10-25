"""Evaluate the configured production cloud stream on frozen reasoning regressions."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import time
import httpx

from voice_conversation import server
from voice_conversation.settings import ROOT, load_settings


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    folder = ROOT / args.output
    folder.mkdir(parents=True, exist_ok=False)
    source = ROOT / "evaluation/datasets/reasoning-regressions-v1.json"
    dataset = json.loads(source.read_text())
    settings = load_settings()
    server.app.state.settings = settings
    rows = []
    async with httpx.AsyncClient(
        timeout=settings["llm"]["request_timeout_seconds"]
    ) as client:
        server.app.state.client = client
        for case in dataset["cases"]:
            row = {
                "case_id": case["case_id"],
                "reference_answer": case["reference_answer"],
            }
            tokens = asyncio.Queue()
            session = server.Session(None)
            messages = [
                {"role": "system", "content": settings["llm"]["system_prompt"]},
                *case["messages"],
            ]
            start = time.monotonic()
            try:
                await asyncio.wait_for(session.stream_llm(messages, tokens), timeout=45)
                fragments = []
                while not tokens.empty():
                    token = tokens.get_nowait()
                    if token is not None:
                        fragments.append(token)
                text = "".join(fragments)
                row.update(
                    answer=text,
                    seconds=time.monotonic() - start,
                    anchor_passed=bool(text.strip())
                    and any(
                        x.casefold() in text.casefold() for x in case["expected_any"]
                    ),
                )
            except Exception as error:
                row.update(error=type(error).__name__, anchor_passed=False)
            rows.append(row)
            (folder / "results.json").write_text(json.dumps(rows, indent=2) + "\n")
            print(
                json.dumps(
                    {
                        "case_id": case["case_id"],
                        "passed": row["anchor_passed"],
                        "error": row.get("error"),
                    }
                ),
                flush=True,
            )
    summary = {
        "cases": len(rows),
        "passed": sum(r["anchor_passed"] for r in rows),
        "execution_errors": sum("error" in r for r in rows),
        "model": settings["llm"]["model"],
        "think": settings["llm"]["think"],
        "temperature": settings["llm"]["temperature"],
        "dataset_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "scope": "Eight exposed development arithmetic/time regressions, configured production streaming function. Required-answer anchors are not a comprehensive semantic judge; no STT/TTS included.",
    }
    (folder / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return (
        0 if summary["passed"] == len(rows) and not summary["execution_errors"] else 1
    )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
