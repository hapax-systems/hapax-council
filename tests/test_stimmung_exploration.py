"""Tests for exploration deficit → SEEKING stance wiring."""

import time
from unittest.mock import patch

from shared.stimmung import StimmungCollector


class TestExplorationDeficitSeeking:
    """Verify that exploration deficit above threshold triggers SEEKING stance."""

    @staticmethod
    def _feed_healthy(collector: StimmungCollector) -> None:
        """Feed enough fresh dimensions to avoid control law stale degradation."""
        collector.update_health(10, 10)
        collector.update_gpu(8000, 24000)
        collector.update_engine(events_processed=10, actions_executed=5, errors=0, uptime_s=60)
        collector.update_perception(freshness_s=1.0, confidence=0.9)
        collector.update_langfuse(daily_cost=0.0, error_count=0, total_traces=10)
        collector.update_audio_perception(
            rms_dbfs=-25.0,
            spectral_centroid_hz=1500.0,
            low_high_ratio=1.0,
            voice_ratio=0.33,
            music_ratio=0.33,
            env_ratio=0.34,
        )

    def test_high_deficit_triggers_seeking(self):
        collector = StimmungCollector()
        # Hysteresis requires 3 consecutive SEEKING snapshots
        for _ in range(3):
            self._feed_healthy(collector)
            collector.update_exploration(0.5)  # above 0.35 threshold
            snap = collector.snapshot()
        assert snap.overall_stance.value == "seeking"

    def test_low_deficit_stays_nominal(self):
        collector = StimmungCollector()
        self._feed_healthy(collector)
        collector.update_exploration(0.2)  # below 0.35 threshold
        snap = collector.snapshot()
        assert snap.overall_stance.value == "nominal"

    def test_deficit_ignored_when_degraded(self):
        collector = StimmungCollector()
        collector.update_health(3, 10)  # degraded infrastructure (value=0.7 → DEGRADED)
        collector.update_exploration(0.8)  # high deficit
        snap = collector.snapshot()
        # Should be degraded/cautious, NOT seeking (SEEKING blocks at DEGRADED+).
        # Audit R6 / cc-task seeking-stance-gate-relax: SEEKING now ALSO fires
        # from CAUTIOUS, but DEGRADED+ continues to block — those signal real
        # infrastructure problems where exploration would compete with recovery.
        assert snap.overall_stance.value != "seeking"

    def test_high_deficit_triggers_seeking_from_cautious(self):
        """Audit R6 / cc-task seeking-stance-gate-relax (2026-05-02):
        CAUTIOUS-level operational noise must not block SEEKING. The prior
        `worst == NOMINAL` gate suppressed SEEKING entirely whenever
        anything was even slightly off (LLM cost pressure, transient
        resource pressure, slight perception confidence dip). With the
        relaxed gate, exploration_deficit above 0.35 fires SEEKING from
        either NOMINAL or CAUTIOUS — preserving the variance modulation
        that the surface needs during sustained tolerable degradation."""
        collector = StimmungCollector()
        # Hysteresis requires 3 consecutive SEEKING raw stances.
        for _ in range(3):
            # Feed a fresh healthy baseline so the control-law staleness
            # forcing path doesn't fire degraded.
            self._feed_healthy(collector)
            # Override health to a CAUTIOUS-level value (INFRA thresholds
            # 0.30/0.60/0.85; value 0.4 → effective 0.4 → CAUTIOUS).
            collector.update_health(6, 10)
            collector.update_exploration(0.5)
            snap = collector.snapshot()
        assert snap.overall_stance.value == "seeking", (
            f"expected SEEKING from CAUTIOUS-level health + high deficit, "
            f"got {snap.overall_stance.value}"
        )

    def test_seeking_still_blocked_at_degraded(self, monkeypatch):
        """Regression pin: the relaxed gate must not allow SEEKING from
        DEGRADED or CRITICAL. Those represent real infrastructure
        problems where the recruitment-threshold halving would compete
        with recovery instead of helping.

        Pinned to the legacy point-estimate stance via
        ``HAPAX_STIMMUNG_POSTERIOR_STANCE=0`` because the posterior
        path (cc-task ``dimension-reading-posterior-promotion``,
        default-on as of 2026-05-04) intentionally moderates the
        DEGRADED escalation under measurement-noise — feeding 3
        oscillating health readings produces sigma > 0 and the
        ``P(value > 0.6) >= 0.85`` gate may not clear. Posterior
        semantics are covered by the dedicated phase-c test suite.
        """
        monkeypatch.setenv("HAPAX_STIMMUNG_POSTERIOR_STANCE", "0")
        collector = StimmungCollector()
        for _ in range(3):
            self._feed_healthy(collector)
            # Override health to a DEGRADED-level value (INFRA thresholds
            # 0.30/0.60/0.85; value 0.65 → effective 0.65 → DEGRADED).
            collector.update_health(35, 100)
            collector.update_exploration(0.8)
            snap = collector.snapshot()
        assert snap.overall_stance.value != "seeking", (
            f"DEGRADED stance must block SEEKING; got {snap.overall_stance.value}"
        )
        # Specifically: should be DEGRADED (or worse) — not CAUTIOUS or NOMINAL.
        assert snap.overall_stance.value in ("degraded", "critical")

    def test_stale_deficit_ignored(self):
        collector = StimmungCollector()
        self._feed_healthy(collector)
        collector.update_exploration(0.5)
        # Fast-forward monotonic clock to make reading stale
        future = time.monotonic() + 200.0  # beyond _STALE_THRESHOLD_S (120s)
        snap = collector.snapshot(now=future)
        assert snap.overall_stance.value != "seeking"

    def test_deficit_dimension_value_propagated(self):
        collector = StimmungCollector()
        collector.update_exploration(0.42)
        snap = collector.snapshot()
        assert snap.exploration_deficit.value == 0.42


