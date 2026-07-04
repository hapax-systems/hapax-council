"""Judge-health gate tests — cost-capture phase 0 (false-accept skew).

Task ``20260628-costcap-phase0-fix-judge-validation-skew-false-accept``:
1. Reproduce the false-accept/false-reject measurement on a held set (the pinned
   VerifierBench confusion matrix from ``docs/research/2026-06-14-local-judge-validation.md``).
2. Authoritative flips stay disabled until judge health meets the AC3 request
   threshold (>=150 scored items, agreement >=90%, Cohen's kappa >=0.80,
   conservative-skewed).
3. Pin the refusal path for unhealthy judge state — an unvalidated judge's
   ``llm_acceptor`` verdicts must never move routing posteriors.
"""

from __future__ import annotations

import json
from pathlib import Path

from shared.gate_log import GateEvent
from shared.route_metadata_schema import LearningEligibility
from shared.sdlc_router import (
    DEFAULT_JUDGE_HEALTH_THRESHOLDS,
    JudgeHealthThresholds,
    SdlcRouter,
    authoritative_flip_allowed,
    judge_promotion_gate,
    load_judge_shadow_pairs,
    measure_judge_health,
)


def _pairs_from_confusion(matrix: dict[tuple[str, str], int]) -> list[tuple[str, str]]:
    """Expand a (authoritative, local) -> count confusion matrix into pairs."""
    pairs: list[tuple[str, str]] = []
    for (authoritative, local), count in matrix.items():
        pairs.extend([(local, authoritative)] * count)
    return pairs


#: The pinned VerifierBench held-set confusion matrix (rows=gold/authoritative,
#: cols=local prediction) from docs/research/2026-06-14-local-judge-validation.md.
#: n=2690 scored; agreement 83.79%; kappa 0.703; false-accept 239 > false-reject 145.
VERIFIERBENCH_CONFUSION: dict[tuple[str, str], int] = {
    ("A", "A"): 947,
    ("A", "B"): 143,
    ("A", "C"): 2,
    ("B", "A"): 207,
    ("B", "B"): 1205,
    ("B", "C"): 35,
    ("C", "A"): 32,
    ("C", "B"): 17,
    ("C", "C"): 102,
}


def _healthy_pairs() -> list[tuple[str, str]]:
    """A synthetic held set that clears every AC3 bar: n=200, agreement 95%,
    kappa 0.90, false-accept 3 < false-reject 7 (conservative-skewed)."""
    return _pairs_from_confusion(
        {
            ("A", "A"): 95,
            ("B", "B"): 95,
            ("A", "B"): 7,  # false-reject (conservative direction)
            ("B", "A"): 3,  # false-accept (dangerous direction)
        }
    )


# --- AC1: the held-set measurement reproduces the published skew ---------------------


def test_held_set_reproduces_verifierbench_false_accept_skew() -> None:
    measure = measure_judge_health(_pairs_from_confusion(VERIFIERBENCH_CONFUSION))
    assert measure.n_pairs == 2690
    assert measure.n_scored == 2690
    assert measure.n_excluded == 0
    assert measure.agreement is not None and round(measure.agreement, 4) == 0.8379
    assert measure.cohen_kappa is not None and round(measure.cohen_kappa, 3) == 0.703
    assert measure.false_accept_count == 239
    assert measure.false_reject_count == 145
    # 239 false-accepts > 145 false-rejects: the dangerous direction dominates.
    assert measure.conservative_skewed is False


def test_measure_excludes_unparseable_locals_from_agreement() -> None:
    # an unparseable local verdict (label "") is a judge failure/escalation — it
    # must not count as agreement, but must stay visible in the counts.
    pairs = [("A", "A"), ("", "A"), ("", "B"), ("B", "B")]
    measure = measure_judge_health(pairs)
    assert measure.n_pairs == 4
    assert measure.n_scored == 2
    assert measure.n_excluded == 2
    assert measure.agreement == 1.0


