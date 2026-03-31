"""Tests for logos/engine/ — reactive engine core infrastructure.

Self-contained, asyncio_mode="auto", unittest.mock only.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from logos.engine.executor import PhasedExecutor
from logos.engine.models import Action, ActionPlan, ChangeEvent
from logos.engine.rules import Rule, RuleRegistry, evaluate_rules
from shared.frontmatter import parse_frontmatter

# ── TestParseFrontmatter ────────────────────────────────────────────────────


class TestParseFrontmatter:
    def test_string_with_frontmatter(self):
        text = "---\ndoc_type: note\ntitle: Hello\n---\nBody text here."
        fm, body = parse_frontmatter(text)
        assert fm == {"doc_type": "note", "title": "Hello"}
        assert body == "Body text here."

    def test_string_without_frontmatter(self):
        text = "Just plain text."
        fm, body = parse_frontmatter(text)
        assert fm == {}
        assert body == "Just plain text."

    def test_path_reads_file(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("---\nkey: value\n---\nContent", encoding="utf-8")
        fm, body = parse_frontmatter(f)
        assert fm == {"key": "value"}
        assert body == "Content"

    def test_missing_file_returns_empty(self, tmp_path):
        fm, body = parse_frontmatter(tmp_path / "nope.md")
        assert fm == {}
        assert body == ""

    def test_invalid_yaml_returns_empty(self):
        text = "---\n[invalid: yaml: {{\n---\nBody"
        fm, body = parse_frontmatter(text)
        assert fm == {}
        assert body == text

    def test_empty_frontmatter(self):
        text = "---\n---\nBody after empty fence."
        fm, body = parse_frontmatter(text)
        assert fm == {}
        assert body == "Body after empty fence."

    def test_non_dict_yaml(self):
        text = "---\n- list\n- items\n---\nBody"
        fm, body = parse_frontmatter(text)
        assert fm == {}
        assert body == text


# ── TestChangeEvent ─────────────────────────────────────────────────────────


class TestChangeEvent:
    def test_subdirectory_relative(self):
        data_dir = Path("/data")
        event = ChangeEvent(
            path=Path("/data/profiles/health.jsonl"),
            event_type="modified",
            doc_type="health-event",
            frontmatter=None,
            timestamp=datetime.now(),
            data_dir=data_dir,
        )
        assert event.subdirectory == "profiles"

    def test_subdirectory_no_data_dir(self):
        event = ChangeEvent(
            path=Path("/some/deep/path/file.md"),
            event_type="created",
            doc_type=None,
            frontmatter=None,
            timestamp=datetime.now(),
        )
        assert event.subdirectory == "path"

    def test_subdirectory_external_path(self):
        event = ChangeEvent(
            path=Path("/external/docs/file.md"),
            event_type="created",
            doc_type=None,
            frontmatter=None,
            timestamp=datetime.now(),
            data_dir=Path("/data"),
        )
        # Falls back to parent dir name
        assert event.subdirectory == "docs"

    def test_source_service_detection(self):
        event = ChangeEvent(
            path=Path("/home/user/documents/rag-sources/gmail/inbox/msg.md"),
            event_type="created",
            doc_type=None,
            frontmatter=None,
            timestamp=datetime.now(),
        )
        assert event.source_service == "gmail"

    def test_source_service_none_for_profiles(self):
        event = ChangeEvent(
            path=Path("/data/profiles/health.jsonl"),
            event_type="modified",
            doc_type=None,
            frontmatter=None,
            timestamp=datetime.now(),
        )
        assert event.source_service is None


# ── TestActionPlan ──────────────────────────────────────────────────────────


class TestActionPlan:
    def test_actions_by_phase_groups_correctly(self):
        plan = ActionPlan(
            actions=[
                Action(name="a", handler=AsyncMock(), phase=0, priority=10),
                Action(name="b", handler=AsyncMock(), phase=1, priority=20),
                Action(name="c", handler=AsyncMock(), phase=0, priority=5),
            ]
        )
        by_phase = plan.actions_by_phase()
        assert set(by_phase.keys()) == {0, 1}
        assert len(by_phase[0]) == 2
        assert len(by_phase[1]) == 1

    def test_priority_sort_within_phase(self):
        plan = ActionPlan(
            actions=[
                Action(name="high", handler=AsyncMock(), phase=0, priority=100),
                Action(name="low", handler=AsyncMock(), phase=0, priority=1),
                Action(name="mid", handler=AsyncMock(), phase=0, priority=50),
            ]
        )
        by_phase = plan.actions_by_phase()
        names = [a.name for a in by_phase[0]]
        assert names == ["low", "mid", "high"]

    def test_empty_plan(self):
        plan = ActionPlan()
        assert plan.actions_by_phase() == {}
        assert plan.results == {}
        assert plan.errors == {}


# ── TestRuleRegistry ────────────────────────────────────────────────────────


class TestRuleRegistry:
    def _make_rule(self, name: str) -> Rule:
        return Rule(
            name=name,
            description=f"Test rule {name}",
            trigger_filter=lambda e: True,
            produce=lambda e: [],
        )

    def test_register_and_iterate(self):
        reg = RuleRegistry()
        reg.register(self._make_rule("a"))
        reg.register(self._make_rule("b"))
        assert len(reg) == 2
        names = {r.name for r in reg}
        assert names == {"a", "b"}

    def test_replace_on_duplicate_name(self):
        reg = RuleRegistry()
        rule1 = self._make_rule("x")
        rule1.description = "first"
        reg.register(rule1)

        rule2 = self._make_rule("x")
        rule2.description = "second"
        reg.register(rule2)

        assert len(reg) == 1
        assert reg.get("x").description == "second"

    def test_unregister(self):
        reg = RuleRegistry()
        reg.register(self._make_rule("a"))
        reg.unregister("a")
        assert len(reg) == 0

    def test_unregister_missing_is_noop(self):
        reg = RuleRegistry()
        reg.unregister("nonexistent")  # Should not raise
        assert len(reg) == 0


# ── TestEvaluateRules ───────────────────────────────────────────────────────


class TestEvaluateRules:
    def _make_event(self, path: str = "/data/test.md") -> ChangeEvent:
        return ChangeEvent(
            path=Path(path),
            event_type="modified",
            doc_type="test",
            frontmatter=None,
            timestamp=datetime.now(),
        )

    def test_matching_rule_produces_actions(self):
        handler = AsyncMock()
        rule = Rule(
            name="test-rule",
            description="test",
            trigger_filter=lambda e: True,
            produce=lambda e: [Action(name="action-1", handler=handler)],
        )
        reg = RuleRegistry()
        reg.register(rule)
        plan = evaluate_rules(self._make_event(), reg)
        assert len(plan.actions) == 1
        assert plan.actions[0].name == "action-1"

    def test_non_matching_rule_skipped(self):
        rule = Rule(
            name="test-rule",
            description="test",
            trigger_filter=lambda e: False,
            produce=lambda e: [Action(name="action-1", handler=AsyncMock())],
        )
        reg = RuleRegistry()
        reg.register(rule)
        plan = evaluate_rules(self._make_event(), reg)
        assert len(plan.actions) == 0

    def test_exception_in_filter_skipped(self):
        def bad_filter(e):
            raise ValueError("boom")

        rule = Rule(
            name="bad-rule",
            description="test",
            trigger_filter=bad_filter,
            produce=lambda e: [Action(name="action-1", handler=AsyncMock())],
        )
        reg = RuleRegistry()
        reg.register(rule)
        plan = evaluate_rules(self._make_event(), reg)
        assert len(plan.actions) == 0

    def test_cooldown_prevents_firing(self):
        handler = AsyncMock()
        rule = Rule(
            name="cool-rule",
            description="test",
            trigger_filter=lambda e: True,
            produce=lambda e: [Action(name="action-1", handler=handler)],
            cooldown_s=60,
        )
        reg = RuleRegistry()
        reg.register(rule)

        # First evaluation fires
        plan1 = evaluate_rules(self._make_event(), reg)
        assert len(plan1.actions) == 1

        # Second evaluation within cooldown window skips
        plan2 = evaluate_rules(self._make_event(), reg)
        assert len(plan2.actions) == 0

    def test_deduplication_by_action_name(self):
        handler = AsyncMock()
        rule1 = Rule(
            name="rule-1",
            description="test",
            trigger_filter=lambda e: True,
            produce=lambda e: [Action(name="shared-action", handler=handler)],
        )
        rule2 = Rule(
            name="rule-2",
            description="test",
            trigger_filter=lambda e: True,
            produce=lambda e: [Action(name="shared-action", handler=handler)],
        )
        reg = RuleRegistry()
        reg.register(rule1)
        reg.register(rule2)
        plan = evaluate_rules(self._make_event(), reg)
        assert len(plan.actions) == 1


# ── TestPhasedExecutor ──────────────────────────────────────────────────────


class TestPhasedExecutor:
    async def test_phase_ordering(self):
        order = []

        async def handler_p0():
            order.append(0)

        async def handler_p1():
            order.append(1)

        async def handler_p2():
            order.append(2)

        plan = ActionPlan(
            actions=[
                Action(name="phase2", handler=handler_p2, phase=2),
                Action(name="phase0", handler=handler_p0, phase=0),
                Action(name="phase1", handler=handler_p1, phase=1),
            ]
        )
        executor = PhasedExecutor()
        await executor.execute(plan)
        assert order == [0, 1, 2]

    async def test_dependency_skip_on_failure(self):
        async def failing():
            raise RuntimeError("fail")

        async def dependent():
            pass  # pragma: no cover

        plan = ActionPlan(
            actions=[
                Action(name="first", handler=failing, phase=0),
                Action(name="second", handler=dependent, phase=1, depends_on=["first"]),
            ]
        )
        executor = PhasedExecutor()
        await executor.execute(plan)
        assert "first" in plan.errors
        assert "second" in plan.skipped

    async def test_timeout_handling(self):
        async def slow():
            await asyncio.sleep(10)

        plan = ActionPlan(
            actions=[
                Action(name="slow-action", handler=slow, phase=0),
            ]
        )
        executor = PhasedExecutor(action_timeout_s=0.05)
        await executor.execute(plan)
        assert "slow-action" in plan.errors
        assert "Timed out" in plan.errors["slow-action"]

    async def test_successful_results_stored(self):
        async def good():
            return "ok"

        plan = ActionPlan(
            actions=[
                Action(name="good-action", handler=good, phase=0),
            ]
        )
        executor = PhasedExecutor()
        await executor.execute(plan)
        assert plan.results["good-action"] == "ok"
        assert len(plan.errors) == 0

    async def test_semaphore_bounds_gpu(self):
        """Verify GPU phase uses semaphore (concurrency 1)."""
        concurrent = 0
        max_concurrent = 0

        async def tracked():
            nonlocal concurrent, max_concurrent
            concurrent += 1
            max_concurrent = max(max_concurrent, concurrent)
            await asyncio.sleep(0.02)
            concurrent -= 1

        plan = ActionPlan(
            actions=[Action(name=f"gpu-{i}", handler=tracked, phase=1) for i in range(3)]
        )
        executor = PhasedExecutor(gpu_concurrency=1)
        await executor.execute(plan)
        assert max_concurrent == 1


# ── TestDirectoryWatcher ────────────────────────────────────────────────────


class TestDirectoryWatcher:
    async def test_debounce_collapses_events(self):
        """Multiple events on same path within window → single callback."""
        from logos.engine.watcher import DirectoryWatcher

        callback = AsyncMock()
        loop = asyncio.get_running_loop()
        watcher = DirectoryWatcher(
            watch_paths=[],
            callback=callback,
            debounce_ms=50,
            loop=loop,
            data_dir=Path("/data"),
        )

        # Manually inject debounced events
        path = Path("/data/test.md")
        watcher._debounce(path, "created")
        watcher._debounce(path, "modified")
        watcher._debounce(path, "modified")

        # Wait for debounce timer to fire + coroutine to complete
        await asyncio.sleep(0.2)

        assert callback.call_count == 1
        event = callback.call_args[0][0]
        assert event.event_type == "created"  # First event type preserved

    async def test_self_trigger_prevention(self):
        from logos.engine.watcher import DirectoryWatcher

        watcher = DirectoryWatcher(
            watch_paths=[],
            callback=AsyncMock(),
            debounce_ms=50,
        )
        path = Path("/data/output.md")
        watcher.ignore_fn(path)
        assert path in watcher._own_writes

        # Simulate event on ignored path — should be consumed
        watcher._own_writes.discard(path)
        assert path not in watcher._own_writes

        # Clean up timers
        await watcher.stop()

    async def test_dotfile_filtering(self):
        from logos.engine.watcher import _should_skip

        assert _should_skip(Path("/data/.hidden/file.md")) is True
        assert _should_skip(Path("/data/processed/file.md")) is True
        assert _should_skip(Path("/data/profiles/health.jsonl")) is False

    async def test_doc_type_inference_path_based(self):
        from logos.engine.watcher import _infer_doc_type

        doc_type, fm = _infer_doc_type(Path("/data/profiles/health-history.jsonl"))
        assert doc_type == "health-event"
        assert fm is None

    async def test_doc_type_inference_axiom_dir(self):
        from logos.engine.watcher import _infer_doc_type

        doc_type, fm = _infer_doc_type(Path("/project/axioms/implications/single_user.yaml"))
        assert doc_type == "axiom-implication"


# ── TestReactiveEngine ──────────────────────────────────────────────────────


class TestReactiveEngine:
    @patch("logos.engine.watcher.DirectoryWatcher")
    async def test_lifecycle_start_stop(self, mock_watcher_cls):
        from logos.engine import ReactiveEngine

        mock_watcher = AsyncMock()
        mock_watcher_cls.return_value = mock_watcher

        engine = ReactiveEngine(data_dir=Path("/tmp/test"))
        await engine.start()
        assert engine.status["running"] is True

        await engine.stop()
        assert engine.status["running"] is False

    async def test_pause_resume(self):
        from logos.engine import ReactiveEngine

        engine = ReactiveEngine(data_dir=Path("/tmp/test"))
        assert engine.status["paused"] is False

        engine.pause()
        assert engine.status["paused"] is True

        engine.resume()
        assert engine.status["paused"] is False

    async def test_status_counters_initial(self):
        from logos.engine import ReactiveEngine

        engine = ReactiveEngine(data_dir=Path("/tmp/test"))
        status = engine.status
        assert status["events_processed"] == 0
        assert status["rules_evaluated"] == 0
        assert status["actions_executed"] == 0
        assert status["errors"] == 0

    async def test_empty_registry(self):
        from logos.engine import ReactiveEngine

        engine = ReactiveEngine(data_dir=Path("/tmp/test"))
        assert len(engine.registry) == 0

    @patch("logos.engine.watcher.DirectoryWatcher")
    async def test_handle_change_paused(self, mock_watcher_cls):
        from logos.engine import ReactiveEngine

        mock_watcher = AsyncMock()
        mock_watcher_cls.return_value = mock_watcher

        engine = ReactiveEngine(data_dir=Path("/tmp/test"))
        engine.pause()

        event = ChangeEvent(
            path=Path("/tmp/test/file.md"),
            event_type="modified",
            doc_type=None,
            frontmatter=None,
            timestamp=datetime.now(),
        )
        await engine._handle_change(event)
        assert engine.status["events_processed"] == 0
