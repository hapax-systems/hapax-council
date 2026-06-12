"""Tests for the reconcile carrier: cc-task-offer-ready rides the canary.

A1 self-binding — every edge names its live consumer. The mint/grade
machinery's live consumer is the existing cc-task-offer-ready systemd
tick (--reconcile). The tick must be fail-soft (a broken registry must
never break ready->offered promotion) and killswitch-able.

Per project convention, no shared conftest fixtures — each test builds
its own tree under ``tmp_path``.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO / "scripts"))

OFFER_READY = _REPO / "scripts" / "cc-task-offer-ready"

# ───────────────────────── helpers ──────────────────────────────────────────


def _build_env(tmp_path: Path) -> dict[str, str]:
    """Repo + registry + vault under tmp_path; env overrides for the tick."""
    repo = tmp_path / "repo"
    target = repo / "shared" / "example.py"
    target.parent.mkdir(parents=True)
    target.write_text("def healthy() -> int:\n    return 1\n", encoding="utf-8")
    sha = hashlib.sha256(target.read_bytes()).hexdigest()

    registry_path = tmp_path / "noop-canaries.yaml"
    registry_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "active_since": "2026-06",
                "platform_tiers": ["claude"],
                "templates": [
                    {
                        "id": "tpl-a",
                        "target_file": "shared/example.py",
                        "target_sha256": sha,
                        "task_id_pattern": "perf-threshold-recheck-{yyyymm}",
                        "title": "Recheck threshold handling",
                        "complaint": "Boundary handling looks off near the limit.",
                        "authority_case": "CASE-SYSTEM-INTEGRITY-20260611",
                        "parent_spec": "/vault/spec.md",
                        "priority": "p2",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    vault = tmp_path / "vault"
    (vault / "active").mkdir(parents=True)
    (vault / "closed").mkdir(parents=True)

    env = dict(os.environ)
    env.update(
        {
            "HAPAX_NOOP_CANARY_REGISTRY": str(registry_path),
            "HAPAX_NOOP_CANARY_REPO_ROOT": str(repo),
            "HAPAX_NOOP_CANARY_STATE": str(tmp_path / "state.yaml"),
            "HAPAX_NOOP_CANARY_LEDGER": str(tmp_path / "ledger" / "events.jsonl"),
        }
    )
    env.pop("HAPAX_NOOP_CANARY_OFF", None)
    return env


def _run_reconcile(tmp_path: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(OFFER_READY), "--reconcile", "--vault-root", str(tmp_path / "vault")],
        capture_output=True,
        text=True,
        cwd=str(_REPO),
        env=env,
        timeout=60,
    )


# ───────────────────────── behavior ─────────────────────────────────────────


def test_reconcile_tick_mints_current_month(tmp_path: Path) -> None:
    env = _build_env(tmp_path)
    result = _run_reconcile(tmp_path, env)

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    notes = list((tmp_path / "vault" / "active").glob("*.md"))
    assert len(notes) == 1, "reconcile tick should mint the current month's canary"
    assert "perf-threshold-recheck-" in notes[0].name


def test_reconcile_tick_killswitch(tmp_path: Path) -> None:
    env = _build_env(tmp_path)
    env["HAPAX_NOOP_CANARY_OFF"] = "1"
    result = _run_reconcile(tmp_path, env)

    assert result.returncode == 0
    assert list((tmp_path / "vault" / "active").glob("*.md")) == []


def test_reconcile_tick_fail_soft_on_broken_registry(tmp_path: Path) -> None:
    env = _build_env(tmp_path)
    Path(env["HAPAX_NOOP_CANARY_REGISTRY"]).write_text(":[ this is not yaml ]:", encoding="utf-8")
    result = _run_reconcile(tmp_path, env)

    # Promotion sweep must survive a broken canary plane.
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "noop-canary" in result.stderr.lower(), "skip should be loud on stderr, not silent"


def test_mint_cli_smoke(tmp_path: Path) -> None:
    env = _build_env(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(_REPO / "scripts" / "cc-noop-canary-mint"),
            "--registry",
            env["HAPAX_NOOP_CANARY_REGISTRY"],
            "--repo-root",
            env["HAPAX_NOOP_CANARY_REPO_ROOT"],
            "--vault-root",
            str(tmp_path / "vault"),
            "--state",
            env["HAPAX_NOOP_CANARY_STATE"],
            "--ledger",
            env["HAPAX_NOOP_CANARY_LEDGER"],
            "--month",
            "2026-06",
            "--now",
            "2026-06-15T12:00:00Z",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert (tmp_path / "vault" / "active" / "perf-threshold-recheck-202606.md").is_file()


def test_grade_cli_smoke(tmp_path: Path) -> None:
    env = _build_env(tmp_path)
    # Mint first, then grade after the deadline with nothing resolved.
    for args in (
        ["cc-noop-canary-mint", "--month", "2026-06", "--now", "2026-06-15T12:00:00Z"],
        ["cc-noop-canary-grade", "--month", "2026-06", "--now", "2026-07-20T12:00:00Z"],
    ):
        result = subprocess.run(
            [
                sys.executable,
                str(_REPO / "scripts" / args[0]),
                "--registry",
                env["HAPAX_NOOP_CANARY_REGISTRY"],
                "--repo-root",
                env["HAPAX_NOOP_CANARY_REPO_ROOT"],
                "--vault-root",
                str(tmp_path / "vault"),
                "--state",
                env["HAPAX_NOOP_CANARY_STATE"],
                "--ledger",
                env["HAPAX_NOOP_CANARY_LEDGER"],
                *args[1:],
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, f"{args[0]}: stdout={result.stdout}\nstderr={result.stderr}"

    ledger = (tmp_path / "ledger" / "events.jsonl").read_text(encoding="utf-8")
    assert "unresolved_at_deadline" in ledger