def test_empty_held_set_yields_no_metrics() -> None:
    measure = measure_judge_health([])
    assert measure.n_scored == 0
    assert measure.agreement is None
    assert measure.cohen_kappa is None
    assert measure.conservative_skewed is False  # fail-closed: no data is not conservative


def test_conservative_skew_definition() -> None:
    # zero false-accepts is conservative even with zero false-rejects
    only_fr = measure_judge_health([("A", "A"), ("B", "A")])  # local B on auth A
    assert only_fr.false_accept_count == 0
    assert only_fr.conservative_skewed is True
    # false-accepts must be strictly fewer than false-rejects
    balanced = measure_judge_health([("A", "B"), ("B", "A")])
    assert balanced.false_accept_count == 1
    assert balanced.false_reject_count == 1
    assert balanced.conservative_skewed is False
    fa_heavy = measure_judge_health([("A", "B"), ("A", "C")])  # two false-accepts
    assert fa_heavy.false_accept_count == 2
    assert fa_heavy.conservative_skewed is False


# --- AC2: promotion gate holds until the request threshold clears --------------------


def test_default_thresholds_pin_the_ac3_request_threshold() -> None:
    assert DEFAULT_JUDGE_HEALTH_THRESHOLDS.min_scored_items == 150
    assert DEFAULT_JUDGE_HEALTH_THRESHOLDS.min_agreement == 0.90
    assert DEFAULT_JUDGE_HEALTH_THRESHOLDS.min_kappa == 0.80
    assert DEFAULT_JUDGE_HEALTH_THRESHOLDS.require_conservative_skew is True


def test_promotion_gate_refuses_the_measured_verifierbench_state() -> None:
    # the published measurement itself must refuse promotion (this is the skew fix:
    # the judge as measured CANNOT be flipped authoritative).
    measure = measure_judge_health(_pairs_from_confusion(VERIFIERBENCH_CONFUSION))
    decision = judge_promotion_gate(measure)
    assert decision.allowed is False
    joined = " ".join(decision.reason_codes)
    assert "judge_agreement_below_floor" in joined
    assert "judge_kappa_below_floor" in joined
    assert "judge_not_conservative_skewed" in joined


def test_promotion_gate_refuses_insufficient_held_set() -> None:
    perfect_but_tiny = measure_judge_health([("A", "A")] * 10)
    decision = judge_promotion_gate(perfect_but_tiny)
    assert decision.allowed is False
    assert any(code.startswith("judge_held_set_insufficient") for code in decision.reason_codes)


def test_promotion_gate_refuses_excluded_rows_even_if_metrics_clear() -> None:
    measure = measure_judge_health([*_healthy_pairs(), ("", "")])
    assert measure.n_scored == 200
    assert measure.n_excluded == 1
    assert measure.agreement is not None and measure.agreement >= 0.90
    assert measure.cohen_kappa is not None and measure.cohen_kappa >= 0.80

    decision = judge_promotion_gate(measure)

    assert decision.allowed is False
    assert "judge_shadow_log_corrupt_rows:1>0" in decision.reason_codes


def test_promotion_gate_refuses_degenerate_single_label_held_set() -> None:
    measure = measure_judge_health([("A", "A")] * 200)
    assert measure.n_scored == 200
    assert measure.degenerate is True
    assert measure.agreement == 1.0
    assert measure.cohen_kappa == 0.0

    decision = judge_promotion_gate(measure)

    assert decision.allowed is False
    assert decision.reason_codes == ("judge_held_set_degenerate:single_label",)


def test_promotion_gate_refuses_missing_held_set() -> None:
    decision = judge_promotion_gate(measure_judge_health([]))
    assert decision.allowed is False
    assert "judge_held_set_missing" in decision.reason_codes


