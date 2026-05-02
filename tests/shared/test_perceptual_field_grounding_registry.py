"""Tests for the PerceptualField grounding key registry."""

from __future__ import annotations

import time

from shared.perceptual_field_grounding_registry import (
    FieldEvidence,
    GroundingDecision,
    default_registry,
)

NOW_MS = 1_777_602_000_000.0  # fixed test instant in ms


def test_default_registry_covers_first_tranche_categories() -> None:
    """The first-tranche fixture must include rows for the high-risk
    categories the spec calls out: track/music (track + source +
    confidence + vinyl_state), stream live + mode + egress + broadcast
    safety, chat, operator presence, camera classification, HOMAGE,
    reactions."""

    reg = default_registry()
    paths = {row.key_path for row in reg.rows}
    expected = {
        "current_track",
        "music.source",
        "music.confidence",
        "music.vinyl_state",
        "stream_live",
        "stream.mode",
        "stream.egress",
        "stream.broadcast_safety",
        "chat.recent_count",
        "presence.operator_present",
        "camera.classifications",
        "homage.active_artefact",
        "reactions.recent",
    }
    assert expected.issubset(paths), f"missing: {expected - paths}"


def test_music_and_stream_extension_rows_have_required_shape() -> None:
    """The 6 newly-added music + stream rows must declare full witness
    shape: TTL, witness_kind, public_scope, failure_policy, allowed
    consumers. Catches drift if a row is added without the full
    contract."""

    reg = default_registry()
    by_path = {row.key_path: row for row in reg.rows}
    new_paths = (
        "music.source",
        "music.confidence",
        "music.vinyl_state",
        "stream.mode",
        "stream.egress",
        "stream.broadcast_safety",
    )
    for path in new_paths:
        row = by_path[path]
        assert row.ttl_ms > 0, f"{path}: TTL must be positive"
        assert row.witness_kind, f"{path}: witness_kind required"
        assert row.public_scope, f"{path}: public_scope required"
        assert row.allowed_consumers, f"{path}: at least one consumer required"
        assert row.failure_policy, f"{path}: failure_policy required"
        # All high-risk public-live rows fail-closed on synthetic-only
        if row.public_scope == "public-live-only-with-witness":
            assert row.failure_policy.get("synthetic-only") == "fail-closed", (
                f"{path}: public-live rows must fail-closed on synthetic-only"
            )


def test_stream_egress_and_broadcast_safety_share_audio_health_surface() -> None:
    """Both stream.egress and stream.broadcast_safety project from the
    audio.broadcast_health WCS substrate registered in #2166. Ensures
    the registry stays consistent with the WCS row's surface_id."""

    reg = default_registry()
    by_path = {row.key_path: row for row in reg.rows}
    assert by_path["stream.egress"].wcs_surface_id == "audio.broadcast_health"
    assert by_path["stream.broadcast_safety"].wcs_surface_id == "audio.broadcast_health"


def test_diagnostic_only_prefixes_block_unconditionally() -> None:
    reg = default_registry()
    for prefix in (
        "inferred.something",
        "parser_fallback.foo",
        "silence_hold.bar",
        "synthetic.x",
        "decorative.y",
        "classifier_fallback.z",
        "protention.next",
        "stale_retention.w",
    ):
        evidence = FieldEvidence(key_path=prefix, value_present=True)
        decision = reg.evaluate(evidence, "director")
        assert not decision.admitted
        assert decision.effective_authority == "none"
        assert decision.rendering == "do-not-render"


def test_unknown_key_path_is_hard_blocked() -> None:
    reg = default_registry()
    evidence = FieldEvidence(key_path="not.a.real.key", value_present=True)
    decision = reg.evaluate(evidence, "director")
    assert not decision.admitted
    assert "missing" in decision.triggered_failures


def test_consumer_not_in_allowed_list_is_blocked() -> None:
    reg = default_registry()
    # `homage.active_artefact` allows director / autonomous-narration /
    # content-programme / dashboard, but NOT private-voice.
    evidence = FieldEvidence(
        key_path="homage.active_artefact",
        value_present=True,
        captured_at_ms=NOW_MS,
        span_ref="span:abc",
    )
    decision = reg.evaluate(evidence, "private-voice", now_ms=NOW_MS)
    assert not decision.admitted
    assert "private-route-requested-public" in decision.triggered_failures


def test_fresh_evidence_with_witness_admits() -> None:
    reg = default_registry()
    evidence = FieldEvidence(
        key_path="current_track",
        value_present=True,
        captured_at_ms=NOW_MS,
        span_ref="span:abc",
        witness_ref="witness:xyz",
    )
    decision = reg.evaluate(evidence, "public-broadcast", now_ms=NOW_MS)
    assert decision.admitted
    assert decision.effective_authority == "public-live"
    assert decision.rendering == "render-with-age-and-window"