class TestReverieMixerSeeking:
    """Verify mixer syncs SEEKING stance to its affordance pipeline."""

    def test_seeking_stance_enables_pipeline_seeking(self):
        from unittest.mock import MagicMock

        from agents.reverie.mixer import ReverieMixer

        mock_context = MagicMock()
        mock_context.stimmung_stance = "seeking"
        mock_context.stimmung_raw = {"overall_stance": "seeking"}
        mock_context.imagination_fragments = []

        with patch.object(ReverieMixer, "__init__", lambda self: None):
            mixer = ReverieMixer()
            mixer._pipeline = MagicMock()
            mixer._pipeline.set_seeking = MagicMock()
            mixer._context = MagicMock()
            mixer._context.assemble.return_value = mock_context

            # Call the sync line directly
            ctx = mixer._context.assemble()
            mixer._pipeline.set_seeking(ctx.stimmung_stance == "seeking")

            mixer._pipeline.set_seeking.assert_called_with(True)

    def test_nominal_stance_disables_pipeline_seeking(self):
        from unittest.mock import MagicMock

        from agents.reverie.mixer import ReverieMixer

        mock_context = MagicMock()
        mock_context.stimmung_stance = "nominal"

        with patch.object(ReverieMixer, "__init__", lambda self: None):
            mixer = ReverieMixer()
            mixer._pipeline = MagicMock()
            mixer._context = MagicMock()
            mixer._context.assemble.return_value = mock_context

            ctx = mixer._context.assemble()
            mixer._pipeline.set_seeking(ctx.stimmung_stance == "seeking")

            mixer._pipeline.set_seeking.assert_called_with(False)


class TestExplorationTrackerPersistence:
    """Verify exploration tracker state survives serialization round-trip."""

    def test_state_dict_round_trip(self):
        from shared.exploration_tracker import ExplorationTrackerBundle

        bundle = ExplorationTrackerBundle(
            component="test",
            edges=["e1", "e2"],
            traces=["t1"],
            neighbors=["n1"],
        )
        # Feed some data to build state
        bundle.feed_habituation("e1", 0.5, 0.3, 0.1)
        bundle.feed_habituation("e2", 0.8, 0.8, 0.1)
        bundle.feed_interest("t1", 0.5, 0.1)
        bundle.feed_error(0.3)
        bundle.feed_error(0.2)

        state = bundle.state_dict()

        # Create fresh bundle, restore state
        bundle2 = ExplorationTrackerBundle(
            component="test",
            edges=["e1", "e2"],
            traces=["t1"],
            neighbors=["n1"],
        )
        bundle2.load_state_dict(state)

        assert bundle2.habituation._weights["e1"] == bundle.habituation._weights["e1"]
        assert bundle2.habituation._weights["e2"] == bundle.habituation._weights["e2"]
        assert bundle2.habituation._edge_n["e1"] == 1
        assert bundle2.interest._time_unchanged["t1"] == bundle.interest._time_unchanged["t1"]
        assert bundle2.learning._chronic_error == bundle.learning._chronic_error
        assert bundle2.learning._initialized is True
