"""hapax-claude: a launch is not a dispatch.

Pins the three defects measured on 2026-09-24:

* Workspace trust. dev3, dev4 and dev5 sat 50-65 min at Claude Code's "Yes, I trust
  this folder" dialog while the seat counted them dispatched. The launcher now marks
  the working directory trusted in the global config before claude starts.
* Readiness. After spawning a tmux/foot lane the launcher waits for the pane to show
  the REPL, and the brief when one was passed. It exits nonzero with the pane text
  when a blocking modal shows instead.
* Inherited identity. A seat-launched ``--role dev6`` tried to claim the seat's own
  charter, because the launcher seeded its task from the parent's
  ``HAPAX_METHODOLOGY_DISPATCH_TASK``. Identity now comes only from explicit flags.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import stat
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-claude"


@pytest.fixture(autouse=True)
def _no_ambient_tmux(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing in this module may reach the tmux server the suite runs under.

    With TMUX/TMUX_PANE removed and TMUX_TMPDIR private, even a tmux call that
    forgets its -S lands on a server under tmp_path (see "Real tmux" below)."""
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    private = tmp_path / "tmux-tmpdir"
    private.mkdir()
    monkeypatch.setenv("TMUX_TMPDIR", str(private))


TRUST_DIALOG = """\
 Accessing workspace:

 /home/hapax/Documents/Personal/30-areas/hapax

 Quick safety check: Is this a project you created or one you trust?

 ❯ 1. Yes, I trust this folder
   2. No, exit

 Enter to confirm · Esc to cancel
"""

REPL_FOOTER = """\
────────────────────────────────────────────────────────────────────────────────
❯
────────────────────────────────────────────────────────────────────────────────
  ⏵⏵ bypass permissions on (shift+tab to cycle)
"""

BRIEF = (
    "You are role dev9, recruited by the coordinator seat. Read your task row in full "
    "and meet its exit predicate, then report to the seat's inbox."
)

# Environment a launch from inside a coordinator session carries.
PARENT_IDENTITY = {
    "HAPAX_METHODOLOGY_DISPATCH_TASK": "coordinator-seat-charter-20260924",
    "HAPAX_SESSION_ID": "11111111-2222-3333-4444-555555555555",
    "CLAUDECODE": "1",
    "CLAUDE_CODE_SESSION_ID": "parent-harness-session",
    "CLAUDE_CODE_MESSAGING_TOKEN": "parent-messaging-token",
    "HAPAX_AGENT_NAME": "dev1",
    "CLAUDE_ROLE": "dev1",
    "HAPAX_AGENT_ROLE": "dev1",
}

FAKE_TMUX = r"""#!/usr/bin/env bash
{ printf -- '--\n'; printf '%s\n' "$@"; } >> "$FAKE_TMUX_LOG"
state="$FAKE_TMUX_STATE"
case "${1:-}" in
  has-session) [ -e "$state/session" ] && [ ! -e "$state/gone" ] ;;
  new-session)
    rc="${FAKE_TMUX_NEW_SESSION_RC:-0}"
    [ "$rc" = 0 ] || exit "$rc"
    : > "$state/session"
    # Run the pane's command (the runner) the way a pane would, minus the terminal:
    # its environment is this one, and it execs the fake claude below.
    for last in "$@"; do :; done
    [ -x "$last" ] && "$last" >/dev/null 2>&1 < /dev/null
    exit 0 ;;
  display-message) printf '%s\n' "${FAKE_PANE_DEAD:-0}" ;;
  capture-pane) [ -n "${FAKE_PANE_FILE:-}" ] && cat "$FAKE_PANE_FILE" ;;
  *) exit 0 ;;
esac
"""