def test_promotion_gate_refuses_low_kappa_despite_high_agreement() -> None:
    # agreement 93% but marginals so skewed kappa collapses to ~0.44: the kappa
    # bar must catch what raw agreement hides. false-accepts are zero, so the
    # ONLY failing bar is kappa.
    pairs = _pairs_from_confusion({("A", "A"): 180, ("B", "B"): 6, ("A", "B"): 14})
    measure = measure_judge_health(pairs)
    assert measure.agreement is not None and measure.agreement >= 0.90
    decision = judge_promotion_gate(measure)
    assert decision.allowed is False
    assert [code.split(":")[0] for code in decision.reason_codes] == ["judge_kappa_below_floor"]


def test_promotion_gate_allows_healthy_held_set() -> None:
    decision = judge_promotion_gate(measure_judge_health(_healthy_pairs()))
    assert decision.allowed is True
    assert decision.reason_codes == ()


def test_promotion_gate_honours_custom_thresholds() -> None:
    thresholds = JudgeHealthThresholds(min_scored_items=1000)
    decision = judge_promotion_gate(measure_judge_health(_healthy_pairs()), thresholds)
    assert decision.allowed is False
    assert any(code.startswith("judge_held_set_insufficient") for code in decision.reason_codes)


# --- the shadow-log loader (council-distribution held set) ---------------------------


def test_load_shadow_pairs_reads_shadow_compare_schema(tmp_path: Path) -> None:
    log = tmp_path / "shadow.jsonl"
    rows = [
        {"local": "A", "authoritative": "A", "agree": True, "false_accept": False},
        {"local": "A", "authoritative": "B", "agree": False, "false_accept": True},
    ]
    log.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    pairs = load_judge_shadow_pairs(log)
    assert pairs == (("A", "A"), ("A", "B"))


def test_load_shadow_pairs_counts_corrupt_lines_as_excluded(tmp_path: Path) -> None:
    log = tmp_path / "shadow.jsonl"
    log.write_text(
        '{"local": "A", "authoritative": "A"}\nnot-json\n\n{"local": null, "authoritative": "A"}\n'
    )
    pairs = load_judge_shadow_pairs(log)
    # corrupt / malformed rows become excluded ("", "") pairs — visible, never silent
    assert pairs == (("A", "A"), ("", ""), ("", ""))
    measure = measure_judge_health(pairs)
    assert measure.n_scored == 1
    assert measure.n_excluded == 2


def test_authoritative_flip_gate_refuses_corrupt_shadow_log_even_when_metrics_clear(
    tmp_path: Path,
) -> None:
    log = tmp_path / "shadow.jsonl"
    with log.open("w") as fh:
        for local, authoritative in _healthy_pairs():
            fh.write(json.dumps({"local": local, "authoritative": authoritative}) + "\n")
        fh.write("not-json\n")

    decision = authoritative_flip_allowed(log_path=log)

    assert decision.allowed is False
    assert decision.measure.n_scored == 200
    assert decision.measure.n_excluded == 1
    assert "judge_shadow_log_corrupt_rows:1>0" in decision.reason_codes


def test_load_shadow_pairs_missing_log_is_empty(tmp_path: Path) -> None:
    assert load_judge_shadow_pairs(tmp_path / "absent.jsonl") == ()


# --- AC2 top entry: the flip gate phase 1 must call ----------------------------------


def test_authoritative_flip_gate_fail_closed_on_missing_log(tmp_path: Path) -> None:
    decision = authoritative_flip_allowed(log_path=tmp_path / "absent.jsonl")
    assert decision.allowed is False
    assert "judge_held_set_missing" in decision.reason_codes


def test_authoritative_flip_gate_clears_on_healthy_shadow_log(tmp_path: Path) -> None:
    log = tmp_path / "shadow.jsonl"
    with log.open("w") as fh:
        for local, authoritative in _healthy_pairs():
            fh.write(json.dumps({"local": local, "authoritative": authoritative}) + "\n")
    decision = authoritative_flip_allowed(log_path=log)
    assert decision.allowed is True
    assert decision.measure.n_scored == 200


# --- AC3: refusal path — unvalidated judge verdicts never move posteriors ------------


