"""AVSDLC visual-eval — intent-as-predicate (predict-then-confirm) mechanism.

A VisualIntentRecord is a set of falsifiable per-region predicates the agent
authors BEFORE a visual change ("I expect entity_core luma to drop to <= 10").
This module ships the MECHANISM only: schema + allowlist-validating parser + a
canonical, note-excluding intent-hash + an anti-vacuity guard + a pure
critical-AND evaluator. It is exercised entirely with SYNTHETIC realized /
baseline vectors.

What this module does NOT do (PR 4/N):
- compute the REALIZED per-region vector from captured frames (witness work);
- wire intent_pass into the release gate (overall PASS = floors AND intent_pass);
- supply a production baseline vector to ``anti_vacuity_check`` — here it is a
  pure function with NO production caller.

HONESTY (single_user, axiom weight 100): a self-authoring session can write a
weak-but-true predicate set. ``anti_vacuity_check`` guards ABSENCE and
TRIVIALITY (a predicate already true on the unchanged bytes), NOT adversarial
weakness. The defense against self-collusion is witness INDEPENDENCE (a separate
session computes the realized verdict), a PR 4/N property not established here.
The ``intent_hash`` folded into the receipt is TAMPER-EVIDENCE only — it does NOT
by itself establish intent<->bytes correspondence (that is the PR 4/N gate check).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# Vendored FROZEN Phase-1 allowlists. The authoritative AESTHETIC_REGIONS /
# POV_STATIONS live in scripts/screwm-effect-drift-matrix-witness.py, which is
# NON-importable (hyphenated filename); test_region_allowlist_matches_witness_
# constants pins this copy against drift. POV is INTENTIONALLY an open non-empty
# string (NOT the closed station enum) to avoid coupling the schema to the
# witness's moving render config.
_PHASE1_REGIONS = frozenset(
    {"ceiling", "left_wall", "right_wall", "floor", "entity_core", "negative_space"}
)
_PHASE1_METRICS = frozenset({"luma", "edge_energy"})
_ALLOWED_OPS = frozenset({"<=", ">=", "=="})
_ALLOWED_DIRECTIONS = frozenset({"increase", "decrease"})
DEFAULT_AGGREGATION_FLOOR = 0.75


@dataclass(frozen=True)
class VisualIntentPredicate:
    """One falsifiable claim about a (pov, region) metric after a change."""

    pov_label: str
    region: str
    metric: str
    op: str
    target: float
    direction: str
    critical: bool = False

    def holds(self, value: float) -> bool:
        if self.op == "<=":
            return value <= self.target
        if self.op == ">=":
            return value >= self.target
        if self.op == "==":
            return value == self.target
        return False  # unreachable once parsed (op is allowlisted)


@dataclass(frozen=True)
class VisualIntentRecord:
    """A pre-authored set of predicates + a non-critical aggregation floor."""

    predicates: tuple[VisualIntentPredicate, ...] = ()
    aggregation_floor: float = DEFAULT_AGGREGATION_FLOOR
    note: str = ""


def parse_intent_record(data: str | Mapping[str, Any]) -> VisualIntentRecord | None:
    """Parse + VALIDATE against the Phase-1 allowlists. Returns None on any
    violation (an empty predicate set is rejected as vacuous-by-absence). Never
    raises."""
    try:
        obj = json.loads(data) if isinstance(data, str) else data
        raw = obj.get("predicates")
        if not isinstance(raw, Sequence) or isinstance(raw, str) or not raw:
            return None
        floor = float(obj.get("aggregation_floor", DEFAULT_AGGREGATION_FLOOR))
        if not (0.0 <= floor <= 1.0):
            return None
        preds: list[VisualIntentPredicate] = []
        for p in raw:
            pov = str(p.get("pov_label", "")).strip()
            region = str(p.get("region", "")).strip()
            metric = str(p.get("metric", "")).strip()
            op = str(p.get("op", "")).strip()
            direction = str(p.get("direction", "")).strip()
            if not pov:
                return None
            if region not in _PHASE1_REGIONS:
                return None
            if metric not in _PHASE1_METRICS:
                return None
            if op not in _ALLOWED_OPS:
                return None
            if direction not in _ALLOWED_DIRECTIONS:
                return None
            preds.append(
                VisualIntentPredicate(
                    pov_label=pov,
                    region=region,
                    metric=metric,
                    op=op,
                    target=float(p["target"]),
                    direction=direction,
                    critical=bool(p.get("critical", False)),
                )
            )
        return VisualIntentRecord(
            predicates=tuple(preds),
            aggregation_floor=floor,
            note=str(obj.get("note", "")),
        )
    except Exception:  # noqa: BLE001 — malformed input must never raise.
        return None


def _canonical_predicate(p: VisualIntentPredicate) -> dict[str, Any]:
    return {
        "pov_label": p.pov_label,
        "region": p.region,
        "metric": p.metric,
        "op": p.op,
        "target": p.target,
        "direction": p.direction,
        "critical": p.critical,
    }


def serialize_intent_record(record: VisualIntentRecord) -> str:
    return json.dumps(
        {
            "predicates": [_canonical_predicate(p) for p in record.predicates],
            "aggregation_floor": record.aggregation_floor,
            "note": record.note,
        }
    )


def intent_hash_from_record(record: VisualIntentRecord) -> str:
    """Canonical sha256 over the predicates (ORDER-significant) + the floor.
    EXCLUDES ``note`` — free-text rationale must not change the bound intent."""
    payload = {
        "predicates": [_canonical_predicate(p) for p in record.predicates],
        "aggregation_floor": record.aggregation_floor,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _resolve(realized: Mapping[str, Any], pov: str, region: str, metric: str) -> float | None:
    pov_map = realized.get(pov) if isinstance(realized, Mapping) else None
    if not isinstance(pov_map, Mapping):
        return None
    region_map = pov_map.get(region)
    if not isinstance(region_map, Mapping):
        return None
    value = region_map.get(metric)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def evaluate_predicate(pred: VisualIntentPredicate, realized: Mapping[str, Any]) -> bool | None:
    """True/False if the (pov, region, metric) resolves; None if it is missing."""
    value = _resolve(realized, pred.pov_label, pred.region, pred.metric)
    if value is None:
        return None
    return pred.holds(value)


def intent_pass(record: VisualIntentRecord, realized: Mapping[str, Any]) -> bool:
    """Critical-AND + non-critical floor. FAIL-CLOSED: an empty predicate set OR
    any unresolvable predicate -> False (never a KeyError, never an auto-pass)."""
    if not record.predicates:
        return False
    non_critical_total = 0
    non_critical_held = 0
    for p in record.predicates:
        result = evaluate_predicate(p, realized)
        if result is None:
            return False
        if p.critical:
            if not result:
                return False
        else:
            non_critical_total += 1
            if result:
                non_critical_held += 1
    if non_critical_total == 0:
        return True
    return (non_critical_held / non_critical_total) >= record.aggregation_floor


def anti_vacuity_check(record: VisualIntentRecord, baseline: Mapping[str, Any]) -> tuple[bool, str]:
    """A record encodes a REAL expected delta iff >=1 predicate evaluates FALSE on
    the unchanged-bytes ``baseline`` vector for its declared (pov, region) — i.e.
    it asserts a state the baseline does not already satisfy.

    Guards ABSENCE / TRIVIALITY only, NOT adversarial weakness (single_user). In
    PR 3/N this is a pure function with NO production caller; the real baseline
    (per-region vector of the unchanged bytes) is a PR 4/N witness responsibility."""
    if not record.predicates:
        return False, "no predicates (vacuous by absence)"
    resolvable = 0
    for p in record.predicates:
        result = evaluate_predicate(p, baseline)
        if result is None:
            continue
        resolvable += 1
        if not result:
            return True, "ok"
    if resolvable == 0:
        return False, "no predicate resolvable against the baseline vector"
    return False, "every resolvable predicate already holds on the baseline (no expected delta)"
