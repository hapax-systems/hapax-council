"""tests/hapax_daimonion/test_ir_signals.py"""

import json
import os
import time

from agents.hapax_daimonion.ir_signals import IR_STATE_DIR, read_ir_signal


def test_read_missing_file(tmp_path):
    result = read_ir_signal(tmp_path / "nonexistent.json")
    assert result is None


def test_read_valid_file(tmp_path):
    data = {"pi": "hapax-pi6", "role": "overhead", "motion_delta": 0.5}
    f = tmp_path / "overhead.json"
    f.write_text(json.dumps(data))
    result = read_ir_signal(f)
    assert result is not None
    assert result["role"] == "overhead"


def test_read_stale_file(tmp_path):
    data = {"pi": "hapax-pi6", "role": "overhead"}
    f = tmp_path / "overhead.json"
    f.write_text(json.dumps(data))
    old_time = time.time() - 20
    os.utime(f, (old_time, old_time))
    result = read_ir_signal(f, max_age_seconds=10)
    assert result is None


def test_read_corrupt_json(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("{not valid json")
    result = read_ir_signal(f)
    assert result is None


def test_default_state_dir():
    assert "pi-noir" in str(IR_STATE_DIR)


import pytest


@pytest.mark.parametrize(
    "payload,kind",
    [("null", "null"), ('"a string"', "string"), ("[1, 2, 3]", "list"), ("42", "int")],
)
def test_read_non_dict_root_returns_none(tmp_path, payload, kind):
    """Pin read_ir_signal against non-dict JSON roots. The ir_presence
    backend at line 233 calls report.get('cadence_interval_s')
    immediately on the returned value — a non-dict root previously
    raised AttributeError and crashed the IR fleet poll. Same shape
    as the other recent SHM-read fixes."""
    f = tmp_path / "report.json"
    f.write_text(payload)
    assert read_ir_signal(f, max_age_seconds=10) is None, f"non-dict root={kind} must yield None"
