"""Reconcile tick: mint the current month, grade the recent window.

Designed to ride an existing periodic carrier (cc-task-offer-ready
--reconcile, every 5 minutes via hapax-cc-task-offer-ready.timer) — both
mint and grade are idempotent per (month, tier), so cadence only bounds
detection latency, never duplicates work. No new systemd unit needed,
and the carrier names this edge's live consumer (A1 self-binding).
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .grade import grade_month
from .mint import mint_month
from .registry import load_registry, month_index

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = REPO_ROOT / "config" / "failure-taxonomy" / "noop-canaries.yaml"
# How many recent months each tick re-examines for undecided cells.
GRADE_WINDOW_MONTHS = 3


def _month_str(index: int) -> str:
    year, mon = divmod(index, 12)
    return f"{year:04d}-{mon + 1:02d}"


def _gh_pr_info(pr_number: str) -> dict[str, Any]:
    """Best-effort PR metrics for diff-growth tracking (A9 interaction)."""
    result = subprocess.run(
        ["gh", "pr", "view", pr_number, "--json", "reviews,additions,deletions"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    data = json.loads(result.stdout)
    return {
        "review_rounds": len(data.get("reviews") or []),
        "additions": data.get("additions"),
        "deletions": data.get("deletions"),
    }


def reconcile_vault(*, vault_root: Path, now: str | None = None) -> dict[str, Any]:
    """One tick: mint current month, grade the recent window. Raises on a
    broken canary plane — the carrier wraps this fail-soft."""
    registry_path = Path(
        os.environ.get("HAPAX_NOOP_CANARY_REGISTRY", str(DEFAULT_REGISTRY))
    ).expanduser()
    repo_root = Path(os.environ.get("HAPAX_NOOP_CANARY_REPO_ROOT", str(REPO_ROOT))).expanduser()
    state_path = Path(
        os.environ.get(
            "HAPAX_NOOP_CANARY_STATE",
            str(vault_root / "_evidence" / "noop-canary" / "state.yaml"),
        )
    ).expanduser()
    ledger_path = Path(
        os.environ.get(
            "HAPAX_NOOP_CANARY_LEDGER",
            str(vault_root / "_evidence" / "failure-ledger" / "events.jsonl"),
        )
    ).expanduser()

    now_str = now or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    registry = load_registry(registry_path)

    current_index = month_index(now_str[:7])
    first_index = max(month_index(registry.active_since), current_index - (GRADE_WINDOW_MONTHS - 1))

    minted = mint_month(
        registry,
        month=_month_str(current_index),
        repo_root=repo_root,
        vault_root=vault_root,
        state_path=state_path,
        ledger_path=ledger_path,
        now=now_str,
    )
    graded: dict[str, dict[str, str]] = {}
    for index in range(first_index, current_index + 1):
        month = _month_str(index)
        outcomes = grade_month(
            month=month,
            platform_tiers=registry.platform_tiers,
            vault_root=vault_root,
            state_path=state_path,
            ledger_path=ledger_path,
            now=now_str,
            pr_info_fn=_gh_pr_info,
        )
        if outcomes:
            graded[month] = outcomes

    return {"minted": minted.minted, "probe_errors": minted.probe_errors, "graded": graded}


__all__ = ["reconcile_vault"]
