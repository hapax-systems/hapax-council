"""The tier-1 snapshot must be chosen by host and tag, never as the repository's bare ``latest``.

Witnessed 2026-09-27 02:14Z: once hapax-backup-transcripts wrote tier1-transcripts snapshots into the NAS
repository, hapax-backup-gdrive-critical's ``restic ls --long latest`` read a transcript snapshot and failed with
"Tier-1 latest snapshot contains no postgres-all.sql". The repository also holds hapax-monocle's monocle-daily
snapshots. The case: a newer snapshot with a different tag (or host) exists.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LIB = REPO / "scripts" / "lib" / "tier1-snapshot.sh"
TIER1_READERS = ("scripts/hapax-backup-gdrive-critical", "scripts/hapax-backup-watchdog")


def test_no_tier1_reader_uses_a_bare_latest() -> None:
    """Every restic ls/dump against the tier-1 repository names its snapshot by the tier-1 helper."""

    offenders = []
    for rel in TIER1_READERS:
        for n, line in enumerate((REPO / rel).read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if re.search(r"\brestic\s+(ls|dump)\b.*\blatest\b", line):
                offenders.append(f"{rel}:{n}")
    assert offenders == [], f"bare `latest` against a shared repository: {offenders}"


def test_watchdog_freshness_is_filtered_to_tier1() -> None:
    text = (REPO / "scripts/hapax-backup-watchdog").read_text(encoding="utf-8")
    assert "tier1_latest_snapshot_time" in text


@pytest.mark.skipif(
    shutil.which("restic") is None or shutil.which("jq") is None, reason="restic or jq absent"
)
def test_a_newer_snapshot_with_a_different_tag_or_host_is_not_tier1(tmp_path: Path) -> None:
    env = dict(
        os.environ,
        RESTIC_REPOSITORY=str(tmp_path / "repo"),
        RESTIC_PASSWORD="test-only",
        RESTIC_CACHE_DIR=str(tmp_path / "cache"),
    )

    def restic(*args: str) -> str:
        return subprocess.run(
            ["restic", *args], env=env, capture_output=True, text=True, check=True, timeout=120
        ).stdout

    restic("init")
    dumps = tmp_path / "dumps"
    dumps.mkdir()
    (dumps / "postgres-all.sql").write_text("-- PostgreSQL database cluster dump complete\n")
    restic("backup", "--host", "hapax-podium", "--tag", "tier1-local", str(dumps))
    tier1 = json.loads(restic("snapshots", "--json"))[-1]["id"]
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    (transcripts / "s.jsonl").write_text("{}\n")
    restic("backup", "--host", "hapax-podium", "--tag", "tier1-transcripts", str(transcripts))
    restic("backup", "--host", "hapax-monocle", "--tag", "monocle-daily", str(transcripts))

    newest = max(json.loads(restic("snapshots", "--json")), key=lambda s: s["time"])["id"]
    assert newest != tier1  # the bare `latest` would now pick a snapshot without the dump

    picked = subprocess.run(
        ["bash", "-c", f'. "{LIB}"; tier1_latest_snapshot_id'],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    ).stdout.strip()
    assert picked == tier1
    listing = restic("ls", "--long", picked)
    assert "postgres-all.sql" in listing
