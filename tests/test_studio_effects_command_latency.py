"""W4.5: per-stage command latency histogram on logos-api studio routes.

These tests exercise the instrumentation calls in ``replace_effect_graph``
and ``patch_effect_graph``. The histogram itself is a thin wrapper around
``prometheus_client.Histogram`` registered on the default REGISTRY at
import time. We patch ``_observe_stage`` to capture stage observations
without touching the live registry.

Sprint 7 P1 observability follow-up — gives Grafana per-stage cost so the
operator can find which command-pipeline stage regresses first.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from logos.api.routes import studio_effects


def _minimal_graph_payload() -> dict[str, object]:
    """Smallest valid EffectGraph payload — empty graph."""
    return {"nodes": {}, "edges": []}


def _minimal_patch_payload() -> dict[str, object]:
    """Smallest valid GraphPatch payload — empty patch."""
    return {"add_nodes": {}, "remove_nodes": [], "add_edges": [], "remove_edges": []}


class TestCommandLatencyInstrumentation:
    @patch("logos.api.routes.studio_effects._observe_stage")
    @patch("logos.api.routes.studio_effects._get_runtime")
    def test_replace_graph_observes_validate_ipc_total(
        self,
        mock_get_runtime: MagicMock,
        mock_observe: MagicMock,
        tmp_path,
    ) -> None:
        """Drop #48 API-1/API-2: replace_effect_graph is mutation-bus
        authoritative — no in-process runtime_load step. Handler
        observes validate + ipc_write + total only."""
        rt = MagicMock()
        # load_graph should NOT be called — the runtime load happens on
        # the compositor side via state_reader_loop's poll of
        # /dev/shm/hapax-compositor/graph-mutation.json.
        rt.load_graph = MagicMock()
        mock_get_runtime.return_value = rt

        # Redirect the IPC write to a tmp dir so the test doesn't touch
        # /dev/shm. Path() inside the handler is relative to the module,
        # so monkey-patching the global is the cleanest way.
        with patch.object(studio_effects, "Path", side_effect=lambda p: tmp_path / p.lstrip("/")):
            asyncio.run(studio_effects.replace_effect_graph(_minimal_graph_payload()))

        observed_stages = {call.args[1] for call in mock_observe.call_args_list}
        assert "validate" in observed_stages
        assert "ipc_write" in observed_stages
        assert "total" in observed_stages
        # Drop #48 API-1: runtime_load is no longer observed — the handler
        # no longer calls rt.load_graph directly. Runtime load happens
        # out-of-process via the mutation bus.
        assert "runtime_load" not in observed_stages
        rt.load_graph.assert_not_called()
        # All observations are tagged with the same command name.
        commands = {call.args[0] for call in mock_observe.call_args_list}
        assert commands == {"replace_graph"}
        # All observations are non-negative durations in milliseconds.
        for call in mock_observe.call_args_list:
            assert call.args[2] >= 0.0

    @patch("logos.api.routes.studio_effects._observe_stage")
    @patch("logos.api.routes.studio_effects._get_runtime")
    def test_patch_graph_observes_validate_runtime_total(
        self,
        mock_get_runtime: MagicMock,
        mock_observe: MagicMock,
    ) -> None:
        rt = MagicMock()
        rt.apply_patch = MagicMock()
        mock_get_runtime.return_value = rt

        asyncio.run(studio_effects.patch_effect_graph(_minimal_patch_payload()))

        observed_stages = {call.args[1] for call in mock_observe.call_args_list}
        assert observed_stages == {"validate", "runtime_load", "total"}
        commands = {call.args[0] for call in mock_observe.call_args_list}
        assert commands == {"patch_graph"}

    @patch("logos.api.routes.studio_effects._observe_stage")
    @patch("logos.api.routes.studio_effects._get_runtime")
    def test_runtime_unavailable_raises_503_without_observation(
        self,
        mock_get_runtime: MagicMock,
        mock_observe: MagicMock,
    ) -> None:
        from fastapi import HTTPException

        mock_get_runtime.return_value = None
        with pytest.raises(HTTPException) as exc:
            asyncio.run(studio_effects.replace_effect_graph(_minimal_graph_payload()))
        assert exc.value.status_code == 503
        # Bail-out path: no stages should be observed.
        assert mock_observe.call_count == 0


class TestLazyHistogramInit:
    def test_returns_none_when_prometheus_client_missing(self) -> None:
        # Force a fresh init that fails by patching the import.
        studio_effects._COMMAND_LATENCY = None
        studio_effects._COMMAND_LATENCY_INIT_FAILED = False
        with patch.dict("sys.modules", {"prometheus_client": None}):
            result = studio_effects._command_latency()
        assert result is None
        assert studio_effects._COMMAND_LATENCY_INIT_FAILED is True
        # Reset for subsequent tests.
        studio_effects._COMMAND_LATENCY_INIT_FAILED = False
        studio_effects._COMMAND_LATENCY = None

    def test_subsequent_call_returns_cached_histogram(self) -> None:
        studio_effects._COMMAND_LATENCY = None
        studio_effects._COMMAND_LATENCY_INIT_FAILED = False
        first = studio_effects._command_latency()
        second = studio_effects._command_latency()
        # Either both None (no prometheus_client) or both the same Histogram.
        assert first is second

    def test_observe_is_safe_when_histogram_unavailable(self) -> None:
        studio_effects._COMMAND_LATENCY = None
        studio_effects._COMMAND_LATENCY_INIT_FAILED = True
        # Must not raise even though the histogram is unavailable.
        studio_effects._observe_stage("replace_graph", "validate", 1.5)
        studio_effects._COMMAND_LATENCY_INIT_FAILED = False
