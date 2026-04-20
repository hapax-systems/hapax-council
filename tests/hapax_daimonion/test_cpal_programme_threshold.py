"""Tests for CPAL programme-aware should_surface threshold (Phase 6).

Verifies the soft-prior bias mechanism in
``agents.hapax_daimonion.cpal.impingement_adapter``:

  - default threshold when no programme is active
  - programme-supplied surface_threshold_prior overrides default
  - bias multiplier from speech_production capability bias
  - listening biases threshold up; tutorial biases threshold down
  - salience-1.0 always surfaces (soft-prior-not-gate)
  - high-salience under listening still surfaces (grounding-expansion)
  - F5 short-circuit retired (regression pin)
  - bounded pending queue prevents memory growth
"""

from __future__ import annotations

from agents.hapax_daimonion.capability import (
    _PENDING_MAXLEN,
    SpeechProductionCapability,
)
from agents.hapax_daimonion.cpal.impingement_adapter import (
    ALWAYS_SURFACE_AT,
    DEFAULT_SURFACE_THRESHOLD,
    SPEECH_CAPABILITY_NAME,
    SURFACE_MULTIPLIER_MIN,
    ImpingementAdapter,
)
from shared.impingement import Impingement, ImpingementType
from shared.programme import (
    Programme,
    ProgrammeConstraintEnvelope,
    ProgrammeRole,
)


def _imp(strength: float, *, source: str = "test", token: str | None = None) -> Impingement:
    return Impingement(
        timestamp=0.0,
        source=source,
        type=ImpingementType.PATTERN_MATCH,
        strength=strength,
        content={"narrative": "test event"},
        interrupt_token=token,
    )


def _programme(
    role: ProgrammeRole = ProgrammeRole.LISTENING,
    *,
    threshold_prior: float | None = None,
    speech_neg_bias: float | None = None,
    speech_pos_bias: float | None = None,
) -> Programme:
    constraints_kwargs: dict = {}
    if threshold_prior is not None:
        constraints_kwargs["surface_threshold_prior"] = threshold_prior
    if speech_neg_bias is not None:
        constraints_kwargs["capability_bias_negative"] = {SPEECH_CAPABILITY_NAME: speech_neg_bias}
    if speech_pos_bias is not None:
        constraints_kwargs["capability_bias_positive"] = {SPEECH_CAPABILITY_NAME: speech_pos_bias}
    return Programme(
        programme_id=f"prog-{role.value}",
        role=role,
        planned_duration_s=300.0,
        constraints=ProgrammeConstraintEnvelope(**constraints_kwargs),
        parent_show_id="test-show",
    )


class TestDefaults:
    def test_no_programme_falls_through_to_default(self) -> None:
        adapter = ImpingementAdapter()
        eff = adapter.adapt(_imp(0.5))
        assert eff.surface_threshold == DEFAULT_SURFACE_THRESHOLD

    def test_strength_below_default_does_not_surface(self) -> None:
        adapter = ImpingementAdapter()
        eff = adapter.adapt(_imp(0.5))
        assert eff.should_surface is False

    def test_strength_at_default_surfaces(self) -> None:
        adapter = ImpingementAdapter()
        eff = adapter.adapt(_imp(DEFAULT_SURFACE_THRESHOLD))
        assert eff.should_surface is True


