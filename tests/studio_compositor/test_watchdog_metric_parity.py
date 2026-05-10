from __future__ import annotations

from pathlib import Path


def test_every_watchdog_ping_branch_records_prometheus_metric_parity() -> None:
    source = (
        Path(__file__).parents[2] / "agents" / "studio_compositor" / "lifecycle.py"
    ).read_text(encoding="utf-8")
    watchdog_pings = source.count("sd_notify_watchdog()")
    metric_records = source.count("_record_watchdog_ping_metrics(compositor)")

    assert watchdog_pings == 3
    assert metric_records == watchdog_pings
    assert "DEGRADED — director silent for >180s" in source
