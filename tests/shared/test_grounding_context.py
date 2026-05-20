"""Tests for the grounding context envelope and clause verifier."""

from shared.grounding_context import (
    GroundingContextVerifier,
    TurnVerificationLog,
)


def _stale_envelope(**overrides):
    bands = {"impression": {"freshness": "stale"}}
    return GroundingContextVerifier.build_envelope(
        turn_id="t1", temporal_bands=bands, phenomenal_lines=[], available_tools=[], **overrides
    )


def _fresh_envelope(**overrides):
    bands = {"impression": {"freshness": "fresh"}}
    return GroundingContextVerifier.build_envelope(
        turn_id="t1",
        temporal_bands=bands,
        phenomenal_lines=["Fresh env"],
        available_tools=[],
        **overrides,
    )


def _protention_envelope():
    bands = {"impression": {"freshness": "missing"}, "protention": {"expected": "event"}}
    return GroundingContextVerifier.build_envelope(
        turn_id="t1", temporal_bands=bands, phenomenal_lines=[], available_tools=[]
    )


class TestBuildEnvelope:
    def test_fresh_no_forbidden(self):
        envelope = _fresh_envelope()
        assert envelope.source_freshness == "fresh"
        assert not envelope.forbidden_assertions

    def test_stale_forbidden_assertions(self):
        envelope = _stale_envelope()
        assert envelope.source_freshness == "stale"
        assert "present-tense current-world factual claims" in envelope.forbidden_assertions
        assert (
            "live deictic visual references without visual tool output"
            in envelope.forbidden_assertions
        )

    def test_protention_forbidden(self):
        envelope = _protention_envelope()
        assert (
            "protention stated as fact without anticipatory language"
            in envelope.forbidden_assertions
        )

    def test_context_hash_is_sha256(self):
        e = _stale_envelope()
        assert len(e.context_hash) == 64
        assert all(c in "0123456789abcdef" for c in e.context_hash)

    def test_recruited_tools_in_envelope(self):
        envelope = _fresh_envelope(recruited_tools=["search_web", "read_calendar"])
        assert envelope.recruited_tools == ["search_web", "read_calendar"]


class TestRenderXml:
    def test_xml_contains_freshness(self):
        xml = GroundingContextVerifier.render_xml(_stale_envelope())
        assert "<source_freshness>stale</source_freshness>" in xml

    def test_xml_contains_recruited_tools(self):
        envelope = _fresh_envelope(recruited_tools=["search_web"])
        xml = GroundingContextVerifier.render_xml(envelope)
        assert "<tool>search_web</tool>" in xml

    def test_xml_contains_forbidden(self):
        xml = GroundingContextVerifier.render_xml(_stale_envelope())
        assert "<forbidden>" in xml

    def test_xml_contains_phenomenal(self):
        xml = GroundingContextVerifier.render_xml(_fresh_envelope())
        assert "Fresh env" in xml


class TestVerifyClauseStaleNow:
    def test_blocks_now(self):
        is_safe, reason = GroundingContextVerifier.verify_clause(
            _stale_envelope(), "The system is currently stable."
        )
        assert not is_safe
        assert reason == "stale impression cannot ground 'now' or 'currently'"

    def test_blocks_live(self):
        is_safe, _ = GroundingContextVerifier.verify_clause(
            _stale_envelope(), "The live feed shows activity."
        )
        assert not is_safe

    def test_allows_past(self):
        is_safe, reason = GroundingContextVerifier.verify_clause(
            _stale_envelope(), "It happened yesterday."
        )
        assert is_safe

    def test_allows_now_when_fresh(self):
        is_safe, _ = GroundingContextVerifier.verify_clause(
            _fresh_envelope(), "The system is currently stable."
        )
        assert is_safe


