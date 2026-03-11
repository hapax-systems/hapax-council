"""Tests for shared.threshold_tuner."""
import json

from shared.threshold_tuner import (
    ThresholdOverride,
    load_thresholds,
    save_thresholds,
    get_threshold,
    is_suppressed,
)


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "thresholds.json"
    overrides = {
        "latency.litellm": ThresholdOverride(
            check_name="latency.litellm",
            threshold_value=300.0,
            reason="Network is slow",
        ),
    }
    save_thresholds(overrides, path=path)
    loaded = load_thresholds(path=path)
    assert "latency.litellm" in loaded
    assert loaded["latency.litellm"].threshold_value == 300.0


def test_get_threshold_with_override(tmp_path):
    path = tmp_path / "thresholds.json"
    overrides = {
        "latency.litellm": ThresholdOverride(
            check_name="latency.litellm",
            threshold_value=500.0,
        ),
    }
    save_thresholds(overrides, path=path)
    assert get_threshold("latency.litellm", 200.0, path=path) == 500.0
    assert get_threshold("latency.qdrant", 100.0, path=path) == 100.0  # no override


def test_is_suppressed(tmp_path):
    path = tmp_path / "thresholds.json"
    overrides = {
        "connectivity.tailscale": ThresholdOverride(
            check_name="connectivity.tailscale",
            suppress=True,
            reason="Not using tailscale currently",
        ),
    }
    save_thresholds(overrides, path=path)
    assert is_suppressed("connectivity.tailscale", path=path) is True
    assert is_suppressed("docker.qdrant", path=path) is False
