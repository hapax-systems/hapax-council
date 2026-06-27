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
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

_REPO = Path(__file__).resolve().parents[2]
_MOD_PATH = _REPO / "hooks" / "scripts" / "sense_reissue_capture.py"
_WRAPPER = _REPO / "hooks" / "scripts" / "sense-reissue-capture.sh"
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
    def eid(session, prompt, *, role="dev2", program="continuity-substrate", now=_NOW):
        return src.reissue_event_id(session, prompt, role=role, program=program, now=now)

    a = eid("sess-1", "research your purview")
    assert a == eid("sess-1", "research your purview")  # deterministic
    assert a.startswith("sigreissue-")
    # genuine later re-issue, different prompt, different lane, different program -> distinct events
    assert a != eid("sess-1", "research your purview", now=datetime(2026, 6, 28, 9, 0, tzinfo=UTC))
    assert a != eid("sess-1", "make sure you have everything")
    assert a != eid("sess-1", "research your purview", role="alpha")
    assert a != eid("sess-1", "research your purview", program="other-program")


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
    committed = src.format_receipt(
        {"appended": True, "spooled": False},
        trigger_class="purview",
        program="continuity-substrate",
    )
    committed_no_prog = src.format_receipt(
        {"appended": True}, trigger_class="purview", program=None
    )
    queued = src.format_receipt({"appended": False, "spooled": True}, trigger_class="purview")
    nothing = src.format_receipt({}, trigger_class="purview")
    assert "captured" in committed and "queued" not in committed
    assert "role/program-scoped" in committed
    assert "role-scoped" in committed_no_prog and "program-scoped" not in committed_no_prog
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


# --- run_emit: the subprocess boundary (was entirely mocked before; review-team blockers) ---


def test_run_emit_against_real_cli_writes_event(tmp_path) -> None:
    """Drive build_emit_command's argv through the REAL coord CLI — pins the flag contract
    (a misspelled/absent flag would make argparse exit nonzero) AND run_emit's success path."""
    cmd = src.build_emit_command(
        role="dev2",
        session_id="itest-sess",
        program=None,
        event_id="sigreissue-itest",
        trigger_class="purview",
        verbatim="research your purview",
        python_exe=sys.executable,
    )
    cmd += [
        "--db-path",
        str(tmp_path / "c.db"),
        "--jsonl-path",
        str(tmp_path / "c.jsonl"),
        "--spool-dir",
        str(tmp_path / "spool"),
    ]
    receipt = src.run_emit(cmd)
    assert receipt.get("appended") is True, receipt
    rows = (tmp_path / "c.jsonl").read_text(encoding="utf-8")
    assert "signal.reissue" in rows
    assert "sigreissue-itest" in rows


def test_run_emit_fail_open_on_nonzero_exit() -> None:
    assert src.run_emit([sys.executable, "-c", "import sys; sys.exit(3)"]) == {}


def test_run_emit_fail_open_on_garbage_stdout() -> None:
    assert src.run_emit([sys.executable, "-c", "print('not json')"]) == {}


def test_run_emit_fail_open_on_non_dict_json() -> None:
    assert src.run_emit([sys.executable, "-c", "print('[1, 2, 3]')"]) == {}


def test_run_emit_fail_open_on_missing_executable() -> None:
    assert src.run_emit(["/nonexistent/python-xyz", "append"]) == {}


def test_build_emit_command_truncates_long_verbatim() -> None:
    cmd = src.build_emit_command(
        role="dev2",
        session_id="s",
        program=None,
        event_id="e",
        trigger_class="coverage",
        verbatim="x" * 1000,
    )
    payload = json.loads(cmd[cmd.index("--payload") + 1])
    assert len(payload["verbatim"]) == 600
    assert payload["trigger_class"] == "coverage"


# --- program resolution (the critical: the real wrapper-to-core path must be program-scoped) ---