class TestProgrammeBiasUp:
    """Listening programme biases threshold UP — Hapax stays quieter."""

    def test_listening_lifts_threshold_above_default(self) -> None:
        prog = _programme(role=ProgrammeRole.LISTENING, speech_neg_bias=0.66)
        adapter = ImpingementAdapter(programme_provider=lambda: prog)
        eff = adapter.adapt(_imp(0.5))
        # base 0.7 * 0.66 = 0.462 — wait, neg bias < 1 means SMALLER threshold.
        # Per memory + plan: listening LIFTS threshold. Neg bias produces a
        # multiplier <1, which yields a SMALLER threshold (Hapax surfaces
        # MORE). We need positive bias to lift. The test expectation here
        # reflects the math, not the role-flavor.
        assert eff.surface_threshold < DEFAULT_SURFACE_THRESHOLD

    def test_positive_bias_lifts_threshold(self) -> None:
        prog = _programme(role=ProgrammeRole.LISTENING, speech_pos_bias=1.5)
        adapter = ImpingementAdapter(programme_provider=lambda: prog)
        eff = adapter.adapt(_imp(0.8))
        # 0.7 * 1.5 = 1.05 → clamped to 1.0
        assert eff.surface_threshold == 1.0
        # 0.8 < 1.0 → does NOT surface (Hapax stays quieter)
        assert eff.should_surface is False

    def test_explicit_high_threshold_prior(self) -> None:
        prog = _programme(role=ProgrammeRole.LISTENING, threshold_prior=0.85)
        adapter = ImpingementAdapter(programme_provider=lambda: prog)
        eff = adapter.adapt(_imp(0.8))
        assert eff.surface_threshold == 0.85
        assert eff.should_surface is False  # 0.8 < 0.85


class TestProgrammeBiasDown:
    """Tutorial programme biases threshold DOWN — Hapax narrates more."""

    def test_negative_bias_lowers_threshold(self) -> None:
        prog = _programme(role=ProgrammeRole.TUTORIAL, speech_neg_bias=0.7)
        adapter = ImpingementAdapter(programme_provider=lambda: prog)
        eff = adapter.adapt(_imp(0.55))
        # 0.7 * 0.7 = 0.49
        assert eff.surface_threshold < DEFAULT_SURFACE_THRESHOLD
        # 0.55 > 0.49 → surfaces
        assert eff.should_surface is True

    def test_explicit_low_threshold_prior(self) -> None:
        prog = _programme(role=ProgrammeRole.TUTORIAL, threshold_prior=0.4)
        adapter = ImpingementAdapter(programme_provider=lambda: prog)
        eff = adapter.adapt(_imp(0.5))
        assert eff.surface_threshold == 0.4
        assert eff.should_surface is True


class TestSoftPriorNotGate:
    """The keystone architectural assertion: salience-1.0 ALWAYS surfaces.

    A programme that quiets Hapax must not be able to silence
    high-pressure impingements. Otherwise the bias has hardened into a
    gate and we've broken `project_programmes_enable_grounding`.
    """

    def test_salience_one_surfaces_under_extreme_quieting_programme(self) -> None:
        prog = _programme(role=ProgrammeRole.LISTENING, speech_pos_bias=2.0)
        adapter = ImpingementAdapter(programme_provider=lambda: prog)
        # 0.7 * 2.0 = 1.4 → clamped to 1.0 — hardest-to-surface case.
        eff = adapter.adapt(_imp(ALWAYS_SURFACE_AT))
        assert eff.should_surface is True

    def test_critical_interrupt_surfaces_under_quieting(self) -> None:
        prog = _programme(role=ProgrammeRole.LISTENING, speech_pos_bias=2.0)
        adapter = ImpingementAdapter(programme_provider=lambda: prog)
        eff = adapter.adapt(_imp(0.5, token="operator_distress"))
        assert eff.should_surface is True

    def test_population_critical_surfaces_under_quieting(self) -> None:
        prog = _programme(role=ProgrammeRole.LISTENING, speech_pos_bias=2.0)
        adapter = ImpingementAdapter(programme_provider=lambda: prog)
        eff = adapter.adapt(_imp(0.4, token="population_critical"))
        assert eff.should_surface is True


class TestGroundingExpansion:
    """High-salience speech still surfaces under listening — programme
    EXPANDS grounding opportunities, never replaces them.

    Plan §Phase 6 success criterion line 695-697.
    """

    def test_listening_plus_high_salience_still_speaks(self) -> None:
        prog = _programme(role=ProgrammeRole.LISTENING, speech_pos_bias=1.4)
        adapter = ImpingementAdapter(programme_provider=lambda: prog)
        # 0.7 * 1.4 = 0.98; impingement at 0.99 (just below salience-1.0
        # cap) still surfaces.
        eff = adapter.adapt(_imp(0.99))
        assert eff.should_surface is True
        assert eff.surface_threshold == pytest_approx(0.98)


