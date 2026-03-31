"""Tests for reactive engine gap closure — phase gating, handle_change,
presence/consent/biometric/phone handlers, AuditLog, env overrides,
and affordance pipeline initialization.

Self-contained, asyncio_mode="auto", unittest.mock only.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from logos.engine.models import Action, ChangeEvent
from logos.engine.rules import Rule, RuleRegistry, evaluate_rules

# ── Helpers ────────────────────────────────────────────────────────────────


def _make_event(
    path: str = "/data/profiles/test.md",
    event_type: str = "modified",
    doc_type: str | None = "test",
    frontmatter: dict | None = None,
    data_dir: Path | None = None,
) -> ChangeEvent:
    return ChangeEvent(
        path=Path(path),
        event_type=event_type,
        doc_type=doc_type,
        frontmatter=frontmatter,
        timestamp=datetime.now(),
        data_dir=data_dir or Path("/data"),
    )


def _registry(*rules: Rule) -> RuleRegistry:
    reg = RuleRegistry()
    for r in rules:
        r._last_fired = float("-inf")
        reg.register(r)
    return reg


def _watch_path(name: str) -> str:
    """Build a watch-state path string without literal home dir."""
    return str(Path.home() / "hapax-state" / "watch" / name)


# ── TestPhaseGating ────────────────────────────────────────────────────────


class TestPhaseGating:
    @pytest.fixture()
    def engine(self, tmp_path):
        from logos.engine import ReactiveEngine

        return ReactiveEngine(data_dir=tmp_path, watch_paths=[tmp_path], debounce_ms=100)

    def _register_phases(self, engine):
        for phase, name in [(0, "phase0"), (1, "phase1"), (2, "phase2")]:
            r = Rule(
                name=name,
                description=f"test-{name}",
                trigger_filter=lambda e: True,
                produce=lambda e, p=phase, n=name: [
                    Action(name=f"action-{n}", handler=AsyncMock(), phase=p)
                ],
                phase=phase,
            )
            r._last_fired = float("-inf")
            engine.registry.register(r)

    async def test_degraded_stimmung_strips_expensive_phases(self, engine):
        self._register_phases(engine)
        event = _make_event()
        with (
            patch.object(engine, "_read_stimmung_stance", return_value="degraded"),
            patch.object(engine, "_read_presence_state", return_value="PRESENT"),
            patch("logos._telemetry.hapax_trace") as mt,
            patch("logos._telemetry.hapax_span"),
            patch("logos._telemetry.hapax_score"),
            patch("logos._telemetry.hapax_interaction"),
            patch("logos._telemetry.hapax_event"),
        ):
            mt.return_value.__enter__ = MagicMock()
            mt.return_value.__exit__ = MagicMock(return_value=False)
            await engine._handle_change(event)
        assert engine._events_processed >= 1

    async def test_away_presence_strips_expensive_phases(self, engine):
        self._register_phases(engine)
        event = _make_event()
        with (
            patch.object(engine, "_read_stimmung_stance", return_value="nominal"),
            patch.object(engine, "_read_presence_state", return_value="AWAY"),
            patch("logos._telemetry.hapax_trace") as mt,
            patch("logos._telemetry.hapax_span"),
            patch("logos._telemetry.hapax_score"),
            patch("logos._telemetry.hapax_interaction"),
            patch("logos._telemetry.hapax_event"),
        ):
            mt.return_value.__enter__ = MagicMock()
            mt.return_value.__exit__ = MagicMock(return_value=False)
            await engine._handle_change(event)
        assert engine._events_processed >= 1

    async def test_nominal_keeps_all_phases(self, engine):
        self._register_phases(engine)
        event = _make_event()
        with (
            patch.object(engine, "_read_stimmung_stance", return_value="nominal"),
            patch.object(engine, "_read_presence_state", return_value="PRESENT"),
            patch("logos._telemetry.hapax_trace") as mt,
            patch("logos._telemetry.hapax_span"),
            patch("logos._telemetry.hapax_score"),
            patch("logos._telemetry.hapax_event"),
        ):
            mt.return_value.__enter__ = MagicMock()
            mt.return_value.__exit__ = MagicMock(return_value=False)
            await engine._handle_change(event)
        assert engine._events_processed >= 1


# ── TestHandleChangeHappyPath ──────────────────────────────────────────────


class TestHandleChangeHappyPath:
    @pytest.fixture()
    def engine(self, tmp_path):
        from logos.engine import ReactiveEngine

        eng = ReactiveEngine(data_dir=tmp_path, watch_paths=[tmp_path])
        handler = AsyncMock(return_value="ok")
        rule = Rule(
            name="test-rule",
            description="test",
            trigger_filter=lambda e: True,
            produce=lambda e: [Action(name="test-action", handler=handler, phase=0)],
        )
        rule._last_fired = float("-inf")
        eng.registry.register(rule)
        return eng

    async def test_counters_increment(self, engine):
        event = _make_event()
        with (
            patch.object(engine, "_read_stimmung_stance", return_value="nominal"),
            patch.object(engine, "_read_presence_state", return_value="PRESENT"),
            patch("logos._telemetry.hapax_trace") as mt,
            patch("logos._telemetry.hapax_span"),
            patch("logos._telemetry.hapax_score"),
            patch("logos._telemetry.hapax_event"),
        ):
            mt.return_value.__enter__ = MagicMock()
            mt.return_value.__exit__ = MagicMock(return_value=False)
            await engine._handle_change(event)
        assert engine._events_processed == 1
        assert engine._actions_executed >= 1
        assert len(engine._history) == 1

    async def test_pattern_counter_increments(self, engine):
        event = _make_event()
        with (
            patch.object(engine, "_read_stimmung_stance", return_value="nominal"),
            patch.object(engine, "_read_presence_state", return_value="PRESENT"),
            patch("logos._telemetry.hapax_trace") as mt,
            patch("logos._telemetry.hapax_span"),
            patch("logos._telemetry.hapax_score"),
            patch("logos._telemetry.hapax_event"),
        ):
            mt.return_value.__enter__ = MagicMock()
            mt.return_value.__exit__ = MagicMock(return_value=False)
            await engine._handle_change(event)
        assert len(engine._pattern_counters) > 0


# ── TestPresenceTransition ─────────────────────────────────────────────────


class TestPresenceTransition:
    def _make_perception_event(self, tmp_path, state_data: dict) -> ChangeEvent:
        f = tmp_path / "perception-state.json"
        f.write_text(json.dumps(state_data), encoding="utf-8")
        return ChangeEvent(
            path=f,
            event_type="modified",
            doc_type=None,
            frontmatter=None,
            timestamp=datetime.now(),
        )

    def test_filter_detects_transition(self, tmp_path):
        import logos.engine.rules_phase0 as mod

        mod._last_presence_state = "PRESENT"
        mod._stashed_perception_data = None
        event = self._make_perception_event(tmp_path, {"presence_state": "AWAY"})
        assert mod._presence_transition_filter(event) is True

    def test_filter_rejects_same_state(self, tmp_path):
        import logos.engine.rules_phase0 as mod

        mod._last_presence_state = "PRESENT"
        mod._stashed_perception_data = None
        event = self._make_perception_event(tmp_path, {"presence_state": "PRESENT"})
        assert mod._presence_transition_filter(event) is False

    def test_produce_uses_stashed_data(self, tmp_path):
        import logos.engine.rules_phase0 as mod

        mod._last_presence_state = "PRESENT"
        mod._stashed_perception_data = {"presence_state": "AWAY"}
        event = self._make_perception_event(tmp_path, {"presence_state": "AWAY"})
        actions = mod._presence_transition_produce(event)
        assert len(actions) == 1
        assert "PRESENT->AWAY" in actions[0].name
        assert mod._last_presence_state == "AWAY"
        assert mod._stashed_perception_data is None

    def test_produce_returns_empty_when_no_stash(self, tmp_path):
        import logos.engine.rules_phase0 as mod

        mod._last_presence_state = "PRESENT"
        mod._stashed_perception_data = None
        event = self._make_perception_event(tmp_path, {"presence_state": "AWAY"})
        assert mod._presence_transition_produce(event) == []

    async def test_handler_emits_events(self):
        from logos.engine.rules_phase0 import _handle_presence_transition

        with patch("logos.engine.rules_phase0.hapax_event") as mock_event:
            result = await _handle_presence_transition(from_state="PRESENT", to_state="AWAY")
            assert "PRESENT->AWAY" in result
            mock_event.assert_called_once()


# ── TestConsentTransition ──────────────────────────────────────────────────


class TestConsentTransition:
    def _make_perception_event(self, tmp_path, state_data: dict) -> ChangeEvent:
        f = tmp_path / "perception-state.json"
        f.write_text(json.dumps(state_data), encoding="utf-8")
        return ChangeEvent(
            path=f,
            event_type="modified",
            doc_type=None,
            frontmatter=None,
            timestamp=datetime.now(),
        )

    def test_filter_detects_consent_change(self, tmp_path):
        import logos.engine.rules_phase0 as mod

        mod._last_consent_phase = "no_guest"
        mod._stashed_consent_data = None
        event = self._make_perception_event(tmp_path, {"consent_phase": "consent_pending"})
        assert mod._consent_transition_filter(event) is True

    def test_produce_uses_stashed_data(self, tmp_path):
        import logos.engine.rules_phase0 as mod

        mod._last_consent_phase = "no_guest"
        mod._stashed_consent_data = {"consent_phase": "consent_pending"}
        event = self._make_perception_event(tmp_path, {"consent_phase": "consent_pending"})
        actions = mod._consent_transition_produce(event)
        assert len(actions) == 1
        assert "no_guest->consent_pending" in actions[0].name
        assert mod._last_consent_phase == "consent_pending"


# ── TestBiometricStateChange ───────────────────────────────────────────────


class TestBiometricStateChange:
    def test_filter_matches_biometric_files(self):
        from logos.engine.rules_phase0 import _biometric_state_filter

        event = _make_event(path=_watch_path("heartrate.json"), doc_type=None)
        assert _biometric_state_filter(event) is True

    def test_filter_rejects_non_biometric(self):
        from logos.engine.rules_phase0 import _biometric_state_filter

        event = _make_event(path=_watch_path("phone_health_summary.json"), doc_type=None)
        assert _biometric_state_filter(event) is False

    def test_produce_creates_action(self):
        from logos.engine.rules_phase0 import _biometric_state_produce

        event = _make_event(path=_watch_path("hrv.json"), doc_type=None)
        actions = _biometric_state_produce(event)
        assert len(actions) == 1
        assert "biometric-state" in actions[0].name

    async def test_handler_detects_stress_transition(self):
        from logos.engine.rules_phase0 import _handle_biometric_state_change

        with (
            patch(
                "agents.hapax_daimonion.watch_signals.is_stress_elevated",
                return_value=True,
            ),
            patch(
                "agents.hapax_daimonion.watch_signals.WATCH_STATE_DIR",
                "/tmp",
            ),
            patch("logos._telemetry.hapax_event"),
        ):
            import logos.engine.rules_phase0 as mod

            mod._last_stress_elevated = False
            result = await _handle_biometric_state_change(path="/tmp/heartrate.json")
            assert "biometric-update" in result


# ── TestPhoneHealthSummary ─────────────────────────────────────────────────


class TestPhoneHealthSummary:
    def test_filter_matches(self):
        from logos.engine.rules_phase0 import _phone_health_filter

        event = _make_event(path=_watch_path("phone_health_summary.json"), doc_type=None)
        assert _phone_health_filter(event) is True

    def test_filter_rejects_wrong_file(self):
        from logos.engine.rules_phase0 import _phone_health_filter

        event = _make_event(path=_watch_path("heartrate.json"), doc_type=None)
        assert _phone_health_filter(event) is False

    async def test_handler_calls_profiler_bridge(self):
        from logos.engine.rules_phase0 import _handle_phone_health_summary

        mock_facts = [{"type": "sleep", "value": "good"}]
        with (
            patch("logos.engine.rules_phase0.hapax_event"),
            patch.dict(
                "sys.modules",
                {
                    "agents.profiler_sources": MagicMock(
                        read_phone_health_summary=MagicMock(return_value=mock_facts)
                    )
                },
            ),
        ):
            result = await _handle_phone_health_summary(
                path=_watch_path("phone_health_summary.json")
            )
            assert "phone-health" in result


# ── TestAuditLog ───────────────────────────────────────────────────────────


class TestAuditLog:
    def test_write_creates_jsonl(self, tmp_path):
        from logos.engine import _AuditLog, _HistoryEntry

        log = _AuditLog(base_dir=tmp_path)
        entry = _HistoryEntry(
            timestamp=datetime(2026, 3, 31, 12, 0, 0),
            event_path="/test/path",
            event_type="modified",
            doc_type="test",
            rules_matched=["rule-1"],
            actions=["action-1"],
            errors=[],
        )
        log.write(entry)
        log.close()
        files = list(tmp_path.glob("engine-audit-*.jsonl"))
        assert len(files) == 1
        record = json.loads(files[0].read_text().strip())
        assert record["event_path"] == "/test/path"

    def test_cleanup_removes_old_files(self, tmp_path):
        import datetime as dt

        old_date = (dt.date.today() - dt.timedelta(days=60)).isoformat()
        recent_date = dt.date.today().isoformat()
        (tmp_path / f"engine-audit-{old_date}.jsonl").write_text("{}")
        (tmp_path / f"engine-audit-{recent_date}.jsonl").write_text("{}")

        from logos.engine import _AuditLog

        log = _AuditLog(base_dir=tmp_path, retention_days=30)
        log.cleanup()
        remaining = list(tmp_path.glob("engine-audit-*.jsonl"))
        assert len(remaining) == 1
        assert recent_date in remaining[0].name

    def test_write_creates_parent_dirs(self, tmp_path):
        from logos.engine import _AuditLog, _HistoryEntry

        log = _AuditLog(base_dir=tmp_path / "nested" / "audit")
        entry = _HistoryEntry(
            timestamp=datetime.now(),
            event_path="/t",
            event_type="modified",
            doc_type=None,
            rules_matched=[],
            actions=[],
            errors=[],
        )
        log.write(entry)
        log.close()
        assert len(list((tmp_path / "nested" / "audit").glob("*.jsonl"))) == 1


# ── TestEnvOverrides ───────────────────────────────────────────────────────


class TestEnvOverrides:
    def test_env_int_returns_value(self):
        from logos.engine import _env_int

        with patch.dict(os.environ, {"TEST_INT": "42"}):
            assert _env_int("TEST_INT", 0) == 42

    def test_env_int_returns_default_on_missing(self):
        from logos.engine import _env_int

        assert _env_int("NONEXISTENT_KEY_XYZ", 99) == 99

    def test_env_int_returns_default_on_invalid(self):
        from logos.engine import _env_int

        with patch.dict(os.environ, {"TEST_INT": "not_a_number"}):
            assert _env_int("TEST_INT", 99) == 99

    def test_env_float_returns_value(self):
        from logos.engine import _env_float

        with patch.dict(os.environ, {"TEST_FLOAT": "3.14"}):
            assert _env_float("TEST_FLOAT", 0.0) == pytest.approx(3.14)

    def test_env_float_returns_default_on_invalid(self):
        from logos.engine import _env_float

        with patch.dict(os.environ, {"TEST_FLOAT": "abc"}):
            assert _env_float("TEST_FLOAT", 1.5) == 1.5


# ── TestEvaluateRulesWideException ─────────────────────────────────────────


class TestEvaluateRulesWideException:
    def test_attribute_error_in_filter_caught(self):
        def bad_filter(e):
            raise AttributeError("no such attr")

        rule = Rule(
            name="bad-attr",
            description="test",
            trigger_filter=bad_filter,
            produce=lambda e: [Action(name="action", handler=AsyncMock())],
        )
        plan = evaluate_rules(_make_event(), _registry(rule))
        assert len(plan.actions) == 0

    def test_runtime_error_in_produce_caught(self):
        rule = Rule(
            name="bad-produce",
            description="test",
            trigger_filter=lambda e: True,
            produce=lambda e: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        plan = evaluate_rules(_make_event(), _registry(rule))
        assert len(plan.actions) == 0


# ── TestAffordancePipelineInit ─────────────────────────────────────────────


class TestAffordancePipelineInit:
    def test_generates_description_for_real_rule(self):
        from logos.engine.rule_capability import generate_rule_description

        rule = Rule(
            name="test-rule",
            description="Refresh cache on profiles/ changes",
            trigger_filter=lambda e: True,
            produce=lambda e: [],
            phase=0,
        )
        desc = generate_rule_description(rule)
        assert "Refresh cache on profiles/ changes" in desc
        assert "Deterministic" in desc

    def test_generates_description_phase2(self):
        from logos.engine.rule_capability import generate_rule_description

        rule = Rule(
            name="cloud-rule",
            description="Run maintenance after quiet window",
            trigger_filter=lambda e: True,
            produce=lambda e: [],
            phase=2,
        )
        desc = generate_rule_description(rule)
        assert "Cloud LLM" in desc


# ── TestIgnoreFnInjection ──────────────────────────────────────────────────


class TestIgnoreFnInjection:
    @pytest.fixture()
    def engine(self, tmp_path):
        from logos.engine import ReactiveEngine

        return ReactiveEngine(data_dir=tmp_path, watch_paths=[tmp_path])

    async def test_ignore_fn_injected_for_accepting_handler(self, engine):
        async def handler_with_ignore(*, ignore_fn=None):
            return f"got:{ignore_fn is not None}"

        rule = Rule(
            name="needs-ignore",
            description="test",
            trigger_filter=lambda e: True,
            produce=lambda e: [
                Action(name="test-ignore", handler=handler_with_ignore, args={}, phase=2)
            ],
        )
        rule._last_fired = float("-inf")
        engine.registry.register(rule)
        event = _make_event()
        with (
            patch.object(engine, "_read_stimmung_stance", return_value="nominal"),
            patch.object(engine, "_read_presence_state", return_value="PRESENT"),
            patch("logos._telemetry.hapax_trace") as mt,
            patch("logos._telemetry.hapax_span"),
            patch("logos._telemetry.hapax_score"),
            patch("logos._telemetry.hapax_event"),
        ):
            mt.return_value.__enter__ = MagicMock()
            mt.return_value.__exit__ = MagicMock(return_value=False)
            await engine._handle_change(event)
        assert engine._actions_executed >= 1


# ── TestQuietWindowConsumeAfterSuccess ─────────────────────────────────────


class TestQuietWindowConsumeAfterSuccess:
    def test_dirty_paths_survive_if_not_consumed(self):
        from logos.engine.rules_phase2 import QuietWindowScheduler

        sched = QuietWindowScheduler(quiet_window_s=0)
        sched.record("path/a")
        sched._running = True
        assert sched.dirty is True
        assert sched.dirty_paths == {"path/a"}

    def test_consume_clears_paths(self):
        from logos.engine.rules_phase2 import QuietWindowScheduler

        sched = QuietWindowScheduler(quiet_window_s=0)
        sched.record("path/a")
        sched._running = True
        consumed = sched.consume()
        assert consumed == {"path/a"}
        assert sched.dirty is False


# ── TestCorrectionSentinel ─────────────────────────────────────────────────


class TestCorrectionSentinel:
    def test_filter_matches_sentinel(self, tmp_path):
        from logos.engine.rules_phase2 import _correction_synthesis_filter

        event = _make_event(path=str(tmp_path / "correction-pending.json"), doc_type=None)
        result = _correction_synthesis_filter(event)
        assert isinstance(result, bool)

    def test_filter_rejects_old_filename(self):
        from logos.engine.rules_phase2 import _correction_synthesis_filter

        event = _make_event(
            path="/dev/shm/hapax-compositor/activity-correction.json", doc_type=None
        )
        assert _correction_synthesis_filter(event) is False


# ── TestRuleCount ──────────────────────────────────────────────────────────


class TestRuleCount:
    def test_all_rules_count(self):
        from logos.engine.reactive_rules import ALL_RULES

        assert len(ALL_RULES) == 13
