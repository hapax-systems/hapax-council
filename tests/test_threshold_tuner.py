"""Tests for shared.threshold_tuner."""

from shared.threshold_tuner import (
    ThresholdOverride,
    get_threshold,
    is_suppressed,
    load_thresholds,
    save_thresholds,
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


import pytest


@pytest.mark.parametrize(
    "payload,kind",
    [("null", "null"), ('"a"', "string"), ("[1,2]", "list"), ("42", "int")],
)
def test_load_thresholds_non_dict_root_returns_empty(tmp_path, payload, kind):
    """Pin load_thresholds against non-dict JSON. data.items() raises
    AttributeError on non-dict — the (json.JSONDecodeError, OSError)
    catch missed it. Same shape as the other recent SHM-read fixes."""
    path = tmp_path / "thresholds.json"
    path.write_text(payload)
    assert load_thresholds(path) == {}, f"non-dict root={kind} must yield empty"


def test_load_thresholds_non_dict_entry_skipped(tmp_path):
    """If root is dict but an entry is non-dict, Pydantic ValidationError
    must be caught per-entry so one bad entry doesn't kill the load."""
    path = tmp_path / "thresholds.json"
    import json as _json

    path.write_text(
        _json.dumps(
            {
                "good": {"check_name": "good", "suppress": True, "reason": "test"},
                "bad": "not-a-dict",
            }
        )
    )
    result = load_thresholds(path)
    assert "good" in result
    assert "bad" not in result
