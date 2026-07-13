"""Gate-0A conformance for support-only liveness observation."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from shared.execution_admission import PROTECTED_ACTION_HOLD_SCHEMA
from shared.liveness import (
    ALIVE,
    EFFECT_HOLD_REASON,
    HELD_NOT_ADMITTED,
    INDETERMINATE,
    MISSING,
    QUIET,
    STALLED,
    SUPPORT_ONLY,
    EffectAdapterDescriptor,
    Heartbeat,
    LivenessSpec,
    LivenessWatchdog,
    classify,
    emit_heartbeat,
    load_registry,
    read_heartbeat,
    register,
)


def _adapter(target: str = "op") -> EffectAdapterDescriptor:
    return EffectAdapterDescriptor(
        adapter_id="hapax.test.recover.v1",
        action_kind="test.recover",
        target_id=target,
    )


def _spec(**changes: object) -> LivenessSpec:
    values: dict[str, object] = {
        "op_id": "op",
        "adapter": _adapter(),
        "max_quiet_s": 100.0,
    }
    values.update(changes)
    return LivenessSpec(**values)


def test_emit_and_read_heartbeat_round_trip(tmp_path: Path) -> None:
    emit_heartbeat("lane:epsilon:progress", 42, ts=1000.0, meta={"lines": 42}, beat_dir=tmp_path)
    assert read_heartbeat("lane:epsilon:progress", beat_dir=tmp_path) == Heartbeat(
        op_id="lane:epsilon:progress",
        ts=1000.0,
        token="42",
        meta={"lines": 42},
    )


def test_heartbeat_rejects_nonfinite_timestamp(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        emit_heartbeat("op", "t", ts=float("nan"), beat_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_read_heartbeat_rejects_identity_substitution(tmp_path: Path) -> None:
    (tmp_path / "op.beat").write_text(
        json.dumps({"meta": {}, "op_id": "other", "token": "x", "ts": 1.0}),
        encoding="utf-8",
    )
    assert read_heartbeat("op", beat_dir=tmp_path) is None


def test_read_heartbeat_rejects_extra_fields_and_nan(tmp_path: Path) -> None:
    (tmp_path / "op.beat").write_text(
        '{"meta":{},"op_id":"op","token":"x","ts":NaN,"authority":true}',
        encoding="utf-8",
    )
    assert read_heartbeat("op", beat_dir=tmp_path) is None


def test_adapter_descriptor_is_frozen_and_symbolic() -> None:
    adapter = _adapter()
    assert dataclasses.is_dataclass(adapter)
    with pytest.raises(dataclasses.FrozenInstanceError):
        adapter.action_kind = "test.escape"  # type: ignore[misc]
    assert not hasattr(adapter, "argv")
    assert not hasattr(adapter, "command")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("adapter_id", "touch /tmp/pwned"),
        ("action_kind", "recover"),
        ("target_id", ""),
        ("version", 2),
    ],
)
def test_adapter_descriptor_rejects_noncanonical_values(field: str, value: object) -> None:
    values: dict[str, object] = {
        "adapter_id": "hapax.test.recover.v1",
        "action_kind": "test.recover",
        "target_id": "op",
        "version": 1,
    }
    values[field] = value
    with pytest.raises((TypeError, ValueError)):
        EffectAdapterDescriptor(**values)


def test_register_and_load_round_trip_without_executable_material(tmp_path: Path) -> None:
    register(_spec(lineage="test", description="support only"), registry_dir=tmp_path)
    loaded = load_registry(registry_dir=tmp_path)
    assert loaded == [_spec(lineage="test", description="support only")]
    wire = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert "recovery_cmd" not in wire
    assert wire["adapter"]["adapter_id"] == "hapax.test.recover.v1"


def test_registry_rejects_legacy_arbitrary_argv(tmp_path: Path) -> None:
    sentinel = tmp_path / "must-not-exist"
    (tmp_path / "hostile.json").write_text(
        json.dumps(
            {
                "op_id": "hostile",
                "recovery_cmd": ["touch", str(sentinel)],
                "max_quiet_s": 0,
            }
        ),
        encoding="utf-8",
    )
    assert load_registry(registry_dir=tmp_path) == []
    assert LivenessWatchdog(registry_dir=tmp_path, beat_dir=tmp_path).scan() == []
    assert not sentinel.exists()


def test_registry_skips_corrupt_and_unknown_entries(tmp_path: Path) -> None:
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "unknown.json").write_text(
        json.dumps({"op_id": "x", "authority": "operator"}),
        encoding="utf-8",
    )
    assert load_registry(registry_dir=tmp_path) == []


def test_classify_missing_is_support_verdict() -> None:
    verdict = classify(_spec(), None, prev_token=None, now=1000.0, threshold_s=100.0)
    assert verdict.status == MISSING
    assert verdict.reason == "heartbeat_missing"


def test_classify_progressing_token_is_alive_even_when_old() -> None:
    verdict = classify(
        _spec(),
        Heartbeat("op", ts=0.0, token="2"),
        prev_token="1",
        now=1000.0,
        threshold_s=100.0,
    )
    assert verdict.status == ALIVE


def test_classify_quiet_and_stalled() -> None:
    quiet = classify(
        _spec(),
        Heartbeat("op", ts=950.0, token="1"),
        prev_token="1",
        now=1000.0,
        threshold_s=100.0,
    )
    stalled = classify(
        _spec(),
        Heartbeat("op", ts=800.0, token="1"),
        prev_token="1",
        now=1000.0,
        threshold_s=100.0,
    )
    assert quiet.status == QUIET
    assert stalled.status == STALLED


def test_classify_future_observation_is_indeterminate() -> None:
    verdict = classify(
        _spec(),
        Heartbeat("op", ts=1001.0, token="1"),
        prev_token=None,
        now=1000.0,
        threshold_s=100.0,
    )
    assert verdict.status == INDETERMINATE
    assert verdict.reason == "heartbeat_from_future"
    assert verdict.quiet_s == 0.0


def test_stalled_candidate_returns_generic_protected_action_hold(tmp_path: Path) -> None:
    registry, beats = tmp_path / "registry", tmp_path / "beats"
    register(_spec(), registry_dir=registry)
    emit_heartbeat("op", "1", ts=0.0, beat_dir=beats)
    result = LivenessWatchdog(
        registry_dir=registry,
        beat_dir=beats,
        now_fn=lambda: 1000.0,
    ).scan()[0]
    assert result.status == STALLED
    assert result.recovered is False
    assert result.effect_state == HELD_NOT_ADMITTED
    assert result.permit_reason == EFFECT_HOLD_REASON
    assert result.hold is not None
    assert result.hold.schema_id == PROTECTED_ACTION_HOLD_SCHEMA
    assert result.hold.operation == "test.recover"
    assert result.hold.may_authorize is False
    assert result.hold.authorizes_direct_fallthrough is False
    assert result.hold.reason_codes == (
        "execution_admission_absent",
        "execution_authority_absent",
        "execution_lease_absent",
    )


def test_missing_candidate_holds_only_when_declared(tmp_path: Path) -> None:
    registry = tmp_path / "registry"
    register(_spec(recover_when_missing=False), registry_dir=registry)
    ordinary = LivenessWatchdog(
        registry_dir=registry,
        beat_dir=tmp_path / "beats",
        now_fn=lambda: 1000.0,
    ).scan()[0]
    assert ordinary.status == MISSING
    assert ordinary.effect_state == SUPPORT_ONLY
    assert ordinary.hold is None

    register(_spec(recover_when_missing=True), registry_dir=registry)
    opted_in = LivenessWatchdog(
        registry_dir=registry,
        beat_dir=tmp_path / "beats",
        now_fn=lambda: 1000.0,
    ).scan()[0]
    assert opted_in.effect_state == HELD_NOT_ADMITTED
    assert opted_in.hold is not None


def test_future_observation_holds_without_effect(tmp_path: Path) -> None:
    registry, beats = tmp_path / "registry", tmp_path / "beats"
    register(_spec(), registry_dir=registry)
    emit_heartbeat("op", "future", ts=2000.0, beat_dir=beats)
    result = LivenessWatchdog(
        registry_dir=registry,
        beat_dir=beats,
        now_fn=lambda: 1000.0,
    ).scan()[0]
    assert result.status == INDETERMINATE
    assert result.recovered is False
    assert result.hold is not None
    assert "heartbeat_from_future" in result.hold.reason_codes


def test_invalid_measured_tau_holds_without_effect(tmp_path: Path) -> None:
    registry, beats = tmp_path / "registry", tmp_path / "beats"
    register(_spec(max_quiet_s=None), registry_dir=registry)
    emit_heartbeat("op", "1", ts=0.0, beat_dir=beats)
    result = LivenessWatchdog(
        registry_dir=registry,
        beat_dir=beats,
        now_fn=lambda: 1000.0,
        tau_fn=lambda _lineage: float("nan"),
    ).scan()[0]
    assert result.status == INDETERMINATE
    assert result.hold is not None
    assert "liveness_threshold_invalid" in result.hold.reason_codes


def test_scan_is_read_only_and_accepts_no_effect_collaborators(tmp_path: Path) -> None:
    registry, beats = tmp_path / "registry", tmp_path / "beats"
    register(_spec(), registry_dir=registry)
    emit_heartbeat("op", "1", ts=0.0, beat_dir=beats)
    before = {
        path: (path.stat().st_mtime_ns, path.read_bytes())
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    LivenessWatchdog(
        registry_dir=registry,
        beat_dir=beats,
        now_fn=lambda: 1000.0,
    ).scan(previous_tokens={"op": "1"})
    after = {
        path: (path.stat().st_mtime_ns, path.read_bytes())
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before
    with pytest.raises(TypeError):
        LivenessWatchdog(governor=object())  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        LivenessWatchdog(exec_fn=lambda _argv: True)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        LivenessWatchdog(
            registry_dir=registry,
            beat_dir=beats,
            now_fn=lambda: 1000.0,
        ).scan(previous_tokens=object())  # type: ignore[arg-type]


def test_observation_only_spec_never_builds_effect_candidate(tmp_path: Path) -> None:
    registry, beats = tmp_path / "registry", tmp_path / "beats"
    register(_spec(adapter=None), registry_dir=registry)
    emit_heartbeat("op", "1", ts=0.0, beat_dir=beats)
    result = LivenessWatchdog(
        registry_dir=registry,
        beat_dir=beats,
        now_fn=lambda: 1000.0,
    ).scan()[0]
    assert result.status == STALLED
    assert result.effect_state == SUPPORT_ONLY
    assert result.hold is None


def test_module_has_no_process_or_governor_execution_path() -> None:
    source = Path(__file__).resolve().parents[2] / "shared" / "liveness.py"
    text = source.read_text(encoding="utf-8")
    assert "import subprocess" not in text
    assert "RecoveryGovernor" not in text
    assert "recovery_cmd" not in text
    assert "exec_fn" not in text
    assert "ledger_fn" not in text
    assert "record_outcome" not in text
