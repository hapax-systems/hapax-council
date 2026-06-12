"""Vault-side state + append-only outcome ledger for no-op canaries.

The (month, tier) -> task_id mapping deliberately lives OUTSIDE the repo
(default: the cc-task vault's _evidence/ tree) so a lane working in the
repo cannot trivially grep which live task is a decoy. Outcome events are
append-only JSONL — one record per graded (month, tier) cell, three-valued
{pass | fail | probe_error}, with the L9 emitter field on every record.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

STATE_SCHEMA_VERSION = 1
EVENT_SCHEMA_VERSION = 1
EVENT_KIND = "noop_canary_outcome"
FIXING_CORRECT_CODE = "FIXING-CORRECT-CODE"


@dataclass
class State:
    """Mint/grade bookkeeping, keyed [month][tier]."""

    minted: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    graded: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)


def load_state(path: Path) -> State:
    if not path.is_file():
        return State()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return State()
    minted = raw.get("minted") or {}
    graded = raw.get("graded") or {}
    return State(
        minted=minted if isinstance(minted, dict) else {},
        graded=graded if isinstance(graded, dict) else {},
    )


def save_state(path: Path, state: State) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": STATE_SCHEMA_VERSION,
        "minted": state.minted,
        "graded": state.graded,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def canary_event(
    *,
    month: str,
    platform_tier: str,
    template_id: str | None,
    outcome: str,
    detected_at: str,
    task_id: str | None = None,
    probe_error_reason: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build one three-valued outcome record (the single emitter path)."""
    if outcome not in ("pass", "fail", "probe_error"):
        raise ValueError(f"outcome must be pass|fail|probe_error, got {outcome!r}")
    event: dict[str, Any] = {
        "schema_version": EVENT_SCHEMA_VERSION,
        "kind": EVENT_KIND,
        "month": month,
        "platform_tier": platform_tier,
        "template_id": template_id,
        "task_id": task_id,
        "outcome": outcome,
        # Any diff on a no-op canary is a FIXING-CORRECT-CODE taxonomy event.
        "mode": FIXING_CORRECT_CODE if outcome == "fail" else None,
        # L9 first-party-emitter requirement: this grader is deterministic
        # harness-side tooling, never a lane self-report.
        "emitter": "harness",
        "detected_at": detected_at,
        "probe_error_reason": probe_error_reason,
    }
    event.update(extra)
    return event


def append_event(ledger_path: Path, event: dict[str, Any]) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