# Records its argv and the identity part of its environment. With FAKE_TRANSCRIPT set
# it also writes a transcript record where Claude Code would, to
# $HOME/.claude/projects/<physical cwd, non-alphanumerics as '-'>/<session>.jsonl:
#   user   the brief (its last argument) as a user record stamped now
#   stale  the same record stamped an hour before the launch
#   meta   the same record marked isMeta
#   other  a user record stamped now whose text is not the brief
FAKE_CLAUDE = r"""#!/usr/bin/env bash
printf '%s\n' "$@" > "$FAKE_CLAUDE_ARGV"
env | grep -E '^(HAPAX_|CLAUDE)' | sort > "$FAKE_CLAUDE_ENV"
[ -n "${FAKE_TRANSCRIPT:-}" ] || exit 0
sid="resumed"; prev=""; last=""
for a in "$@"; do [ "$prev" = --session-id ] && sid="$a"; prev="$a"; last="$a"; done
dir="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects/$(pwd -P | sed 's/[^A-Za-z0-9]/-/g')"
mkdir -p "$dir"
python3 - "$FAKE_TRANSCRIPT" "$sid" "$last" >> "$dir/$sid.jsonl" <<'PY'
import datetime, json, sys
mode, sid, brief = sys.argv[1:4]
now = datetime.datetime.now(datetime.timezone.utc)
if mode == "stale":
    now -= datetime.timedelta(hours=1)
print(json.dumps({"type": "permission-mode", "sessionId": sid}))
print(json.dumps({
    "type": "user",
    "timestamp": now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    "sessionId": sid,
    "isMeta": mode == "meta",
    "message": {"role": "user", "content": "something else" if mode == "other" else brief},
}))
PY
"""

CC_CLAIM_RECORDER = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$(dirname "$0")/../cc-claim-calls.txt"
"""


def _executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _seed_config() -> dict:
    return {
        "numStartups": 412,
        "theme": "dark",
        "oauthAccount": {"emailAddress": "operator@example.invalid", "organizationRole": "admin"},
        "tipsHistory": {"memory-command": 7},
        "lastFps": 4.06,
        "note": "unicode survives — ✓ ⏵⏵",
        "projects": {
            "/some/other/project": {
                "allowedTools": ["Bash(ls:*)"],
                "hasTrustDialogAccepted": True,
                "lastSessionId": "d42178dd-8b1e-4631-8db8-10511643f342",
                "lastFpsLow1Pct": 371.36,
            }
        },
    }


class Launch:
    """One hermetic launcher environment: private HOME, fake claude/tmux/cc-claim."""

    def __init__(self, tmp_path: Path, *, config: dict | None | str = "seed") -> None:
        self.tmp = tmp_path
        self.home = tmp_path / "home"
        self.work = tmp_path / "work"
        self.bin = tmp_path / "bin"
        self.state = tmp_path / "tmux-state"
        for d in (self.home, self.work, self.bin, self.state):
            d.mkdir(parents=True, exist_ok=True)
        self.config_path = self.home / ".claude.json"
        if config == "seed":
            config = _seed_config()
        if isinstance(config, dict):
            self.config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False))
            self.config_path.chmod(0o600)
        self.credentials = self.home / ".claude" / ".credentials.json"
        self.credentials.parent.mkdir(parents=True, exist_ok=True)
        self.credentials.write_text('{"claudeAiOauth": {"accessToken": "sk-ant-oat01-FAKE"}}')
        self.pane = tmp_path / "pane.txt"
        self.tmux_log = tmp_path / "tmux-calls.txt"
        self.argv = tmp_path / "claude-argv.txt"
        self.claude_env = tmp_path / "claude-env.txt"
        _executable(self.bin / "tmux", FAKE_TMUX)
        _executable(self.bin / "claude", FAKE_CLAUDE)
        _executable(self.bin / "claude-recorder", FAKE_CLAUDE)  # for scripted real-tmux claudes
        _executable(self.work / "scripts" / "cc-claim", CC_CLAIM_RECORDER)
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("HAPAX_", "CLAUDE")) and k not in ("TMUX", "TMUX_PANE")
        }
        env.update(
            {
                "HOME": str(self.home),
                "XDG_CACHE_HOME": str(tmp_path / "cache"),
                "PATH": f"{self.bin}:{env['PATH']}",
                "HAPAX_COUNCIL_DIR": str(REPO_ROOT),
                "HAPAX_SESSION_PROTECTION_FILE": str(tmp_path / "no-protection.md"),
                "FAKE_TMUX_LOG": str(self.tmux_log),
                "FAKE_TMUX_STATE": str(self.state),
                "FAKE_PANE_FILE": str(self.pane),
                "FAKE_CLAUDE_ARGV": str(self.argv),
                "FAKE_CLAUDE_ENV": str(self.claude_env),
                "HAPAX_CLAUDE_READY_TIMEOUT": "3",
            }
        )
        self.env = env

    def show(self, text: str) -> None:
        self.pane.write_text(text, encoding="utf-8")

    def run(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(SCRIPT), "--cd", str(self.work), *args],
            env={**self.env, **env},
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def config(self) -> dict:
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    def runner(self) -> str:
        runners = sorted((self.tmp / "cache" / "hapax" / "claude-spawns").glob("run-*.sh"))
        assert len(runners) == 1, runners
        return runners[0].read_text(encoding="utf-8")

    def tmux_calls(self) -> list[list[str]]:
        blocks: list[list[str]] = []
        text = self.tmux_log.read_text() if self.tmux_log.exists() else ""
        for line in text.splitlines():
            if line == "--":
                blocks.append([])
            elif blocks:
                blocks[-1].append(line)
        return blocks

    def cc_claim_calls(self) -> list[str]:
        calls = self.work / "cc-claim-calls.txt"
        return calls.read_text().splitlines() if calls.exists() else []


# ── Workspace trust ─────────────────────────────────────────────────────────


def _trust_launch(launch: Launch, **env: str) -> subprocess.CompletedProcess[str]:
    """terminal=none: the trust write happens, then the fake claude is exec'd."""
    return launch.run("--role", "dev", "--terminal", "none", "--readonly", **env)