class TestVerifyClauseProtentionNotFact:
    def test_blocks_factual_statement(self):
        is_safe, reason = GroundingContextVerifier.verify_clause(
            _protention_envelope(), "The event is happening."
        )
        assert not is_safe
        assert reason == "protention stated as fact"

    def test_allows_anticipatory_language(self):
        is_safe, _ = GroundingContextVerifier.verify_clause(
            _protention_envelope(), "The event is likely to happen."
        )
        assert is_safe

    def test_allows_could(self):
        is_safe, _ = GroundingContextVerifier.verify_clause(
            _protention_envelope(), "The event could unfold differently."
        )
        assert is_safe


class TestVerifyClauseDeicticVisual:
    def test_blocks_look_at_this(self):
        is_safe, reason = GroundingContextVerifier.verify_clause(
            _stale_envelope(), "Take a look at this."
        )
        assert not is_safe
        assert reason == "ungrounded deictic visual reference"

    def test_blocks_on_screen_now(self):
        is_safe, _ = GroundingContextVerifier.verify_clause(
            _stale_envelope(), "The data on screen now confirms it."
        )
        assert not is_safe

    def test_allows_non_visual_this(self):
        is_safe, _ = GroundingContextVerifier.verify_clause(
            _stale_envelope(), "This is an interesting idea."
        )
        assert is_safe


class TestStructuredVerdict:
    def test_safe_verdict(self):
        v = GroundingContextVerifier.verify_clause_structured(
            _fresh_envelope(), "All systems nominal."
        )
        assert v.kind == "safe"
        assert v.reason is None

    def test_refused_verdict_has_correction(self):
        v = GroundingContextVerifier.verify_clause_structured(
            _stale_envelope(), "The system is currently online."
        )
        assert v.kind == "refused"
        assert v.corrected is not None
        assert "temporal impression" in v.corrected

    def test_corrected_verdict_for_protention(self):
        v = GroundingContextVerifier.verify_clause_structured(
            _protention_envelope(), "The update is deploying."
        )
        assert v.kind == "corrected"
        assert v.corrected is not None
        assert "anticipated" in v.corrected

    def test_deictic_refusal_has_correction(self):
        v = GroundingContextVerifier.verify_clause_structured(
            _stale_envelope(), "Look at this data."
        )
        assert v.kind == "refused"
        assert "tool output" in v.corrected


class TestTurnVerificationLog:
    def test_log_counts(self):
        envelope = _stale_envelope()
        verdicts = [
            GroundingContextVerifier.verify_clause_structured(
                envelope, "Safe sentence about history."
            ),
            GroundingContextVerifier.verify_clause_structured(
                envelope, "The system is currently up."
            ),
            GroundingContextVerifier.verify_clause_structured(envelope, "Look at this chart."),
        ]
        entry = GroundingContextVerifier.log_turn_verification(envelope, verdicts)
        assert isinstance(entry, TurnVerificationLog)
        assert entry.turn_id == "t1"
        assert entry.context_hash == envelope.context_hash
        assert entry.clauses_checked == 3
        assert entry.clauses_safe == 1
        assert entry.clauses_refused == 2

    def test_log_empty_turn(self):
        entry = GroundingContextVerifier.log_turn_verification(_fresh_envelope(), [])
        assert entry.clauses_checked == 0
        assert entry.clauses_safe == 0


class TestOutputChangesNotPromptOnly:
    """A/B fixture: verify that the verifier changes OUTPUT (refused/corrected
    clauses produce different speech), not just the prompt XML."""

    def test_same_sentence_different_envelope_different_output(self):
        sentence = "The system is currently running smoothly."
        fresh_v = GroundingContextVerifier.verify_clause_structured(_fresh_envelope(), sentence)
        stale_v = GroundingContextVerifier.verify_clause_structured(_stale_envelope(), sentence)
        assert fresh_v.kind == "safe"
        assert stale_v.kind == "refused"
        assert stale_v.corrected != sentence

    def test_correction_is_speakable(self):
        v = GroundingContextVerifier.verify_clause_structured(
            _stale_envelope(), "The feed is live now."
        )
        assert v.kind == "refused"
        assert v.corrected
        assert len(v.corrected) > 10
        assert v.corrected.endswith(".")
