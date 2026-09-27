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
import re
import resource
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
  display-message)
    case "$*" in
      *pane_pid*) printf '%s\n' "${FAKE_PANE_PID:-}" ;;
      *) printf '%s\n' "${FAKE_PANE_DEAD:-0}" ;;
    esac ;;
  capture-pane) [ -n "${FAKE_PANE_FILE:-}" ] && cat "$FAKE_PANE_FILE" ;;
  *) exit 0 ;;
esac
"""

# Claude Code 2.1.281's project-directory encoder (uC/k in the binary):
#   k(e) = e.replace(/[^a-zA-Z0-9]/g, "-"), cut to 200 plus "-" + a hash when longer.
# The hash is internal, so the fixture writes a stand-in suffix. The launcher must
# find the transcript however the directory is named: by pinned session id, or by
# this encoding for a resumed session. test_the_fixture_encoder_matches_real_claude_dirs
# pins this against directory names Claude wrote on the dev host.
CLAUDE_SLUG_PY = (
    'import os, re; s = re.sub(r"[^a-zA-Z0-9]", "-", os.getcwd()); '
    'print(s if len(s) <= 200 else s[:200] + "-fixturehash")'
)


def claude_project_slug(path: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]", "-", path)
    return slug if len(slug) <= 200 else slug[:200] + "-fixturehash"


# Records its argv and the identity part of its environment. With FAKE_TRANSCRIPT set
# it also writes a transcript record where Claude Code would, to
# $HOME/.claude/projects/<claude_project_slug(physical cwd)>/<session>.jsonl:
#   user   the brief (its last argument) as a user record stamped now
#   stale  the same record stamped an hour before the launch
#   meta   the same record marked isMeta
#   other  a user record stamped now whose text is not the brief
FAKE_CLAUDE = (
    r"""#!/usr/bin/env bash
printf '%s\n' "$@" > "$FAKE_CLAUDE_ARGV"
env | grep -E '^(HAPAX_|CLAUDE)' | sort > "$FAKE_CLAUDE_ENV"
ulimit -Sn > "$FAKE_CLAUDE_NOFILE"
[ -n "${FAKE_TRANSCRIPT:-}" ] || exit 0
sid="resumed"; prev=""; last=""
for a in "$@"; do [ "$prev" = --session-id ] && sid="$a"; prev="$a"; last="$a"; done
dir="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects/$(python3 -c '"""
    + CLAUDE_SLUG_PY
    + r"""')"
dir="${FAKE_TRANSCRIPT_DIR:-$dir}"
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
)

CC_CLAIM_RECORDER = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$(dirname "$0")/../cc-claim-calls.txt"
"""


def _nofile_setter(limits: tuple[int, int] | None):
    """A preexec_fn that starts the child at (soft, hard) RLIMIT_NOFILE."""
    if limits is None:
        return None
    return lambda: resource.setrlimit(resource.RLIMIT_NOFILE, limits)


def _hard_nofile() -> int:
    return resource.getrlimit(resource.RLIMIT_NOFILE)[1]


