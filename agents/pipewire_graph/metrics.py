"""Prometheus metrics for ``hapax-pipewire-graph`` shadow mode."""

from __future__ import annotations

from typing import Any

from agents.pipewire_graph.circuit_breaker import EgressFailureMode, EgressHealth

try:  # pragma: no cover - exercised when prometheus_client is installed
    from prometheus_client import CollectorRegistry, Counter, Gauge, start_http_server
except Exception:  # pragma: no cover - optional dependency fallback
    CollectorRegistry = None  # type: ignore[assignment]
    Counter = None  # type: ignore[assignment]
    Gauge = None  # type: ignore[assignment]
    start_http_server = None  # type: ignore[assignment]


class PipewireGraphMetrics:
    """Small metric surface for the shadow daemon.

    The class is a no-op when ``prometheus_client`` is unavailable, so
    the daemon can still run locally in minimal environments.
    """

    def __init__(self, registry: Any | None = None) -> None:
        self.enabled = CollectorRegistry is not None
        self.registry = registry or (
            CollectorRegistry(auto_describe=True) if self.enabled else None
        )
        if not self.enabled:
            self._rms = None
            self._crest = None
            self._zcr = None
            self._state = None
            self._dry_runs = None
            self._alerts = None
            return

        assert Gauge is not None
        assert Counter is not None
        self._rms = Gauge(
            "hapax_pipewire_graph_egress_rms_dbfs",
            "OBS-bound egress RMS measured by the shadow PipeWire graph daemon.",
            ["source"],
            registry=self.registry,
        )
        self._crest = Gauge(
            "hapax_pipewire_graph_egress_crest_factor",
            "OBS-bound egress crest factor measured by the shadow PipeWire graph daemon.",
            ["source"],
            registry=self.registry,
        )
        self._zcr = Gauge(
            "hapax_pipewire_graph_egress_zcr",
            "OBS-bound egress zero-crossing rate measured by the shadow daemon.",
            ["source"],
            registry=self.registry,
        )
        self._state = Gauge(
            "hapax_pipewire_graph_shadow_state",
            "Shadow breaker state by mode, one-hot encoded.",
            ["mode"],
            registry=self.registry,
        )
        self._dry_runs = Counter(
            "hapax_pipewire_graph_shadow_dry_runs_total",
            "Shadow dry-run reports written by result.",
            ["result"],
            registry=self.registry,
        )
        self._alerts = Counter(
            "hapax_pipewire_graph_shadow_alerts_total",
            "Shadow alerts that would have engaged safe-mute in active mode.",
            ["mode"],
            registry=self.registry,
        )
        for mode in EgressFailureMode:
            self._state.labels(mode=mode.value).set(0)

    def start_http_server(self, port: int, addr: str = "127.0.0.1") -> bool:
        if not self.enabled or start_http_server is None:
            return False
        start_http_server(port, addr=addr, registry=self.registry)
        return True

    def observe_health(self, health: EgressHealth, state: EgressFailureMode) -> None:
        if not self.enabled:
            return
        self._rms.labels(source=health.source).set(health.rms_dbfs)
        self._crest.labels(source=health.source).set(health.crest_factor)
        self._zcr.labels(source=health.source).set(health.zcr)
        for mode in EgressFailureMode:
            self._state.labels(mode=mode.value).set(1 if mode == state else 0)

    def record_dry_run(self, result: str) -> None:
        if self.enabled:
            self._dry_runs.labels(result=result).inc()

    def record_shadow_alert(self, mode: EgressFailureMode) -> None:
        if self.enabled:
            self._alerts.labels(mode=mode.value).inc()


__all__ = ["PipewireGraphMetrics"]
