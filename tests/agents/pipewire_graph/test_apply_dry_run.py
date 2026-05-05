from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from agents.pipewire_graph.circuit_breaker import EgressFailureMode, EgressHealth
from agents.pipewire_graph.daemon import (
    ShadowDaemonConfig,
    ShadowPipewireGraphDaemon,
    apply_dry_run,
)
from agents.pipewire_graph.safe_mute import SafeMuteRail
from shared.audio_graph import AudioGraph, AudioNode, ChannelMap, NodeKind


def _graph() -> AudioGraph:
    return AudioGraph(
        nodes=[
            AudioNode(
                id="hapax-livestream-tap",
                kind=NodeKind.TAP,
                pipewire_name="hapax-livestream-tap",
                channels=ChannelMap(count=2, positions=["FL", "FR"]),
            ),
            AudioNode(
                id="obs-broadcast-remap",
                kind=NodeKind.LOOPBACK,
                pipewire_name="hapax-obs-broadcast-remap",
                channels=ChannelMap(count=2, positions=["FL", "FR"]),
            ),
        ]
    )


def test_apply_dry_run_writes_report_under_state_root(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    pipewire_root = tmp_path / "pipewire"
    wireplumber_root = tmp_path / "wireplumber"
    pipewire_root.mkdir()
    wireplumber_root.mkdir()

    report = apply_dry_run(
        _graph(),
        state_root=state_root,
        pipewire_conf_dir=pipewire_root,
        wireplumber_conf_dir=wireplumber_root,
        now_utc=datetime(2026, 5, 5, 0, 0, 0, tzinfo=UTC),
    )

    report_path = Path(str(report["report_path"]))
    assert report_path.is_file()
    assert report_path.is_relative_to(state_root)
    payload = json.loads(report_path.read_text())
    assert payload["mode"] == "shadow"
    assert payload["guardrails"]["live_pipewire_mutation"] is False
    assert payload["guardrails"]["pactl_load_module"] is False
    assert payload["compile"]["pipewire_conf_count"] == 2
    assert payload["diff"]["pipewire"][0]["state"] == "missing"


def test_shadow_daemon_observe_once_appends_jsonl_without_safe_mute(tmp_path: Path) -> None:
    safe_mute = SafeMuteRail()
    config = ShadowDaemonConfig(
        state_root=tmp_path,
        enable_ntfy=False,
        run_once=True,
    )
    daemon = ShadowPipewireGraphDaemon(config, safe_mute=safe_mute)
    health = EgressHealth(
        rms_dbfs=-22.0,
        peak_dbfs=-3.0,
        crest_factor=3.0,
        zcr=0.08,
        timestamp_utc="2026-05-05T00:00:00.000Z",
        sample_count=24000,
    )

    daemon.observe_once(health)

    rows = [json.loads(line) for line in config.egress_health_path.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["failure_mode"] == EgressFailureMode.NOMINAL.value
    assert rows[0]["rms_dbfs"] == -22.0
    assert rows[0]["clipping_candidate"] is False
    assert safe_mute.engaged is False
    assert safe_mute.engage_attempts == 0


def test_safe_mute_shadow_operations_never_mutate_live_graph() -> None:
    safe_mute = SafeMuteRail()

    load_result = safe_mute.load_shadow()
    engage_result = safe_mute.engage(reason="synthetic clipping shadow")
    disengage_result = safe_mute.disengage()

    assert load_result.mutated_live_graph is False
    assert engage_result.mutated_live_graph is False
    assert disengage_result.mutated_live_graph is False
    assert safe_mute.loaded is True
    assert safe_mute.engaged is False
    assert safe_mute.engage_attempts == 1


def test_shadow_daemon_apply_dry_run_records_report(tmp_path: Path) -> None:
    config = ShadowDaemonConfig(
        state_root=tmp_path / "state",
        pipewire_conf_dir=tmp_path / "pipewire",
        wireplumber_conf_dir=tmp_path / "wireplumber",
        enable_ntfy=False,
        run_once=True,
    )
    config.pipewire_conf_dir.mkdir()
    config.wireplumber_conf_dir.mkdir()
    daemon = ShadowPipewireGraphDaemon(config)

    report = daemon.apply_dry_run(_graph())

    assert report["result"] == "ok"
    assert Path(str(report["report_path"])).is_file()
