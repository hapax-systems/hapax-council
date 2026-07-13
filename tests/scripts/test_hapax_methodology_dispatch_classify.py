"""Gate-0A retirement and read-only output-tail tests for failure classification."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest import mock

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-methodology-dispatch"


def _load_module() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader(
        "hapax_methodology_dispatch_under_test", str(SCRIPT)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


_MOD = _load_module()

_CTX = {
    "task_id": "t",
    "lane": "cc-sdlc",
    "platform": "claude",
    "mode": "headless",
    "profile": "opus",
}


# --- retired effectful classification paths -----------------------------------------------------


def test_launch_and_witness_holds_before_callback_or_classifier() -> None:
    callback_called = False

    def callback() -> int:
        nonlocal callback_called
        callback_called = True
        return 0

    with mock.patch.object(_MOD, "_classify_and_witness_terminal_failure") as classifier:
        with pytest.raises(_MOD.Gate0AEffectHold, match="worker.launch-and-witness"):
            _MOD.classify_and_witness_launch(callback, **_CTX)

    assert callback_called is False
    classifier.assert_not_called()


def test_terminal_failure_holds_before_reader_or_removed_writers() -> None:
    with mock.patch.object(_MOD, "_read_worker_failure_text") as reader:
        with pytest.raises(_MOD.Gate0AEffectHold, match="worker-failure.publish"):
            _MOD._classify_and_witness_terminal_failure(1, **_CTX)

    reader.assert_not_called()
    assert not hasattr(_MOD, "append_failure_receipt_record")
    assert not hasattr(_MOD, "update_worker_family_availability")


# --- _read_worker_failure_text ------------------------------------------------------------------


def test_read_text_non_claude_or_non_headless_returns_empty() -> None:
    assert _MOD._read_worker_failure_text("codex", "headless", "cx-amber") == ""
    assert _MOD._read_worker_failure_text("claude", "interactive", "beta") == ""


def test_read_text_claude_headless_missing_file_returns_empty(tmp_path) -> None:
    with mock.patch.object(_MOD.Path, "home", return_value=tmp_path):
        assert _MOD._read_worker_failure_text("claude", "headless", "no-such-lane") == ""


def test_read_text_claude_headless_reads_output_tail(tmp_path) -> None:
    lane = "beta"
    out = tmp_path / ".cache" / "hapax" / "claude-headless" / lane / "output.jsonl"
    out.parent.mkdir(parents=True)
    out.write_text("\n".join(f"line {i}" for i in range(100)), encoding="utf-8")
    with mock.patch.object(_MOD.Path, "home", return_value=tmp_path):
        text = _MOD._read_worker_failure_text("claude", "headless", lane)
    lines = text.split("\n")
    assert "line 99" in text and "line 50" in text  # tail present
    assert "line 0" not in lines  # only the last 50 lines
