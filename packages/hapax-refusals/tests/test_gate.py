"""RefusalGate + refuse_and_reroll tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from hapax_refusals.claim import ClaimSpec
from hapax_refusals.gate import (
    RefusalGate,
    RefusalResult,
    claim_discipline_score,
    parse_emitted_propositions,
    refuse_and_reroll,
)
from hapax_refusals.registry import RefusalRegistry


def _claim(
    name: str = "vinyl_is_playing",
    posterior: float = 0.75,
    proposition: str = "Vinyl is currently playing.",
) -> ClaimSpec:
    return ClaimSpec(name=name, posterior=posterior, proposition=proposition)


# ── parse_emitted_propositions ─────────────────────────────────────


class TestParseEmittedPropositions:
    def test_empty_returns_empty(self) -> None:
        assert parse_emitted_propositions("") == []
        assert parse_emitted_propositions("   ") == []

    def test_single_sentence(self) -> None:
        assert parse_emitted_propositions("Vinyl is playing.") == ["Vinyl is playing."]

    def test_multiple_sentences(self) -> None:
        text = "Vinyl is playing. The mood is rising! Why now?"
        # Question is dropped.
        assert parse_emitted_propositions(text) == [
            "Vinyl is playing.",
            "The mood is rising!",
        ]

    def test_skips_unknown_marker(self) -> None:
        text = "Vinyl is playing. [UNKNOWN] something hidden."
        out = parse_emitted_propositions(text)
        assert "Vinyl is playing." in out
        assert all("[UNKNOWN]" not in s for s in out)

    def test_strips_envelope_markers(self) -> None:
        text = "[p=0.92 src=ir_hand_zone] Vinyl is playing."
        out = parse_emitted_propositions(text)
        assert out == ["Vinyl is playing."]


# ── RefusalGate.check ──────────────────────────────────────────────


class TestRefusalGateCheck:
    def test_construction_unknown_surface_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown surface"):
            RefusalGate(surface="bogus")  # type: ignore[arg-type]

    def test_construction_uses_default_floor(self, tmp_path: Path) -> None:
        gate = RefusalGate(
            surface="director",
            registry=RefusalRegistry(log_path=tmp_path / "log.jsonl"),
        )
        assert gate.floor == 0.60

    def test_floor_override(self, tmp_path: Path) -> None:
        gate = RefusalGate(
            surface="director",
            floor=0.95,
            registry=RefusalRegistry(log_path=tmp_path / "log.jsonl"),
        )
        assert gate.floor == 0.95

    def test_floor_override_out_of_range_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="floor must be in"):
            RefusalGate(
                surface="director",
                floor=1.5,
                registry=RefusalRegistry(log_path=tmp_path / "log.jsonl"),
            )

    def test_empty_text_accepted(self, tmp_path: Path) -> None:
        gate = RefusalGate(
            surface="director",
            registry=RefusalRegistry(log_path=tmp_path / "log.jsonl"),
        )
        result = gate.check("", available_claims=[])
        assert result.accepted is True

    def test_question_only_accepted(self, tmp_path: Path) -> None:
        gate = RefusalGate(
            surface="director",
            registry=RefusalRegistry(log_path=tmp_path / "log.jsonl"),
        )
        result = gate.check("What about the vinyl?", available_claims=[])
        assert result.accepted is True

    def test_above_floor_claim_accepted(self, tmp_path: Path) -> None:
        gate = RefusalGate(
            surface="director",
            registry=RefusalRegistry(log_path=tmp_path / "log.jsonl"),
        )
        result = gate.check(
            "Vinyl is playing.",
            available_claims=[_claim(posterior=0.92)],
        )
        assert result.accepted is True
        assert result.rejected_propositions == []

    def test_below_floor_claim_rejected(self, tmp_path: Path) -> None:
        gate = RefusalGate(
            surface="director",
            registry=RefusalRegistry(log_path=tmp_path / "log.jsonl"),
        )
        result = gate.check(
            "Vinyl is playing.",
            available_claims=[_claim(posterior=0.42)],
        )
        assert result.accepted is False
        assert "Vinyl is playing." in result.rejected_propositions
        assert "below the director floor of 0.60" in result.reroll_prompt_addendum

    def test_unmatched_assertion_rejected(self, tmp_path: Path) -> None:
        gate = RefusalGate(
            surface="director",
            registry=RefusalRegistry(log_path=tmp_path / "log.jsonl"),
        )
        result = gate.check(
            "The vinyl is playing.",
            available_claims=[],  # no claims at all
        )
        assert result.accepted is False

    def test_hedge_phrase_accepted(self, tmp_path: Path) -> None:
        gate = RefusalGate(
            surface="director",
            registry=RefusalRegistry(log_path=tmp_path / "log.jsonl"),
        )
        # Even with no matching claim, "appears to" hedges out the assertion.
        result = gate.check(
            "Vinyl appears to be playing.",
            available_claims=[],
        )
        assert result.accepted is True

    def test_per_surface_floor_asymmetry(self, tmp_path: Path) -> None:
        # 0.65 posterior — passes director (0.60), fails grounding-act (0.90).
        director_gate = RefusalGate(
            surface="director",
            registry=RefusalRegistry(log_path=tmp_path / "d.jsonl"),
        )
        grounding_gate = RefusalGate(
            surface="grounding_act",
            registry=RefusalRegistry(log_path=tmp_path / "g.jsonl"),
        )
        text = "Vinyl is playing."
        claim = _claim(posterior=0.65)

        d_result = director_gate.check(text, available_claims=[claim])
        g_result = grounding_gate.check(text, available_claims=[claim])
        assert d_result.accepted is True
        assert g_result.accepted is False

    def test_logs_to_registry_on_rejection(self, tmp_path: Path) -> None:
        log = tmp_path / "log.jsonl"
        gate = RefusalGate(surface="director", registry=RefusalRegistry(log_path=log))
        gate.check(
            "Vinyl is playing.",
            available_claims=[_claim(posterior=0.42)],
        )
        assert log.exists()
        assert log.read_text().strip() != ""

    def test_log_refusals_false_skips_log(self, tmp_path: Path) -> None:
        log = tmp_path / "log.jsonl"
        gate = RefusalGate(surface="director", registry=RefusalRegistry(log_path=log))
        gate.check(
            "Vinyl is playing.",
            available_claims=[_claim(posterior=0.42)],
            log_refusals=False,
        )
        # File is not created when logging is suppressed.
        assert not log.exists()


# ── claim_discipline_score ─────────────────────────────────────────


class TestClaimDisciplineScore:
    def test_accepted_is_one(self) -> None:
        assert claim_discipline_score(RefusalResult(accepted=True)) == 1.0

    def test_rejected_is_zero(self) -> None:
        assert (
            claim_discipline_score(RefusalResult(accepted=False, rejected_propositions=["x"]))
            == 0.0
        )


# ── refuse_and_reroll ──────────────────────────────────────────────


class TestRefuseAndReroll:
    def test_first_pass_accepted_no_reroll(self, tmp_path: Path) -> None:
        gate = RefusalGate(
            surface="director",
            registry=RefusalRegistry(log_path=tmp_path / "log.jsonl"),
        )
        attempts_log: list[str | None] = []

        def call(addendum: str | None) -> str:
            attempts_log.append(addendum)
            return "Vinyl is playing."

        text, result, attempts = refuse_and_reroll(
            call,
            gate=gate,
            available_claims=[_claim(posterior=0.92)],
        )
        assert result.accepted is True
        assert attempts == 1
        assert attempts_log == [None]
        assert text == "Vinyl is playing."

    def test_reroll_accepts_after_one_retry(self, tmp_path: Path) -> None:
        gate = RefusalGate(
            surface="director",
            registry=RefusalRegistry(log_path=tmp_path / "log.jsonl"),
        )
        attempts_log: list[str | None] = []
        responses = [
            "Vinyl is playing.",  # gets rejected (posterior below floor)
            "Vinyl appears to be playing.",  # hedged → accepted
        ]

        def call(addendum: str | None) -> str:
            attempts_log.append(addendum)
            return responses[len(attempts_log) - 1]

        text, result, attempts = refuse_and_reroll(
            call,
            gate=gate,
            available_claims=[_claim(posterior=0.42)],
            max_rerolls=1,
        )
        assert result.accepted is True
        assert attempts == 2
        assert attempts_log[0] is None
        # Second call received the addendum from the gate.
        assert attempts_log[1] is not None
        assert "below the director floor" in attempts_log[1]
        assert text == "Vinyl appears to be playing."

    def test_all_rerolls_rejected_returns_last_text(self, tmp_path: Path) -> None:
        gate = RefusalGate(
            surface="director",
            registry=RefusalRegistry(log_path=tmp_path / "log.jsonl"),
        )

        def call(addendum: str | None) -> str:
            return "Vinyl is playing."

        text, result, attempts = refuse_and_reroll(
            call,
            gate=gate,
            available_claims=[_claim(posterior=0.42)],
            max_rerolls=2,
        )
        assert result.accepted is False
        assert attempts == 3  # 1 initial + 2 rerolls
        assert text == "Vinyl is playing."

    def test_max_rerolls_zero_is_one_shot(self, tmp_path: Path) -> None:
        gate = RefusalGate(
            surface="director",
            registry=RefusalRegistry(log_path=tmp_path / "log.jsonl"),
        )
        calls = 0

        def call(addendum: str | None) -> str:
            nonlocal calls
            calls += 1
            return "Vinyl is playing."

        _text, result, attempts = refuse_and_reroll(
            call,
            gate=gate,
            available_claims=[_claim(posterior=0.42)],
            max_rerolls=0,
        )
        assert result.accepted is False
        assert attempts == 1
        assert calls == 1

    def test_max_rerolls_negative_raises(self, tmp_path: Path) -> None:
        gate = RefusalGate(
            surface="director",
            registry=RefusalRegistry(log_path=tmp_path / "log.jsonl"),
        )

        with pytest.raises(ValueError, match="max_rerolls must be"):
            refuse_and_reroll(
                lambda _addendum: "x",
                gate=gate,
                available_claims=[],
                max_rerolls=-1,
            )

    def test_log_refusals_false_propagates(self, tmp_path: Path) -> None:
        log = tmp_path / "log.jsonl"
        gate = RefusalGate(surface="director", registry=RefusalRegistry(log_path=log))

        def call(_addendum: str | None) -> str:
            return "Vinyl is playing."

        refuse_and_reroll(
            call,
            gate=gate,
            available_claims=[_claim(posterior=0.42)],
            max_rerolls=2,
            log_refusals=False,
        )
        assert not log.exists()
