"""Unit tests for M8ButtonsBackend perception backend.

Verifies SHM sidecar ingest, debounced press counting, and
m8_button_engaged threshold behavior. Tolerates SHM file absence
(M8 unplugged) without crashing.

cc-task: m8-button-activity-perception-signal
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from agents.hapax_daimonion.backends.m8_buttons import M8ButtonsBackend
from agents.hapax_daimonion.primitives import Behavior


@pytest.fixture
def shm_path(tmp_path: Path) -> Path:
    return tmp_path / "m8-buttons.json"


def _write_packet(
    path: Path, mask: int, indicator: int = 0, ts: str = "2026-05-02T03:00:00Z"
) -> None:
    path.write_text(json.dumps({"mask": mask, "indicator": indicator, "ts": ts}))


def test_provides_two_behaviors():
    backend = M8ButtonsBackend()
    assert backend.provides == frozenset({"m8_button_activity_rate", "m8_button_engaged"})


def test_no_sidecar_returns_zero_rate(shm_path: Path):
    """When M8 is unplugged (sidecar absent), rate=0 and engaged=False."""
    backend = M8ButtonsBackend(shm_path=shm_path)
    behaviors: dict[str, Behavior] = {}
    backend.contribute(behaviors)

    assert behaviors["m8_button_activity_rate"].value == 0.0
    assert behaviors["m8_button_engaged"].value is False


def test_single_press_records_one_event(shm_path: Path):
    backend = M8ButtonsBackend(shm_path=shm_path)
    _write_packet(shm_path, mask=0x01, ts="2026-05-02T03:00:00Z")

    behaviors: dict[str, Behavior] = {}
    backend.contribute(behaviors)

    # 1 press in the last 1 second window
    assert behaviors["m8_button_activity_rate"].value == 1.0


def test_repeated_same_packet_not_double_counted(shm_path: Path):
    """Polling the same SHM payload twice must not record two press events."""
    backend = M8ButtonsBackend(shm_path=shm_path)
    _write_packet(shm_path, mask=0x01, ts="2026-05-02T03:00:00Z")

    behaviors: dict[str, Behavior] = {}
    backend.contribute(behaviors)
    backend.contribute(behaviors)

    # Still 1 press recorded (debounced by ts comparison)
    assert behaviors["m8_button_activity_rate"].value == 1.0


def test_mask_zero_then_nonzero_counts_as_press(shm_path: Path):
    """Key-up (mask=0) followed by key-down (mask!=0) registers one press."""
    backend = M8ButtonsBackend(shm_path=shm_path)

    _write_packet(shm_path, mask=0x00, ts="2026-05-02T03:00:00Z")
    behaviors: dict[str, Behavior] = {}
    backend.contribute(behaviors)
    assert behaviors["m8_button_activity_rate"].value == 0.0

    _write_packet(shm_path, mask=0x04, ts="2026-05-02T03:00:00.100Z")
    backend.contribute(behaviors)
    assert behaviors["m8_button_activity_rate"].value == 1.0


def test_engaged_threshold_requires_sustained_activity(shm_path: Path):
    """m8_button_engaged is True only when 5s sustained rate > 0.5."""
    backend = M8ButtonsBackend(shm_path=shm_path)

    # Inject 4 distinct press events into history within 5s window
    backend._press_history.append((time.monotonic() - 4.0, 0x01))
    backend._press_history.append((time.monotonic() - 3.0, 0x02))
    backend._press_history.append((time.monotonic() - 2.0, 0x04))
    backend._press_history.append((time.monotonic() - 1.0, 0x08))

    behaviors: dict[str, Behavior] = {}
    backend.contribute(behaviors)

    # 4 presses / 5s = 0.8 > 0.5 threshold
    assert behaviors["m8_button_engaged"].value is True


def test_engaged_decays_after_quiet_window(shm_path: Path):
    """After 5s of silence, m8_button_engaged returns to False."""
    backend = M8ButtonsBackend(shm_path=shm_path)

    # Old presses outside the 5s window
    backend._press_history.append((time.monotonic() - 10.0, 0x01))
    backend._press_history.append((time.monotonic() - 9.0, 0x02))

    behaviors: dict[str, Behavior] = {}
    backend.contribute(behaviors)

    assert behaviors["m8_button_engaged"].value is False


def test_malformed_sidecar_does_not_crash(shm_path: Path):
    """Backend tolerates a corrupt JSON file without raising."""
    backend = M8ButtonsBackend(shm_path=shm_path)
    shm_path.write_text("{ this is not valid json")

    behaviors: dict[str, Behavior] = {}
    backend.contribute(behaviors)

    assert behaviors["m8_button_activity_rate"].value == 0.0
    assert behaviors["m8_button_engaged"].value is False


def test_available_returns_true_even_without_sidecar(shm_path: Path):
    """available() does not require M8 to be plugged in."""
    backend = M8ButtonsBackend(shm_path=shm_path)
    assert backend.available() is True
