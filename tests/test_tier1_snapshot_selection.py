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


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq absent")
def test_watchdog_age_check_ignores_a_fresh_non_tier1_snapshot(tmp_path: Path) -> None:
    """A stalled tier-1 job with a fresh transcript snapshot beside it: the tier-1 age check must still fail.

    The fake restic answers a --tag-filtered query with a tier-1 snapshot three days old, and an unfiltered query
    with a snapshot from now (the transcript job). The watchdog's own functions run against it.
    """

    text = (REPO / "scripts/hapax-backup-watchdog").read_text(encoding="utf-8")
    start = text.index("restic_password() {")
    end = text.index("check_qdrant_snapshots() {", start)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "hapax-secret").write_text("#!/usr/bin/env bash\necho secret\n", encoding="utf-8")
    (bin_dir / "restic").write_text(
        "#!/usr/bin/env bash\n"
        'old="$(date -u -d "3 days ago" +%Y-%m-%dT%H:%M:%SZ)"; now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"\n'
        'if [[ " $* " == *" --tag "* ]]; then echo "[{\\"id\\":\\"t1\\",\\"time\\":\\"$old\\"}]";\n'
        'else echo "[{\\"id\\":\\"tx\\",\\"time\\":\\"$now\\"}]"; fi\n',
        encoding="utf-8",
    )
    for tool in ("hapax-secret", "restic"):
        (bin_dir / tool).chmod(0o755)
    probe = tmp_path / "probe.sh"
    probe.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        f'. "{REPO}/scripts/lib/secret.sh"\n. "{LIB}"\n'
        "FAILURES=()\nlog() { :; }\n"
        + text[start:end]
        + "check_snapshot_age repo Tier1-NAS 36 entry tier1\n"
        + 'printf "%s\\n" "${FAILURES[@]}"\n',
        encoding="utf-8",
    )
    probe.chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
    result = subprocess.run([str(probe)], capture_output=True, text=True, timeout=30, env=env)
    assert result.returncode == 0, result.stderr
    assert "Tier1-NAS: latest snapshot is" in result.stdout and "h old" in result.stdout


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
    # Explicit snapshot times, so the order never rests on clock resolution.
    t1 = ("--time", "2026-09-26 03:25:00")
    restic("backup", "--host", "hapax-podium", "--tag", "tier1-local", *t1, str(dumps))
    tier1 = json.loads(restic("snapshots", "--json"))[-1]["id"]
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    (transcripts / "s.jsonl").write_text("{}\n")
    restic(
        "backup",
        "--host",
        "hapax-podium",
        "--tag",
        "tier1-transcripts",
        "--time",
        "2026-09-27 01:44:00",
        str(transcripts),
    )
    restic(
        "backup",
        "--host",
        "hapax-monocle",
        "--tag",
        "monocle-daily",
        "--time",
        "2026-09-27 02:00:00",
        str(transcripts),
    )

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


def _fake_bin(tmp_path: Path, restic_body: str) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "hapax-secret").write_text("#!/usr/bin/env bash\necho secret\n", encoding="utf-8")
    (bin_dir / "restic").write_text("#!/usr/bin/env bash\n" + restic_body, encoding="utf-8")
    for tool in ("hapax-secret", "restic"):
        (bin_dir / tool).chmod(0o755)
    return dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")


def _helper(env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", f'. "{LIB}"; tier1_latest_snapshot_id'],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq absent")
def test_helper_empty_and_error_paths(tmp_path: Path) -> None:
    # No tier-1 snapshot: nothing printed, success.
    empty = _helper(_fake_bin(tmp_path, "echo '[]'\n"))
    assert empty.returncode == 0 and empty.stdout.strip() == ""
    # restic fails: non-zero, even without pipefail in the caller.
    failed = _helper(_fake_bin(tmp_path, "exit 1\n"))
    assert failed.returncode != 0


def _watchdog_probe(tmp_path: Path, env: dict[str, str], call: str) -> subprocess.CompletedProcess:
    text = (REPO / "scripts/hapax-backup-watchdog").read_text(encoding="utf-8")
    start = text.index("restic_password() {")
    end = text.index("check_qdrant_snapshots() {", start)
    dump_start = text.index("check_postgres_dump_in_snapshot() {")
    dump_end = text.index("\n}\n", dump_start) + 3
    probe = tmp_path / "probe.sh"
    probe.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        f'. "{REPO}/scripts/lib/secret.sh"\n. "{LIB}"\n'
        "FAILURES=()\nlog() { :; }\n"
        + text[start:end]
        + text[dump_start:dump_end]
        + call
        + "\n"
        + 'printf "%s\\n" "${FAILURES[@]}"\n',
        encoding="utf-8",
    )
    probe.chmod(0o755)
    return subprocess.run([str(probe)], capture_output=True, text=True, timeout=30, env=env)


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq absent")
def test_watchdog_reports_a_restic_failure_instead_of_aborting(tmp_path: Path) -> None:
    """Under set -euo pipefail, a failing tier-1 query must become a reported failure, and the watchdog must go on
    to its remaining checks and its alert."""

    env = _fake_bin(tmp_path, "exit 1\n")
    age = _watchdog_probe(tmp_path, env, "check_snapshot_age repo Tier1-NAS 36 entry tier1")
    assert age.returncode == 0, age.stderr
    assert "cannot read tier-1 snapshots" in age.stdout
    dump = _watchdog_probe(
        tmp_path, env, "check_postgres_dump_in_snapshot repo Tier1-NAS entry tier1"
    )
    assert dump.returncode == 0, dump.stderr
    assert "cannot read tier-1 snapshots" in dump.stdout


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq absent")
def test_watchdog_gdrive_dump_check_names_the_newest_snapshot(tmp_path: Path) -> None:
    """The non-tier-1 branch (the GDrive repository): the newest snapshot by time, listed by id."""

    env = _fake_bin(
        tmp_path,
        'if [[ "$1" == snapshots ]]; then echo \'[{"id":"old","time":"2026-09-01T00:00:00Z"},'
        '{"id":"new","time":"2026-09-26T00:00:00Z"}]\'; exit 0; fi\n'
        'if [[ "$1" == ls && "$3" == new ]]; then '
        "echo '-rw- 1 1 2000000000 date /snap/postgres-all.sql'; fi\n"
        "exit 0\n",
    )
    result = _watchdog_probe(
        tmp_path, env, "check_postgres_dump_in_snapshot repo GDrive-Critical entry"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""  # no failures: it listed "new", which holds the dump
