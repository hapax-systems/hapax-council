"""Tests for hooks/scripts/sense_reissue_capture.py (gestalt-substrate Move 1).

The hook captures re-issue-shaped operator prompts as durable signal.reissue coord events. These
tests pin: (a) the classifier flags real re-issues and not ordinary task prompts (false positives
would erode the surface's trust); (b) event-id determinism; (c) the sanctioned emit command shape;
(d) honest receipts; (e) fail-open, non-blocking main.
"""

from __future__ import annotations

import importlib.util
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

_REPO = Path(__file__).resolve().parents[2]
_MOD_PATH = _REPO / "hooks" / "scripts" / "sense_reissue_capture.py"
_spec = importlib.util.spec_from_file_location("sense_reissue_capture", _MOD_PATH)
assert _spec is not None and _spec.loader is not None
src = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(src)

_NOW = datetime(2026, 6, 27, 12, 0, 0, tzinfo=UTC)

# The operator's actual re-issues this session — the surface MUST flag every one.
REAL_REISSUES = [
    "make sure you have all directional signals and plans and commitments in view",
    "research your purview",
    "Research your purview as well, make sure you have all directional signals and plans in view",
    "make sure you have everything",
    "Follow all leads, make sure you have everything",
    "I am getting the impression that you are missing a large tranche of planned work",
    "make sure you didn't go lossy after compaction",
]

# Ordinary task prompts — the surface MUST NOT flag any (false positives erode trust).
ORDINARY = [
    "fix the failing test in test_foo.py",
    "research the root cause of the latency bug",
    "implement the feature per the spec",
    "make sure the build passes before pushing",
    "make sure you have the API key set in the env",
    "review the PR comments and address them",
    "",
    "   ",
]


def test_classify_flags_real_reissues() -> None:
    for prompt in REAL_REISSUES:
        is_reissue, trigger = src.classify_reissue(prompt)
        assert is_reissue is True, prompt
        assert trigger, prompt


def test_classify_ignores_ordinary_prompts() -> None:
    for prompt in ORDINARY:
        is_reissue, trigger = src.classify_reissue(prompt)
        assert is_reissue is False, prompt
        assert trigger is None, prompt


def test_event_id_is_deterministic_and_distinguishing() -> None:
    a = src.reissue_event_id("sess-1", "research your purview", now=_NOW)
    again = src.reissue_event_id("sess-1", "research your purview", now=_NOW)
    later_day = src.reissue_event_id(
        "sess-1", "research your purview", now=datetime(2026, 6, 28, 9, 0, tzinfo=UTC)
    )
    other_prompt = src.reissue_event_id("sess-1", "make sure you have everything", now=_NOW)
    assert a == again
    assert a.startswith("sigreissue-")
    assert a != later_day  # genuine later re-issue is a new event
    assert a != other_prompt


def test_build_emit_command_shape() -> None:
    cmd = src.build_emit_command(
        role="dev2",
        session_id="sess-1",
        program="continuity-substrate",
        event_id="sigreissue-abc",
        trigger_class="purview",
        verbatim="research your purview",
        python_exe="python3",
    )
    assert cmd[:4] == ["python3", "-m", "shared.coord_event_log", "append"]
    assert "--fail-open" in cmd
    assert cmd[cmd.index("--event-type") + 1] == "signal.reissue"
    assert cmd[cmd.index("--actor") + 1] == "dev2"
    assert cmd[cmd.index("--subject") + 1] == "sess-1"
    assert cmd[cmd.index("--event-id") + 1] == "sigreissue-abc"
    assert cmd[cmd.index("--parent-spec") + 1] == "continuity-substrate"
    payload = json.loads(cmd[cmd.index("--payload") + 1])
    assert payload["trigger_class"] == "purview"
    assert payload["verbatim"] == "research your purview"


def test_build_emit_command_omits_parent_spec_when_no_program() -> None:
    cmd = src.build_emit_command(
        role="",
        session_id="sess-1",
        program=None,
        event_id="sigreissue-abc",
        trigger_class="coverage",
        verbatim="make sure you have everything",
    )
    assert "--parent-spec" not in cmd
    assert cmd[cmd.index("--actor") + 1] == "roleless"  # empty role -> roleless, still captured


def test_format_receipt_is_honest() -> None:
    committed = src.format_receipt({"appended": True, "spooled": False}, trigger_class="purview")
    queued = src.format_receipt({"appended": False, "spooled": True}, trigger_class="purview")
    nothing = src.format_receipt({}, trigger_class="purview")
    assert "captured" in committed and "queued" not in committed
    assert "queued" in queued
    assert nothing == ""


def test_main_emits_on_reissue_and_prints_receipt(capsys) -> None:
    stdin = io.StringIO(json.dumps({"prompt": "research your purview", "session_id": "sess-1"}))
    with mock.patch.object(src, "run_emit", return_value={"appended": True}) as emit:
        rc = src.main(["dev2"], stdin=stdin, now=_NOW)
    assert rc == 0
    emit.assert_called_once()
    out = capsys.readouterr().out
    assert "signal.reissue" in out and "captured" in out


def test_main_skips_ordinary_prompt(capsys) -> None:
    stdin = io.StringIO(json.dumps({"prompt": "fix the failing test", "session_id": "sess-1"}))
    with mock.patch.object(src, "run_emit") as emit:
        rc = src.main(["dev2"], stdin=stdin, now=_NOW)
    assert rc == 0
    emit.assert_not_called()
    assert capsys.readouterr().out == ""


def test_main_is_fail_open_on_garbage_stdin(capsys) -> None:
    with mock.patch.object(src, "run_emit") as emit:
        rc = src.main(["dev2"], stdin=io.StringIO("{not json"), now=_NOW)
    assert rc == 0
    emit.assert_not_called()
    assert capsys.readouterr().out == ""
