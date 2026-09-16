"""Backup, streaming and reporting scripts read the FileStore, not pass.

These are services rather than lane spawns, but they fail the same way: the moment pass is
uninstalled a backup watchdog reports "cannot read restic password" and a stream never
starts. Assertions are on INVOCATIONS against comment- and docstring-stripped source, via
the shared helper.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.conftest import code_without_prose

REPO_ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash") or "/usr/bin/bash"

SHELL_SCRIPTS = (
    "hapax-backup-watchdog",
    "hapax-backup-gdrive-critical",
    "hapax-velocity-report",
    "mediamtx-start.sh",
    "hapax-vibe",
    "hapax-codex-headless",
)
PYTHON_SCRIPTS = ("reverb-inventory-sync",)
ALL_SCRIPTS = SHELL_SCRIPTS + PYTHON_SCRIPTS

FORBIDDEN = (
    "pass show",
    "pass ls",
    "pass insert",
    "gopass",
    "pass_first_line",
    "load_first_available_pass_secret",
    "PASSWORD_STORE_DIR",
    '"pass"',
    "'pass'",
)


def _code(name: str) -> str:
    text = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")
    language = "python" if text.lstrip().startswith("#!/usr/bin/env python") else "shell"
    return code_without_prose(text, language=language)


@pytest.mark.parametrize("name", ALL_SCRIPTS)
def test_no_pass_invocation_remains(name: str) -> None:
    code = _code(name)
    for forbidden in FORBIDDEN:
        assert forbidden not in code, f"{name}: {forbidden}"


@pytest.mark.parametrize("name", SHELL_SCRIPTS)
def test_the_shell_scripts_are_syntactically_valid(name: str) -> None:
    result = subprocess.run(
        [BASH, "-n", str(REPO_ROOT / "scripts" / name)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("name", ALL_SCRIPTS)
def test_diagnostics_name_an_action_that_will_still_work(name: str) -> None:
    code = _code(name).lower()
    for phrase in ("pass entry", "from pass", "check: pass"):
        assert phrase not in code, f"{name}: diagnostic still names pass ({phrase})"


class TestResticPasswordResolution:
    """The backup watchdogs must still tell an UNREADABLE password from an EMPTY one.

    A backup that runs with an empty repository password is worse than one that refuses:
    restic would either fail deep in the run or, worse, initialise something unintended.
    Both scripts branched on it before, and the migration must not flatten that.
    """

    @staticmethod
    def _cli(tmp_path: Path, body: str) -> Path:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        (bin_dir / "hapax-secret").write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
        (bin_dir / "hapax-secret").chmod(0o755)
        return bin_dir

    def _probe(self, tmp_path: Path, body: str, script: str):
        bin_dir = self._cli(tmp_path, body)
        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        return subprocess.run(
            [BASH, "-c", f'. "{REPO_ROOT}/scripts/lib/secret.sh"\n{script}'],
            capture_output=True,
            text=True,
            env=env,
            cwd=REPO_ROOT,
        )

    def test_a_present_password_resolves(self, tmp_path: Path) -> None:
        result = self._probe(
            tmp_path,
            'printf "restic-pw\\n"',
            'printf "%s" "$(hapax_secret_read backups/restic-password)"',
        )
        assert result.stdout == "restic-pw", result.stderr

    def test_an_empty_password_is_distinguishable_from_an_unreadable_one(
        self, tmp_path: Path
    ) -> None:
        empty = self._probe(
            tmp_path / "e",
            'printf "\\n"',
            'if value="$(hapax_secret_read x/y)"; then printf "READ:[%s]" "$value"; '
            'else printf "UNREADABLE"; fi',
        )
        unreadable = self._probe(
            tmp_path / "u",
            "exit 1",
            'if value="$(hapax_secret_read x/y)"; then printf "READ:[%s]" "$value"; '
            'else printf "UNREADABLE"; fi',
        )
        assert empty.stdout == "READ:[]", empty.stdout
        assert unreadable.stdout == "UNREADABLE", unreadable.stdout


class TestBackupWatchdogResticPassword:
    """`restic_password` in the watchdog must keep EMPTY and UNREADABLE distinct.

    A backup that runs with an empty repository password is worse than one that refuses.
    The previous test pinned only the shared helper, so a mutation collapsing the two inside
    the watchdog itself stayed green — the same gap that hid a real regression in
    `hapax-glmcp-claude`. This extracts the function and drives it.
    """

    SCRIPT = REPO_ROOT / "scripts" / "hapax-backup-watchdog"

    @staticmethod
    def _extract(function: str, text: str) -> str:
        """The named shell function's source, from `name() {` to the first column-0 `}`."""
        start = text.index(f"{function}() {{")
        end = text.index("\n}\n", start) + len("\n}\n")
        return text[start:end]

    def _run(self, tmp_path: Path, cli_body: str, probe: str):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        (bin_dir / "hapax-secret").write_text(
            f"#!/usr/bin/env bash\n{cli_body}\n", encoding="utf-8"
        )
        (bin_dir / "hapax-secret").chmod(0o755)
        body = self._extract("restic_password", self.SCRIPT.read_text(encoding="utf-8"))
        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        return subprocess.run(
            [
                BASH,
                "-c",
                f'. "{REPO_ROOT}/scripts/lib/secret.sh"\nFAILURES=()\n{body}\n{probe}',
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=REPO_ROOT,
        )

    def test_a_present_password_is_returned(self, tmp_path: Path) -> None:
        result = self._run(
            tmp_path,
            'printf "restic-pw\\n"',
            'printf "%s" "$(restic_password backups/restic-password local)"',
        )
        assert result.stdout == "restic-pw", result.stderr

    def test_an_unreadable_password_fails_and_says_so(self, tmp_path: Path) -> None:
        result = self._run(
            tmp_path,
            "exit 1",
            "restic_password backups/restic-password local >/dev/null; "
            'printf "rc=%s|%s" "$?" "${FAILURES[0]:-}"',
        )
        assert "rc=1" in result.stdout
        assert "cannot read" in result.stdout, result.stdout

    def test_an_empty_password_fails_with_a_DIFFERENT_message(self, tmp_path: Path) -> None:
        """The distinction, isolated. Collapsing it sends the operator to put a password
        that is already there."""
        result = self._run(
            tmp_path,
            'printf "\\n"',
            "restic_password backups/restic-password local >/dev/null; "
            'printf "rc=%s|%s" "$?" "${FAILURES[0]:-}"',
        )
        assert "rc=1" in result.stdout
        assert "is empty" in result.stdout, result.stdout
        assert "cannot read" not in result.stdout, result.stdout
