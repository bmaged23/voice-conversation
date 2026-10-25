"""Export exact distributions installed in the current interpreter."""

from importlib.metadata import distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

if __name__ == "__main__":
    packages = {}
    for dist in distributions():
        name = dist.metadata.get("Name", "").lower().replace("_", "-")
        if name and name != "voice-conversation":
            packages[name] = dist.version
    lines = [f"{name}=={version}" for name, version in sorted(packages.items())]
    header = (
        "# Exact installed environment: Python 3.12, Linux x86_64.\n"
        "# Includes runtime, CUDA libraries, browser QA and test tools.\n"
        "# Regenerate: .venv/bin/python scripts/dependencies/export_installed_versions.py\n"
    )
    (ROOT / "requirements.txt").write_text(header + "\n".join(lines) + "\n-e .\n")
    print(f"Exported {len(lines)} exact package pins plus the editable project.")