def test_trust_is_preaccepted_and_every_other_key_survives(tmp_path: Path) -> None:
    launch = Launch(tmp_path)
    before = launch.config()
    res = _trust_launch(launch)
    assert res.returncode == 0, res.stderr
    after = launch.config()
    key = str(launch.work.resolve())
    assert after["projects"][key]["hasTrustDialogAccepted"] is True
    # The entry Claude Code itself would create, so no reader meets a missing field.
    assert after["projects"][key]["allowedTools"] == []
    assert after["projects"][key]["mcpServers"] == {}
    after["projects"].pop(key)
    assert after == before, "the trust write changed a key it does not own"
    assert stat.S_IMODE(launch.config_path.stat().st_mode) == 0o600
    assert not list(launch.home.glob(".claude.json.hapax-trust.*")), "temp file left behind"


def test_trust_key_is_the_physical_path(tmp_path: Path) -> None:
    launch = Launch(tmp_path)
    link = tmp_path / "work-link"
    link.symlink_to(launch.work)
    res = subprocess.run(
        [str(SCRIPT), "--cd", str(link), "--role", "dev", "--terminal", "none", "--readonly"],
        env=launch.env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    projects = launch.config()["projects"]
    assert projects[str(launch.work.resolve())]["hasTrustDialogAccepted"] is True
    assert str(link) not in projects


def test_an_existing_entry_keeps_its_fields(tmp_path: Path) -> None:
    seed = _seed_config()
    key = str((tmp_path / "work").resolve())
    seed["projects"][key] = {
        "allowedTools": ["Bash(git status)"],
        "hasTrustDialogAccepted": False,
        "lastCost": 1.25,
    }
    launch = Launch(tmp_path, config=seed)
    assert _trust_launch(launch).returncode == 0
    entry = launch.config()["projects"][key]
    assert entry == {
        "allowedTools": ["Bash(git status)"],
        "hasTrustDialogAccepted": True,
        "lastCost": 1.25,
    }


def test_an_already_trusted_directory_is_not_rewritten(tmp_path: Path) -> None:
    seed = _seed_config()
    seed["projects"][str((tmp_path / "work").resolve())] = {"hasTrustDialogAccepted": True}
    launch = Launch(tmp_path, config=seed)
    raw, mtime = launch.config_path.read_bytes(), launch.config_path.stat().st_mtime_ns
    assert _trust_launch(launch).returncode == 0
    assert launch.config_path.read_bytes() == raw
    assert launch.config_path.stat().st_mtime_ns == mtime


def test_credentials_are_never_touched(tmp_path: Path) -> None:
    launch = Launch(tmp_path)
    raw, mtime = launch.credentials.read_bytes(), launch.credentials.stat().st_mtime_ns
    assert _trust_launch(launch).returncode == 0
    assert launch.credentials.read_bytes() == raw
    assert launch.credentials.stat().st_mtime_ns == mtime
    assert ".credentials" not in SCRIPT.read_text(encoding="utf-8").split("TRUST_PY=")[1].split(
        "preaccept_workspace_trust\n"
    )[0].replace("Credentials live in ~/.claude/.credentials.json", "")


def test_a_malformed_config_is_left_alone_and_the_launch_continues(tmp_path: Path) -> None:
    launch = Launch(tmp_path, config=None)
    launch.config_path.write_text('{"projects": {', encoding="utf-8")
    res = _trust_launch(launch)
    assert res.returncode == 0, res.stderr
    assert launch.config_path.read_text(encoding="utf-8") == '{"projects": {'
    assert "could not pre-accept workspace trust" in res.stderr
    assert "not valid JSON" in res.stderr


def test_a_symlinked_config_is_not_written_through(tmp_path: Path) -> None:
    launch = Launch(tmp_path, config=None)
    real = tmp_path / "real-claude.json"
    real.write_text(json.dumps(_seed_config()), encoding="utf-8")
    launch.config_path.symlink_to(real)
    raw = real.read_bytes()
    res = _trust_launch(launch)
    assert res.returncode == 0, res.stderr
    assert real.read_bytes() == raw
    assert "symlink" in res.stderr


def test_a_missing_config_is_not_created(tmp_path: Path) -> None:
    launch = Launch(tmp_path, config=None)
    res = _trust_launch(launch)
    assert res.returncode == 0, res.stderr
    assert not launch.config_path.exists()
    assert "does not exist" in res.stderr


def test_claude_config_dir_is_honoured(tmp_path: Path) -> None:
    launch = Launch(tmp_path)
    cfg_dir = tmp_path / "claude-config"
    cfg_dir.mkdir()
    (cfg_dir / ".claude.json").write_text(json.dumps(_seed_config()), encoding="utf-8")
    home_raw = launch.config_path.read_bytes()
    assert _trust_launch(launch, CLAUDE_CONFIG_DIR=str(cfg_dir)).returncode == 0
    moved = json.loads((cfg_dir / ".claude.json").read_text(encoding="utf-8"))
    assert moved["projects"][str(launch.work.resolve())]["hasTrustDialogAccepted"] is True
    assert launch.config_path.read_bytes() == home_raw


def test_home_itself_is_not_marked_trusted(tmp_path: Path) -> None:
    """Claude Code honours home-directory trust per session only; a persisted flag
    there would look like a fix and change nothing."""
    launch = Launch(tmp_path)
    raw = launch.config_path.read_bytes()
    res = subprocess.run(
        [
            str(SCRIPT),
            "--cd",
            str(launch.home),
            "--role",
            "dev",
            "--terminal",
            "none",
            "--readonly",
        ],
        env=launch.env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    assert launch.config_path.read_bytes() == raw
    assert "home trust per session only" in res.stderr


def test_trust_is_written_before_the_tmux_lane_starts(tmp_path: Path) -> None:
    launch = Launch(tmp_path)
    launch.show(REPL_FOOTER)
    res = launch.run("--role", "dev", "--terminal", "tmux", "--readonly")
    assert res.returncode == 0, res.stderr
    assert launch.config()["projects"][str(launch.work.resolve())]["hasTrustDialogAccepted"]


# ── Readiness witness ───────────────────────────────────────────────────────


def _spawn(launch: Launch, *extra: str, **env: str) -> subprocess.CompletedProcess[str]:
    return launch.run("--role", "dev9", "--terminal", "tmux", *extra, **env)


def test_a_trust_dialog_fails_the_launch_with_the_pane_text(tmp_path: Path) -> None:
    launch = Launch(tmp_path)
    launch.show(TRUST_DIALOG)
    res = _spawn(launch, "--", BRIEF)
    assert res.returncode == 20, res.stderr
    assert "modal_blocked: trust" in res.stderr
    assert "Yes, I trust this folder" in res.stderr, "the pane text must reach the caller"
    assert "hapax-claude-dev9" not in res.stdout, "a blocked lane must not print as launched"
    assert not any(b[:1] == ["kill-session"] for b in launch.tmux_calls()), (
        "the blocked pane must be left alive to inspect or answer"
    )


@pytest.mark.parametrize(
    ("pane", "modal"),
    [
        ("Some other dialog\n\n Enter to confirm · Esc to cancel\n", "confirm"),
        ("Allow this?\n Esc to cancel\n", "confirm"),
        ("WARNING: Bypass Permissions mode\n 1. No, exit\n 2. Yes, I accept\n", "confirm"),
        (f"❯ {BRIEF}\n\n  ⎿  You've hit your limit · resets 9pm\n{REPL_FOOTER}", "limit"),
        (
            f"❯ {BRIEF}\n\n  ⎿  API Error: Claude's safeguards stopped the response\n{REPL_FOOTER}",
            "safeguard",
        ),
    ],
)
def test_each_known_blocking_modal_fails_the_launch(tmp_path: Path, pane: str, modal: str) -> None:
    """A modal fails the launch even when the transcript already holds the brief:
    a lane stopped at its limit after the first turn is not working."""
    launch = Launch(tmp_path)
    launch.show(pane)
    res = _spawn(launch, "--", BRIEF, FAKE_TRANSCRIPT="user")
    assert res.returncode == 20, res.stderr
    assert f"modal_blocked: {modal}" in res.stderr


def test_a_brief_recorded_in_the_lanes_transcript_is_ready(tmp_path: Path) -> None:
    launch = Launch(tmp_path)
    launch.show(f"❯ {BRIEF}\n\n✶ Cultivating… (3s · ↓ 120 tokens)\n{REPL_FOOTER}")
    res = _spawn(launch, "--", BRIEF, FAKE_TRANSCRIPT="user")
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "hapax-claude-dev9"


def test_a_brief_on_screen_is_not_delivery(tmp_path: Path) -> None:
    """Measured 2026-09-24 19:39-19:54Z: seven lanes showed their note in the input
    box for ~14 min and none had received it. Only the transcript counts."""
    launch = Launch(tmp_path)
    launch.show(f"❯ {BRIEF}\n\n✶ Cultivating… (3s · ↓ 120 tokens)\n{REPL_FOOTER}")
    res = _spawn(launch, "--", BRIEF, HAPAX_CLAUDE_READY_TIMEOUT="1")
    assert res.returncode == 21, res.stderr
    assert "hapax-claude-dev9" not in res.stdout


@pytest.mark.parametrize(
    "record",
    [
        pytest.param("stale", id="stamped-before-the-launch"),
        pytest.param("meta", id="a-meta-record"),
        pytest.param("other", id="a-different-message"),
    ],
)
def test_only_a_fresh_user_record_of_the_brief_counts(tmp_path: Path, record: str) -> None:
    launch = Launch(tmp_path)
    launch.show(f"❯ {BRIEF}\n{REPL_FOOTER}")
    res = _spawn(launch, "--", BRIEF, FAKE_TRANSCRIPT=record, HAPAX_CLAUDE_READY_TIMEOUT="1")
    assert res.returncode == 21, res.stderr


def test_a_resumed_lanes_brief_is_found_in_its_project_transcripts(tmp_path: Path) -> None:
    """--continue picks the session itself, so there is no pinned path; any transcript
    of this workdir written since the launch may carry the brief."""
    launch = Launch(tmp_path)
    launch.show(f"❯ {BRIEF}\n{REPL_FOOTER}")
    res = _spawn(launch, "--continue", "--", BRIEF, FAKE_TRANSCRIPT="user")
    assert res.returncode == 0, res.stderr
    assert "--session-id" not in launch.runner()


def test_a_brief_that_quotes_modal_words_is_not_a_modal(tmp_path: Path) -> None:
    """The seat's briefs quote these phrases (this row's own does). Only text AFTER
    the rendered brief can be a modal, and the TUI re-wraps the brief to the pane."""
    brief = (
        "Sweep every pane for modal text (trust this folder / Enter to confirm / Esc to "
        "cancel / hit your limit / safeguard) and report what you find."
    )
    words, lines, line = brief.split(), [], ""
    for w in words:  # re-wrap to a 40-column pane with the TUI's two-space indent
        if len(line) + len(w) + 1 > 38:
            lines.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    lines.append(line)
    launch = Launch(tmp_path)
    launch.show("❯ " + "\n  ".join(lines) + f"\n\n✶ Thinking…\n{REPL_FOOTER}")
    res = _spawn(launch, "--", brief, FAKE_TRANSCRIPT="user")
    assert res.returncode == 0, res.stderr


def test_a_brieffree_launch_is_ready_at_the_idle_repl(tmp_path: Path) -> None:
    """The supervisor and watchdog respawn --readonly lanes with no brief."""
    launch = Launch(tmp_path)
    launch.show(
        " ✻ Welcome to Claude Code\n\n"
        + REPL_FOOTER.replace("bypass permissions on", "? for shortcuts")
    )
    res = _spawn(launch, "--readonly")
    assert res.returncode == 0, res.stderr


def test_no_witness_in_time_fails_the_launch(tmp_path: Path) -> None:
    launch = Launch(tmp_path)
    launch.show("")
    started = time.monotonic()
    res = _spawn(launch, "--", BRIEF, HAPAX_CLAUDE_READY_TIMEOUT="1")
    assert res.returncode == 21, res.stderr
    assert "readiness_timeout" in res.stderr
    assert time.monotonic() - started < 20, "the wait must be bounded"


def test_a_dead_pane_fails_the_launch(tmp_path: Path) -> None:
    launch = Launch(tmp_path)
    launch.show("claude: error: unknown option '--bogus'\n")
    res = _spawn(launch, "--", BRIEF, FAKE_PANE_DEAD="1")
    assert res.returncode == 22, res.stderr
    assert "unknown option" in res.stderr


def test_a_session_that_vanished_fails_the_launch(tmp_path: Path) -> None:
    launch = Launch(tmp_path)
    (launch.state / "gone").write_text("")
    res = _spawn(launch, "--", BRIEF)
    assert res.returncode == 22, res.stderr


def test_the_witness_is_off_only_when_asked_and_says_so(tmp_path: Path) -> None:
    launch = Launch(tmp_path)
    launch.show(TRUST_DIALOG)
    res = _spawn(launch, "--", BRIEF, HAPAX_CLAUDE_READY_TIMEOUT="0")
    assert res.returncode == 0
    assert "UNWITNESSED" in res.stderr


@pytest.mark.parametrize("bad", ["-1", "soon", "1.5"])
def test_an_invalid_timeout_is_refused(tmp_path: Path, bad: str) -> None:
    launch = Launch(tmp_path)
    res = _spawn(launch, HAPAX_CLAUDE_READY_TIMEOUT=bad)
    assert res.returncode == 2
    assert not launch.tmux_calls()


def test_result_json_reports_a_witnessed_launch(tmp_path: Path) -> None:
    launch = Launch(tmp_path)
    launch.show(f"❯ {BRIEF}\n{REPL_FOOTER}")
    out = tmp_path / "result.json"
    res = _spawn(launch, "--result-json", str(out), "--", BRIEF, FAKE_TRANSCRIPT="user")
    assert res.returncode == 0, res.stderr
    result = json.loads(out.read_text())
    assert result["outcome"] == "ready"
    assert result["exit_code"] == 0
    assert result["tmux_session"] == "hapax-claude-dev9"
    assert result["readiness"]["witnessed"] is True
    assert result["readiness"]["evidence"] == "transcript_user_record"
    assert result["readiness"]["at"]
    assert result["brief_sent"] is True and result["brief_delivered"] is True
    assert result["workspace_trust"] == "trusted"
    harness = result["harness_session_id"]
    slug = "".join(c if c.isalnum() else "-" for c in str(launch.work.resolve()))
    trace = launch.home / ".claude" / "projects" / slug / f"{harness}.jsonl"
    assert result["trace_path"] == str(trace)
    assert trace.is_file(), "trace_path must name the transcript the lane actually writes"
    assert f"--session-id {harness}" in launch.runner().replace("\\", "")


def test_result_json_reports_a_blocked_launch(tmp_path: Path) -> None:
    launch = Launch(tmp_path)
    launch.show(TRUST_DIALOG)
    out = tmp_path / "result.json"
    res = _spawn(launch, "--result-json", str(out), "--", BRIEF)
    assert res.returncode == 20
    result = json.loads(out.read_text())
    assert result["outcome"] == "modal_blocked"
    assert result["modal"] == "trust"
    assert result["readiness"] == {"witnessed": False, "at": None, "evidence": None}
    assert result["brief_delivered"] is False


def test_a_resumed_launch_does_not_pin_the_harness_session(tmp_path: Path) -> None:
    launch = Launch(tmp_path)
    launch.show(REPL_FOOTER)
    assert _spawn(launch, "--readonly", "--continue").returncode == 0
    assert "--session-id" not in launch.runner()


def test_new_session_failure_is_reported_as_launch_failed(tmp_path: Path) -> None:
    launch = Launch(tmp_path)
    out = tmp_path / "result.json"
    res = _spawn(launch, "--result-json", str(out), FAKE_TMUX_NEW_SESSION_RC="7")
    assert res.returncode == 7
    assert json.loads(out.read_text())["outcome"] == "launch_failed"


# ── Inherited identity ──────────────────────────────────────────────────────


def test_a_parents_dispatch_task_is_never_claimed(tmp_path: Path) -> None:
    """The 19:15Z defect: a seat-launched dev lane claimed the seat's charter."""
    launch = Launch(tmp_path)
    launch.show(REPL_FOOTER)
    res = launch.run("--role", "dev9", "--terminal", "tmux", **PARENT_IDENTITY)
    assert res.returncode == 0, res.stderr
    assert launch.cc_claim_calls() == [], "the parent's task was claimed for the child"
    runner = launch.runner()
    assert "coordinator-seat-charter-20260924" not in runner.split("unset ", 1)[1]
    assert "ignoring inherited HAPAX_METHODOLOGY_DISPATCH_TASK" in res.stderr


def test_an_inherited_task_does_not_satisfy_a_greek_lanes_binding(tmp_path: Path) -> None:
    launch = Launch(tmp_path)
    res = launch.run("--role", "delta", "--terminal", "tmux", **PARENT_IDENTITY)
    assert res.returncode == 13, res.stderr
    assert launch.cc_claim_calls() == []


def test_an_explicit_task_is_claimed_and_exported(tmp_path: Path) -> None:
    launch = Launch(tmp_path)
    launch.show(REPL_FOOTER)
    res = launch.run(
        "--role", "dev9", "--terminal", "tmux", "--task", "child-task-x", **PARENT_IDENTITY
    )
    assert res.returncode == 0, res.stderr
    assert launch.cc_claim_calls() == ["child-task-x"]
    assert "export HAPAX_METHODOLOGY_DISPATCH_TASK=child-task-x" in launch.runner()


def test_the_runner_scrubs_the_parent_identity_and_mints_a_session(tmp_path: Path) -> None:
    """A pane's environment comes from the tmux server, not the launcher, so the
    runner itself must unset what a parent could have left there."""
    launch = Launch(tmp_path)
    launch.show(REPL_FOOTER)
    assert launch.run("--role", "dev9", "--terminal", "tmux", **PARENT_IDENTITY).returncode == 0
    runner = launch.runner()
    unset_line = next(line for line in runner.splitlines() if line.startswith("unset "))
    for var in (
        "HAPAX_METHODOLOGY_DISPATCH_TASK",
        "HAPAX_SESSION_ID",
        "CLAUDECODE",
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_CODE_MESSAGING_TOKEN",
    ):
        assert var in unset_line.split(), var
    assert runner.index("unset ") < runner.index("export HAPAX_SESSION_ID=")
    assert PARENT_IDENTITY["HAPAX_SESSION_ID"] not in runner
    assert "export HAPAX_AGENT_NAME=dev9" in runner


def test_a_spawn_without_a_role_is_refused_even_when_the_parent_has_one(tmp_path: Path) -> None:
    launch = Launch(tmp_path)
    res = launch.run("--terminal", "tmux", **PARENT_IDENTITY)
    assert res.returncode == 2
    assert "explicit --role" in res.stderr
    assert not launch.tmux_calls()


def test_an_inplace_launch_execs_claude_without_the_parent_identity(tmp_path: Path) -> None:
    launch = Launch(tmp_path)
    res = launch.run("--role", "dev9", "--terminal", "none", **PARENT_IDENTITY)
    assert res.returncode == 0, res.stderr
    child = dict(
        line.split("=", 1) for line in launch.claude_env.read_text().splitlines() if "=" in line
    )
    for var in ("HAPAX_METHODOLOGY_DISPATCH_TASK", "CLAUDECODE", "CLAUDE_CODE_SESSION_ID"):
        assert var not in child, var
    assert child["HAPAX_SESSION_ID"] != PARENT_IDENTITY["HAPAX_SESSION_ID"]
    assert child["HAPAX_AGENT_NAME"] == "dev9"


# ── Real tmux, private server ───────────────────────────────────────────────
#
# tmux picks its server from $TMUX before TMUX_TMPDIR. The first version of these
# tests set only TMUX_TMPDIR, and its teardown ran `tmux kill-server` with the
# suite's own environment. The suite was running inside an estate pane, so that
# kill took down the estate's server with every lane and the coordinator seat
# (2026-09-24T19:33:00Z). Three things now keep a test off any server it did not
# start: the autouse fixture above removes TMUX/TMUX_PANE and sets a private
# TMUX_TMPDIR for the whole module; every real tmux call names its socket with -S;
# and every call drops TMUX/TMUX_PANE from its environment.


def _without_ambient_tmux(env: Mapping[str, str]) -> dict[str, str]:
    return {k: v for k, v in env.items() if k not in ("TMUX", "TMUX_PANE")}


class PrivateTmux:
    """A tmux server on its own socket, and the only way these tests reach real tmux."""

    def __init__(self, root: Path) -> None:
        real = shutil.which("tmux")
        if real is None:
            pytest.skip("tmux not installed")
        root.mkdir(parents=True, exist_ok=True)
        self.real = real
        self.sock = root / "s"
        # What the launcher finds as `tmux` on PATH: the same pinned socket.
        self.wrapper = root / "tmux"
        _executable(
            self.wrapper,
            "#!/usr/bin/env bash\n"
            "unset TMUX TMUX_PANE\n"
            f'exec {shlex.quote(real)} -f /dev/null -S {shlex.quote(str(self.sock))} "$@"\n',
        )

    def __call__(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.real, "-S", str(self.sock), *args],
            env=_without_ambient_tmux(os.environ),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def kill(self) -> None:
        self("kill-server")


@pytest.fixture
def private_tmux(tmp_path: Path):
    server = PrivateTmux(tmp_path / "tm")
    yield server
    server.kill()


READY_CLAUDE = (
    "#!/usr/bin/env bash\n"
    'for a in "$@"; do last="$a"; done\n'
    'printf "❯ %s\\n\\n" "$last"\n'
    "cat <<'EOF'\n" + REPL_FOOTER + "EOF\n"
    'FAKE_TRANSCRIPT=user "$(dirname "$0")/claude-recorder" "$@"\n'
    "sleep 60\n"
)


def _real_tmux_launch(tmp_path: Path, server: PrivateTmux, claude_body: str, *args: str):
    launch = Launch(tmp_path)
    (launch.bin / "tmux").unlink()
    (launch.bin / "tmux").symlink_to(server.wrapper)
    _executable(launch.bin / "claude", claude_body)
    return launch, launch.run(
        "--role", "dev9", "--terminal", "tmux", *args, HAPAX_CLAUDE_READY_TIMEOUT="10"
    )


def test_this_module_cannot_address_the_suites_tmux_server(tmp_path: Path) -> None:
    assert "TMUX" not in os.environ and "TMUX_PANE" not in os.environ
    assert Path(os.environ["TMUX_TMPDIR"]).is_relative_to(tmp_path)


def test_tmux_helpers_never_address_the_ambient_server(tmp_path: Path, monkeypatch) -> None:
    """The unsafe case: run as if inside a pane of another server (the sentinel),
    launch a lane, tear it down, and require the sentinel to be untouched."""
    real = shutil.which("tmux")
    if real is None:
        pytest.skip("tmux not installed")
    sentinel_sock = tmp_path / "sn"

    def sentinel(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [real, "-f", "/dev/null", "-S", str(sentinel_sock), *args],
            env=_without_ambient_tmux(os.environ),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    started = sentinel("new-session", "-d", "-s", "sentinel", "sleep 300")
    assert started.returncode == 0, started.stderr
    try:
        pid = sentinel("display-message", "-p", "-t", "=sentinel:", "#{pid}").stdout.strip()
        monkeypatch.setenv("TMUX", f"{sentinel_sock},{pid},0")
        monkeypatch.setenv("TMUX_PANE", "%0")
        server = PrivateTmux(tmp_path / "tm")
        try:
            _launch, res = _real_tmux_launch(tmp_path, server, READY_CLAUDE, "--", BRIEF)
            assert res.returncode == 0, res.stderr
        finally:
            server.kill()
        assert sentinel("has-session", "-t", "=sentinel").returncode == 0, (
            "a helper's kill-server reached the ambient ($TMUX) server"
        )
        assert sentinel("has-session", "-t", "=hapax-claude-dev9").returncode != 0, (
            "the lane was spawned on the ambient ($TMUX) server"
        )
    finally:
        sentinel("kill-server")


def test_real_tmux_trust_dialog_is_witnessed_as_blocked(tmp_path: Path, private_tmux) -> None:
    body = "#!/usr/bin/env bash\ncat <<'EOF'\n" + TRUST_DIALOG + "EOF\nsleep 60\n"
    _launch, res = _real_tmux_launch(tmp_path, private_tmux, body, "--", BRIEF)
    assert res.returncode == 20, res.stderr
    assert "Yes, I trust this folder" in res.stderr


def test_real_tmux_rendered_brief_is_witnessed_as_ready(tmp_path: Path, private_tmux) -> None:
    _launch, res = _real_tmux_launch(tmp_path, private_tmux, READY_CLAUDE, "--", BRIEF)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "hapax-claude-dev9"


def test_real_tmux_early_death_is_witnessed(tmp_path: Path, private_tmux) -> None:
    body = "#!/usr/bin/env bash\necho 'claude: fatal: bad flag' >&2\nexit 3\n"
    _launch, res = _real_tmux_launch(tmp_path, private_tmux, body, "--", BRIEF)
    assert res.returncode == 22, res.stderr
