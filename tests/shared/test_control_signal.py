"""Tests for shared.control_signal.

48-LOC perceptual control-error measurement + atomic /dev/shm
publication. Untested before this commit.
"""

from __future__ import annotations

import json
from pathlib import Path

from shared.control_signal import ControlSignal, publish_health

# ── ControlSignal.error ────────────────────────────────────────────


class TestControlSignalError:
    def test_error_is_abs_diff(self) -> None:
        s = ControlSignal(component="ir", reference=0.8, perception=0.6)
        assert s.error == 0.2 or abs(s.error - 0.2) < 1e-9

    def test_error_is_positive_when_perception_above_reference(self) -> None:
        s = ControlSignal(component="ir", reference=0.5, perception=0.9)
        assert abs(s.error - 0.4) < 1e-9

    def test_error_zero_when_aligned(self) -> None:
        s = ControlSignal(component="x", reference=0.7, perception=0.7)
        assert s.error == 0.0


# ── ControlSignal.to_dict ──────────────────────────────────────────


class TestToDict:
    def test_dict_includes_all_fields(self) -> None:
        s = ControlSignal(component="ir-presence", reference=0.8, perception=0.6)
        d = s.to_dict()
        assert d["component"] == "ir-presence"
        assert d["reference"] == 0.8
        assert d["perception"] == 0.6
        assert abs(d["error"] - 0.2) < 1e-9
        assert "timestamp" in d
        assert isinstance(d["timestamp"], float)


# ── publish_health ─────────────────────────────────────────────────


class TestPublishHealth:
    def test_writes_atomically_to_explicit_path(self, tmp_path: Path) -> None:
        target = tmp_path / "subdir" / "health.json"
        signal = ControlSignal(component="x", reference=0.5, perception=0.4)
        publish_health(signal, path=target)
        assert target.exists()
        data = json.loads(target.read_text())
        assert data["component"] == "x"
        assert data["reference"] == 0.5
        assert data["perception"] == 0.4

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        """publish_health mkdir-p's the parent — no caller-side prep
        required."""
        target = tmp_path / "deeply" / "nested" / "path" / "health.json"
        signal = ControlSignal(component="x", reference=0.0, perception=0.0)
        publish_health(signal, path=target)
        assert target.exists()
        assert target.parent.is_dir()

    def test_atomic_write_no_partial_visible(self, tmp_path: Path) -> None:
        """The .tmp + rename pattern means a reader never sees a
        partially-written file. Verify the target file is non-empty +
        well-formed JSON after publish completes."""
        target = tmp_path / "health.json"
        signal = ControlSignal(component="x", reference=1.0, perception=0.0)
        publish_health(signal, path=target)
        # The temp file should have been renamed away.
        assert not target.with_suffix(".tmp").exists()
        # And the target should be valid JSON top-to-bottom.
        data = json.loads(target.read_text())
        assert abs(data["error"] - 1.0) < 1e-9

    def test_publish_does_not_use_shared_temp_path(self, tmp_path: Path) -> None:
        """Parallel workers must not collide on a fixed health.tmp path."""
        target = tmp_path / "health.json"
        fixed_tmp = target.with_suffix(".tmp")
        fixed_tmp.write_text("occupied", encoding="utf-8")

        signal = ControlSignal(component="x", reference=0.5, perception=0.25)
        publish_health(signal, path=target)

        assert fixed_tmp.read_text(encoding="utf-8") == "occupied"
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["component"] == "x"
        assert data["perception"] == 0.25

    def test_overwrites_existing_target(self, tmp_path: Path) -> None:
        target = tmp_path / "health.json"
        target.write_text("{}")
        signal = ControlSignal(component="x", reference=0.5, perception=0.5)
        publish_health(signal, path=target)
        data = json.loads(target.read_text())
        assert data["component"] == "x"


# ── Frozen dataclass guarantee ─────────────────────────────────────


class TestFrozen:
    def test_signal_is_frozen(self) -> None:
        s = ControlSignal(component="x", reference=0.5, perception=0.5)
        try:
            s.component = "y"  # type: ignore[misc]
        except Exception as exc:
            assert "frozen" in str(exc).lower() or "FrozenInstance" in type(exc).__name__
            return
        raise AssertionError("Expected FrozenInstanceError when mutating frozen dataclass")
