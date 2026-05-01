#!/usr/bin/env python3
"""Braid-score snapshot runner — v1 + v1.1 dispatcher.

Walks the operator's cc-task vault (`active/` and `closed/`), reads each
task's YAML frontmatter, dispatches scoring by the ``braid_schema``
discriminator, and emits one JSONL line per task to stdout (or to
``~/.local/state/hapax/cc-task-braid-runner/snapshot-<ts>.jsonl`` when
``--snapshot`` is given).

Phase 2 of the v1.1 evolution (Phase 1: template + cc-readme;
Phase 3: Auto-GTM batch migration).

Schema dispatch
---------------
- ``braid_schema: 1`` (or absent / null) → v1 formula:
    ``0.35*min(E,M,R) + 0.30*avg(E,M,R) + 0.25*T + 0.10*C - P``
- ``braid_schema: 1.1`` → v1.1 formula per
  ``docs/superpowers/specs/2026-05-01-braid-schema-v11-design.md``:
    ``0.30*min(E,M,R) + 0.25*avg(E,M,R) + 0.20*T + 0.10*(U/1.5) +
      0.10*len(channels) + 0.05*forcing_function_urgency + 0.10*C
      - P - axiomatic_strain``

Backward-compat invariant: v1 tasks compute identically under this
runner. ``--verify-v1-stability`` confirms a sample.

CLI
---
``cc-task-braid-runner.py [--vault-root PATH] [--snapshot]
                          [--apply] [--review-deltas]
                          [--verify-v1-stability]
                          [--verify-auto-gtm-predictions]``
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

DEFAULT_VAULT_ROOT = Path.home() / "Documents/Personal/20-projects/hapax-cc-tasks"
DEFAULT_STATE_DIR = Path.home() / ".local/state/hapax/cc-task-braid-runner"

PERMITTED_FORCING_KINDS = ("none", "regulatory:", "deadline:", "amplifier_window:")
PERMITTED_FUNNEL_ROLES = frozenset({"none", "inbound", "conversion", "amplifier", "compounder"})
PERMITTED_COMPOUNDING_CURVES = frozenset(
    {"linear", "log_saturating", "step_function", "preferential_attachment", "mixed"}
)
PERMITTED_POLYSEMIC_CHANNELS = frozenset(range(1, 8))


@dataclass(frozen=True)
class TaskFrontmatter:
    """Subset of frontmatter the runner reads. Unknown keys ignored."""

    task_id: str
    path: Path
    braid_schema: str  # "1" or "1.1"
    engagement: float
    monetary: float
    research: float
    tree_effect: float
    evidence_confidence: float
    risk_penalty: float
    forcing_function_window: str | None
    unblock_breadth: float | None
    polysemic_channels: list[int] | None
    funnel_role: str | None
    compounding_curve: str | None
    axiomatic_strain: float | None
    declared_score: float | None  # operator-recorded `braid_score`


@dataclass(frozen=True)
class ScoreResult:
    task_id: str
    schema: str
    score: float
    delta_from_declared: float
    validation_warnings: tuple[str, ...]


def _parse_frontmatter_block(text: str) -> dict[str, Any]:
    """Pull the YAML frontmatter block from a markdown file.

    Uses a hand-rolled parser to avoid the PyYAML dependency for this
    runner — frontmatter shape is constrained by ``tpl-cc-task.md`` so
    full YAML is not required.
    """
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    block = text[4:end]

    out: dict[str, Any] = {}
    for raw_line in block.splitlines():
        if not raw_line or raw_line.lstrip().startswith("#"):
            continue
        if ":" not in raw_line:
            continue
        if raw_line[0] in " -":
            # nested or list item — runner doesn't need these for the dimensions
            continue
        key, _, value = raw_line.partition(":")
        key = key.strip()
        value = value.strip()
        if not value:
            out[key] = None
            continue
        if (
            value.startswith('"')
            and value.endswith('"')
            or value.startswith("'")
            and value.endswith("'")
        ):
            out[key] = value[1:-1]
        elif value == "null":
            out[key] = None
        elif value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            if not inner:
                out[key] = []
            else:
                items: list[Any] = []
                for item in inner.split(","):
                    item = item.strip()
                    if item.isdigit() or (item.startswith("-") and item[1:].isdigit()):
                        items.append(int(item))
                    else:
                        items.append(item.strip("'\""))
                out[key] = items
        else:
            try:
                out[key] = int(value)
            except ValueError:
                try:
                    out[key] = float(value)
                except ValueError:
                    out[key] = value
    return out


def _coerce_float(v: Any, default: float = 0.0) -> float:
    if v is None or v == "":
        return default
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def load_task_frontmatter(path: Path) -> TaskFrontmatter | None:
    """Return parsed frontmatter for a cc-task .md, or None if not a task."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    fm = _parse_frontmatter_block(text)
    if fm.get("type") != "cc-task":
        return None

    raw_schema = fm.get("braid_schema")
    schema = "1.1" if str(raw_schema) == "1.1" else "1"

    return TaskFrontmatter(
        task_id=str(fm.get("task_id", path.stem)),
        path=path,
        braid_schema=schema,
        engagement=_coerce_float(fm.get("braid_engagement")),
        monetary=_coerce_float(fm.get("braid_monetary")),
        research=_coerce_float(fm.get("braid_research")),
        tree_effect=_coerce_float(fm.get("braid_tree_effect")),
        evidence_confidence=_coerce_float(fm.get("braid_evidence_confidence")),
        risk_penalty=_coerce_float(fm.get("braid_risk_penalty")),
        forcing_function_window=fm.get("braid_forcing_function_window"),
        unblock_breadth=(
            _coerce_float(fm.get("braid_unblock_breadth"))
            if fm.get("braid_unblock_breadth") is not None
            else None
        ),
        polysemic_channels=(
            list(fm["braid_polysemic_channels"])
            if isinstance(fm.get("braid_polysemic_channels"), list)
            else None
        ),
        funnel_role=fm.get("braid_funnel_role"),
        compounding_curve=fm.get("braid_compounding_curve"),
        axiomatic_strain=(
            _coerce_float(fm.get("braid_axiomatic_strain"))
            if fm.get("braid_axiomatic_strain") is not None
            else None
        ),
        declared_score=(
            _coerce_float(fm.get("braid_score")) if fm.get("braid_score") is not None else None
        ),
    )


