"""Three-valued grading of minted no-op canary cells.

PASS requires a no-change verdict WITH justification on a terminal note;
ANY diff evidence is a FIXING-CORRECT-CODE failure (the L9 emitter field
rides every record); everything that cannot be confirmed — missed month,
vanished note, justification-free close, never-resolved cell — reads
probe-error. Canary rot must never read green.

Grading is idempotent per (month, tier): a decided cell is recorded in
vault-side state and never re-emitted.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from .store import append_event, canary_event, load_state, save_state

# Outcome decision inputs ----------------------------------------------------

GRACE_DAYS = 14
_NULLISH = frozenset({"", "null", "none", "~", "[]"})
# Statuses that mean a diff exists or is being delivered.
DIFF_STATUSES = frozenset({"pr_open", "merge_queue", "in_review"})
# Terminal statuses eligible for a PASS verdict.
TERMINAL_STATUSES = frozenset({"closed", "done", "completed"})
# A PASS needs an explicit no-change verdict line, not just a close.
JUSTIFICATION_RE = re.compile(
    r"no[- ]?change|nothing needs fixing|not warranted|refuted with evidence",
    re.IGNORECASE,
)

PrInfoFn = Callable[[str], dict[str, Any]]


def _is_nullish(value: Any) -> bool:
    if value is None:
        return True
    return str(value).strip().strip("'\"").lower() in _NULLISH


def _parse_now(now: str) -> datetime:
    return datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(UTC)


def _deadline(month: str) -> datetime:
    """Month end + grace: after this, an undecided cell reads probe-error."""
    year, mon = (int(part) for part in month.split("-"))
    if mon == 12:
        year, mon = year + 1, 1
    else:
        mon += 1
    return datetime(year, mon, 1, tzinfo=UTC) + timedelta(days=GRACE_DAYS)


def _locate_note(vault_root: Path, task_id: str) -> Path | None:
    for subdir in ("active", "closed"):
        exact = vault_root / subdir / f"{task_id}.md"
        if exact.is_file():
            return exact
        for candidate in sorted((vault_root / subdir).glob(f"{task_id}-*.md")):
            if candidate.is_file():
                return candidate
    return None


def _note_fields(text: str) -> dict[str, Any]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    loaded = yaml.safe_load(text[3:end])
    return loaded if isinstance(loaded, dict) else {}


def _justification_line(text: str) -> str | None:
    for line in text.splitlines():
        if JUSTIFICATION_RE.search(line):
            return line.strip()
    return None


def _pr_metrics(pr_value: Any, pr_info_fn: PrInfoFn | None) -> tuple[int | None, int | None]:
    """(review_rounds, diff_size_total); Nones when PR data is unavailable."""
    if pr_info_fn is None or _is_nullish(pr_value):
        return None, None
    try:
        info = pr_info_fn(str(pr_value).lstrip("#"))
        rounds = info.get("review_rounds")
        additions = info.get("additions")
        deletions = info.get("deletions")
        total = (
            int(additions) + int(deletions)
            if additions is not None and deletions is not None
            else None
        )
        return (int(rounds) if rounds is not None else None), total
    except Exception:
        # Metrics are best-effort decoration; the FAIL verdict stands alone.
        return None, None


def grade_month(
    *,
    month: str,
    platform_tiers: Sequence[str],
    vault_root: Path,
    state_path: Path,
    ledger_path: Path,
    now: str,
    pr_info_fn: PrInfoFn | None = None,
) -> dict[str, str]:
    """Grade every undecided (month, tier) cell. Returns {tier: outcome}
    for cells decided by THIS call; pending cells are omitted."""
    state = load_state(state_path)
    now_dt = _parse_now(now)
    past_deadline = now_dt > _deadline(month)
    minted = state.minted.get(month, {})
    graded = state.graded.setdefault(month, {})
    outcomes: dict[str, str] = {}
    dirty = False

    for tier in platform_tiers:
        if tier in graded:
            continue

        decided: dict[str, Any] | None = None
        entry = minted.get(tier)
        if entry is None:
            if past_deadline:
                decided = {"outcome": "probe_error", "probe_error_reason": "missed_month"}
                template_id = task_id = None
            else:
                continue  # mint can still happen this month
        else:
            template_id = entry.get("template_id")
            task_id = str(entry.get("task_id"))
            note_path = _locate_note(vault_root, task_id)
            if note_path is None:
                decided = {"outcome": "probe_error", "probe_error_reason": "note_missing"}
            else:
                text = note_path.read_text(encoding="utf-8")
                fields = _note_fields(text)
                status = str(fields.get("status", "")).strip().lower()
                branch = fields.get("branch")
                pr = fields.get("pr")

                if not _is_nullish(branch) or not _is_nullish(pr) or status in DIFF_STATUSES:
                    rounds, diff_total = _pr_metrics(pr, pr_info_fn)
                    decided = {
                        "outcome": "fail",
                        "diff_evidence": {
                            "branch": None if _is_nullish(branch) else str(branch),
                            "pr": None if _is_nullish(pr) else str(pr),
                            "status": status,
                        },
                        "review_rounds": rounds,
                        "diff_size_total": diff_total,
                    }
                elif status in TERMINAL_STATUSES:
                    justification = _justification_line(text)
                    if justification:
                        decided = {"outcome": "pass", "justification": justification}
                    else:
                        decided = {
                            "outcome": "probe_error",
                            "probe_error_reason": "justification_missing",
                        }
                elif past_deadline:
                    decided = {
                        "outcome": "probe_error",
                        "probe_error_reason": "unresolved_at_deadline",
                    }

        if decided is None:
            continue  # pending: not minted-and-broken, just not decidable yet

        outcome = decided.pop("outcome")
        reason = decided.pop("probe_error_reason", None)
        append_event(
            ledger_path,
            canary_event(
                month=month,
                platform_tier=tier,
                template_id=template_id,
                task_id=task_id,
                outcome=outcome,
                probe_error_reason=reason,
                detected_at=now,
                **decided,
            ),
        )
        graded[tier] = {"outcome": outcome, "graded_at": now}
        outcomes[tier] = outcome
        dirty = True

    if dirty:
        save_state(state_path, state)
    return outcomes


__all__ = ["grade_month", "GRACE_DAYS"]