def _executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def lane_work(tmp_path: Path) -> Path:
    return tmp_path / "home" / "projects" / "lane-work"


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

    def __init__(
        self, tmp_path: Path, *, config: dict | None | str = "seed", work: Path | None = None
    ) -> None:
        self.tmp = tmp_path
        self.home = tmp_path / "home"
        # A lane folder under a declared trust root ($HOME/projects) unless a test says otherwise.
        self.work = work if work is not None else lane_work(tmp_path)
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
        self.nofile = tmp_path / "claude-nofile.txt"
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
                "XDG_CONFIG_HOME": str(self.home / ".config"),
                "PATH": f"{self.bin}:{env['PATH']}",
                "HAPAX_COUNCIL_DIR": str(REPO_ROOT),
                "HAPAX_SESSION_PROTECTION_FILE": str(tmp_path / "no-protection.md"),
                "FAKE_TMUX_LOG": str(self.tmux_log),
                "FAKE_TMUX_STATE": str(self.state),
                "FAKE_PANE_FILE": str(self.pane),
                "FAKE_CLAUDE_ARGV": str(self.argv),
                "FAKE_CLAUDE_ENV": str(self.claude_env),
                "FAKE_CLAUDE_NOFILE": str(self.nofile),
                "HAPAX_CLAUDE_READY_TIMEOUT": "3",
            }
        )
        self.env = env

    def show(self, text: str) -> None:
        self.pane.write_text(text, encoding="utf-8")

    def run(
        self, *args: str, nofile: tuple[int, int] | None = None, **env: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(SCRIPT), "--cd", str(self.work), *args],
            env={**self.env, **env},
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            preexec_fn=_nofile_setter(nofile),
        )

    def child_nofile(self) -> int:
        return int(self.nofile.read_text().strip())

    def result_path(self, name: str = "result.json") -> Path:
        """Where --result-json may write: the declared launch-results directory."""
        return self.tmp / "cache" / "hapax" / "launch-results" / name

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
    key = str(lane_work(tmp_path))
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
    seed["projects"][str(lane_work(tmp_path))] = {"hasTrustDialogAccepted": True}
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
            f"❯ {BRIEF}\n\n  Fable 5.1's safeguards flagged this message [cyber]\n"
            "  ❯ 1. Switch to Opus 4.8\n    2. Edit prompt and retry\n",
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


@pytest.mark.parametrize(
    ("claude_args", "carries_brief"),
    [
        pytest.param(["--allowedTools", "Bash(git status) Read"], False, id="spaced-tool-list"),
        pytest.param(["--allowedTools", "Bash", "Read"], False, id="variadic-takes-all"),
        pytest.param(["--agents", '{"r": {"description": "a b"}}'], False, id="agents-json"),
        pytest.param(["--debug", "api hooks"], False, id="optional-value"),
        pytest.param(["--model", "claude-opus-5-5", "--effort", "high"], False, id="plain-values"),
        pytest.param(['--settings={"a": "b c"}'], False, id="inline-value"),
        pytest.param(["--model", "m", "--effort", "high", BRIEF], True, id="seat-launch-shape"),
        pytest.param(
            ["--allowedTools", "Bash", "--", BRIEF], True, id="brief-after-end-of-options"
        ),
        pytest.param(["hi"], True, id="one-word-prompt"),
    ],
)
def test_only_claudes_positional_prompt_is_the_brief(
    tmp_path: Path, claude_args: list[str], carries_brief: bool
) -> None:
    """An option's value read as the brief would wait for a transcript record that
    never comes, and fail a healthy brief-free lane. Parsed the way claude's option
    parser reads the argv (claude --help, 2.1.281)."""
    launch = Launch(tmp_path)
    launch.show(REPL_FOOTER)  # idle REPL, nothing in the transcript
    res = _spawn(launch, "--readonly", "--", *claude_args, HAPAX_CLAUDE_READY_TIMEOUT="1")
    assert res.returncode == (21 if carries_brief else 0), res.stderr


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
    out = launch.result_path()
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
    out = launch.result_path()
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
    out = launch.result_path()
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


# ── Review round 1 (PR #4729): trust scope and lock ────────────────────────