def test_resolve_program_reads_train_from_active_task(tmp_path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (cache / "cc-active-task-dev2").write_text("cc-task-x-20260627\n", encoding="utf-8")
    (tasks / "cc-task-x-20260627.md").write_text(
        "---\nstatus: in_progress\ntrain: continuity-substrate\n---\n", encoding="utf-8"
    )
    assert src.resolve_program("dev2", cache_dir=cache, tasks_dir=tasks) == "continuity-substrate"


def test_resolve_program_none_when_no_marker_or_role(tmp_path) -> None:
    assert src.resolve_program("nobody", cache_dir=tmp_path, tasks_dir=tmp_path) is None
    assert src.resolve_program("", cache_dir=tmp_path, tasks_dir=tmp_path) is None


def test_main_resolves_and_passes_program() -> None:
    stdin = io.StringIO(json.dumps({"prompt": "research your purview", "session_id": "s"}))
    captured: dict[str, list[str]] = {}

    def fake_emit(cmd):
        captured["cmd"] = list(cmd)
        return {"appended": True}

    with (
        mock.patch.object(src, "run_emit", side_effect=fake_emit),
        mock.patch.object(src, "resolve_program", return_value="continuity-substrate"),
    ):
        rc = src.main(["dev2"], stdin=stdin, now=_NOW)
    assert rc == 0
    cmd = captured["cmd"]
    assert "--parent-spec" in cmd
    assert cmd[cmd.index("--parent-spec") + 1] == "continuity-substrate"


def test_main_uses_wall_clock_when_now_is_none() -> None:
    stdin = io.StringIO(json.dumps({"prompt": "research your purview", "session_id": "s"}))
    with (
        mock.patch.object(src, "run_emit", return_value={"appended": True}),
        mock.patch.object(src, "resolve_program", return_value=None),
    ):
        rc = src.main(["dev2"], stdin=stdin)  # now omitted -> datetime.now(UTC) branch
    assert rc == 0


# --- the .sh wrapper: fail-open guarantee (was untested; review-team blockers) ---


def test_wrapper_is_fail_open_on_garbage_stdin() -> None:
    proc = subprocess.run(
        [str(_WRAPPER)], input="{not json", capture_output=True, text=True, timeout=15
    )
    assert proc.returncode == 0, proc.stderr


def test_wrapper_is_fail_open_on_empty_stdin() -> None:
    proc = subprocess.run([str(_WRAPPER)], input="", capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0, proc.stderr


# --- round-2 review-team coverage ---


def test_run_emit_real_cli_pins_parent_spec(tmp_path) -> None:
    """The one flag the prior real-CLI test never exercised. A misnamed/unsupported --parent-spec
    would make the real argparse exit nonzero -> run_emit -> {} -> this assertion fails."""
    cmd = src.build_emit_command(
        role="dev2",
        session_id="itest-prog",
        program="continuity-substrate",
        event_id="sigreissue-prog",
        trigger_class="purview",
        verbatim="research your purview",
        python_exe=sys.executable,
    )
    cmd += [
        "--db-path",
        str(tmp_path / "c.db"),
        "--jsonl-path",
        str(tmp_path / "c.jsonl"),
        "--spool-dir",
        str(tmp_path / "spool"),
    ]
    receipt = src.run_emit(cmd)
    assert receipt.get("appended") is True, receipt
    rows = (tmp_path / "c.jsonl").read_text(encoding="utf-8")
    assert "continuity-substrate" in rows  # --parent-spec accepted + persisted by the real CLI


def test_resolve_program_fail_open_on_unreadable_marker(tmp_path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "cc-active-task-dev2").mkdir()  # a dir -> read_text raises -> caught -> None
    assert src.resolve_program("dev2", cache_dir=cache, tasks_dir=tmp_path / "tasks") is None


def test_resolve_program_prefers_session_keyed_over_stale_legacy(tmp_path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    # stale legacy pointer -> program-A; session-keyed pointer -> program-B (the active claim)
    (cache / "cc-active-task-dev2").write_text("cc-task-legacy\n", encoding="utf-8")
    (cache / "cc-active-task-dev2-sess9").write_text("cc-task-current\n", encoding="utf-8")
    (tasks / "cc-task-legacy.md").write_text("---\ntrain: program-A\n---\n", encoding="utf-8")
    (tasks / "cc-task-current.md").write_text("---\ntrain: program-B\n---\n", encoding="utf-8")
    # with the session id, the session-keyed claim wins (not the stale legacy pointer)
    assert (
        src.resolve_program("dev2", session_id="sess9", cache_dir=cache, tasks_dir=tasks)
        == "program-B"
    )
    # without a session id, falls back to the legacy pointer
    assert src.resolve_program("dev2", cache_dir=cache, tasks_dir=tasks) == "program-A"


def test_run_emit_fail_open_on_timeout() -> None:
    with mock.patch.object(
        src.subprocess, "run", side_effect=src.subprocess.TimeoutExpired("x", 8)
    ):
        assert src.run_emit([sys.executable, "-c", "pass"]) == {}


def test_wrapper_success_path_emits_event(tmp_path) -> None:
    """End-to-end through the REAL wrapper -> core -> coord CLI (isolated coord dir). Pins that the
    shell forwards a re-issue to the core and an event lands — the path where a program/flag break
    would surface in production."""
    coord = tmp_path / "coord"
    env = {**os.environ, "HAPAX_COORD_DIR": str(coord), "HAPAX_AGENT_NAME": "dev2"}
    proc = subprocess.run(
        [str(_WRAPPER)],
        input=json.dumps({"prompt": "research your purview", "session_id": "wrap-itest"}),
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    found = list(coord.rglob("*.jsonl"))
    assert found, f"no ledger written; stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert any("signal.reissue" in f.read_text(encoding="utf-8") for f in found)
