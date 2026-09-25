"""Live recording consent fails closed on the compositor's perception record.

The recording and HLS valves open only on a fresh perception record whose
``persistence_allowed`` is exactly ``true``. A missing, stale, future-dated,
unreadable or malformed record, a missing key, or a non-boolean answer holds
them closed. Absence is never permission (``interpersonal_transparency``,
it-consent-001 / it-backend-001; face privacy fails closed).

Positive controls: a fresh operator-only ``no_guest`` record and a fresh
``consent_granted`` record both still open recording, and a blocked
compositor reopens when a fresh affirmative record returns.
"""

from __future__ import annotations

import inspect
import json
import logging
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agents.studio_compositor import consent, lifecycle, state
from agents.studio_compositor.models import OverlayData, OverlayState

NOW = 1_800_000_000.0
# A raw value that must never reach a log line (pydantic errors echo inputs).
_SENTINEL = "guest-alice-sentinel"


class _Valve:
    def __init__(self) -> None:
        self.drop = False  # built open, as the live constructor does

    def set_property(self, name: str, value: object) -> None:
        assert name == "drop"
        self.drop = value


class _ImmediateGLib:
    """Runs idle callbacks at once so the valve effect is observable."""

    @staticmethod
    def idle_add(fn: Any) -> None:
        fn()


def _compositor() -> SimpleNamespace:
    # Mirrors compositor.py: the flag starts True and the valves are built open.
    return SimpleNamespace(
        _overlay_state=OverlayState(),
        _recording_valves={"brio-operator": _Valve(), "c920-desk": _Valve()},
        _recording_muxes={},
        _recording_status={"brio-operator": "active", "c920-desk": "active"},
        _recording_status_lock=threading.Lock(),
        _hls_valve=_Valve(),
        _consent_recording_allowed=True,
        _GLib=_ImmediateGLib,
        _Gst=None,
    )


def _valves(compositor: SimpleNamespace) -> list[_Valve]:
    return [*compositor._recording_valves.values(), compositor._hls_valve]


def _record(**overrides: object) -> dict[str, object]:
    rec: dict[str, object] = {
        "timestamp": NOW - 1.0,
        "persistence_allowed": True,
        "guest_present": False,
        "consent_phase": "no_guest",
        "active_contracts": [],
    }
    rec.update(overrides)
    return rec


def _without(key: str) -> dict[str, object]:
    return {k: v for k, v in _record().items() if k != key}


_MISSING = object()
_DIRECTORY = object()

UNSAFE = [
    pytest.param(_MISSING, "record_missing", id="missing"),
    pytest.param(_DIRECTORY, "record_unreadable", id="unreadable"),
    pytest.param(_record(timestamp=NOW - 11.0), "record_stale", id="stale"),
    pytest.param(_without("timestamp"), "record_stale", id="timestamp-absent"),
    pytest.param(_record(timestamp=NOW + 60.0), "record_stale", id="future-dated"),
    pytest.param(
        '{"timestamp": NaN, "persistence_allowed": true}', "record_stale", id="timestamp-nan"
    ),
    pytest.param("{not json", "record_malformed", id="unparseable"),
    pytest.param(b"\xff\xfe\x00garbage", "record_malformed", id="not-utf8"),
    pytest.param("[1, 2]", "record_malformed", id="not-an-object"),
    pytest.param(_record(persistence_allowed="true"), "record_malformed", id="non-bool-string"),
    pytest.param(_record(persistence_allowed=1), "record_malformed", id="non-bool-int"),
    pytest.param(_record(persistence_allowed=None), "record_malformed", id="null"),
    pytest.param(_without("persistence_allowed"), "persistence_not_affirmed", id="key-absent"),
    pytest.param(
        {"timestamp": NOW - 1.0, "error": True, "operator_present": False},
        "persistence_not_affirmed",
        id="writer-error-fallback",
    ),
    pytest.param(
        _record(persistence_allowed=False, guest_present=True, consent_phase="guest_detected"),
        "persistence_not_affirmed",
        id="refused",
    ),
]

SAFE = [
    pytest.param(_record(), id="operator-only-no-guest"),
    pytest.param(
        _record(guest_present=True, consent_phase="consent_granted", active_contracts=["c-1"]),
        id="consent-granted",
    ),
]


def _place(path: Path, payload: object) -> None:
    if payload is _MISSING:
        return
    if payload is _DIRECTORY:
        path.mkdir()
        return
    if isinstance(payload, bytes):
        path.write_bytes(payload)
        return
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload))


@pytest.fixture()
def perception_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "perception-state.json"
    monkeypatch.setattr(lifecycle, "PERCEPTION_STATE_PATH", path)
    monkeypatch.setattr(state, "PERCEPTION_STATE_PATH", path)
    monkeypatch.setattr(consent, "CONSENT_AUDIT_PATH", tmp_path / "consent-audit.jsonl")
    return path


# ── Overlay model: the record's own defaults never grant ────────────────


def test_overlay_default_does_not_grant_persistence() -> None:
    assert OverlayData().persistence_allowed is False


def test_overlay_record_without_the_key_does_not_grant() -> None:
    assert OverlayData(**_without("persistence_allowed")).persistence_allowed is False


