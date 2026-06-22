"""AVSDLC visual-eval — intent-as-predicate (predict-then-confirm) core.

Thin PR 3/N: a VisualIntent is a set of falsifiable per-region predicates the
agent authors BEFORE a change. PR 3/N ships the MECHANISM — schema + parser +
canonical intent-hash + anti-vacuity guard + a pure critical-AND evaluator —
exercised entirely with SYNTHETIC realized/baseline vectors. The witness-side
realized-vector computation and the gate wiring (overall PASS = floors AND
intent_pass) are PR 4/N. Self-contained per convention.

cc-task: avsdlc-visual-eval-intent-predicate (CASE-AVSDLC-VISUAL-INTENT-20260622).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from shared.avsdlc_visual_intent import (
    _PHASE1_REGIONS,
    DEFAULT_AGGREGATION_FLOOR,
    VisualIntentPredicate,
    VisualIntentRecord,
    anti_vacuity_check,
    evaluate_predicate,
    intent_hash_from_record,
    intent_pass,
    parse_intent_record,
    serialize_intent_record,
)


def _pred(
    pov="cam0",
    region="entity_core",
    metric="luma",
    op="<=",
    target=10.0,
    direction="decrease",
    critical=True,
):
    return {
        "pov_label": pov,
        "region": region,
        "metric": metric,
        "op": op,
        "target": target,
        "direction": direction,
        "critical": critical,
    }


def _record_dict(preds=None, floor=0.75, note=""):
    return {
        "predicates": preds if preds is not None else [_pred()],
        "aggregation_floor": floor,
        "note": note,
    }


def _vec(pov="cam0", region="entity_core", metric="luma", value=100.0):
    return {pov: {region: {metric: value}}}


# ── schema / parse ────────────────────────────────────────────────────


class TestSchemaParse:
    def test_predicate_frozen_immutable(self) -> None:
        p = VisualIntentPredicate("cam0", "floor", "luma", "<=", 10.0, "decrease", True)
        with pytest.raises(Exception):
            p.target = 99.0  # type: ignore[misc]

    def test_record_round_trips_through_json(self) -> None:
        rec = parse_intent_record(_record_dict([_pred(), _pred(region="floor", critical=False)]))
        assert rec is not None
        again = parse_intent_record(serialize_intent_record(rec))
        assert again is not None
        assert again.predicates == rec.predicates
        assert again.aggregation_floor == rec.aggregation_floor

    def test_parse_rejects_empty_predicate_set(self) -> None:
        assert parse_intent_record(_record_dict(preds=[])) is None

    def test_parse_rejects_unknown_op(self) -> None:
        for bad in ("!=", "<", ">"):
            assert parse_intent_record(_record_dict([_pred(op=bad)])) is None

    def test_parse_rejects_unknown_metric(self) -> None:
        for bad in ("white_fraction", "hue"):
            assert parse_intent_record(_record_dict([_pred(metric=bad)])) is None

    def test_parse_rejects_unknown_region(self) -> None:
        assert parse_intent_record(_record_dict([_pred(region="unknown")])) is None
        for region in _PHASE1_REGIONS:
            assert parse_intent_record(_record_dict([_pred(region=region)])) is not None

    def test_parse_rejects_unknown_direction(self) -> None:
        assert parse_intent_record(_record_dict([_pred(direction="sideways")])) is None

    def test_parse_rejects_empty_pov_label(self) -> None:
        assert parse_intent_record(_record_dict([_pred(pov="")])) is None

    def test_parse_rejects_floor_out_of_range(self) -> None:
        assert parse_intent_record(_record_dict(floor=1.5)) is None
        assert parse_intent_record(_record_dict(floor=-0.1)) is None

    def test_parse_strips_whitespace_in_string_fields(self) -> None:
        rec = parse_intent_record(
            _record_dict([_pred(pov=" cam0 ", region=" entity_core ", metric=" luma ")])
        )
        assert rec is not None
        p = rec.predicates[0]
        assert p.pov_label == "cam0" and p.region == "entity_core" and p.metric == "luma"

    def test_parse_open_pov_label_accepted(self) -> None:
        # POV is an open non-empty string (the closed station enum lives in the
        # non-importable witness script) — an arbitrary label parses.
        assert parse_intent_record(_record_dict([_pred(pov="some-novel-station")])) is not None


# ── canonical intent hash ─────────────────────────────────────────────


class TestIntentHash:
    def test_deterministic(self) -> None:
        rec = parse_intent_record(_record_dict())
        assert intent_hash_from_record(rec) == intent_hash_from_record(rec)
        assert len(intent_hash_from_record(rec)) == 64

    def test_insensitive_to_key_order_and_whitespace(self) -> None:
        a = parse_intent_record(_record_dict([_pred()]))
        b = parse_intent_record(serialize_intent_record(a))  # re-serialized, normalized
        assert intent_hash_from_record(a) == intent_hash_from_record(b)

    def test_excludes_note(self) -> None:
        a = parse_intent_record(_record_dict(note="first rationale"))
        b = parse_intent_record(_record_dict(note="totally different note"))
        assert intent_hash_from_record(a) == intent_hash_from_record(b)

    def test_sensitive_to_target_and_op(self) -> None:
        base = parse_intent_record(_record_dict([_pred(target=10.0, op="<=")]))
        diff_target = parse_intent_record(_record_dict([_pred(target=20.0, op="<=")]))
        diff_op = parse_intent_record(_record_dict([_pred(target=10.0, op=">=")]))
        assert intent_hash_from_record(base) != intent_hash_from_record(diff_target)
        assert intent_hash_from_record(base) != intent_hash_from_record(diff_op)

    def test_sensitive_to_predicate_order(self) -> None:
        p1, p2 = _pred(region="ceiling"), _pred(region="floor")
        a = parse_intent_record(_record_dict([p1, p2]))
        b = parse_intent_record(_record_dict([p2, p1]))
        assert intent_hash_from_record(a) != intent_hash_from_record(b)


# ── anti-vacuity (pure; synthetic baseline only in PR 3/N) ─────────────


class TestAntiVacuity:
    def test_false_on_baseline_for_one_region_passes(self) -> None:
        rec = parse_intent_record(_record_dict([_pred(op="<=", target=50.0)]))
        ok, _ = anti_vacuity_check(rec, _vec(value=100.0))  # 100<=50 is False -> real delta
        assert ok

    def test_all_true_on_baseline_rejected(self) -> None:
        rec = parse_intent_record(_record_dict([_pred(op=">=", target=0.0)]))
        ok, reason = anti_vacuity_check(rec, _vec(value=100.0))  # 100>=0 already true
        assert not ok and reason

    def test_no_resolvable_predicate_rejected(self) -> None:
        rec = parse_intent_record(_record_dict([_pred()]))
        ok, reason = anti_vacuity_check(rec, {"other_pov": {}})
        assert not ok and reason

    def test_mixed_satisfied_by_one_region(self) -> None:
        preds = [
            _pred(region="ceiling", op="<=", target=50.0),
            _pred(region="floor", op=">=", target=0.0),
        ]
        rec = parse_intent_record(_record_dict(preds))
        baseline = {"cam0": {"ceiling": {"luma": 100.0}, "floor": {"luma": 100.0}}}
        ok, _ = anti_vacuity_check(rec, baseline)  # ceiling 100<=50 False -> one suffices
        assert ok


# ── evaluator ─────────────────────────────────────────────────────────


class TestEvaluator:
    def test_evaluate_predicate_resolves_op(self) -> None:
        assert evaluate_predicate(
            VisualIntentPredicate("cam0", "floor", "luma", "<=", 10.0, "decrease"),
            _vec(region="floor", value=5.0),
        )
        assert evaluate_predicate(
            VisualIntentPredicate("cam0", "floor", "luma", ">=", 10.0, "increase"),
            _vec(region="floor", value=20.0),
        )
        assert evaluate_predicate(
            VisualIntentPredicate("cam0", "floor", "luma", "==", 10.0, "increase"),
            _vec(region="floor", value=10.0),
        )

    def test_evaluate_predicate_missing_entry_returns_none(self) -> None:
        p = VisualIntentPredicate("cam0", "entity_core", "luma", "<=", 10.0, "decrease")
        assert evaluate_predicate(p, {"cam0": {"floor": {"luma": 5.0}}}) is None  # region missing
        assert evaluate_predicate(p, {"other": {}}) is None  # pov missing
        assert (
            evaluate_predicate(p, {"cam0": {"entity_core": {"edge_energy": 5.0}}}) is None
        )  # metric missing

    def test_intent_pass_empty_predicates_false(self) -> None:
        assert intent_pass(VisualIntentRecord(predicates=()), _vec()) is False

    def test_intent_pass_critical_AND_all_hold(self) -> None:
        preds = [_pred(region=r, op="<=", target=10.0) for r in ("ceiling", "floor", "entity_core")]
        rec = parse_intent_record(_record_dict(preds))
        realized = {"cam0": {r: {"luma": 5.0} for r in ("ceiling", "floor", "entity_core")}}
        assert intent_pass(rec, realized) is True

    def test_intent_pass_critical_AND_one_fails(self) -> None:
        preds = [_pred(region=r, op="<=", target=10.0) for r in ("ceiling", "floor", "entity_core")]
        rec = parse_intent_record(_record_dict(preds))
        realized = {
            "cam0": {
                "ceiling": {"luma": 5.0},
                "floor": {"luma": 5.0},
                "entity_core": {"luma": 99.0},
            }
        }
        assert intent_pass(rec, realized) is False

    def test_intent_pass_non_critical_floor_met(self) -> None:
        preds = [_pred(region=r, op="<=", target=10.0, critical=False) for r in _PHASE1_REGIONS]
        rec = parse_intent_record(_record_dict(list(preds)[:5], floor=0.6))
        regions = [p["region"] for p in _record_dict(list(preds)[:5])["predicates"]]
        realized = {"cam0": {r: {"luma": (5.0 if i < 3 else 99.0)} for i, r in enumerate(regions)}}
        assert intent_pass(rec, realized) is True  # 3/5 >= 0.6

    def test_intent_pass_non_critical_below_floor(self) -> None:
        preds = [
            _pred(region=r, op="<=", target=10.0, critical=False) for r in list(_PHASE1_REGIONS)[:5]
        ]
        rec = parse_intent_record(_record_dict(preds, floor=0.6))
        regions = [p["region"] for p in preds]
        realized = {"cam0": {r: {"luma": (5.0 if i < 2 else 99.0)} for i, r in enumerate(regions)}}
        assert intent_pass(rec, realized) is False  # 2/5 < 0.6

    def test_default_floor_is_0_75(self) -> None:
        assert DEFAULT_AGGREGATION_FLOOR == 0.75
        preds = [
            _pred(region=r, op="<=", target=10.0, critical=False) for r in list(_PHASE1_REGIONS)[:4]
        ]
        rec = parse_intent_record({"predicates": preds})  # floor omitted -> default 0.75
        regions = [p["region"] for p in preds]
        realized3 = {"cam0": {r: {"luma": (5.0 if i < 3 else 99.0)} for i, r in enumerate(regions)}}
        realized2 = {"cam0": {r: {"luma": (5.0 if i < 2 else 99.0)} for i, r in enumerate(regions)}}
        assert intent_pass(rec, realized3) is True  # 3/4 == 0.75
        assert intent_pass(rec, realized2) is False  # 2/4 < 0.75

    def test_mixed_critical_and_non_critical(self) -> None:
        preds = [
            _pred(region="ceiling", op="<=", target=10.0, critical=True),
            _pred(region="floor", op="<=", target=10.0, critical=True),
            *[
                _pred(region=r, op="<=", target=10.0, critical=False)
                for r in ("left_wall", "right_wall", "entity_core", "negative_space")
            ],
        ]
        rec = parse_intent_record(_record_dict(preds, floor=0.5))
        realized = {
            "cam0": {
                "ceiling": {"luma": 5.0},
                "floor": {"luma": 5.0},
                "left_wall": {"luma": 5.0},
                "right_wall": {"luma": 5.0},
                "entity_core": {"luma": 99.0},
                "negative_space": {"luma": 99.0},
            }
        }
        assert intent_pass(rec, realized) is True  # criticals hold, 2/4 non-critical == floor 0.5

    def test_unresolvable_predicate_fails_closed(self) -> None:
        preds = [_pred(region="ceiling"), _pred(region="floor")]
        rec = parse_intent_record(_record_dict(preds))
        realized = {"cam0": {"ceiling": {"luma": 5.0}}}  # floor missing
        assert intent_pass(rec, realized) is False  # no KeyError, no auto-pass

    def test_synthetic_white_blob_predicate_fails(self) -> None:
        # The motivating case: the change CLAIMED to kill the white blob, but the
        # realized vector still shows high luma in entity_core -> intent_pass False.
        rec = parse_intent_record(
            _record_dict([_pred(region="entity_core", op="<=", target=10.0, critical=True)])
        )
        assert intent_pass(rec, _vec(region="entity_core", value=200.0)) is False


# ── allowlist drift pin ───────────────────────────────────────────────


def test_region_allowlist_matches_witness_constants() -> None:
    # Drift pin: the vendored _PHASE1_REGIONS must equal the six AESTHETIC_REGIONS
    # names in the (non-importable, hyphenated) matrix witness. POV is DELIBERATELY
    # NOT pinned to POV_STATIONS — it is an open string, to avoid coupling the
    # intent schema to a moving witness render config.
    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "screwm-effect-drift-matrix-witness.py"
    )
    text = script.read_text(encoding="utf-8")
    block = text.split("AESTHETIC_REGIONS", 1)[1].split("}", 1)[0]
    names = set(re.findall(r'"([a-z_]+)":', block))
    assert names == set(_PHASE1_REGIONS)
