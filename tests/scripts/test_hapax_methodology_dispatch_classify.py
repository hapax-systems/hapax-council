"""Launcher-wiring tests for the worker-path classify+witness integration in
hapax-methodology-dispatch (cc-task capability-adapter-worker-path-classify-failure).

Covers the wrapper (classify_and_witness_launch — success no-op / failure-triggers-classify /
fail-open), the terminal-failure wiring (_classify_and_witness_terminal_failure — the
rc==QUOTA_WALL_EXIT_CODE override, adapter classification, UNKNOWN default, no-adapter fallback),
and the lane-output reader (_read_worker_failure_text)."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest import mock

from shared.failure_classification import FailureCode

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


# --- classify_and_witness_launch: the fail-open wrapper -----------------------------------------


def test_launch_success_skips_classification() -> None:
    with mock.patch.object(_MOD, "_classify_and_witness_terminal_failure") as cw:
        rc = _MOD.classify_and_witness_launch(lambda: 0, **_CTX)
    assert rc == 0
    cw.assert_not_called()


def test_launch_failure_triggers_classification_and_returns_rc_verbatim() -> None:
    with mock.patch.object(_MOD, "_classify_and_witness_terminal_failure") as cw:
        rc = _MOD.classify_and_witness_launch(lambda: 75, **_CTX)
    assert rc == 75
    cw.assert_called_once()
    assert cw.call_args.args[0] == 75  # rc passed positionally to the classifier


def test_launch_is_fail_open_when_classification_raises() -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("classify exploded")

    with mock.patch.object(_MOD, "_classify_and_witness_terminal_failure", side_effect=boom):
        rc = _MOD.classify_and_witness_launch(lambda: 70, **{**_CTX, "platform": "codex"})
    assert rc == 70  # a classification failure NEVER changes the dispatch outcome


# --- _classify_and_witness_terminal_failure: the wiring -----------------------------------------


def test_quota_wall_exit_code_overrides_to_quota_exhaustion() -> None:
    # rc==QUOTA_WALL_EXIT_CODE forces QUOTA_EXHAUSTION even when the output tail is empty (UNKNOWN).
    with (
        mock.patch.object(_MOD, "_read_worker_failure_text", return_value=""),
        mock.patch.object(_MOD, "append_failure_receipt_record") as rec,
        mock.patch.object(_MOD, "update_worker_family_availability") as wit,
    ):
        _MOD._classify_and_witness_terminal_failure(_MOD.QUOTA_WALL_EXIT_CODE, **_CTX)
    assert rec.call_args.kwargs["receipt"].code is FailureCode.QUOTA_EXHAUSTION
    assert wit.call_args.kwargs["code"] is FailureCode.QUOTA_EXHAUSTION
    assert wit.call_args.kwargs["family"] == "claude"


def test_quota_text_classifies_to_quota_via_adapter() -> None:
    with (
        mock.patch.object(
            _MOD, "_read_worker_failure_text", return_value="You've hit your usage limit"
        ),
        mock.patch.object(_MOD, "append_failure_receipt_record") as rec,
        mock.patch.object(_MOD, "update_worker_family_availability") as wit,
    ):
        _MOD._classify_and_witness_terminal_failure(1, **_CTX)
    assert rec.call_args.kwargs["receipt"].code is FailureCode.QUOTA_EXHAUSTION
    assert wit.call_args.kwargs["code"] is FailureCode.QUOTA_EXHAUSTION


def test_unknown_text_stays_unknown() -> None:
    with (
        mock.patch.object(
            _MOD, "_read_worker_failure_text", return_value="ordinary failure, nothing notable"
        ),
        mock.patch.object(_MOD, "append_failure_receipt_record") as rec,
        mock.patch.object(_MOD, "update_worker_family_availability") as wit,
    ):
        _MOD._classify_and_witness_terminal_failure(1, **_CTX)
    assert rec.call_args.kwargs["receipt"].code is FailureCode.UNKNOWN
    # witness is still CALLED with UNKNOWN; the guard (no-op on UNKNOWN) lives in the witness module
    assert wit.call_args.kwargs["code"] is FailureCode.UNKNOWN


def test_platform_without_adapter_emits_unknown_receipt() -> None:
    with (
        mock.patch.object(_MOD, "_read_worker_failure_text", return_value=""),
        mock.patch.object(_MOD, "append_failure_receipt_record") as rec,
        mock.patch.object(_MOD, "update_worker_family_availability"),
    ):
        _MOD._classify_and_witness_terminal_failure(
            1, task_id="t", lane="vbe-1", platform="vibe", mode="headless", profile="worker"
        )
    assert rec.call_args.kwargs["receipt"].code is FailureCode.UNKNOWN
    assert rec.call_args.kwargs["receipt"].platform == "vibe"


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