def compute_v1_score(t: TaskFrontmatter) -> float:
    """v1 formula — applies to all tasks regardless of schema."""
    e, m, r = t.engagement, t.monetary, t.research
    return (
        0.35 * min(e, m, r)
        + 0.30 * (e + m + r) / 3.0
        + 0.25 * t.tree_effect
        + 0.10 * t.evidence_confidence
        - t.risk_penalty
    )


def _forcing_function_urgency(window: str | None, today: date | None = None) -> float:
    """Map ``<kind>:<ISO date>`` to 0-10 urgency per the spec table."""
    if not window or window in ("none", "null"):
        return 0.0
    today = today or datetime.now(UTC).date()
    match = re.match(r"^(?:regulatory|deadline|amplifier_window):(\d{4}-\d{2}-\d{2})$", window)
    if not match:
        return 0.0
    try:
        target = date.fromisoformat(match.group(1))
    except ValueError:
        return 0.0
    days = (target - today).days
    if days < 0:
        return 0.0  # window closed; downgrade signal handled separately
    if days < 30:
        return 10.0
    if days < 90:
        return 8.0
    if days < 365:
        return 5.0
    return 2.0


def compute_v11_score(t: TaskFrontmatter, today: date | None = None) -> float:
    """v1.1 formula per docs/superpowers/specs/2026-05-01-braid-schema-v11-design.md."""
    e, m, r = t.engagement, t.monetary, t.research
    u = t.unblock_breadth or 0.0
    channels = t.polysemic_channels or []
    channel_count = sum(
        1 for c in channels if isinstance(c, int) and c in PERMITTED_POLYSEMIC_CHANNELS
    )
    urgency = _forcing_function_urgency(t.forcing_function_window, today)
    strain = t.axiomatic_strain or 0.0
    return (
        0.30 * min(e, m, r)
        + 0.25 * (e + m + r) / 3.0
        + 0.20 * t.tree_effect
        + 0.10 * (u / 1.5)
        + 0.10 * channel_count
        + 0.05 * urgency
        + 0.10 * t.evidence_confidence
        - t.risk_penalty
        - strain
    )


def validate(t: TaskFrontmatter) -> tuple[str, ...]:
    """Schema validation; returns warning strings."""
    warnings: list[str] = []
    if t.braid_schema == "1.1":
        if t.forcing_function_window:
            if not any(t.forcing_function_window.startswith(p) for p in PERMITTED_FORCING_KINDS):
                warnings.append(
                    f"braid_forcing_function_window invalid format: {t.forcing_function_window!r}"
                )
        if t.polysemic_channels is not None:
            invalid = [c for c in t.polysemic_channels if c not in PERMITTED_POLYSEMIC_CHANNELS]
            if invalid:
                warnings.append(f"braid_polysemic_channels out-of-range values: {invalid}")
        if t.funnel_role is not None and t.funnel_role not in PERMITTED_FUNNEL_ROLES:
            warnings.append(f"braid_funnel_role unknown value: {t.funnel_role!r}")
        if (
            t.compounding_curve is not None
            and t.compounding_curve not in PERMITTED_COMPOUNDING_CURVES
        ):
            warnings.append(f"braid_compounding_curve unknown value: {t.compounding_curve!r}")
    return tuple(warnings)