def test_a_folder_outside_the_declared_roots_is_refused_loudly(tmp_path: Path) -> None:
    """Muse C1: the dialog guards project-local hooks/MCP/settings, so only lane
    folders are pre-accepted, never an arbitrary caller-supplied --cd."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    launch = Launch(tmp_path, work=elsewhere)
    raw = launch.config_path.read_bytes()
    res = _trust_launch(launch)
    assert res.returncode == 0, res.stderr  # the launch goes on; Claude's own dialog asks
    assert launch.config_path.read_bytes() == raw
    assert "REFUSING to pre-accept workspace trust" in res.stderr
    assert "claude-trust-roots" in res.stderr


def test_a_root_listed_in_the_roots_file_is_honoured(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "lane").mkdir(parents=True)
    roots = tmp_path / "home" / ".config" / "hapax" / "claude-trust-roots"
    roots.parent.mkdir(parents=True)
    roots.write_text(f"# extra lane roots\n{elsewhere}  # trailing comment\nrelative/ignored\n")
    launch = Launch(tmp_path, work=elsewhere / "lane")
    assert _trust_launch(launch).returncode == 0
    assert launch.config()["projects"][str(elsewhere / "lane")]["hasTrustDialogAccepted"] is True


def test_a_symlink_out_of_a_root_is_refused(tmp_path: Path) -> None:
    """The root test runs on the physical path, so a link inside a root cannot
    carry trust to a folder outside it."""
    outside = tmp_path / "outside"
    outside.mkdir()
    launch = Launch(tmp_path)
    link = launch.home / "projects" / "escape"
    link.symlink_to(outside)
    raw = launch.config_path.read_bytes()
    res = subprocess.run(
        [str(SCRIPT), "--cd", str(link), "--role", "dev", "--terminal", "none", "--readonly"],
        env=launch.env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    assert launch.config_path.read_bytes() == raw
    assert "REFUSING" in res.stderr


def test_the_trust_write_waits_for_claudes_config_lock(tmp_path: Path) -> None:
    """Muse M7 / qwen TOCTOU: Claude Code 2.1.281 writes its config under
    proper-lockfile's mkdir lock "<config>.lock". The trust write takes the same
    lock, so a Claude write made while the lock is held is never lost."""
    launch = Launch(tmp_path)
    lock = Path(str(launch.config_path) + ".lock")
    lock.mkdir()
    proc = subprocess.Popen(
        [
            str(SCRIPT),
            "--cd",
            str(launch.work),
            "--role",
            "dev",
            "--terminal",
            "none",
            "--readonly",
        ],
        env=launch.env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        time.sleep(1.5)
        # The holder (standing in for a Claude process) writes while holding the lock.
        held = launch.config()
        assert str(launch.work) not in held["projects"], "the trust write did not wait for the lock"
        held["concurrentClaudeWrite"] = 1
        launch.config_path.write_text(json.dumps(held, indent=2))
        lock.rmdir()
        _out, err = proc.communicate(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 0, err
    after = launch.config()
    assert after["concurrentClaudeWrite"] == 1, "the holder's write was lost"
    assert after["projects"][str(launch.work)]["hasTrustDialogAccepted"] is True
    assert not lock.exists(), "the launcher left the lock behind"


def test_a_stale_config_lock_is_broken_like_proper_lockfile_does(tmp_path: Path) -> None:
    launch = Launch(tmp_path)
    lock = Path(str(launch.config_path) + ".lock")
    lock.mkdir()
    old = time.time() - 60
    os.utime(lock, (old, old))
    started = time.monotonic()
    assert _trust_launch(launch).returncode == 0
    assert time.monotonic() - started < 10
    assert launch.config()["projects"][str(launch.work)]["hasTrustDialogAccepted"] is True
    assert not lock.exists()


def test_credentials_are_never_opened(tmp_path: Path) -> None:
    """m8: observed, not read from the source. The credentials file is a FIFO, so any
    open of it (read or write) blocks and the launch would time out."""
    launch = Launch(tmp_path)
    launch.credentials.unlink()
    os.mkfifo(launch.credentials)
    res = subprocess.run(
        [
            str(SCRIPT),
            "--cd",
            str(launch.work),
            "--role",
            "dev",
            "--terminal",
            "none",
            "--readonly",
        ],
        env=launch.env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    assert launch.config()["projects"][str(launch.work)]["hasTrustDialogAccepted"] is True


# ── Review round 1: --result-json, timeout, runner, foot ────────────────────


def test_result_json_outside_its_directory_is_refused(tmp_path: Path) -> None:
    """qwen critical: no arbitrary file write through --result-json."""
    launch = Launch(tmp_path)
    target = tmp_path / "home" / ".bashrc"
    res = _spawn(launch, "--result-json", str(target))
    assert res.returncode == 2
    assert not target.exists()
    assert not launch.tmux_calls(), "nothing may be launched after the refusal"
    traversal = launch.result_path("../../escaped.json")
    assert _spawn(launch, "--result-json", str(traversal)).returncode == 2
    assert not (tmp_path / "cache" / "escaped.json").exists()


def test_result_json_through_a_symlink_is_refused(tmp_path: Path) -> None:
    launch = Launch(tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    link = launch.result_path("link.json")
    link.parent.mkdir(parents=True)
    link.symlink_to(victim)
    assert _spawn(launch, "--result-json", str(link)).returncode == 2
    assert victim.read_text() == "keep me"


def test_result_json_creates_its_subdirectory(tmp_path: Path) -> None:
    launch = Launch(tmp_path)
    launch.show(REPL_FOOTER)
    out = launch.result_path("a2/succession/r1.json")
    assert _spawn(launch, "--readonly", "--result-json", str(out)).returncode == 0
    assert json.loads(out.read_text())["outcome"] == "ready"


def test_result_json_needs_a_witness_and_a_value(tmp_path: Path) -> None:
    """Muse M6 and m1."""
    launch = Launch(tmp_path)
    out = launch.result_path()
    res = launch.run("--role", "dev9", "--terminal", "none", "--result-json", str(out))
    assert res.returncode == 2 and "needs --terminal tmux|foot" in res.stderr
    assert launch.run("--role", "dev9", "--terminal", "tmux", "--result-json").returncode == 2
    assert launch.run("--role", "dev9", "--terminal", "tmux", "--result-json=").returncode == 2


@pytest.mark.parametrize(
    ("value", "rc"), [("08", 0), ("09", 0), ("3600", 0), ("3601", 2), ("99999", 2)]
)
def test_the_timeout_is_base_ten_and_bounded(tmp_path: Path, value: str, rc: int) -> None:
    """Muse M4: "08" crashed the arithmetic under set -e; qwen: no upper bound."""
    launch = Launch(tmp_path)
    launch.show(REPL_FOOTER)
    res = _spawn(launch, "--readonly", HAPAX_CLAUDE_READY_TIMEOUT=value)
    assert res.returncode == rc, res.stderr


def test_two_launches_in_one_second_get_their_own_runners(tmp_path: Path) -> None:
    """Muse M8: the runner name was per second, so a second launch in that second
    rewrote the script the first pane was executing."""
    launch = Launch(tmp_path)
    launch.show(REPL_FOOTER)
    _executable(
        launch.bin / "date",
        '#!/usr/bin/env bash\ncase "$*" in *%H%M%S*) echo 20260924T200000Z ;; *) exec /usr/bin/date "$@" ;; esac\n',
    )
    for _ in range(2):
        assert _spawn(launch, "--readonly", "--force").returncode == 0
    runners = list((tmp_path / "cache" / "hapax" / "claude-spawns").glob("run-*.sh"))
    assert len(runners) == 2, runners


@pytest.mark.parametrize(
    ("pane", "rc", "outcome"),
    [
        pytest.param(TRUST_DIALOG, 20, "modal_blocked", id="stuck-at-a-dialog"),
        pytest.param(REPL_FOOTER, 0, "ready_existing_session", id="idle"),
    ],
)
def test_foot_onto_an_existing_session_is_witnessed(
    tmp_path: Path, pane: str, rc: int, outcome: str
) -> None:
    """Muse M3: --force onto a live session attached a window and exited 0 with no
    result, whatever the pane showed."""
    launch = Launch(tmp_path)
    _executable(launch.bin / "footclient", "#!/usr/bin/env bash\nexit 0\n")
    (launch.state / "session").write_text("")
    launch.show(pane)
    out = launch.result_path()
    res = launch.run(
        "--role", "dev9", "--terminal", "foot", "--force", "--readonly", "--result-json", str(out)
    )
    assert res.returncode == rc, res.stderr
    assert json.loads(out.read_text())["outcome"] == outcome
    assert not any(b[:1] == ["new-session"] for b in launch.tmux_calls())


@pytest.mark.parametrize(
    "pane",
    [
        pytest.param(REPL_FOOTER, id="idle"),
        pytest.param(f"❯ {BRIEF}\n{REPL_FOOTER}", id="brief-on-screen"),
    ],
)
def test_foot_onto_an_existing_session_never_drops_the_brief(tmp_path: Path, pane: str) -> None:
    """Round 2, N1: a launch delivers its brief as claude's argv, and an existing
    session's claude is already running. So the brief cannot arrive: fail with 23,
    and never report ready over an undelivered brief, whatever the pane shows."""
    launch = Launch(tmp_path)
    _executable(launch.bin / "footclient", "#!/usr/bin/env bash\nexit 0\n")
    (launch.state / "session").write_text("")
    launch.show(pane)
    out = launch.result_path()
    res = launch.run(
        "--role", "dev9", "--terminal", "foot", "--force", "--result-json", str(out),
        "--", BRIEF, FAKE_TRANSCRIPT="user",
    )  # fmt: skip
    assert res.returncode == 23, res.stderr
    assert "NOT delivered" in res.stderr and "hapax-claude-send" in res.stderr
    result = json.loads(out.read_text())
    assert result["outcome"] == "brief_not_delivered"
    assert result["brief_sent"] is True and result["brief_delivered"] is False
    assert result["readiness"]["witnessed"] is False


def test_the_witness_timeout_is_never_inherited(tmp_path: Path) -> None:
    """Round 2, N2: the timeout configures one launch. A parent that exported 0 must
    not unwitness the launches its lane makes later."""
    launch = Launch(tmp_path)
    res = launch.run("--role", "dev9", "--terminal", "none", HAPAX_CLAUDE_READY_TIMEOUT="0")
    assert res.returncode == 0, res.stderr
    assert "HAPAX_CLAUDE_READY_TIMEOUT" not in launch.claude_env.read_text()


def test_the_runner_drops_an_inherited_witness_timeout(tmp_path: Path) -> None:
    """A pane gets the tmux server's environment, which may carry the export."""
    launch = Launch(tmp_path)
    launch.show(REPL_FOOTER)
    assert _spawn(launch, "--readonly").returncode == 0
    (runner,) = (tmp_path / "cache" / "hapax" / "claude-spawns").glob("run-*.sh")
    subprocess.run(
        [str(runner)],
        env={**launch.env, "HAPAX_CLAUDE_READY_TIMEOUT": "0"},
        capture_output=True,
        timeout=60,
        check=True,
    )
    assert "HAPAX_CLAUDE_READY_TIMEOUT" not in launch.claude_env.read_text()