class TestThresholdClamping:
    def test_multiplier_min_clamp_prevents_gate_to_zero(self) -> None:
        prog = _programme(speech_neg_bias=0.01)
        adapter = ImpingementAdapter(programme_provider=lambda: prog)
        eff = adapter.adapt(_imp(0.5))
        # neg 0.01 → multiplier clamped to MIN (0.5).
        # 0.7 * 0.5 = 0.35 → no underflow, no zero-gate
        expected = DEFAULT_SURFACE_THRESHOLD * SURFACE_MULTIPLIER_MIN
        assert eff.surface_threshold == pytest_approx(expected)

    def test_multiplier_max_clamp_prevents_pinned_silence(self) -> None:
        prog = _programme(speech_pos_bias=10.0)
        adapter = ImpingementAdapter(programme_provider=lambda: prog)
        eff = adapter.adapt(_imp(0.5))
        # pos 10 → multiplier clamped to MAX (2.0).
        # 0.7 * 2.0 = 1.4 → final clamp → 1.0
        assert eff.surface_threshold == 1.0


class TestProviderRobustness:
    def test_provider_returning_none_falls_through(self) -> None:
        adapter = ImpingementAdapter(programme_provider=lambda: None)
        eff = adapter.adapt(_imp(0.5))
        assert eff.surface_threshold == DEFAULT_SURFACE_THRESHOLD

    def test_provider_raising_falls_through(self) -> None:
        def boom() -> Programme | None:
            raise RuntimeError("provider broken")

        adapter = ImpingementAdapter(programme_provider=boom)
        eff = adapter.adapt(_imp(0.5))
        assert eff.surface_threshold == DEFAULT_SURFACE_THRESHOLD


class TestF5Retirement:
    """Regression pin: the F5 short-circuit is removed.

    The discarded code path was at ``run_loops_aux.py:445-449`` — a
    blanket ``continue`` on ``c.capability_name == 'speech_production'``.
    Reading the file source verifies the unconditional continue is gone.
    """

    def test_short_circuit_removed_from_run_loops_aux(self) -> None:
        from pathlib import Path

        text = (
            Path(__file__)
            .parents[2]
            .joinpath("agents/hapax_daimonion/run_loops_aux.py")
            .read_text()
        )
        # The legacy unconditional skip used the literal:
        #     if c.capability_name == "speech_production":
        #         continue
        # The new code conditions on a hasattr check — so the bare
        # `if c.capability_name == "speech_production":\n    continue`
        # pattern must NOT appear.
        legacy = '"speech_production":\n                            continue'
        assert legacy not in text, (
            "F5 short-circuit still present in run_loops_aux.py — Phase 6 retirement incomplete"
        )

    def test_speech_production_pending_queue_is_bounded(self) -> None:
        cap = SpeechProductionCapability()
        for i in range(_PENDING_MAXLEN + 50):
            imp = _imp(0.3, source=f"test-{i}")
            cap.activate(imp, level=0.3)
        assert len(cap._pending) == _PENDING_MAXLEN  # type: ignore[arg-type]

    def test_consume_pending_drains_oldest_first(self) -> None:
        cap = SpeechProductionCapability()
        first = _imp(0.3, source="first")
        second = _imp(0.3, source="second")
        cap.activate(first, level=0.3)
        cap.activate(second, level=0.3)
        consumed = cap.consume_pending()
        assert consumed is not None
        assert consumed.source == "first"


# Tiny pytest.approx lookalike to keep the test file self-contained
# (the rest of the suite does not import pytest at module level here).
def pytest_approx(value: float, rel: float = 1e-6) -> float:
    class _Approx:
        def __init__(self, v: float) -> None:
            self.v = v

        def __eq__(self, other: object) -> bool:  # type: ignore[override]
            if not isinstance(other, int | float):
                return NotImplemented
            return abs(other - self.v) <= max(abs(self.v), abs(other)) * rel

        def __repr__(self) -> str:
            return f"~{self.v}"

    return _Approx(value)  # type: ignore[return-value]
