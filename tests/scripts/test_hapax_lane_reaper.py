"""Contract tests for the observation-only lane inventory projection."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REAPER = REPO_ROOT / "scripts" / "hapax-lane-reaper"
SESSION_FORMAT = (
    "#{session_id}\t#{q:session_name}\t#{session_activity}\t#{session_created}\t#{session_windows}"
)
PANE_FORMAT = "#{session_id}\t#{pane_id}\t#{pane_pid}\t#{pane_dead}\t#{pane_active}"


def _write_executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _out(stdout: str = "", *, returncode: int = 0, stderr: str = "") -> dict[str, Any]:
    return {"stdout": stdout, "stderr": stderr, "returncode": returncode}


def _session(
    session_id: str,
    name: str,
    *,
    activity: str = "1700000000",
    created: str = "1690000000",
    windows: str = "1",
) -> str:
    return f"{session_id}\t{name}\t{activity}\t{created}\t{windows}\n"


def _pane(
    session_id: str,
    pane_id: str,
    *,
    pid: str = "4242",
    dead: str = "0",
    active: str = "1",
) -> str:
    return f"{session_id}\t{pane_id}\t{pid}\t{dead}\t{active}\n"


def _single_lane_scenario() -> dict[str, Any]:
    pane = _pane("$2", "%3")
    return {
        "list_sessions": _out(
            _session("$9", "unrelated-session") + _session("$2", "hapax-codex-cx-red", windows="2")
        ),
        "list_panes": {"$2": _out(pane)},
        "display_message": {"%3": _out(pane)},
    }


def _write_fake_tmux(bin_dir: Path) -> None:
    _write_executable(
        bin_dir / "tmux",
        f"""
        #!{sys.executable}
        import json
        import os
        import sys
        from pathlib import Path

        session_format = {SESSION_FORMAT!r}
        pane_format = {PANE_FORMAT!r}
        scenario = json.loads(Path(os.environ["HAPAX_TMUX_SCENARIO"]).read_text())
        ledger = Path(os.environ["HAPAX_TMUX_LEDGER"])
        args = sys.argv[1:]
        with ledger.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(args, separators=(",", ":")) + "\\n")

        outcome = None
        if os.environ.get("LC_ALL") != "C.UTF-8":
            sys.stderr.write("raw fake tmux locale rejection\\n")
            raise SystemExit(97)
        if args == ["list-sessions", "-F", session_format]:
            outcome = scenario["list_sessions"]
        elif (
            len(args) == 6
            and args[:3] == ["list-panes", "-s", "-t"]
            and args[4:] == ["-F", pane_format]
        ):
            outcome = scenario.get("list_panes", {{}}).get(args[3])
        elif (
            len(args) == 5
            and args[:3] == ["display-message", "-p", "-t"]
            and args[4] == pane_format
        ):
            outcome = scenario.get("display_message", {{}}).get(args[3])

        if outcome is None:
            sys.stderr.write("raw fake tmux argv rejection\\n")
            raise SystemExit(97)
        sys.stdout.write(outcome.get("stdout", ""))
        sys.stderr.write(outcome.get("stderr", ""))
        raise SystemExit(outcome.get("returncode", 0))
        """,
    )


DENIED_EXECUTABLES = (
    "awk",
    "cat",
    "cp",
    "curl",
    "date",
    "git",
    "grep",
    "hapax-alert",
    "kill",
    "killall",
    "mkdir",
    "mv",
    "nc",
    "notify-send",
    "pgrep",
    "pkill",
    "ps",
    "python",
    "python3",
    "rm",
    "sed",
    "sort",
    "ssh",
    "stat",
    "systemctl",
    "tee",
    "timeout",
    "touch",
    "tr",
    "truncate",
    "wc",
    "wget",
)


def _write_deny_shims(bin_dir: Path) -> None:
    for name in DENIED_EXECUTABLES:
        _write_executable(
            bin_dir / name,
            f"""
            #!/usr/bin/env bash
            printf '%s\\n' {name!r} >>"$HAPAX_DENY_LEDGER"
            exit 96
            """,
        )


def _base(tmp_path: Path, scenario: dict[str, Any]) -> tuple[dict[str, str], Path, Path]:
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    harness_dir = tmp_path / "harness"
    protected_dir = tmp_path / "protected"
    scenario_path = harness_dir / "scenario.json"
    ledger_path = harness_dir / "tmux-ledger.jsonl"
    deny_ledger = harness_dir / "deny-ledger.txt"

    harness_dir.mkdir(parents=True)
    protected_dir.mkdir(parents=True)
    home.mkdir(parents=True)
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
    (protected_dir / "task-note.md").write_text(
        "status: in_progress\nlabel: quota-receipt\ntext: BLOCKED: quota wall\n",
        encoding="utf-8",
    )
    (protected_dir / "cc-active-task-cx-red").write_text("fixture-task\n", encoding="utf-8")
    (protected_dir / "worktree-state").write_text("dirty sentinel\n", encoding="utf-8")
    (protected_dir / "cache-state.json").write_text('{"attempts": 7}\n', encoding="utf-8")

    _write_fake_tmux(bin_dir)
    _write_deny_shims(bin_dir)

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{bin_dir}:{env['PATH']}",
            "HAPAX_TMUX_SCENARIO": str(scenario_path),
            "HAPAX_TMUX_LEDGER": str(ledger_path),
            "HAPAX_DENY_LEDGER": str(deny_ledger),
        }
    )
    return env, protected_dir, harness_dir


def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(REAPER), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def _ledger(harness_dir: Path) -> list[list[str]]:
    path = harness_dir / "tmux-ledger.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _snapshot(root: Path) -> dict[str, tuple[int, str]]:
    return {
        str(path.relative_to(root)): (
            path.stat().st_mode,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _assert_no_denied_command(harness_dir: Path) -> None:
    path = harness_dir / "deny-ledger.txt"
    assert not path.exists() or not path.read_text(encoding="utf-8")


def _hold(operation: str, context: str, detail: str) -> str:
    return (
        "lane-reaper: projection state=HOLD scope=tmux "
        f"operation={operation} context={context} "
        "reason=tmux_observation_unavailable "
        f"detail={detail} exit=69 universal_observer_successor=required\n"
    )


def test_valid_inventory_projects_unknown_and_preserves_all_fixture_state(
    tmp_path: Path,
) -> None:
    env, protected_dir, harness_dir = _base(tmp_path, _single_lane_scenario())
    before = _snapshot(protected_dir)

    result = _run(env)

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == (
        "lane-reaper: projection state=UNKNOWN scope=lane session_id=$2 "
        "session_name=hapax-codex-cx-red role=cx-red pane_count=1 "
        "live_pane_count=1 active_pane_count=1 "
        "reason=direct_tmux_metadata_not_activation_grade "
        "universal_observer_successor=required\n"
        "lane-reaper: projection state=UNKNOWN scope=inventory lane_count=1 "
        "pane_count=1 live_pane_count=1 active_pane_count=1 "
        "reason=direct_tmux_metadata_not_activation_grade "
        "universal_observer_successor=required\n"
    )
    assert _snapshot(protected_dir) == before
    assert _ledger(harness_dir) == [
        ["list-sessions", "-F", SESSION_FORMAT],
        ["list-panes", "-s", "-t", "$2", "-F", PANE_FORMAT],
        ["display-message", "-p", "-t", "%3", PANE_FORMAT],
    ]
    _assert_no_denied_command(harness_dir)


def test_multiple_lanes_and_panes_are_numeric_sorted_and_aggregated(tmp_path: Path) -> None:
    pane_12 = _pane("$12", "%11", pid="511", active="1")
    pane_2_high = _pane("$2", "%10", pid="210", dead="1", active="0")
    pane_2_low = _pane("$2", "%3", pid="203", active="1")
    scenario = {
        "list_sessions": _out(
            _session("$12", "hapax-claude-beta") + _session("$2", "hapax-codex-cx-alpha")
        ),
        "list_panes": {
            "$2": _out(pane_2_high + pane_2_low),
            "$12": _out(pane_12),
        },
        "display_message": {
            "%3": _out(pane_2_low),
            "%10": _out(pane_2_high),
            "%11": _out(pane_12),
        },
    }
    env, _, harness_dir = _base(tmp_path, scenario)

    result = _run(env)

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr.splitlines() == [
        "lane-reaper: projection state=UNKNOWN scope=lane session_id=$2 "
        "session_name=hapax-codex-cx-alpha role=cx-alpha pane_count=2 "
        "live_pane_count=1 active_pane_count=1 "
        "reason=direct_tmux_metadata_not_activation_grade "
        "universal_observer_successor=required",
        "lane-reaper: projection state=UNKNOWN scope=lane session_id=$12 "
        "session_name=hapax-claude-beta role=beta pane_count=1 "
        "live_pane_count=1 active_pane_count=1 "
        "reason=direct_tmux_metadata_not_activation_grade "
        "universal_observer_successor=required",
        "lane-reaper: projection state=UNKNOWN scope=inventory lane_count=2 "
        "pane_count=3 live_pane_count=2 active_pane_count=2 "
        "reason=direct_tmux_metadata_not_activation_grade "
        "universal_observer_successor=required",
    ]
    ledger = _ledger(harness_dir)
    assert ledger == [
        ["list-sessions", "-F", SESSION_FORMAT],
        ["list-panes", "-s", "-t", "$2", "-F", PANE_FORMAT],
        ["display-message", "-p", "-t", "%3", PANE_FORMAT],
        ["display-message", "-p", "-t", "%10", PANE_FORMAT],
        ["list-panes", "-s", "-t", "$12", "-F", PANE_FORMAT],
        ["display-message", "-p", "-t", "%11", PANE_FORMAT],
    ]
    for call in ledger:
        format_arg = call[-1]
        assert format_arg.count("\t") == 4
        assert "\\t" not in format_arg
    _assert_no_denied_command(harness_dir)


def test_live_dry_run_and_compatibility_arguments_are_byte_identical(tmp_path: Path) -> None:
    env, protected_dir, harness_dir = _base(tmp_path, _single_lane_scenario())
    before = _snapshot(protected_dir)
    outcomes: list[tuple[int, str, str, list[list[str]]]] = []

    for args in (
        (),
        ("--dry-run",),
        ("--threshold", "0"),
        ("--reap-lineage", "fixture.task-1"),
        ("--dry-run", "--threshold", "30", "--reap-lineage", "fixture_task"),
    ):
        ledger_path = harness_dir / "tmux-ledger.jsonl"
        ledger_path.unlink(missing_ok=True)
        result = _run(env, *args)
        outcomes.append((result.returncode, result.stdout, result.stderr, _ledger(harness_dir)))
        assert _snapshot(protected_dir) == before

    assert all(outcome == outcomes[0] for outcome in outcomes)
    _assert_no_denied_command(harness_dir)


@pytest.mark.parametrize("session_stdout", ["", _session("$7", "not-a-hapax-lane")])
def test_valid_empty_eligible_inventory_does_not_query_panes(
    tmp_path: Path, session_stdout: str
) -> None:
    scenario = {"list_sessions": _out(session_stdout)}
    env, _, harness_dir = _base(tmp_path, scenario)

    result = _run(env)

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == (
        "lane-reaper: projection state=UNKNOWN scope=inventory lane_count=0 "
        "reason=valid_empty_inventory universal_observer_successor=required\n"
    )
    assert _ledger(harness_dir) == [["list-sessions", "-F", SESSION_FORMAT]]


@pytest.mark.parametrize(
    ("scenario", "operation", "context"),
    [
        (
            {"list_sessions": _out("partial", returncode=1, stderr="secret ls error\n")},
            "list-sessions",
            "none",
        ),
        (
            {
                "list_sessions": _out(_session("$2", "hapax-codex-cx-red")),
                "list_panes": {"$2": _out("partial", returncode=1, stderr="secret panes error\n")},
            },
            "list-panes",
            "session_id=$2",
        ),
        (
            {
                "list_sessions": _out(_session("$2", "hapax-codex-cx-red")),
                "list_panes": {"$2": _out(_pane("$2", "%3"))},
                "display_message": {
                    "%3": _out("partial", returncode=1, stderr="secret display error\n")
                },
            },
            "display-message",
            "session_id=$2,pane_id=%3",
        ),
    ],
)
def test_tmux_failures_emit_one_sanitized_operation_hold(
    tmp_path: Path, scenario: dict[str, Any], operation: str, context: str
) -> None:
    env, _, harness_dir = _base(tmp_path, scenario)

    result = _run(env)

    assert result.returncode == 69
    assert result.stdout == ""
    assert result.stderr == _hold(operation, context, "unavailable")
    assert "secret" not in result.stderr
    assert "scope=lane" not in result.stderr
    assert len(result.stderr.splitlines()) == 1
    _assert_no_denied_command(harness_dir)


@pytest.mark.parametrize(
    ("scenario", "operation", "context"),
    [
        (
            {"list_sessions": _out("$2\thapax-codex-cx-red\t1\t2\n")},
            "list-sessions",
            "none",
        ),
        (
            {
                "list_sessions": _out(_session("$2", "hapax-codex-cx-red")),
                "list_panes": {"$2": _out(_pane("$2", "%3", pid="0"))},
            },
            "list-panes",
            "session_id=$2",
        ),
        (
            {
                "list_sessions": _out(_session("$2", "hapax-codex-cx-red")),
                "list_panes": {"$2": _out(_pane("$2", "%3"))},
                "display_message": {"%3": _out(_pane("$2", "%3") + _pane("$2", "%4"))},
            },
            "display-message",
            "session_id=$2,pane_id=%3",
        ),
    ],
)
def test_malformed_metadata_emits_one_hold_without_partial_projection(
    tmp_path: Path, scenario: dict[str, Any], operation: str, context: str
) -> None:
    env, _, _ = _base(tmp_path, scenario)

    result = _run(env)

    assert result.returncode == 69
    assert result.stdout == ""
    assert result.stderr == _hold(operation, context, "malformed")
    assert "scope=lane" not in result.stderr


@pytest.mark.parametrize(
    ("scenario", "operation", "context"),
    [
        (
            {
                "list_sessions": _out(
                    _session("$2", "hapax-codex-cx-red") + _session("$2", "hapax-claude-blue")
                )
            },
            "list-sessions",
            "none",
        ),
        (
            {
                "list_sessions": _out(
                    _session("$2", "hapax-codex-cx-red") + _session("$3", "hapax-codex-cx-red")
                )
            },
            "list-sessions",
            "none",
        ),
        (
            {
                "list_sessions": _out(_session("$2", "hapax-codex-cx-red")),
                "list_panes": {"$2": _out("")},
            },
            "list-panes",
            "session_id=$2",
        ),
        (
            {
                "list_sessions": _out(
                    _session("$2", "hapax-codex-cx-red") + _session("$3", "hapax-claude-blue")
                ),
                "list_panes": {
                    "$2": _out(_pane("$2", "%3")),
                    "$3": _out(_pane("$3", "%3", pid="4343")),
                },
                "display_message": {"%3": _out(_pane("$2", "%3"))},
            },
            "list-panes",
            "session_id=$3",
        ),
        (
            {
                "list_sessions": _out(_session("$2", "hapax-codex-cx-red")),
                "list_panes": {"$2": _out(_pane("$9", "%3"))},
            },
            "list-panes",
            "session_id=$2",
        ),
        (
            {
                "list_sessions": _out(_session("$2", "hapax-codex-cx-red")),
                "list_panes": {"$2": _out(_pane("$2", "%3"))},
                "display_message": {"%3": _out(_pane("$2", "%3", pid="9999"))},
            },
            "display-message",
            "session_id=$2,pane_id=%3",
        ),
    ],
)
def test_incoherent_metadata_emits_one_hold(
    tmp_path: Path, scenario: dict[str, Any], operation: str, context: str
) -> None:
    env, _, _ = _base(tmp_path, scenario)

    result = _run(env)

    assert result.returncode == 69
    assert result.stdout == ""
    assert result.stderr == _hold(operation, context, "incoherent")


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        (("--threshold",), "missing_operand"),
        (("--reap-lineage",), "missing_operand"),
        (("--threshold", "-1"), "invalid_operand"),
        (("--threshold", "01"), "invalid_operand"),
        (("--reap-lineage", ".bad"), "invalid_operand"),
        (("--dry-run", "--dry-run"), "duplicate_option"),
        (("--threshold", "1", "--threshold", "2"), "duplicate_option"),
        (("--reap-lineage", "one", "--reap-lineage", "two"), "duplicate_option"),
        (("--unknown",), "unknown_argument"),
        (("bare-value",), "positional_argument"),
    ],
)
def test_invalid_arguments_fail_without_observing_tmux(
    tmp_path: Path, args: tuple[str, ...], reason: str
) -> None:
    env, protected_dir, harness_dir = _base(tmp_path, _single_lane_scenario())
    before = _snapshot(protected_dir)

    result = _run(env, *args)

    assert result.returncode == 64
    assert result.stdout == ""
    assert result.stderr == f"lane-reaper: usage_error reason={reason} exit=64\n"
    assert _ledger(harness_dir) == []
    assert _snapshot(protected_dir) == before


def test_sentinel_process_identity_is_unchanged(tmp_path: Path) -> None:
    env, _, harness_dir = _base(tmp_path, _single_lane_scenario())
    sentinel = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        stat_path = Path(f"/proc/{sentinel.pid}/stat")
        start_identity = stat_path.read_text(encoding="utf-8").split()[21]

        result = _run(env)

        assert result.returncode == 0, result.stderr
        assert sentinel.poll() is None
        assert stat_path.read_text(encoding="utf-8").split()[21] == start_identity
        _assert_no_denied_command(harness_dir)
    finally:
        sentinel.terminate()
        sentinel.wait(timeout=10)


def test_static_observation_only_effect_closure() -> None:
    text = REAPER.read_text(encoding="utf-8")
    forbidden = (
        "capture-pane",
        "pane_current_command",
        "pane_title",
        "pane_current_path",
        "cc-active-task",
        "os.kill",
        "kill-session",
        "recovery_governor",
        "dispatch-service-time",
        "lane-reap-attempts",
        "hapax-alert",
        "notify-send",
        "systemctl",
        "worktree remove",
        "/dev/tcp",
    )
    for token in forbidden:
        assert token not in text

    external_names = re.compile(
        r"\b(?:awk|cat|cp|curl|date|eval|git|grep|kill|killall|mkdir|mv|nc|"
        r"pgrep|pkill|ps|python3?|rm|sed|sort|ssh|stat|tee|timeout|touch|tr|"
        r"truncate|wc|wget)\b"
    )
    assert not external_names.search(text)
    assert text.count('LC_ALL=C.UTF-8 tmux "$@" 2>/dev/null') == 1
    without_conditionals = re.sub(r"\[\[.*?\]\]", "", text, flags=re.S)
    assert ">" not in without_conditionals.replace(">&2", "").replace("2>/dev/null", "")


def test_script_remains_executable() -> None:
    assert os.access(REAPER, os.X_OK)
