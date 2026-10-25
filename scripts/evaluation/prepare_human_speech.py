"""Freeze a balanced FLEURS English subset before inference; preserve references/hashes."""

import csv, hashlib, io, json, random, tarfile, urllib.request
from pathlib import Path
from voice_conversation.settings import ROOT
from evaluation.config import CONFIG


def main():
    cfg = CONFIG["fleurs"]
    folder = ROOT / cfg["source_directory"]
    folder.mkdir(parents=True, exist_ok=True)
    if (folder / "inputs.json").exists():
        raise RuntimeError("Frozen inputs already exist; do not silently reselect them")
    base = f"https://huggingface.co/datasets/{cfg['repository']}/resolve/{cfg['revision']}/data/{cfg['language']}"
    with urllib.request.urlopen(base + "/test.tsv", timeout=60) as response:
        table = response.read()
    (folder / "source-test.tsv").write_bytes(table)
    unique = {}
    for row in csv.reader(
        io.StringIO(table.decode()), delimiter="\t", quoting=csv.QUOTE_NONE
    ):
        if not row:
            continue
        if len(row) != 7:
            raise ValueError("Unexpected FLEURS transcript columns")
        unique.setdefault(row[0], row)
    rng = random.Random(CONFIG["seed"])
    selected = []
    for gender in ("MALE", "FEMALE"):
        pool = [row for row in unique.values() if row[6] == gender]
        rows = rng.sample(pool, cfg["examples_per_gender"])
        for i, row in enumerate(rows):
            selected.append(
                {
                    "case_id": "fleurs-en-" + row[0],
                    "source_file": row[1],
                    "reference": row[2],
                    "gender": gender,
                    "split": "validation"
                    if i < cfg["validation_per_gender"]
                    else "development",
                }
            )
    names = {row["source_file"] for row in selected}
    (folder / "selection.json").write_text(
        json.dumps({"source": cfg, "seed": CONFIG["seed"], "cases": selected}, indent=2)
        + "\n"
    )
    # Stream the compressed archive; only selected WAV files are written to disk.
    print(
        "Streaming the pinned English test archive; retaining",
        len(names),
        "recordings.",
        flush=True,
    )
    with urllib.request.urlopen(base + "/audio/test.tar.gz", timeout=120) as response:
        with tarfile.open(fileobj=response, mode="r|gz") as archive:
            for member in archive:
                filename = Path(member.name).name
                if member.isfile() and filename in names:
                    data = archive.extractfile(member).read()
                    target = folder / filename
                    target.write_bytes(data)
                    row = next(r for r in selected if r["source_file"] == filename)
                    row.update(
                        audio=str(target.relative_to(ROOT)),
                        audio_sha256=hashlib.sha256(data).hexdigest(),
                    )
                    names.remove(filename)
                    print("Retained", filename, flush=True)
                    if not names:
                        break
    if names:
        raise RuntimeError("Missing selected files: " + repr(sorted(names)))
    public = {
        "source": cfg,
        "seed": CONFIG["seed"],
        "cases": [{k: v for k, v in r.items() if k != "audio"} for r in selected],
        "scope": "40 balanced read-speech clips, 20 development/20 validation; unique sentence IDs across splits. Selection fixed before model inference. This small public subset is not a general benchmark ranking.",
    }
    reference_path = ROOT / "evaluation/datasets/human-english-v1.json"
    expected = json.loads(reference_path.read_text())
    for field in ("source", "seed", "cases"):
        if expected[field] != public[field]:
            raise ValueError(
                f"Frozen human reference mismatch in {field}; refusing to rewrite the gold dataset"
            )
    (folder / "inputs.json").write_text(
        json.dumps({"source": cfg, "seed": CONFIG["seed"], "cases": selected}, indent=2)
        + "\n"
    )
    print("Frozen 40 human recordings and reference transcripts.", flush=True)


if __name__ == "__main__":
    main()
