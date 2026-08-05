"""Capability onboarding disposition ledgers — append-only classify records.

Persists Edge A/B classify outcomes (admit_supply | evidence_only | EXPLORE | HOLD |
refuse) without activating supply or moving Thompson posteriors.

Default root: ``~/.cache/hapax/capability-onboarding/`` (NVMe, not tmpfs).
Override: ``HAPAX_CAPABILITY_ONBOARDING_LEDGER_ROOT`` or explicit ``path`` args.

Streams (one JSONL file per disposition under the root):
  explore.jsonl | hold.jsonl | evidence_only.jsonl | admit_supply.jsonl | refuse.jsonl

EXPLORE is first-class: under-measured / INCOMPARABLE surfaces land here as success.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from shared.capability_onboarding_classify import (
    OnboardingDisposition,
    classify_onboarding_surface,
)
from shared.route_metadata_schema import stable_payload_hash

SCHEMA_V0: Final[str] = "hapax.capability_onboarding_ledger_row.v0"
DEFAULT_LEDGER_ROOT: Final[Path] = Path(
    os.environ.get(
        "HAPAX_CAPABILITY_ONBOARDING_LEDGER_ROOT",
        str(Path.home() / ".cache" / "hapax" / "capability-onboarding"),
    )
)

_STREAM_FILES: Final[dict[str, str]] = {
    OnboardingDisposition.EXPLORE.value: "explore.jsonl",
    OnboardingDisposition.HOLD.value: "hold.jsonl",
    OnboardingDisposition.EVIDENCE_ONLY.value: "evidence_only.jsonl",
    OnboardingDisposition.ADMIT_SUPPLY.value: "admit_supply.jsonl",
    OnboardingDisposition.REFUSE.value: "refuse.jsonl",
}


def ledger_root(root: Path | str | None = None) -> Path:
    return Path(root) if root is not None else DEFAULT_LEDGER_ROOT


def stream_path(disposition: str, *, root: Path | str | None = None) -> Path:
    key = disposition.strip()
    if key not in _STREAM_FILES:
        raise ValueError(
            f"unknown onboarding disposition {disposition!r}; next action: use one of "
            + ", ".join(sorted(_STREAM_FILES))
        )
    return ledger_root(root) / _STREAM_FILES[key]


def build_ledger_row(
    classify_result: Mapping[str, Any],
    *,
    observed_at: str | None = None,
    source_ref: str | None = None,
    demand_shape_ref: str | None = None,
    admission_tuple_id: str | None = None,
) -> dict[str, Any]:
    """Normalize a classify result into a ledger row (does not write)."""
    if not isinstance(classify_result, Mapping):
        raise ValueError("classify_result must be a mapping")
    disposition = str(classify_result.get("disposition") or "").strip()
    if disposition not in _STREAM_FILES:
        raise ValueError(f"classify_result missing valid disposition: {disposition!r}")
    # Defense: never persist admit_supply if may_fulfill_demand is false
    if disposition == OnboardingDisposition.ADMIT_SUPPLY.value:
        if classify_result.get("may_fulfill_demand") is not True:
            raise ValueError(
                "refuse to ledger admit_supply without may_fulfill_demand=true; "
                "next action: re-classify or write EXPLORE/HOLD instead"
            )
    ts = observed_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    row: dict[str, Any] = {
        "schema": SCHEMA_V0,
        "observed_at": ts,
        "disposition": disposition,
        "modal_class": classify_result.get("modal_class"),
        "reasons": list(classify_result.get("reasons") or []),
        "surface_id": classify_result.get("surface_id"),
        "success": bool(classify_result.get("success", True)),
        "may_fulfill_demand": bool(classify_result.get("may_fulfill_demand", False)),
        "source_ref": source_ref,
        "demand_shape_ref": demand_shape_ref,
        "admission_tuple_id": admission_tuple_id,
    }
    notes = classify_result.get("notes")
    if isinstance(notes, Mapping) and notes:
        row["notes"] = dict(notes)
    row["row_id"] = stable_payload_hash(
        {k: v for k, v in row.items() if k != "row_id" and v is not None}
    )
    return row


def append_classify_result(
    classify_result: Mapping[str, Any],
    *,
    root: Path | str | None = None,
    observed_at: str | None = None,
    source_ref: str | None = None,
    demand_shape_ref: str | None = None,
    admission_tuple_id: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Append one classify result to the disposition stream; return (path, row)."""
    row = build_ledger_row(
        classify_result,
        observed_at=observed_at,
        source_ref=source_ref,
        demand_shape_ref=demand_shape_ref,
        admission_tuple_id=admission_tuple_id,
    )
    target = stream_path(str(row["disposition"]), root=root)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    return target, row


def read_ledger(
    disposition: str,
    *,
    root: Path | str | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield rows from one disposition stream; skip corrupt lines."""
    target = stream_path(disposition, root=root)
    if not target.exists():
        return
    with target.open(encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                yield payload


def classify_and_ledger(
    *,
    root: Path | str | None = None,
    source_ref: str | None = None,
    demand_shape_ref: str | None = None,
    admission_tuple_id: str | None = None,
    **classify_kwargs: Any,
) -> dict[str, Any]:
    """Classify a surface and append the result; return classify + ledger meta."""
    result = classify_onboarding_surface(**classify_kwargs)
    path, row = append_classify_result(
        result,
        root=root,
        source_ref=source_ref,
        demand_shape_ref=demand_shape_ref,
        admission_tuple_id=admission_tuple_id,
    )
    return {
        "classify": result,
        "ledger_path": str(path),
        "row": row,
    }
