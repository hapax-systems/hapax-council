"""hapax-rag-edge — Pi-side document preprocessor for the RAG ingest path.

Watches a local staging dir for new files (PDFs, .md, .txt, images),
performs cheap preprocessing where possible, then rsyncs the processed
output to the workstation's rag-sources dir for the council ingest
agent to pick up.

Preprocessing is best-effort:
- text/markdown: passthrough
- PDF: pdftotext if installed, else passthrough
- image: passthrough (council does its own OCR)

The daemon polls the staging dir every POLL_INTERVAL_S seconds.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

POLL_INTERVAL_S = int(os.environ.get("RAG_EDGE_POLL_INTERVAL_S", "30"))
STAGING_DIR = Path(os.environ.get("RAG_EDGE_STAGING_DIR", str(Path.home() / "rag-staging")))
PROCESSED_DIR = Path(os.environ.get("RAG_EDGE_PROCESSED_DIR", str(Path.home() / "rag-processed")))
WORKSTATION_HOST = os.environ.get("RAG_EDGE_WORKSTATION_HOST", "hapax-podium.local")
WORKSTATION_PATH = os.environ.get("RAG_EDGE_WORKSTATION_PATH", "rag-sources/pi-edge/")
STATE_FILE = Path.home() / "hapax-state" / "rag-edge" / "last-run.json"


def write_state(payload: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(STATE_FILE)


def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def preprocess_one(src: Path, out_dir: Path) -> Path | None:
    """Return the processed-output path if successful, else None."""
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = src.suffix.lower()
    if suffix == ".pdf" and have("pdftotext"):
        target = out_dir / (src.stem + ".txt")
        try:
            subprocess.run(
                ["pdftotext", "-layout", str(src), str(target)],
                check=True,
                timeout=120,
                capture_output=True,
            )
            return target
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            print(f"rag-edge: pdftotext failed for {src}: {e}", file=sys.stderr)
    target = out_dir / src.name
    shutil.copy2(src, target)
    return target


def push_to_workstation() -> bool:
    if not PROCESSED_DIR.exists() or not any(PROCESSED_DIR.iterdir()):
        return True
    cmd = [
        "rsync",
        "-a",
        "--timeout=30",
        "--remove-source-files",
        f"{PROCESSED_DIR}/",
        f"hapax@{WORKSTATION_HOST}:{WORKSTATION_PATH}",
    ]
    try:
        subprocess.run(cmd, check=True, timeout=60, capture_output=True)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"rag-edge: rsync failed: {e}", file=sys.stderr)
        return False


def tick() -> dict:
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    processed = 0
    failed = 0
    for src in sorted(STAGING_DIR.iterdir()):
        if not src.is_file():
            continue
        try:
            out = preprocess_one(src, PROCESSED_DIR)
            if out:
                src.unlink()
                processed += 1
        except Exception as e:
            print(f"rag-edge: preprocess failed for {src}: {e}", file=sys.stderr)
            failed += 1
    pushed = push_to_workstation()
    return {
        "ts": time.time(),
        "processed": processed,
        "failed": failed,
        "pushed_to_workstation": pushed,
    }


def main() -> None:
    print(
        f"rag-edge: watching {STAGING_DIR} every {POLL_INTERVAL_S}s, "
        f"pushing to {WORKSTATION_HOST}:{WORKSTATION_PATH}",
        flush=True,
    )
    while True:
        result = tick()
        write_state(result)
        if result["processed"] or result["failed"]:
            print(f"rag-edge: tick {result}", flush=True)
        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()