def _learning_eligibility() -> LearningEligibility:
    return LearningEligibility.model_validate(
        {
            "thompson_update_allowed": True,
            "local_posterior_update_allowed": True,
            "evidence_kind": "witnessed",
            "evidence_freshness": "fresh",
            "confidence": 0.9,
            "envelope_valid": True,
            "support_only": False,
            "hkp_only": False,
            "public_projection_forbidden": False,
            "evidence_refs": ["witness:route-success"],
        }
    )


def _judge_gate_event(gate_result: str, gate_type: str = "llm_acceptor") -> GateEvent:
    return GateEvent(
        route="local-judge",
        routing_class="verification",
        requirement_vector={
            "quality_floor": 4,
            "information_scope": 3,
            "context_length": 3,
            "mutation_risk": 3,
            "verification_demand": 3,
            "ambiguity_novelty": 2,
            "composition_coupling": 2,
            "governance_sensitivity": 2,
        },
        task_hash="sha256:judge-health-test",
        gate_result=gate_result,  # type: ignore[arg-type]
        gate_type=gate_type,  # type: ignore[arg-type]
        provenance="witnessed",
        ts="2026-07-03T00:00:00+00:00",
        learning_eligibility=_learning_eligibility(),
    )


def test_unvalidated_judge_llm_acceptor_events_never_move_posteriors() -> None:
    router = SdlcRouter()  # no judge promotion evidence: fail-closed
    assert router.record_gate_event(_judge_gate_event("accept")) is False
    assert router.record_gate_event(_judge_gate_event("reject")) is False
    assert router.state.route_posteriors == {}


def test_refused_judge_promotion_also_blocks_llm_acceptor_learning() -> None:
    refused = judge_promotion_gate(measure_judge_health([]))
    router = SdlcRouter(judge_promotion=refused)
    assert router.record_gate_event(_judge_gate_event("accept")) is False
    assert router.state.route_posteriors == {}


def test_validated_judge_llm_acceptor_events_move_posteriors() -> None:
    cleared = judge_promotion_gate(measure_judge_health(_healthy_pairs()))
    assert cleared.allowed is True
    router = SdlcRouter(judge_promotion=cleared)
    assert router.record_gate_event(_judge_gate_event("accept")) is True
    posterior = router.state.posterior_for_read("verification", "local-judge")
    assert posterior.ts_alpha > 2.0


def test_flip_check_cli_exits_refused_on_missing_log(tmp_path: Path, capsys) -> None:
    # the __main__ probe (python -m shared.sdlc_router --shadow-log ...) is the
    # static operator/phase-1 entrypoint for the flip gate: exit 0 = flip allowed,
    # exit 2 = refused, decision JSON on stdout either way.
    from shared.sdlc_router import _judge_flip_check_main

    exit_code = _judge_flip_check_main(["--shadow-log", str(tmp_path / "absent.jsonl")])
    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["allowed"] is False
    assert "judge_held_set_missing" in payload["reason_codes"]


def test_flip_check_cli_exits_zero_on_healthy_log(tmp_path: Path, capsys) -> None:
    from shared.sdlc_router import _judge_flip_check_main

    log = tmp_path / "shadow.jsonl"
    with log.open("w") as fh:
        for local, authoritative in _healthy_pairs():
            fh.write(json.dumps({"local": local, "authoritative": authoritative}) + "\n")
    exit_code = _judge_flip_check_main(["--shadow-log", str(log)])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["allowed"] is True
    assert payload["measure"]["n_scored"] == 200


def test_non_judge_gate_types_learn_without_judge_promotion() -> None:
    # deterministic / gold_verifier / frontier_review verdicts are not the LLM
    # judge — the judge-health gate must not block them.
    router = SdlcRouter()
    for gate_type in ("deterministic", "gold_verifier", "frontier_review"):
        event = _judge_gate_event("accept", gate_type=gate_type)
        assert router.record_gate_event(event) is True, gate_type
