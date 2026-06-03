"""Tests for scripts/coord-retro-grant-watch (reform Phase 4, NEW-2 deprecation).

The deprecation backstop for HAPAX_*_OFF: every emergency bypass records a
pending retro-grant obligation with a 1h deadline. This watcher fulfils the
obligation if a covering signed EscapeGrant landed, and ntfy-escalates if the
deadline passed with none — so the unconditional off-switch can never be used
silently and then forgotten.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "coord-retro-grant-watch"
MINT_SCRIPT = REPO_ROOT / "scripts" / "coord-grant-mint"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from shared.governance.coord_capabilities import mint_escape_grant, write_grant_file  # noqa: E402

KEY = b"test-operator-grant-key-0123456789abcdef"


def _write_obligation(
    path: Path, *, gate: str, ts_s: int, deadline_s: int, status: str = "pending", task: str = "t1"
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": "2026-05-31T00:00:00Z",
        "ts_s": ts_s,
        "deadline_s": deadline_s,
        "status": status,
        "gate": gate,
        "trigger": "HAPAX_METHODOLOGY_EMERGENCY",
        "role": "beta",
        "task": task,
        "case": "CASE-TEST-001",
        "tool": "Edit",
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(rec) + "\n")


def _run(obligations: Path, grant_dir: Path, key: Path, *, now: int) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HAPAX_COORD_RETRO_OBLIGATIONS"] = str(obligations)
    env["HAPAX_COORD_GRANT_DIR"] = str(grant_dir)
    env["HAPAX_COORD_GRANT_KEY"] = str(key)
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--dry-run", "--now", str(now)],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class TestRetroGrantWatch:
    def _setup(self, tmp_path: Path) -> tuple[Path, Path, Path]:
        obligations = tmp_path / "obligations.jsonl"
        grant_dir = tmp_path / "grants"
        grant_dir.mkdir()
        key = tmp_path / "grant-key"
        key.write_bytes(KEY)
        return obligations, grant_dir, key

    def test_overdue_unfulfilled_escalates(self, tmp_path: Path) -> None:
        obligations, grant_dir, key = self._setup(tmp_path)
        _write_obligation(obligations, gate="cc-task-gate", ts_s=1000, deadline_s=4600)
        r = _run(obligations, grant_dir, key, now=10_000)  # past deadline, no grant
        assert r.returncode == 0, f"stderr={r.stderr}"
        summary = json.loads(r.stdout)
        assert summary["escalated"] == 1
        assert _records(obligations)[-1]["status"] == "escalated"

    def test_fulfilled_when_covering_grant_landed(self, tmp_path: Path) -> None:
        obligations, grant_dir, key = self._setup(tmp_path)
        _write_obligation(obligations, gate="cc-task-gate", ts_s=1000, deadline_s=4600)
        # A retro-grant minted AFTER the obligation, covering the gate, still valid.
        grant = mint_escape_grant(
            grantor="operator",
            scope="cc-task-gate",
            reason="retro",
            ttl_s=100_000,
            key=KEY,
            now=2000.0,
        )
        write_grant_file(grant, grant_dir / f"{grant.grant_id}.grant")
        r = _run(obligations, grant_dir, key, now=10_000)
        assert r.returncode == 0, f"stderr={r.stderr}"
        summary = json.loads(r.stdout)
        assert summary["fulfilled"] == 1
        assert summary["escalated"] == 0
        assert _records(obligations)[-1]["status"] == "fulfilled"

    def test_grant_predating_obligation_does_not_fulfil(self, tmp_path: Path) -> None:
        # A grant minted BEFORE the emergency cannot retro-justify it.
        obligations, grant_dir, key = self._setup(tmp_path)
        _write_obligation(obligations, gate="cc-task-gate", ts_s=5000, deadline_s=8600)
        grant = mint_escape_grant(
            grantor="operator",
            scope="cc-task-gate",
            reason="stale",
            ttl_s=100_000,
            key=KEY,
            now=1000.0,  # issued before ts_s=5000
        )
        write_grant_file(grant, grant_dir / f"{grant.grant_id}.grant")
        r = _run(obligations, grant_dir, key, now=10_000)
        summary = json.loads(r.stdout)
        assert summary["escalated"] == 1
        assert summary["fulfilled"] == 0

    def test_not_yet_due_stays_pending(self, tmp_path: Path) -> None:
        obligations, grant_dir, key = self._setup(tmp_path)
        _write_obligation(obligations, gate="cc-task-gate", ts_s=9000, deadline_s=12_600)
        r = _run(obligations, grant_dir, key, now=10_000)  # before deadline
        summary = json.loads(r.stdout)
        assert summary["pending"] == 1
        assert summary["escalated"] == 0
        assert _records(obligations)[-1]["status"] == "pending"

    def test_already_escalated_is_idempotent(self, tmp_path: Path) -> None:
        obligations, grant_dir, key = self._setup(tmp_path)
        _write_obligation(
            obligations, gate="cc-task-gate", ts_s=1000, deadline_s=4600, status="escalated"
        )
        r = _run(obligations, grant_dir, key, now=10_000)
        summary = json.loads(r.stdout)
        assert summary["escalated"] == 0  # not re-escalated
        assert _records(obligations)[-1]["status"] == "escalated"

    def test_missing_obligations_file_is_noop(self, tmp_path: Path) -> None:
        obligations = tmp_path / "does-not-exist.jsonl"
        grant_dir = tmp_path / "grants"
        grant_dir.mkdir()
        key = tmp_path / "grant-key"
        key.write_bytes(KEY)
        r = _run(obligations, grant_dir, key, now=10_000)
        assert r.returncode == 0, f"stderr={r.stderr}"

    def test_reader_writer_parity_via_coord_base_dir(self, tmp_path: Path) -> None:
        """The watcher reads the SAME grants dir + key coord-grant-mint writes when
        only the canonical base (HAPAX_COORD_DIR) is set — both scripts resolve
        through shared.coord_event_log, not divergent /var/lib defaults.

        Before the path-unify fix the watcher's bare default was
        ``/var/lib/hapax/coord/grants`` while the mint wrote to ``<base>/grants``,
        so a freshly minted covering grant never fulfilled the obligation.
        """
        base = tmp_path / "coord"
        obligations = tmp_path / "obligations.jsonl"
        # Overdue obligation: absent a covering grant the watcher escalates.
        _write_obligation(obligations, gate="cc-task-gate", ts_s=1, deadline_s=1)

        env = os.environ.copy()
        # Only the canonical base is set — NO per-surface grant overrides — so both
        # scripts must derive <base>/grants and <base>/grant-key from it.
        for var in ("HAPAX_COORD_GRANT_DIR", "HAPAX_COORD_GRANT_KEY"):
            env.pop(var, None)
        env["HAPAX_COORD_DIR"] = str(base)

        # Writer: mint a covering grant (auto-creates the signing key under <base>).
        mint = subprocess.run(
            [
                sys.executable,
                str(MINT_SCRIPT),
                "--scope",
                "cc-task-gate",
                "--reason",
                "parity",
                "--grantor",
                "operator",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        assert mint.returncode == 0, f"mint stderr={mint.stderr}"

        # Reader: the watcher must find that grant via the same base resolution.
        env["HAPAX_COORD_RETRO_OBLIGATIONS"] = str(obligations)
        watch = subprocess.run(
            [sys.executable, str(SCRIPT), "--dry-run"],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        assert watch.returncode == 0, f"watch stderr={watch.stderr}"
        summary = json.loads(watch.stdout)
        assert summary["fulfilled"] == 1, summary
        assert summary["escalated"] == 0, summary