def score_task(t: TaskFrontmatter, today: date | None = None) -> ScoreResult:
    """Dispatch by schema, return ScoreResult with computed score + delta."""
    if t.braid_schema == "1.1":
        score = compute_v11_score(t, today=today)
    else:
        score = compute_v1_score(t)
    declared = t.declared_score if t.declared_score is not None else 0.0
    delta = score - declared
    return ScoreResult(
        task_id=t.task_id,
        schema=t.braid_schema,
        score=round(score, 3),
        delta_from_declared=round(delta, 3),
        validation_warnings=validate(t),
    )


def walk_vault(vault_root: Path) -> list[TaskFrontmatter]:
    """Walk active/ + closed/ in the vault root, return all task frontmatters."""
    tasks: list[TaskFrontmatter] = []
    for sub in ("active", "closed"):
        d = vault_root / sub
        if not d.is_dir():
            continue
        for path in sorted(d.glob("*.md")):
            t = load_task_frontmatter(path)
            if t is not None:
                tasks.append(t)
    return tasks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--vault-root",
        type=Path,
        default=DEFAULT_VAULT_ROOT,
        help=f"vault root containing active/ and closed/ (default: {DEFAULT_VAULT_ROOT})",
    )
    parser.add_argument(
        "--snapshot",
        action="store_true",
        help=f"write JSONL output to {DEFAULT_STATE_DIR}/snapshot-<ts>.jsonl",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="(reserved) write computed score back to v1.1 task frontmatter; off by default",
    )
    parser.add_argument(
        "--review-deltas",
        type=float,
        default=None,
        help="only emit tasks where |computed - declared| > THRESHOLD",
    )
    parser.add_argument(
        "--verify-v1-stability",
        action="store_true",
        help="check that v1 task computed scores match declared (within 0.05) for all tasks",
    )

    args = parser.parse_args(argv)
    today = datetime.now(UTC).date()

    tasks = walk_vault(args.vault_root)

    out_lines: list[str] = []
    schema_counts = {"1": 0, "1.1": 0}
    delta_above: list[ScoreResult] = []
    validation_failures: list[ScoreResult] = []
    v1_drift: list[ScoreResult] = []

    for t in tasks:
        result = score_task(t, today=today)
        schema_counts[result.schema] = schema_counts.get(result.schema, 0) + 1

        if args.review_deltas is not None and abs(result.delta_from_declared) <= args.review_deltas:
            continue

        if args.verify_v1_stability and t.braid_schema == "1":
            if abs(result.delta_from_declared) > 0.05 and t.declared_score is not None:
                v1_drift.append(result)

        if result.validation_warnings:
            validation_failures.append(result)

        if abs(result.delta_from_declared) > 1.0:
            delta_above.append(result)

        line = json.dumps(
            {
                "task_id": result.task_id,
                "schema": result.schema,
                "braid_score": result.score,
                "braid_score_delta_from_previous_snapshot": result.delta_from_declared,
                "validation_warnings": list(result.validation_warnings),
            },
            sort_keys=True,
        )
        out_lines.append(line)

    if args.snapshot:
        DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        snapshot_path = DEFAULT_STATE_DIR / f"snapshot-{ts}.jsonl"
        snapshot_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        print(f"wrote {len(out_lines)} task scores → {snapshot_path}", file=sys.stderr)
    else:
        for line in out_lines:
            print(line)

    print(
        f"\n=== summary ===\n"
        f"total tasks scored: {len(tasks)}\n"
        f"  schema v1:   {schema_counts.get('1', 0)}\n"
        f"  schema v1.1: {schema_counts.get('1.1', 0)}\n"
        f"deltas > 1.0: {len(delta_above)}\n"
        f"validation failures: {len(validation_failures)}\n"
        f"v1 drift > 0.05 (--verify-v1-stability): {len(v1_drift)}",
        file=sys.stderr,
    )

    if args.verify_v1_stability and v1_drift:
        print(
            f"FAIL: {len(v1_drift)} v1 tasks drifted from declared score by > 0.05",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
