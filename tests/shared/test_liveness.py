"""Tests for shared.liveness — the unified liveness + recovery substrate.

Self-contained (no shared conftest). The watchdog tests drive the REAL
``RecoveryGovernor`` with injected deterministic collaborators (tmp state dir,
fixed clock, open admission, no-op notify/mint, identity jitter) so the
bounding/pressure/escalation integration is exercised end-to-end without touching
prod state or randomness.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from shared.liveness import (
    ALIVE,
    MISSING,
    QUIET,
    STALLED,
    Heartbeat,
    LivenessSpec,
    LivenessWatchdog,
    classify,
    emit_heartbeat,
    load_registry,
    read_heartbeat,
    register,
)
from shared.recovery_governor import RecoveryGovernor, RecoveryParams

# ── Heartbeat ────────────────────────────────────────────────────────────────


def test_emit_and_read_heartbeat_round_trips(tmp_path: Path) -> None:
    emit_heartbeat("lane:epsilon:progress", "42", ts=1000.0, meta={"lines": 42}, beat_dir=tmp_path)
    hb = read_heartbeat("lane:epsilon:progress", beat_dir=tmp_path)
    assert hb == Heartbeat(op_id="lane:epsilon:progress", ts=1000.0, token="42", meta={"lines": 42})


def test_read_missing_heartbeat_is_none(tmp_path: Path) -> None:
    assert read_heartbeat("nope", beat_dir=tmp_path) is None


def test_emit_heartbeat_sanitizes_op_id_into_filename(tmp_path: Path) -> None:
    emit_heartbeat("deploy:post-merge/x", "sha1", ts=1.0, beat_dir=tmp_path)
    # exactly one beat file, no path traversal out of beat_dir
    beats = list(tmp_path.glob("*.beat"))
    assert len(beats) == 1
    assert beats[0].parent == tmp_path


def test_emit_heartbeat_is_atomic_no_partial_file(tmp_path: Path) -> None:
    emit_heartbeat("op", "t", ts=1.0, beat_dir=tmp_path)
    assert not list(tmp_path.glob("*.tmp"))


def test_corrupt_heartbeat_reads_as_none(tmp_path: Path) -> None:
    emit_heartbeat("op", "t", ts=1.0, beat_dir=tmp_path)
    beat = next(tmp_path.glob("*.beat"))
    beat.write_text("{ not json")
    assert read_heartbeat("op", beat_dir=tmp_path) is None


# ── Registry ─────────────────────────────────────────────────────────────────


def test_register_and_load_round_trips(tmp_path: Path) -> None:
    spec = LivenessSpec(
        op_id="deploy:post-merge",
        recovery_cmd=["scripts/redeploy", "--rearm"],
        max_quiet_s=900.0,
        lineage="deploy",
        description="post-merge deploy chain",
    )
    register(spec, registry_dir=tmp_path)
    loaded = load_registry(registry_dir=tmp_path)
    assert loaded == [spec]


def test_load_registry_empty_dir(tmp_path: Path) -> None:
    assert load_registry(registry_dir=tmp_path) == []


def test_register_overwrites_same_op_id(tmp_path: Path) -> None:
    register(LivenessSpec(op_id="x", recovery_cmd=["a"], max_quiet_s=10.0), registry_dir=tmp_path)
    register(LivenessSpec(op_id="x", recovery_cmd=["b"], max_quiet_s=20.0), registry_dir=tmp_path)
    loaded = load_registry(registry_dir=tmp_path)
    assert len(loaded) == 1
    assert loaded[0].recovery_cmd == ["b"]


def test_load_registry_skips_corrupt_entries(tmp_path: Path) -> None:
    register(LivenessSpec(op_id="ok", recovery_cmd=["a"], max_quiet_s=10.0), registry_dir=tmp_path)
    (tmp_path / "broken.json").write_text("{ not json")
    loaded = load_registry(registry_dir=tmp_path)
    assert [s.op_id for s in loaded] == ["ok"]


# ── classify (pure: progress-token, not wall-clock) ──────────────────────────


def _spec(**kw) -> LivenessSpec:
    base = {"op_id": "op", "recovery_cmd": ["x"], "max_quiet_s": 100.0}
    base.update(kw)
    return LivenessSpec(**base)


def test_classify_missing_when_no_heartbeat() -> None:
    v = classify(_spec(), None, prev_token=None, now=1000.0, threshold_s=100.0)
    assert v.status == MISSING


def test_classify_alive_when_token_advanced_even_if_quiet_exceeds_threshold() -> None:
    # silent for 10000s (>> threshold) BUT the token moved since last scan ⇒ alive
    hb = Heartbeat("op", ts=0.0, token="500", meta={})
    v = classify(_spec(max_quiet_s=100.0), hb, prev_token="490", now=10000.0, threshold_s=100.0)
    assert v.status == ALIVE


def test_classify_quiet_when_token_unchanged_within_threshold() -> None:
    hb = Heartbeat("op", ts=950.0, token="500", meta={})
    v = classify(_spec(max_quiet_s=100.0), hb, prev_token="500", now=1000.0, threshold_s=100.0)
    assert v.status == QUIET
    assert v.quiet_s == pytest.approx(50.0)


def test_classify_stalled_when_token_unchanged_and_past_threshold() -> None:
    hb = Heartbeat("op", ts=800.0, token="500", meta={})
    v = classify(_spec(max_quiet_s=100.0), hb, prev_token="500", now=1000.0, threshold_s=100.0)
    assert v.status == STALLED
    assert v.quiet_s == pytest.approx(200.0)


def test_classify_first_scan_no_prev_token_uses_quiet_age_only() -> None:
    # never seen before (prev_token None) but a real beat exists: fall back to age
    hb = Heartbeat("op", ts=800.0, token="500", meta={})
    stalled = classify(_spec(max_quiet_s=100.0), hb, prev_token=None, now=1000.0, threshold_s=100.0)
    assert stalled.status == STALLED
    fresh = classify(_spec(max_quiet_s=100.0), hb, prev_token=None, now=850.0, threshold_s=100.0)
    assert fresh.status == QUIET


# ── Watchdog.scan (integration with the real governor) ───────────────────────


class _RecordingExec:
    def __init__(self, result: bool = True) -> None:
        self.calls: list[list[str]] = []
        self.result = result

    def __call__(self, cmd: list[str]) -> bool:
        self.calls.append(list(cmd))
        return self.result


class _RecordingLedger:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def __call__(self, event: dict) -> None:
        self.events.append(event)


def _governor(tmp_path: Path, *, now: float) -> RecoveryGovernor:
    return RecoveryGovernor(
        params=RecoveryParams(bucket_burst=10, bucket_rate=10.0),
        state_dir=tmp_path / "gov",
        now_fn=lambda: now,
        admission_fn=lambda: types.SimpleNamespace(state="open"),
        psi_readable_fn=lambda: True,
        jitter_fn=lambda d: d,
        notify_fn=lambda *a, **k: None,
        mint_fn=lambda *a, **k: None,
    )


def _watchdog(tmp_path: Path, *, now: float, exec_fn, ledger, governor=None) -> LivenessWatchdog:
    return LivenessWatchdog(
        registry_dir=tmp_path / "registry",
        beat_dir=tmp_path / "beats",
        scan_state_path=tmp_path / "scan-state.json",
        governor=governor or _governor(tmp_path, now=now),
        now_fn=lambda: now,
        exec_fn=exec_fn,
        ledger_fn=ledger,
        tau_fn=lambda lineage: 100.0,
    )


def test_scan_recovers_stalled_op_and_ledgers(tmp_path: Path) -> None:
    reg = tmp_path / "registry"
    beats = tmp_path / "beats"
    register(
        LivenessSpec(op_id="op", recovery_cmd=["do", "recover"], max_quiet_s=100.0),
        registry_dir=reg,
    )
    emit_heartbeat("op", "5", ts=0.0, beat_dir=beats)  # silent 1000s, token static
    execer, ledger = _RecordingExec(), _RecordingLedger()
    wd = _watchdog(tmp_path, now=1000.0, exec_fn=execer, ledger=ledger)
    results = wd.scan()
    assert execer.calls == [["do", "recover"]]
    assert len(ledger.events) == 1
    assert ledger.events[0]["op_id"] == "op"
    assert [r.status for r in results] == [STALLED]
    assert results[0].recovered is True


def test_scan_does_not_recover_progressing_op(tmp_path: Path) -> None:
    reg, beats = tmp_path / "registry", tmp_path / "beats"
    register(LivenessSpec(op_id="op", recovery_cmd=["x"], max_quiet_s=100.0), registry_dir=reg)
    execer, ledger = _RecordingExec(), _RecordingLedger()
    # scan 1: a fresh beat ⇒ QUIET (within threshold); records the baseline token "1"
    emit_heartbeat("op", "1", ts=950.0, beat_dir=beats)
    _watchdog(tmp_path, now=1000.0, exec_fn=execer, ledger=ledger).scan()
    # scan 2: quiet now far exceeds the threshold, BUT the token advanced 1→2 since the
    # last scan ⇒ ALIVE (progressing), never recovered. (The Gittins move.)
    emit_heartbeat("op", "2", ts=950.0, beat_dir=beats)
    res = _watchdog(tmp_path, now=2000.0, exec_fn=execer, ledger=ledger).scan()
    assert execer.calls == []
    assert res[0].status == ALIVE


def test_scan_quiet_op_within_threshold_not_recovered(tmp_path: Path) -> None:
    reg, beats = tmp_path / "registry", tmp_path / "beats"
    register(LivenessSpec(op_id="op", recovery_cmd=["x"], max_quiet_s=100.0), registry_dir=reg)
    emit_heartbeat("op", "1", ts=950.0, beat_dir=beats)  # quiet only 50s
    execer, ledger = _RecordingExec(), _RecordingLedger()
    res = _watchdog(tmp_path, now=1000.0, exec_fn=execer, ledger=ledger).scan()
    assert execer.calls == []
    assert res[0].status == QUIET


def test_scan_missing_op_not_recovered_by_default(tmp_path: Path) -> None:
    reg = tmp_path / "registry"
    register(LivenessSpec(op_id="op", recovery_cmd=["x"], max_quiet_s=100.0), registry_dir=reg)
    execer, ledger = _RecordingExec(), _RecordingLedger()
    res = _watchdog(tmp_path, now=1000.0, exec_fn=execer, ledger=ledger).scan()
    assert execer.calls == []
    assert res[0].status == MISSING


def test_scan_missing_op_recovered_when_opted_in(tmp_path: Path) -> None:
    reg = tmp_path / "registry"
    register(
        LivenessSpec(op_id="op", recovery_cmd=["x"], max_quiet_s=100.0, recover_when_missing=True),
        registry_dir=reg,
    )
    execer, ledger = _RecordingExec(), _RecordingLedger()
    res = _watchdog(tmp_path, now=1000.0, exec_fn=execer, ledger=ledger).scan()
    assert execer.calls == [["x"]]
    assert res[0].recovered is True


def test_scan_uses_measured_tau_when_no_explicit_threshold(tmp_path: Path) -> None:
    reg, beats = tmp_path / "registry", tmp_path / "beats"
    register(
        LivenessSpec(op_id="reaper:beta", recovery_cmd=["reap"], lineage="beta"), registry_dir=reg
    )
    emit_heartbeat("reaper:beta", "1", ts=0.0, beat_dir=beats)  # silent 1000s
    execer, ledger = _RecordingExec(), _RecordingLedger()
    wd = LivenessWatchdog(
        registry_dir=reg,
        beat_dir=beats,
        scan_state_path=tmp_path / "scan-state.json",
        governor=_governor(tmp_path, now=1000.0),
        now_fn=lambda: 1000.0,
        exec_fn=execer,
        ledger_fn=ledger,
        tau_fn=lambda lineage: 500.0 if lineage == "beta" else 99999.0,
    )
    res = wd.scan()
    assert res[0].status == STALLED  # 1000s quiet > tau 500s
    assert execer.calls == [["reap"]]


def test_scan_respects_governor_backoff(tmp_path: Path) -> None:
    reg, beats = tmp_path / "registry", tmp_path / "beats"
    register(
        LivenessSpec(op_id="op", recovery_cmd=["x"], max_quiet_s=100.0, lineage="op"),
        registry_dir=reg,
    )
    emit_heartbeat("op", "1", ts=0.0, beat_dir=beats)
    gov = _governor(tmp_path, now=1000.0)
    # drive the target into backoff: one failure ⇒ next_eligible in the future
    gov.record_outcome("op", success=False)
    execer, ledger = _RecordingExec(), _RecordingLedger()
    wd = _watchdog(tmp_path, now=1000.0, exec_fn=execer, ledger=ledger, governor=gov)
    res = wd.scan()
    assert execer.calls == []  # governor denied — backoff
    assert res[0].status == STALLED
    assert res[0].recovered is False
    assert "backoff" in res[0].permit_reason


def test_scan_records_failure_outcome_into_governor(tmp_path: Path) -> None:
    reg, beats = tmp_path / "registry", tmp_path / "beats"
    register(
        LivenessSpec(op_id="op", recovery_cmd=["x"], max_quiet_s=100.0, lineage="op"),
        registry_dir=reg,
    )
    emit_heartbeat("op", "1", ts=0.0, beat_dir=beats)
    gov = _governor(tmp_path, now=1000.0)
    execer = _RecordingExec(result=False)  # recovery command fails
    wd = _watchdog(tmp_path, now=1000.0, exec_fn=execer, ledger=_RecordingLedger(), governor=gov)
    wd.scan()
    # a failed recovery must bump the governor's attempt counter (AIMD increase)
    assert gov.backoff_entry("op").attempt == 1


def test_scan_persists_tokens_between_scans(tmp_path: Path) -> None:
    scan_state = tmp_path / "scan-state.json"
    reg, beats = tmp_path / "registry", tmp_path / "beats"
    register(LivenessSpec(op_id="op", recovery_cmd=["x"], max_quiet_s=100.0), registry_dir=reg)
    emit_heartbeat("op", "7", ts=0.0, beat_dir=beats)
    _watchdog(tmp_path, now=1000.0, exec_fn=_RecordingExec(), ledger=_RecordingLedger()).scan()
    saved = json.loads(scan_state.read_text())
    assert saved["op"] == "7"
