"""Health monitor and introspection tolerate missing OpenTelemetry."""

from __future__ import annotations

import builtins
import importlib
import json
from pathlib import Path
from unittest.mock import patch

from agents.health_monitor.models import HealthReport, Status


def _blocked_otel_import(real_import):
    def _import(name, *args, **kwargs):
        if name == "opentelemetry" or name.startswith("opentelemetry."):
            raise ModuleNotFoundError("mocked missing opentelemetry")
        return real_import(name, *args, **kwargs)

    return _import


def test_tracing_helper_returns_noop_without_opentelemetry() -> None:
    from agents.health_monitor import tracing

    real_import = builtins.__import__
    with patch("builtins.__import__", side_effect=_blocked_otel_import(real_import)):
        tracer = tracing.get_tracer("test")

    with tracer.start_as_current_span("missing-otel"):
        pass


def test_health_monitor_runner_imports_without_opentelemetry() -> None:
    import agents.health_monitor.runner as runner

    real_import = builtins.__import__
    with patch("builtins.__import__", side_effect=_blocked_otel_import(real_import)):
        reloaded = importlib.reload(runner)
        with reloaded._tracer.start_as_current_span("missing-otel"):
            pass

    importlib.reload(runner)


def test_introspect_imports_without_opentelemetry() -> None:
    import agents.introspect as introspect

    real_import = builtins.__import__
    with patch("builtins.__import__", side_effect=_blocked_otel_import(real_import)):
        reloaded = importlib.reload(introspect)
        with reloaded._tracer.start_as_current_span("missing-otel"):
            pass

    importlib.reload(introspect)


def test_snapshot_writes_structured_degradation_without_networkx(
    tmp_path: Path, monkeypatch
) -> None:
    from agents.health_monitor import snapshot

    monkeypatch.setattr(snapshot, "PROFILES_DIR", tmp_path)
    monkeypatch.setattr(snapshot, "INFRA_SNAPSHOT_FILE", tmp_path / "infra-snapshot.json")
    monkeypatch.setattr(snapshot, "_collect_all_timers", lambda: [])

    report = HealthReport(
        timestamp="2026-06-11T00:00:00Z",
        hostname="testhost",
        overall_status=Status.HEALTHY,
        groups=[],
    )

    real_import = builtins.__import__

    def blocked_networkx(name, *args, **kwargs):
        if name == "networkx" or name.startswith("networkx."):
            raise ModuleNotFoundError("mocked missing networkx")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=blocked_networkx):
        snapshot.write_infra_snapshot(report)

    data = json.loads((tmp_path / "infra-snapshot.json").read_text())
    assert data["topology"]["error"] == "failed"
    assert data["topology"]["detail"]
