"""Tests for resource lifecycle management."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

from agents.hapax_daimonion.resource_lifecycle import (
    ExecutorResource,
    ResourceRegistry,
)


class TestResourceRegistry:
    def test_register_and_stop_all(self):
        reg = ResourceRegistry()
        r1 = MagicMock()
        r1.is_alive.return_value = True
        r2 = MagicMock()
        r2.is_alive.return_value = True

        reg.register("r1", r1)
        reg.register("r2", r2)

        failed = reg.stop_all(timeout=1.0)
        assert failed == []
        r1.stop.assert_called_once()
        r2.stop.assert_called_once()

    def test_stop_all_reverse_order(self):
        order: list[str] = []
        r1 = MagicMock()
        r1.stop.side_effect = lambda: order.append("r1")
        r1.is_alive.return_value = True
        r2 = MagicMock()
        r2.stop.side_effect = lambda: order.append("r2")
        r2.is_alive.return_value = True

        reg = ResourceRegistry()
        reg.register("r1", r1)
        reg.register("r2", r2)
        reg.stop_all(timeout=1.0)

        assert order == ["r2", "r1"]

    def test_stop_failure_captured(self):
        reg = ResourceRegistry()
        r1 = MagicMock()
        r1.stop.side_effect = RuntimeError("boom")
        r1.is_alive.return_value = True
        reg.register("r1", r1)

        failed = reg.stop_all(timeout=1.0)
        assert failed == ["r1"]

    def test_skip_already_stopped(self):
        reg = ResourceRegistry()
        r1 = MagicMock()
        r1.is_alive.return_value = False
        reg.register("r1", r1)

        reg.stop_all(timeout=1.0)
        r1.stop.assert_not_called()


class TestExecutorResource:
    def test_wraps_thread_pool(self):
        pool = ThreadPoolExecutor(max_workers=1)
        res = ExecutorResource(pool)
        assert res.is_alive()
        res.stop()
        assert not res.is_alive()