# ── Review round 1: witness matching ────────────────────────────────────────


@pytest.mark.parametrize(
    "noise",
    [
        pytest.param(
            "  Fable 5.1's safeguards stopped the response above · continuing once with that noted",
            id="self-continuing-notice",
        ),
        pytest.param(
            "● The claim gate is a safeguard, not a boundary; reading it now.", id="lane-output"
        ),
    ],
)
def test_safeguard_words_that_do_not_block_are_not_a_modal(tmp_path: Path, noise: str) -> None:
    """qwen #3 / Muse M9: only the pausing modal blocks."""
    launch = Launch(tmp_path)
    launch.show(f"❯ {BRIEF}\n\n{noise}\n{REPL_FOOTER}")
    res = _spawn(launch, "--", BRIEF, FAKE_TRANSCRIPT="user")
    assert res.returncode == 0, res.stderr


def test_a_brief_sharing_a_prefix_with_another_is_not_confused(tmp_path: Path) -> None:
    """m11: a resumed lane's transcript holding a sibling brief with the same opening
    is not this brief's delivery."""
    shared = "You are role dev9, recruited by the coordinator seat. Read your task row in full "
    sibling, mine = shared + "and review PR 4728.", shared + "and review PR 4729."
    launch = Launch(tmp_path)
    tdir = launch.home / ".claude" / "projects" / claude_project_slug(str(launch.work))
    tdir.mkdir(parents=True)
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() + 5))
    (tdir / "sibling.jsonl").write_text(
        json.dumps({"type": "user", "timestamp": now, "message": {"content": sibling}}) + "\n"
    )
    launch.show(f"❯ {mine}\n{REPL_FOOTER}")
    res = _spawn(launch, "--continue", "--", mine, HAPAX_CLAUDE_READY_TIMEOUT="1")
    assert res.returncode == 21, res.stderr


