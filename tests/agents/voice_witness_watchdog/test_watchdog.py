"""Tests for the voice witness watchdog (consumer of voice-output-witness.json).

Audit SS6.2 (CASE-VOICE-FOUNDATION-20260610): the witness records the truth;
nothing consumes it. The watchdog is the trivial consumer — ntfy on
drop-streak >= N or witness staleness > threshold, quiet on healthy.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from agents.voice_witness_watchdog import (
    Alert,
    WatchdogConfig,
    main,
    run_tick,
)

BASE_TS = 1_780_000_000.0  # arbitrary fixed epoch for deterministic ticks


def _iso(ts: float) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(ts, tz=UTC).isoformat().replace("+00:00", "Z")


def _write_witness(
    path: Path,
    *,
    now: float,
    status: str = "drop_recorded",
    drop_ts: float | None = None,
    drop_reason: str = "pipeline_unavailable",
    success_ts: float | None = None,
) -> None:
    payload: dict = {
        "version": 1,
        "updated_at": _iso(now),
        "freshness_s": 0.0,
        "status": status,
    }
    if drop_ts is not None:
        payload["last_drop"] = {
            "ts": _iso(drop_ts),
            "status": "dropped",
            "completed": False,
            "source": "stimmung",
            "reason": drop_reason,
        }
    if success_ts is not None:
        payload["last_successful_playback"] = {
            "ts": _iso(success_ts),
            "status": "completed",
            "completed": True,
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    os.utime(path, (now, now))


@pytest.fixture
def config(tmp_path: Path) -> WatchdogConfig:
    return WatchdogConfig(
        witness_path=tmp_path / "voice-output-witness.json",
        state_path=tmp_path / "watchdog-state.json",
        drop_streak_threshold=3,
        staleness_threshold_s=1800.0,
        alert_cooldown_s=3600.0,
    )


class Recorder:
    def __init__(self) -> None:
        self.alerts: list[Alert] = []

    def __call__(self, alert: Alert) -> None:
        self.alerts.append(alert)


# ── Healthy path ─────────────────────────────────────────────────────────────


def test_quiet_on_healthy_witness(config: WatchdogConfig) -> None:
    """Recent successful playback after a drop: no alert, streak 0."""
    send = Recorder()
    _write_witness(
        config.witness_path,
        now=BASE_TS,
        status="playback_completed",
        drop_ts=BASE_TS - 600,
        success_ts=BASE_TS - 60,
    )
    result = run_tick(config, now=BASE_TS + 10, send=send)
    assert send.alerts == []
    assert result.alerts == []
    assert result.drop_streak == 0


def test_quiet_on_witness_with_no_drops(config: WatchdogConfig) -> None:
    send = Recorder()
    _write_witness(config.witness_path, now=BASE_TS, status="composed")
    result = run_tick(config, now=BASE_TS + 10, send=send)
    assert send.alerts == []
    assert result.drop_streak == 0


# ── Drop-streak ──────────────────────────────────────────────────────────────


def test_alert_fires_on_induced_drop_streak(config: WatchdogConfig) -> None:
    """Three distinct drops with no intervening success: alert on tick 3."""
    send = Recorder()
    for i in range(3):
        tick = BASE_TS + i * 60
        _write_witness(config.witness_path, now=tick, drop_ts=tick - 1)
        result = run_tick(config, now=tick + 10, send=send)
    assert result.drop_streak == 3
    assert len(send.alerts) == 1
    assert send.alerts[0].kind == "drop_streak"
    assert "pipeline_unavailable" in send.alerts[0].body
    assert "3" in send.alerts[0].body


def test_same_drop_does_not_increment_streak(config: WatchdogConfig) -> None:
    """Re-observing the identical drop across ticks is not new evidence."""
    send = Recorder()
    _write_witness(config.witness_path, now=BASE_TS, drop_ts=BASE_TS - 1)
    for i in range(5):
        result = run_tick(config, now=BASE_TS + 10 + i * 60, send=send)
    assert result.drop_streak == 1
    assert send.alerts == []


def test_successful_playback_resets_streak(config: WatchdogConfig) -> None:
    send = Recorder()
    for i in range(2):
        tick = BASE_TS + i * 60
        _write_witness(config.witness_path, now=tick, drop_ts=tick - 1)
        run_tick(config, now=tick + 10, send=send)
    # Playback succeeds after the drops.
    _write_witness(
        config.witness_path,
        now=BASE_TS + 180,
        status="playback_completed",
        drop_ts=BASE_TS + 119,
        success_ts=BASE_TS + 175,
    )
    result = run_tick(config, now=BASE_TS + 190, send=send)
    assert result.drop_streak == 0
    assert send.alerts == []


def test_drop_streak_alert_respects_cooldown(config: WatchdogConfig) -> None:
    """Within the cooldown window the alert does not repeat; after it, it does."""
    send = Recorder()
    for i in range(4):
        tick = BASE_TS + i * 60
        _write_witness(config.witness_path, now=tick, drop_ts=tick - 1)
        run_tick(config, now=tick + 10, send=send)
    assert len(send.alerts) == 1  # fired at streak 3, suppressed at streak 4

    # New drop after the cooldown elapses → re-alert.
    late = BASE_TS + 3 * 60 + 10 + config.alert_cooldown_s + 60
    _write_witness(config.witness_path, now=late, drop_ts=late - 1)
    run_tick(config, now=late + 10, send=send)
    assert len(send.alerts) == 2


def test_recovery_clears_cooldown_for_next_incident(config: WatchdogConfig) -> None:
    """A new streak after recovery alerts immediately, inside the old cooldown."""
    send = Recorder()
    for i in range(3):
        tick = BASE_TS + i * 60
        _write_witness(config.witness_path, now=tick, drop_ts=tick - 1)
        run_tick(config, now=tick + 10, send=send)
    assert len(send.alerts) == 1

    # Recovery: successful playback.
    _write_witness(
        config.witness_path,
        now=BASE_TS + 240,
        status="playback_completed",
        drop_ts=BASE_TS + 119,
        success_ts=BASE_TS + 235,
    )
    run_tick(config, now=BASE_TS + 250, send=send)

    # Fresh incident inside the original cooldown window.
    for i in range(3):
        tick = BASE_TS + 300 + i * 60
        _write_witness(config.witness_path, now=tick, drop_ts=tick - 1)
        run_tick(config, now=tick + 10, send=send)
    assert len(send.alerts) == 2


# ── Staleness ────────────────────────────────────────────────────────────────


def test_staleness_alert_on_stale_witness_file(config: WatchdogConfig) -> None:
    send = Recorder()
    _write_witness(config.witness_path, now=BASE_TS, status="composed")
    result = run_tick(config, now=BASE_TS + 2000, send=send)  # > 1800s threshold
    assert result.witness_status == "stale"
    assert len(send.alerts) == 1
    assert send.alerts[0].kind == "witness_stale"


def test_staleness_alert_on_missing_witness_file(config: WatchdogConfig) -> None:
    send = Recorder()
    result = run_tick(config, now=BASE_TS, send=send)
    assert result.witness_status == "missing"
    assert len(send.alerts) == 1
    assert send.alerts[0].kind == "witness_stale"
    assert "voice_output_witness_missing" in send.alerts[0].body


def test_staleness_alert_on_malformed_witness_file(config: WatchdogConfig) -> None:
    send = Recorder()
    config.witness_path.write_text("not json {{{", encoding="utf-8")
    os.utime(config.witness_path, (BASE_TS, BASE_TS))
    result = run_tick(config, now=BASE_TS + 10, send=send)
    assert result.witness_status == "malformed"
    assert len(send.alerts) == 1
    assert send.alerts[0].kind == "witness_stale"


def test_staleness_alert_respects_cooldown(config: WatchdogConfig) -> None:
    send = Recorder()
    _write_witness(config.witness_path, now=BASE_TS, status="composed")
    run_tick(config, now=BASE_TS + 2000, send=send)
    run_tick(config, now=BASE_TS + 2060, send=send)
    assert len(send.alerts) == 1
    run_tick(config, now=BASE_TS + 2000 + config.alert_cooldown_s + 60, send=send)
    assert len(send.alerts) == 2


def test_fresh_witness_clears_staleness_cooldown(config: WatchdogConfig) -> None:
    send = Recorder()
    _write_witness(config.witness_path, now=BASE_TS, status="composed")
    run_tick(config, now=BASE_TS + 2000, send=send)
    assert len(send.alerts) == 1
    # Witness comes back fresh, then goes stale again within old cooldown.
    _write_witness(config.witness_path, now=BASE_TS + 2100, status="composed")
    run_tick(config, now=BASE_TS + 2110, send=send)
    run_tick(config, now=BASE_TS + 2100 + 2000, send=send)
    assert len(send.alerts) == 2


def test_stale_witness_preserves_drop_streak_state(config: WatchdogConfig) -> None:
    """Staleness ticks must not corrupt the accumulated streak."""
    send = Recorder()
    for i in range(2):
        tick = BASE_TS + i * 60
        _write_witness(config.witness_path, now=tick, drop_ts=tick - 1)
        run_tick(config, now=tick + 10, send=send)
    # Witness goes stale (daemon dead) — streak survives.
    run_tick(config, now=BASE_TS + 60 + 2000, send=send)
    state = json.loads(config.state_path.read_text(encoding="utf-8"))
    assert state["drop_streak"] == 2


# ── Sender / config plumbing ─────────────────────────────────────────────────


def test_default_sender_uses_shared_notify(
    config: WatchdogConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple] = []

    def fake_send_notification(title: str, message: str, **kwargs) -> bool:
        sent.append((title, message, kwargs))
        return True

    import shared.notify

    monkeypatch.setattr(shared.notify, "send_notification", fake_send_notification)
    run_tick(config, now=BASE_TS)  # missing witness → staleness alert
    assert len(sent) == 1
    title, _message, kwargs = sent[0]
    assert "voice" in title.lower()
    assert kwargs.get("priority") == "high"


def test_no_ntfy_suppresses_send_but_reports_alerts(
    config: WatchdogConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple] = []

    def fake_send_notification(title: str, message: str, **kwargs) -> bool:
        sent.append((title, message))
        return True

    import shared.notify

    monkeypatch.setattr(shared.notify, "send_notification", fake_send_notification)
    config.enable_ntfy = False
    result = run_tick(config, now=BASE_TS)
    assert sent == []
    assert len(result.alerts) == 1  # condition still evaluated and reported


def test_config_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HAPAX_VOICE_WITNESS_PATH", str(tmp_path / "w.json"))
    monkeypatch.setenv("HAPAX_VOICE_WITNESS_WATCHDOG_STATE_PATH", str(tmp_path / "s.json"))
    monkeypatch.setenv("HAPAX_VOICE_WITNESS_DROP_STREAK_THRESHOLD", "5")
    monkeypatch.setenv("HAPAX_VOICE_WITNESS_STALENESS_THRESHOLD_S", "900")
    monkeypatch.setenv("HAPAX_VOICE_WITNESS_ALERT_COOLDOWN_S", "120")
    monkeypatch.setenv("HAPAX_VOICE_WITNESS_ENABLE_NTFY", "0")
    config = WatchdogConfig.from_env()
    assert config.witness_path == tmp_path / "w.json"
    assert config.state_path == tmp_path / "s.json"
    assert config.drop_streak_threshold == 5
    assert config.staleness_threshold_s == 900.0
    assert config.alert_cooldown_s == 120.0
    assert config.enable_ntfy is False


def test_main_once_prints_summary_and_exits_zero(
    config: WatchdogConfig, capsys: pytest.CaptureFixture
) -> None:
    _write_witness(config.witness_path, now=time.time(), status="composed")
    rc = main(
        [
            "--witness-path",
            str(config.witness_path),
            "--state-path",
            str(config.state_path),
            "--no-ntfy",
            "--print",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "witness_status" in out


def test_main_exits_zero_even_when_alerting(config: WatchdogConfig) -> None:
    """Alerting is the job — a firing alert is not a unit failure."""
    rc = main(
        [
            "--witness-path",
            str(config.witness_path),  # missing → staleness alert
            "--state-path",
            str(config.state_path),
            "--no-ntfy",
        ]
    )
    assert rc == 0
