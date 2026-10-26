"""Live positive/negative controls for the production clarification interpreter."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import time

import httpx
from voice_conversation.interpretation import interpret_speech
from voice_conversation.settings import ROOT, load_settings


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    folder = ROOT / args.output
    folder.mkdir(parents=True, exist_ok=False)
    source = ROOT / "evaluation/datasets/speech-interpretation-v1.json"
    dataset = json.loads(source.read_text())
    settings = load_settings()
    rows = []
    async with httpx.AsyncClient(
        timeout=settings["llm"]["request_timeout_seconds"]
    ) as client:
        for case in dataset["cases"]:
            start = time.monotonic()
            result = await interpret_speech(
                case["transcript"], client, settings["llm"], settings["interpretation"]
            )
            checks = {
                "expected_text": result.text == case["expected_text"],
                "expected_uncertainty": result.needs_clarification
                == case["expected_needs_clarification"],
                "expected_status": result.status == case["expected_status"],
                "raw_preserved": result.raw_text == case["transcript"],
            }
            row = {
                "case_id": case["case_id"],
                "checks": checks,
                "passed": all(checks.values()),
                "interpretation": result.packet(),
                "seconds": time.monotonic() - start,
                "usage": result.usage,
            }
            rows.append(row)
            (folder / "results.json").write_text(json.dumps(rows, indent=2) + "\n")
            print(
                json.dumps(
                    {
                        "case_id": case["case_id"],
                        "passed": row["passed"],
                        "interpretation": result.packet(),
                    }
                ),
                flush=True,
            )
    summary = {
        "cases": len(rows),
        "passed": sum(row["passed"] for row in rows),
        "false_changes_on_unchanged_controls": sum(
            row["interpretation"]["changed"]
            for row, case in zip(rows, dataset["cases"])
            if case["transcript"] == case["expected_text"]
        ),
        "failed": [row["case_id"] for row in rows if not row["passed"]],
        "dataset_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "model": settings["llm"]["model"],
        "scope": dataset["scope"],
    }
    (folder / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return 0 if summary["passed"] == summary["cases"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
