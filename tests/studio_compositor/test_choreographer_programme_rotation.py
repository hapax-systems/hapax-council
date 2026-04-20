"""Phase 11 — choreographer rotation_mode reads programme priors.

Plan §lines 1067-1142 of
``docs/superpowers/plans/2026-04-20-programme-layer-plan.md``. Verifies:

  - Programme prior wins when no narrative/structural intent file exists
  - Structural intent file wins over programme prior (cascade order)
  - Narrative-tier per-tick override wins over both
  - Provider absent / returning None / raising → cascade unchanged
  - Programme without ``homage_rotation_modes`` falls through to default
  - Unknown mode strings in priors are ignored (defensive)
  - GROUNDING-EXPANSION: programme priors do NOT prevent the structural
    director from emitting an out-of-prior mode — the structural intent
    sits above the programme prior in the cascade.

The choreographer remains un-bypassed (B3) — these tests pin the
*selection* layer; the FSM advance behaviour is covered elsewhere.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from agents.studio_compositor.homage.choreographer import Choreographer
from shared.programme import (
    Programme,
    ProgrammeConstraintEnvelope,
    ProgrammeRole,
)

# ── Fixtures + helpers ─────────────────────────────────────────────────


def _programme(
    *,
    role: ProgrammeRole = ProgrammeRole.LISTENING,
    rotation_modes: list[str] | None = None,
) -> Programme:
    return Programme(
        programme_id=f"prog-{role.value}-test",
        role=role,
        planned_duration_s=300.0,
        constraints=ProgrammeConstraintEnvelope(
            homage_rotation_modes=rotation_modes or [],
        ),
        parent_show_id="show-test",
    )


def _make_choreographer(
    tmp_path: Path,
    *,
    programme_provider=None,
) -> Choreographer:
    """Build a Choreographer pointed at tmp paths for both intent files."""
    return Choreographer(
        pending_file=tmp_path / "pending-transitions.json",
        uniforms_file=tmp_path / "uniforms.json",
        substrate_package_file=tmp_path / "substrate-package.json",
        consent_safe_flag_file=tmp_path / "consent-safe.flag",
        voice_register_file=tmp_path / "voice-register.json",
        structural_intent_file=tmp_path / "structural-intent.json",
        narrative_structural_intent_file=tmp_path / "narrative-intent.json",
        programme_provider=programme_provider,
    )


def _write_intent(path: Path, mode: str, *, fresh: bool = True) -> None:
    """Write a minimal intent file containing ``homage_rotation_mode``."""
    payload: dict = {"homage_rotation_mode": mode}
    if fresh:
        payload["updated_at"] = time.time()
        payload["emitted_at"] = time.time()
    path.write_text(json.dumps(payload), encoding="utf-8")


# ── Cascade order ──────────────────────────────────────────────────────


class TestCascadeOrder:
    def test_default_when_no_intent_no_programme(self, tmp_path: Path) -> None:
        choreo = _make_choreographer(tmp_path)
        assert choreo._read_rotation_mode() == "weighted_by_salience"

    def test_programme_prior_wins_when_no_intent_files(self, tmp_path: Path) -> None:
        prog = _programme(rotation_modes=["paused"])
        choreo = _make_choreographer(tmp_path, programme_provider=lambda: prog)
        assert choreo._read_rotation_mode() == "paused"

    def test_structural_intent_wins_over_programme_prior(self, tmp_path: Path) -> None:
        """Cascade pin: structural intent sits ABOVE programme prior."""
        prog = _programme(rotation_modes=["paused"])
        _write_intent(tmp_path / "structural-intent.json", "random")
        choreo = _make_choreographer(tmp_path, programme_provider=lambda: prog)
        assert choreo._read_rotation_mode() == "random"

    def test_narrative_intent_wins_over_programme_prior(self, tmp_path: Path) -> None:
        prog = _programme(rotation_modes=["paused"])
        _write_intent(tmp_path / "narrative-intent.json", "weighted_by_salience")
        choreo = _make_choreographer(tmp_path, programme_provider=lambda: prog)
        assert choreo._read_rotation_mode() == "weighted_by_salience"

    def test_narrative_wins_over_structural_and_programme(self, tmp_path: Path) -> None:
        prog = _programme(rotation_modes=["paused"])
        _write_intent(tmp_path / "structural-intent.json", "random")
        _write_intent(tmp_path / "narrative-intent.json", "sequential")
        choreo = _make_choreographer(tmp_path, programme_provider=lambda: prog)
        assert choreo._read_rotation_mode() == "sequential"


# ── Per-mode coverage ───────────────────────────────────────────────────


class TestProgrammePriorPerMode:
    @pytest.mark.parametrize("mode", ["sequential", "random", "weighted_by_salience", "paused"])
    def test_each_mode_propagates_through(self, tmp_path: Path, mode: str) -> None:
        prog = _programme(rotation_modes=[mode])
        choreo = _make_choreographer(tmp_path, programme_provider=lambda: prog)
        assert choreo._read_rotation_mode() == mode

    def test_first_prior_wins_when_multiple_listed(self, tmp_path: Path) -> None:
        """The choreographer picks the FIRST entry; structural director
        is responsible for picking among the list given the soft priors.
        """
        prog = _programme(rotation_modes=["paused", "random", "sequential"])
        choreo = _make_choreographer(tmp_path, programme_provider=lambda: prog)
        assert choreo._read_rotation_mode() == "paused"


# ── Provider robustness ─────────────────────────────────────────────────


class TestProviderRobustness:
    def test_absent_provider_yields_default(self, tmp_path: Path) -> None:
        choreo = _make_choreographer(tmp_path, programme_provider=None)
        assert choreo._read_rotation_mode() == "weighted_by_salience"

    def test_provider_returning_none_yields_default(self, tmp_path: Path) -> None:
        choreo = _make_choreographer(tmp_path, programme_provider=lambda: None)
        assert choreo._read_rotation_mode() == "weighted_by_salience"

    def test_provider_raising_does_not_break_tick(self, tmp_path: Path) -> None:
        def boom() -> Programme | None:
            raise RuntimeError("provider broken")

        choreo = _make_choreographer(tmp_path, programme_provider=boom)
        assert choreo._read_rotation_mode() == "weighted_by_salience"

    def test_programme_with_empty_priors_falls_through(self, tmp_path: Path) -> None:
        prog = _programme(rotation_modes=[])
        choreo = _make_choreographer(tmp_path, programme_provider=lambda: prog)
        assert choreo._read_rotation_mode() == "weighted_by_salience"

    def test_unknown_first_prior_falls_through(self, tmp_path: Path) -> None:
        """An unknown mode token is ignored, not propagated."""
        # Build the programme with a normal mode then mutate the list to
        # bypass the field's literal-type validator.
        prog = _programme(rotation_modes=["paused"])
        prog.constraints.homage_rotation_modes.clear()
        prog.constraints.homage_rotation_modes.append("not_a_mode")  # type: ignore[arg-type]
        choreo = _make_choreographer(tmp_path, programme_provider=lambda: prog)
        assert choreo._read_rotation_mode() == "weighted_by_salience"


# ── Grounding-expansion: structural director can override programme ────


class TestGroundingExpansion:
    """A programme that prefers `paused` does NOT prevent the structural
    director from publishing `burst`-equivalent modes when impingement
    pressure justifies it. Pinned at the cascade level: structural
    intent sits above programme prior.

    Plan §line 1114-1118: "the rotation-mode catalog is ADDITIVE under
    programme — programmes don't forbid modes; they bias."
    """

    def test_paused_programme_does_not_block_random_burst(self, tmp_path: Path) -> None:
        prog = _programme(role=ProgrammeRole.LISTENING, rotation_modes=["paused"])
        # Structural director picks `random` despite the listening
        # programme's `paused` prior — the choreographer publishes random.
        _write_intent(tmp_path / "structural-intent.json", "random")
        choreo = _make_choreographer(tmp_path, programme_provider=lambda: prog)
        assert choreo._read_rotation_mode() == "random"

    def test_pathological_listening_can_still_emit_weighted(self, tmp_path: Path) -> None:
        """Listening programme priors include only `paused`; structural
        director picks `weighted_by_salience`. Choreographer publishes
        weighted — no silent rewrite to `paused`."""
        prog = _programme(rotation_modes=["paused"])
        _write_intent(tmp_path / "structural-intent.json", "weighted_by_salience")
        choreo = _make_choreographer(tmp_path, programme_provider=lambda: prog)
        assert choreo._read_rotation_mode() == "weighted_by_salience"

    def test_replay_distribution_propagates_unmodified(self, tmp_path: Path) -> None:
        """Across 100 ticks the structural director picks 30 out-of-prior
        modes; the choreographer publishes ALL 30 unmodified.
        """
        prog = _programme(rotation_modes=["paused"])
        # Pre-write a `paused` structural intent then rewrite per tick.
        for tick in range(100):
            mode = "random" if tick < 30 else "paused"
            _write_intent(tmp_path / "structural-intent.json", mode)
            choreo = _make_choreographer(tmp_path, programme_provider=lambda: prog)
            published = choreo._read_rotation_mode()
            assert published == mode  # No silent rewrite-to-prior


# ── Stale narrative falls through to structural / programme / default ──


class TestStalenessHandling:
    def test_stale_narrative_skipped_then_programme_wins(self, tmp_path: Path) -> None:
        """Narrative file with old timestamp → skipped; structural absent
        → programme prior wins."""
        prog = _programme(rotation_modes=["random"])
        # Write a narrative file with timestamp from way back
        stale = {
            "homage_rotation_mode": "paused",
            "updated_at": time.time() - 99999.0,
            "emitted_at": time.time() - 99999.0,
        }
        (tmp_path / "narrative-intent.json").write_text(json.dumps(stale))
        choreo = _make_choreographer(tmp_path, programme_provider=lambda: prog)
        assert choreo._read_rotation_mode() == "random"