@pytest.mark.parametrize("value", ["true", "yes", 1])
def test_overlay_rejects_a_non_bool_answer(value: object) -> None:
    with pytest.raises(ValueError):
        OverlayData(persistence_allowed=value)


def test_fresh_overlay_state_does_not_grant_before_any_record() -> None:
    assert OverlayState().recording_consent() == (False, "record_missing")


def test_stale_overlay_state_withdraws_an_earlier_grant() -> None:
    overlay = OverlayState()
    overlay.update(OverlayData(**_record()))
    assert overlay.recording_consent() == (True, "")

    overlay.mark_stale("record_stale")

    assert overlay.recording_consent() == (False, "record_stale")


# ── Compositor start: the initial valves ─────────────────────────────────


@pytest.mark.parametrize(("payload", "cause"), UNSAFE)
def test_start_holds_valves_closed(perception_path: Path, payload: object, cause: str) -> None:
    _place(perception_path, payload)
    compositor = _compositor()

    allowed = lifecycle.apply_initial_recording_consent(compositor, now=NOW)

    assert allowed is False
    assert compositor._consent_recording_allowed is False
    assert all(valve.drop is True for valve in _valves(compositor))
    assert compositor._overlay_state.recording_consent() == (False, cause)


@pytest.mark.parametrize("payload", SAFE)
def test_start_opens_valves_on_a_fresh_affirmative_record(
    perception_path: Path, payload: dict[str, object]
) -> None:
    _place(perception_path, payload)
    compositor = _compositor()
    for valve in _valves(compositor):
        valve.drop = True

    assert lifecycle.apply_initial_recording_consent(compositor, now=NOW) is True
    assert compositor._consent_recording_allowed is True
    assert all(valve.drop is False for valve in _valves(compositor))


def test_start_applies_consent_before_the_pipeline_plays() -> None:
    source = inspect.getsource(lifecycle.start_compositor)
    applied = source.index("apply_initial_recording_consent(compositor)")
    playing = source.index("compositor.pipeline.set_state(Gst.State.PLAYING)")
    assert applied < playing


# ── Reader loop: the running valves ──────────────────────────────────────


def _tick(compositor: SimpleNamespace, now: float) -> tuple[bool, str]:
    state.refresh_overlay_from_perception_file(
        compositor._overlay_state, state.PERCEPTION_STATE_PATH, now=now
    )
    return state.enforce_recording_consent(compositor)


@pytest.mark.parametrize(("payload", "cause"), UNSAFE)
def test_reader_loop_closes_valves(perception_path: Path, payload: object, cause: str) -> None:
    _place(perception_path, payload)
    compositor = _compositor()

    assert _tick(compositor, NOW) == (False, cause)
    assert compositor._consent_recording_allowed is False
    assert all(valve.drop is True for valve in _valves(compositor))


def test_reader_loop_closes_valves_when_a_granting_record_goes_stale(
    perception_path: Path,
) -> None:
    _place(perception_path, _record())
    compositor = _compositor()
    assert _tick(compositor, NOW) == (True, "")
    assert all(valve.drop is False for valve in _valves(compositor))

    # The writer stops; the same record ages past its freshness bound.
    assert _tick(compositor, NOW + 30.0) == (False, "record_stale")
    assert all(valve.drop is True for valve in _valves(compositor))


def test_reader_loop_closes_valves_when_a_granting_record_disappears(
    perception_path: Path,
) -> None:
    _place(perception_path, _record())
    compositor = _compositor()
    assert _tick(compositor, NOW)[0] is True

    perception_path.unlink()

    assert _tick(compositor, NOW + 1.0) == (False, "record_missing")
    assert all(valve.drop is True for valve in _valves(compositor))


@pytest.mark.parametrize("payload", SAFE)
def test_reader_loop_reopens_on_a_fresh_affirmative_record(
    perception_path: Path, payload: dict[str, object]
) -> None:
    compositor = _compositor()
    assert _tick(compositor, NOW) == (False, "record_missing")

    _place(perception_path, payload)

    assert _tick(compositor, NOW) == (True, "")
    assert compositor._consent_recording_allowed is True
    assert all(valve.drop is False for valve in _valves(compositor))


def test_reader_loop_runs_the_refresh_and_the_enforcement() -> None:
    source = inspect.getsource(state.state_reader_loop)
    refresh = source.index("refresh_overlay_from_perception_file(")
    enforce = source.index("enforce_recording_consent(compositor)")
    assert refresh < enforce


# ── Refusal logs: sanitized cause and remedy, never raw values ───────────


def test_start_refusal_logs_cause_and_remedy_without_raw_values(
    perception_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _place(perception_path, _record(persistence_allowed=_SENTINEL, active_contracts=[_SENTINEL]))
    caplog.set_level(logging.DEBUG)

    lifecycle.apply_initial_recording_consent(_compositor(), now=NOW)

    assert "cause=record_malformed" in caplog.text
    assert "remedy:" in caplog.text
    assert _SENTINEL not in caplog.text


def test_reader_loop_refusal_logs_cause_and_remedy_without_raw_values(
    perception_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _place(perception_path, _record(persistence_allowed=_SENTINEL, active_contracts=[_SENTINEL]))
    caplog.set_level(logging.DEBUG)

    _tick(_compositor(), NOW)

    assert "cause=record_malformed" in caplog.text
    assert "remedy:" in caplog.text
    assert _SENTINEL not in caplog.text