# ── Review round 1: where the transcript lives (Muse M1) ────────────────────


@pytest.mark.parametrize(
    ("cwd", "real_dir"),
    [
        # Directory names Claude Code 2.1.281 wrote on the dev host (the newest of each
        # pair; older versions kept '.', '_' and '@', and those directories remain).
        (
            "/home/hapax/Documents/Personal/30-areas/hapax",
            "-home-hapax-Documents-Personal-30-areas-hapax",
        ),
        ("/home/hapax/.cache/hapax", "-home-hapax--cache-hapax"),
        (
            "/home/hapax/.npm-global/lib/node_modules/@anthropic-ai/claude-code",
            "-home-hapax--npm-global-lib-node-modules--anthropic-ai-claude-code",
        ),
    ],
)
def test_the_fixture_encoder_matches_real_claude_dirs(cwd: str, real_dir: str) -> None:
    assert claude_project_slug(cwd) == real_dir


def test_a_pinned_session_is_found_whatever_its_directory_is_called(tmp_path: Path) -> None:
    """The launcher finds <session>.jsonl under any project directory, so a slug
    encoding change (this host holds two) cannot hide a delivered brief."""
    launch = Launch(tmp_path)
    legacy = launch.home / ".claude" / "projects" / "-home-legacy.encoding_kept@here"
    launch.show(f"❯ {BRIEF}\n{REPL_FOOTER}")
    out = launch.result_path()
    res = _spawn(
        launch,
        "--result-json",
        str(out),
        "--",
        BRIEF,
        FAKE_TRANSCRIPT="user",
        FAKE_TRANSCRIPT_DIR=str(legacy),
    )
    assert res.returncode == 0, res.stderr
    result = json.loads(out.read_text())
    assert result["trace_path"] == str(legacy / f"{result['harness_session_id']}.jsonl")


