"""Tests for shared.recovery_counter_textfile (H3 helper)."""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.recovery_counter_textfile import (
    increment_counter,
    write_gauge,
)

# ── Counter ─────────────────────────────────────────────────────────


class TestIncrementCounter:
    def test_first_write_creates_file_with_help_type_value(self, tmp_path: Path) -> None:
        v = increment_counter(
            metric_name="hapax_xhci_recovery_total",
            labels={"controller": "0000:71:00.0"},
            help_text="xHCI recovery events by controller.",
            collector_dir=tmp_path,
        )
        assert v == 1.0
        text = (tmp_path / "hapax_xhci_recovery_total.prom").read_text()
        assert "# HELP hapax_xhci_recovery_total xHCI recovery events by controller." in text
        assert "# TYPE hapax_xhci_recovery_total counter" in text
        assert 'hapax_xhci_recovery_total{controller="0000:71:00.0"} 1' in text

    def test_repeated_increments_accumulate(self, tmp_path: Path) -> None:
        for _ in range(3):
            increment_counter(
                metric_name="hapax_xhci_recovery_total",
                labels={"controller": "0000:71:00.0"},
                help_text="x",
                collector_dir=tmp_path,
            )
        text = (tmp_path / "hapax_xhci_recovery_total.prom").read_text()
        assert 'hapax_xhci_recovery_total{controller="0000:71:00.0"} 3' in text

    def test_distinct_labels_track_independently(self, tmp_path: Path) -> None:
        increment_counter(
            metric_name="hapax_xhci_recovery_total",
            labels={"controller": "0000:71:00.0"},
            help_text="x",
            collector_dir=tmp_path,
        )
        increment_counter(
            metric_name="hapax_xhci_recovery_total",
            labels={"controller": "0000:00:14.0"},
            help_text="x",
            collector_dir=tmp_path,
        )
        increment_counter(
            metric_name="hapax_xhci_recovery_total",
            labels={"controller": "0000:71:00.0"},
            help_text="x",
            collector_dir=tmp_path,
        )
        text = (tmp_path / "hapax_xhci_recovery_total.prom").read_text()
        assert 'hapax_xhci_recovery_total{controller="0000:71:00.0"} 2' in text
        assert 'hapax_xhci_recovery_total{controller="0000:00:14.0"} 1' in text

    def test_empty_labels_render_unlabelled(self, tmp_path: Path) -> None:
        v = increment_counter(
            metric_name="hapax_bt_firmware_reload_total",
            labels={},
            help_text="BT firmware reload events.",
            collector_dir=tmp_path,
        )
        assert v == 1.0
        text = (tmp_path / "hapax_bt_firmware_reload_total.prom").read_text()
        # No braces when labels are empty.
        assert "hapax_bt_firmware_reload_total 1" in text

    def test_negative_delta_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="counter delta must be >= 0"):
            increment_counter(
                metric_name="x",
                labels={},
                help_text="x",
                delta=-1,
                collector_dir=tmp_path,
            )

    def test_custom_basename_carries_multiple_metrics(self, tmp_path: Path) -> None:
        """One file can hold counter + gauge for the H3 trio without
        clobbering each other."""
        increment_counter(
            metric_name="hapax_xhci_recovery_total",
            labels={"controller": "X"},
            help_text="x",
            collector_dir=tmp_path,
            file_basename="hapax_audio_recovery.prom",
        )
        increment_counter(
            metric_name="hapax_bt_firmware_reload_total",
            labels={},
            help_text="b",
            collector_dir=tmp_path,
            file_basename="hapax_audio_recovery.prom",
        )
        text = (tmp_path / "hapax_audio_recovery.prom").read_text()
        assert "hapax_xhci_recovery_total" in text
        assert "hapax_bt_firmware_reload_total" in text

    def test_corrupt_value_resets_to_delta_not_crash(self, tmp_path: Path) -> None:
        """A non-numeric value already on disk should not crash the
        watchdog — log + reset to delta."""
        path = tmp_path / "hapax_x.prom"
        path.write_text(
            "# HELP hapax_x x\n# TYPE hapax_x counter\nhapax_x not_a_number\n",
            encoding="utf-8",
        )
        v = increment_counter(
            metric_name="hapax_x",
            labels={},
            help_text="x",
            collector_dir=tmp_path,
            file_basename="hapax_x.prom",
        )
        assert v == 1.0


# ── Gauge ───────────────────────────────────────────────────────────


class TestWriteGauge:
    def test_first_write_creates_gauge(self, tmp_path: Path) -> None:
        write_gauge(
            metric_name="hapax_audio_egress_lufs_dbfs",
            labels={"stage": "broadcast-master"},
            help_text="Audio egress LUFS by stage.",
            value=-14.2,
            collector_dir=tmp_path,
        )
        text = (tmp_path / "hapax_audio_egress_lufs_dbfs.prom").read_text()
        assert "# TYPE hapax_audio_egress_lufs_dbfs gauge" in text
        assert 'hapax_audio_egress_lufs_dbfs{stage="broadcast-master"} -14.2' in text

    def test_repeated_writes_replace_value(self, tmp_path: Path) -> None:
        for v in [-13.0, -14.5, -15.1]:
            write_gauge(
                metric_name="hapax_audio_egress_lufs_dbfs",
                labels={"stage": "broadcast-master"},
                help_text="x",
                value=v,
                collector_dir=tmp_path,
            )
        text = (tmp_path / "hapax_audio_egress_lufs_dbfs.prom").read_text()
        # Only the last value remains.
        assert "-15.1" in text
        assert "-13.0" not in text
        assert "-14.5" not in text

    def test_distinct_label_stages_coexist(self, tmp_path: Path) -> None:
        write_gauge(
            metric_name="hapax_audio_egress_lufs_dbfs",
            labels={"stage": "broadcast-master"},
            help_text="x",
            value=-14.0,
            collector_dir=tmp_path,
        )
        write_gauge(
            metric_name="hapax_audio_egress_lufs_dbfs",
            labels={"stage": "private-monitor"},
            help_text="x",
            value=-23.0,
            collector_dir=tmp_path,
        )
        text = (tmp_path / "hapax_audio_egress_lufs_dbfs.prom").read_text()
        assert 'hapax_audio_egress_lufs_dbfs{stage="broadcast-master"} -14' in text
        assert 'hapax_audio_egress_lufs_dbfs{stage="private-monitor"} -23' in text


# ── Atomicity / parent dir creation ─────────────────────────────────


class TestAtomicWrite:
    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "deeply" / "nested" / "collector"
        v = increment_counter(
            metric_name="hapax_x",
            labels={},
            help_text="x",
            collector_dir=target,
        )
        assert v == 1.0
        assert (target / "hapax_x.prom").exists()
