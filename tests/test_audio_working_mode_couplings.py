"""Tests for shared.audio_working_mode_couplings.

Closes audit finding E#7: working-mode is decoupled from audio routing.
The coupling layer must:

- Return distinct constraint dicts per WorkingMode value.
- Default to the (RND) empty dict on missing/invalid mode files.
- Surface mtime change detection so consumers can react within one tick.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from shared.audio_working_mode_couplings import (
    current_audio_constraints,
    fortress_audio_constraints,
    research_audio_constraints,
    rnd_audio_constraints,
    working_mode_changed_since,
    working_mode_mtime,
)
from shared.working_mode import WorkingMode


def _set_mode(tmp_path: Path, mode: WorkingMode) -> Path:
    mode_file = tmp_path / "working-mode"
    mode_file.write_text(f"{mode.value}\n")
    return mode_file


def test_fortress_constraints_tighten_true_peak():
    constraints = fortress_audio_constraints()
    assert constraints["broadcast_true_peak_dbtp"] == -1.5
    # Tighter than nominal -1.0 dBTP YouTube ceiling.
    assert constraints["broadcast_true_peak_dbtp"] < -1.0


def test_fortress_constraints_freeze_routing_yaml():
    constraints = fortress_audio_constraints()
    assert constraints["audio_routing_policy_yaml_frozen"] is True
    assert constraints["default_sink_change_allowed"] is False


def test_fortress_refuses_role_assistant_into_broadcast():
    constraints = fortress_audio_constraints()
    assert constraints["duck_role_assistant_into_broadcast"] is False


def test_fortress_obs_publish_kill_on_blocking():
    constraints = fortress_audio_constraints()
    assert constraints["obs_publish_kill_on_any_blocking_reason"] is True


def test_research_relaxes_lufs_check():
    constraints = research_audio_constraints()
    assert constraints["lufs_egress_check_skipped"] is True
    assert constraints["conf_hot_swap_window_seconds"] == 60


def test_rnd_is_permissive_default():
    assert rnd_audio_constraints() == {}


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (WorkingMode.FORTRESS, fortress_audio_constraints()),
        (WorkingMode.RESEARCH, research_audio_constraints()),
        (WorkingMode.RND, rnd_audio_constraints()),
    ],
)
def test_current_audio_constraints_matches_mode(
    tmp_path: Path,
    mode: WorkingMode,
    expected: dict[str, object],
):
    mode_file = _set_mode(tmp_path, mode)
    with patch("shared.working_mode.WORKING_MODE_FILE", mode_file):
        assert current_audio_constraints() == expected


def test_current_audio_constraints_defaults_to_rnd_when_file_missing(tmp_path: Path):
    """A missing working-mode file must default to permissive (RND)."""
    missing = tmp_path / "nonexistent"
    with patch("shared.working_mode.WORKING_MODE_FILE", missing):
        assert current_audio_constraints() == {}


def test_current_audio_constraints_defaults_to_rnd_when_file_invalid(tmp_path: Path):
    mode_file = tmp_path / "working-mode"
    mode_file.write_text("turbo\n")
    with patch("shared.working_mode.WORKING_MODE_FILE", mode_file):
        # Invalid mode falls through WorkingMode() ValueError → RND default.
        assert current_audio_constraints() == {}


def test_working_mode_mtime_returns_none_when_missing(tmp_path: Path):
    assert working_mode_mtime(tmp_path / "nonexistent") is None


def test_working_mode_mtime_returns_float_when_present(tmp_path: Path):
    mode_file = _set_mode(tmp_path, WorkingMode.RND)
    mtime = working_mode_mtime(mode_file)
    assert isinstance(mtime, float)
    assert mtime > 0


def test_working_mode_changed_since_first_call_returns_true(tmp_path: Path):
    mode_file = _set_mode(tmp_path, WorkingMode.RND)
    changed, current = working_mode_changed_since(None, path=mode_file)
    assert changed is True
    assert current is not None


def test_working_mode_changed_since_no_change_returns_false(tmp_path: Path):
    mode_file = _set_mode(tmp_path, WorkingMode.RND)
    _, first = working_mode_changed_since(None, path=mode_file)
    changed, second = working_mode_changed_since(first, path=mode_file)
    assert changed is False
    assert second == first


def test_working_mode_changed_since_detects_flip(tmp_path: Path):
    """Rewriting the file with a fresh mtime must trip detection."""
    import os
    import time

    mode_file = _set_mode(tmp_path, WorkingMode.RND)
    _, first = working_mode_changed_since(None, path=mode_file)
    # Force a distinct mtime — st_mtime is fp seconds but resolution
    # varies across filesystems; bump explicitly.
    new_mtime = time.time() + 5.0
    os.utime(mode_file, (new_mtime, new_mtime))
    changed, second = working_mode_changed_since(first, path=mode_file)
    assert changed is True
    assert second != first


def test_working_mode_changed_since_disappearing_file(tmp_path: Path):
    """File deleted after a successful read → changed=True with None mtime."""
    mode_file = _set_mode(tmp_path, WorkingMode.RND)
    _, first = working_mode_changed_since(None, path=mode_file)
    mode_file.unlink()
    changed, second = working_mode_changed_since(first, path=mode_file)
    assert changed is True
    assert second is None