@pytest.mark.parametrize("resume", [False, True], ids=["pinned", "resumed"])
def test_dotted_and_long_workdirs_are_found(tmp_path: Path, resume: bool) -> None:
    """A slug over 200 characters is cut and hashed by Claude; '.', '_', '@' become '-'."""
    deep = lane_work(tmp_path) / "lane.work_v2@x" / ("very-long-segment-" * 12)
    launch = Launch(tmp_path, work=deep)
    assert len(claude_project_slug(str(deep))) > 200
    launch.show(f"❯ {BRIEF}\n{REPL_FOOTER}")
    extra = ["--continue"] if resume else []
    res = _spawn(launch, *extra, "--", BRIEF, FAKE_TRANSCRIPT="user")
    assert res.returncode == 0, res.stderr


# ── Review round 1: callers (Muse M2) ───────────────────────────────────────


HAPAX_DEV = REPO_ROOT / "scripts" / "hapax-dev"


def _hapax_dev(
    tmp_path: Path, launcher_rc: int, *args: str
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """hapax-dev with a stub hapax-claude that brings a session up and exits
    `launcher_rc`, and a stub tmux that records the attach."""
    bin_dir = tmp_path / "dev-bin"
    marker = tmp_path / "session-up"
    attached = tmp_path / "attached.txt"
    _executable(
        bin_dir / "hapax-claude",
        f'#!/usr/bin/env bash\n: > "{marker}"\necho "pane shows a dialog" >&2\nexit {launcher_rc}\n',
    )
    _executable(
        bin_dir / "tmux",
        "#!/usr/bin/env bash\n"
        f'case "$1" in\n  has-session) [ -e "{marker}" ] ;;\n'
        f'  attach|attach-session) printf "%s\\n" "$*" > "{attached}" ;;\n'
        "  *) exit 0 ;;\nesac\n",
    )
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "HAPAX_DEV_CLAIM_DIR": str(tmp_path / "claims"),
        "HAPAX_DEV_WORKDIR": str(work),
        "HAPAX_DEV_TMUX": str(bin_dir / "tmux"),
        "HAPAX_DEV_CLAUDE_BIN": str(bin_dir / "hapax-claude"),
    }
    res = subprocess.run(
        ["bash", str(HAPAX_DEV), "claude", "dev", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return res, attached


@pytest.mark.parametrize("rc", [20, 21])
def test_hapax_dev_attaches_the_operator_to_a_lane_that_is_not_ready(
    tmp_path: Path, rc: int
) -> None:
    """Attach mode has the operator at the pane, which is where a dialog is answered."""
    res, attached = _hapax_dev(tmp_path, rc)
    assert res.returncode == 0, res.stderr
    assert attached.read_text().split() == ["attach", "-t", "=hapax-claude-dev"]
    assert "not ready yet" in res.stderr


@pytest.mark.parametrize(("rc", "args"), [(20, ["--detach"]), (22, [])])
def test_hapax_dev_reports_what_nobody_can_answer(tmp_path: Path, rc: int, args: list[str]) -> None:
    res, attached = _hapax_dev(tmp_path, rc, *args)
    assert res.returncode == rc
    assert not attached.exists()


# ── Open-file limit ─────────────────────────────────────────────────────────
# Resumed codex/fugu lanes ran at soft nofile 1024, so the claim inspector hit EMFILE
# and their claims failed as claim_publication_inspection_failed (2026-09-24 20:05Z).
# The estate tmux server runs at soft 1024 too, and a pane inherits the server's limits.

NOFILE_TARGET = 65536


def test_an_inplace_launch_raises_a_low_soft_nofile(tmp_path: Path) -> None:
    launch = Launch(tmp_path)
    hard = _hard_nofile()
    res = launch.run("--role", "dev9", "--terminal", "none", "--readonly", nofile=(1024, hard))
    assert res.returncode == 0, res.stderr
    assert launch.child_nofile() == min(hard, NOFILE_TARGET)


def test_the_runner_raises_nofile_itself(tmp_path: Path) -> None:
    """Run the runner the way a pane of a soft-1024 tmux server would."""
    launch = Launch(tmp_path)
    launch.show(REPL_FOOTER)
    assert _spawn(launch, "--readonly").returncode == 0
    (runner,) = (tmp_path / "cache" / "hapax" / "claude-spawns").glob("run-*.sh")
    hard = _hard_nofile()
    subprocess.run(
        [str(runner)],
        env=launch.env,
        capture_output=True,
        timeout=60,
        check=True,
        preexec_fn=_nofile_setter((1024, hard)),
    )
    assert launch.child_nofile() == min(hard, NOFILE_TARGET)


def test_a_lower_hard_limit_caps_the_raise(tmp_path: Path) -> None:
    launch = Launch(tmp_path)
    res = launch.run("--role", "dev9", "--terminal", "none", "--readonly", nofile=(512, 2048))
    assert res.returncode == 0, res.stderr
    assert launch.child_nofile() == 2048


def test_a_higher_soft_limit_is_never_lowered(tmp_path: Path) -> None:
    hard = _hard_nofile()
    if hard != resource.RLIM_INFINITY and hard <= NOFILE_TARGET:
        pytest.skip(f"hard nofile {hard} leaves no room above {NOFILE_TARGET}")
    soft = 100_000 if hard == resource.RLIM_INFINITY else min(hard, 100_000)
    launch = Launch(tmp_path)
    res = launch.run("--role", "dev9", "--terminal", "none", "--readonly", nofile=(soft, hard))
    assert res.returncode == 0, res.stderr
    assert launch.child_nofile() == soft


def test_the_witness_records_the_lanes_soft_nofile(tmp_path: Path) -> None:
    """Read from /proc/<pane pid>/limits, i.e. what the lane really runs with."""
    lane = subprocess.Popen(["sleep", "30"], preexec_fn=_nofile_setter((4096, _hard_nofile())))
    try:
        launch = Launch(tmp_path)
        launch.show(REPL_FOOTER)
        out = launch.result_path()
        res = _spawn(launch, "--readonly", "--result-json", str(out), FAKE_PANE_PID=str(lane.pid))
        assert res.returncode == 0, res.stderr
        assert json.loads(out.read_text())["child_nofile_soft"] == 4096
        assert "soft nofile 4096" in res.stderr
    finally:
        lane.kill()
        lane.wait()


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