def test_stale_evidence_fails_for_high_risk_row() -> None:
    reg = default_registry()
    # stream_live is high-risk; ttl_ms=5000. Set captured_at 30s ago.
    evidence = FieldEvidence(
        key_path="stream_live",
        value_present=True,
        captured_at_ms=NOW_MS - 30_000,
        span_ref="span:abc",
    )
    decision = reg.evaluate(evidence, "public-broadcast", now_ms=NOW_MS)
    assert not decision.admitted
    assert "stale" in decision.triggered_failures


def test_synthetic_evidence_fails_closed() -> None:
    reg = default_registry()
    evidence = FieldEvidence(
        key_path="current_track",
        value_present=True,
        captured_at_ms=NOW_MS,
        span_ref="span:abc",
        is_synthetic=True,
    )
    decision = reg.evaluate(evidence, "public-broadcast", now_ms=NOW_MS)
    assert not decision.admitted
    assert "synthetic-only" in decision.triggered_failures


def test_spanless_high_risk_evidence_fails_when_span_required() -> None:
    reg = default_registry()
    evidence = FieldEvidence(
        key_path="current_track",
        value_present=True,
        captured_at_ms=NOW_MS,
        span_ref=None,  # required by the row
    )
    decision = reg.evaluate(evidence, "public-broadcast", now_ms=NOW_MS)
    assert not decision.admitted
    assert "spanless" in decision.triggered_failures


def test_low_risk_stale_evidence_renders_as_diagnostic_not_blocked() -> None:
    """chat.recent_count is low-risk; stale evidence should render
    diagnostically rather than fail closed."""

    reg = default_registry()
    evidence = FieldEvidence(
        key_path="chat.recent_count",
        value_present=True,
        captured_at_ms=NOW_MS - 600_000,  # 10 min old, ttl_ms=60_000
    )
    decision = reg.evaluate(evidence, "director", now_ms=NOW_MS)
    assert "stale" in decision.triggered_failures
    # admitted because policy is render-as-diagnostic (not fail-closed)
    assert decision.admitted
    assert decision.rendering == "render-as-diagnostic-block"
    assert decision.effective_authority == "diagnostic"


def test_protention_treated_as_fact_fails_closed() -> None:
    """A row that's normally claimable becomes nonclaimable when the
    caller marks the value as a future projection presented as fact."""

    reg = default_registry()
    evidence = FieldEvidence(
        key_path="current_track",
        value_present=True,
        captured_at_ms=NOW_MS,
        span_ref="span:abc",
        is_protention=True,
    )
    decision = reg.evaluate(evidence, "public-broadcast", now_ms=NOW_MS)
    assert not decision.admitted
    assert "protention-as-fact" in decision.triggered_failures


def test_private_only_row_blocked_for_public_broadcast() -> None:
    """presence.operator_present has public_scope=never-public; even with
    perfect evidence, the public-broadcast consumer must not get it."""

    reg = default_registry()
    evidence = FieldEvidence(
        key_path="presence.operator_present",
        value_present=True,
        captured_at_ms=NOW_MS,
        span_ref="span:abc",
    )
    # public-broadcast is not in allowed_consumers for this row
    decision = reg.evaluate(evidence, "public-broadcast", now_ms=NOW_MS)
    assert not decision.admitted
    assert "private-route-requested-public" in decision.triggered_failures


def test_all_first_tranche_rows_have_complete_failure_policy() -> None:
    """Every first-tranche row must define a policy for every failure
    mode, so the registry never falls back to undefined behaviour."""

    expected_modes = {
        "missing",
        "stale",
        "malformed",
        "spanless",
        "contradictory",
        "synthetic-only",
        "inferred-only",
        "parser-fallback",
        "private-route-requested-public",
        "protention-as-fact",
    }
    reg = default_registry()
    for row in reg.rows:
        defined = set(row.failure_policy.keys())
        missing = expected_modes - defined
        assert not missing, f"{row.key_path} missing policy for: {missing}"


def test_registry_row_public_safe_classifies_high_authority_correctly() -> None:
    reg = default_registry()
    by_path = reg.by_key_path()
    # current_track — public_scope=public-live-only-with-witness +
    # authority_ceiling=public-live → public-safe
    assert by_path["current_track"].public_safe()
    # presence.operator_present — public_scope=never-public → NOT public-safe
    assert not by_path["presence.operator_present"].public_safe()


def test_grounding_decision_hard_blocked_factory() -> None:
    decision = GroundingDecision.hard_blocked(
        key_path="some.key",
        consumer="director",
        failures=("missing",),
        reason="test",
    )
    assert not decision.admitted
    assert decision.effective_authority == "none"
    assert decision.rendering == "do-not-render"


def test_real_time_evaluation_with_default_clock() -> None:
    """Smoke test that the registry's default-clock path works without
    explicit now_ms (uses time.time() * 1000)."""

    reg = default_registry()
    evidence = FieldEvidence(
        key_path="current_track",
        value_present=True,
        captured_at_ms=time.time() * 1000,
        span_ref="span:abc",
    )
    decision = reg.evaluate(evidence, "director")
    assert decision.admitted
