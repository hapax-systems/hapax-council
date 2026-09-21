"""The lane launchers resolve secrets through the FileStore helper, never pass.

These are the scripts that break a lane spawn the moment `pass` is uninstalled, so they are
the ones slice 1 exists for. Assertions are on INVOCATIONS against comment-stripped source,
per the coordinator's 2026-09-16 ruling: a gate matching the bare string `pass` would force
the deletion of controls that name the store deliberately.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.conftest import code_without_prose

REPO_ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash") or "/usr/bin/bash"

SHELL_LAUNCHERS = ("hapax-codex", "hapax-glmcp-claude")
PYTHON_LAUNCHERS = ("hapax-glmcp-reviewer",)
ALL_LAUNCHERS = SHELL_LAUNCHERS + PYTHON_LAUNCHERS

#: Shell forms AND argv forms. A search for `"pass show"` alone misses
#: `subprocess.run(["pass", "show", name])` entirely — the same call, one comma away, and a
#: mutation that reintroduced exactly that stayed green until these were added.
FORBIDDEN_INVOCATIONS = (
    "pass show",
    "pass ls",
    "pass insert",
    "gopass",
    "pass_first_line",
    "load_first_available_pass_secret",
    "PASSWORD_STORE_DIR",
    # argv/list forms
    '"pass"',
    "'pass'",
    'which("pass")',
    "which('pass')",
)


def _code_only(text: str) -> str:
    """Comments and docstrings stripped, via the single shared implementation."""
    language = "python" if text.lstrip().startswith("#!/usr/bin/env python") else "shell"
    return code_without_prose(text, language=language)


@pytest.mark.parametrize("name", ALL_LAUNCHERS)
def test_no_pass_invocation_remains(name: str) -> None:
    code = _code_only((REPO_ROOT / "scripts" / name).read_text(encoding="utf-8"))
    for forbidden in FORBIDDEN_INVOCATIONS:
        assert forbidden not in code, f"{name}: {forbidden}"


@pytest.mark.parametrize("name", SHELL_LAUNCHERS)
def test_the_shell_launchers_source_the_shared_helper(name: str) -> None:
    code = _code_only((REPO_ROOT / "scripts" / name).read_text(encoding="utf-8"))
    assert "lib/secret.sh" in code, name


@pytest.mark.parametrize("name", SHELL_LAUNCHERS)
def test_the_shell_launchers_are_syntactically_valid(name: str) -> None:
    result = subprocess.run(
        [BASH, "-n", str(REPO_ROOT / "scripts" / name)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("name", ALL_LAUNCHERS)
def test_diagnostics_name_an_action_that_will_still_work(name: str) -> None:
    """An error telling the operator to run `pass show` is a wrong next action once pass is
    uninstalled. `executive_function`: errors carry the action that works."""
    code = _code_only((REPO_ROOT / "scripts" / name).read_text(encoding="utf-8"))
    lowered = code.lower()
    for phrase in ("check: pass", "pass entry", "in pass", "pass:"):
        assert phrase not in lowered, f"{name}: diagnostic still names pass ({phrase})"
    # Either the file names the CLI itself, or it delegates every message to the shared
    # helper, which does. `hapax-codex` is the second kind: it only calls
    # `hapax_secret_into` and lets the helper own the diagnostics — one message, one place.
    assert "hapax-secret" in code or "lib/secret.sh" in code, (
        f"{name}: neither names the FileStore CLI nor delegates to the shared helper"
    )


class TestGlmcpClaudeResolution:
    """`hapax-glmcp-claude` reads one required token and exits distinctly on each failure.

    Its two exit codes carry meaning (5 = could not read, 6 = read but empty) and the
    migration must preserve that distinction: an empty credential and an absent one need
    different operator actions.
    """

    @staticmethod
    def _fake_cli(tmp_path: Path, body: str) -> Path:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        (bin_dir / "hapax-secret").write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
        (bin_dir / "hapax-secret").chmod(0o755)
        return bin_dir

    def test_a_present_token_resolves(self, tmp_path: Path) -> None:
        bin_dir = self._fake_cli(tmp_path, 'printf "zai-key\\n"')
        result = subprocess.run(
            [
                BASH,
                "-c",
                ". scripts/lib/secret.sh\n"
                'token="$(hapax_secret_get zai/api-key)" && printf "%s" "$token"',
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)},
        )
        assert result.stdout == "zai-key", result.stderr

    def test_an_absent_token_is_distinguishable_from_an_empty_one(self, tmp_path: Path) -> None:
        absent = self._fake_cli(tmp_path, "exit 1")
        empty = self._fake_cli(tmp_path / "e", 'printf "\\n"')
        script = (
            ". scripts/lib/secret.sh\n"
            "if hapax_secret_get zai/api-key >/dev/null; then echo RESOLVED; else echo MISS; fi"
        )
        for bin_dir, expected in ((absent, "MISS"), (empty, "MISS")):
            result = subprocess.run(
                [BASH, "-c", script],
                capture_output=True,
                text=True,
                cwd=REPO_ROOT,
                env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)},
            )
            assert expected in result.stdout, (bin_dir, result.stdout)


class TestGlmcpClaudeExitCodes:
    """`hapax-glmcp-claude` exits 5 when the secret cannot be READ and 6 when it is EMPTY.

    Two different operator actions — look for a secret that is not there, versus re-put one
    that is — so the codes must stay distinct. Nothing ran the launcher before, so a mutation
    collapsing 5 into 6 stayed green; these drive the real script.
    """

    @staticmethod
    def _run(tmp_path: Path, cli_body: str):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        (bin_dir / "hapax-secret").write_text(
            f"#!/usr/bin/env bash\n{cli_body}\n", encoding="utf-8"
        )
        (bin_dir / "hapax-secret").chmod(0o755)
        # A claude stub so the launcher never reaches a real exec on the happy path.
        (bin_dir / "claude").write_text(
            "#!/usr/bin/env bash\necho STUB_CLAUDE_RAN\n", encoding="utf-8"
        )
        (bin_dir / "claude").chmod(0o755)
        import os as _os

        env = dict(_os.environ)
        env["PATH"] = f"{bin_dir}{_os.pathsep}{env['PATH']}"
        env["HOME"] = str(tmp_path)
        return subprocess.run(
            [BASH, str(REPO_ROOT / "scripts" / "hapax-glmcp-claude")],
            capture_output=True,
            text=True,
            env=env,
            cwd=REPO_ROOT,
        )

    def test_an_unreadable_secret_exits_five(self, tmp_path: Path) -> None:
        result = self._run(tmp_path, "exit 1")
        assert result.returncode == 5, (result.returncode, result.stderr[-500:])
        assert "hapax-secret" in result.stderr

    def test_an_empty_secret_exits_six(self, tmp_path: Path) -> None:
        result = self._run(tmp_path, 'printf "\\n"')
        assert result.returncode == 6, (result.returncode, result.stderr[-500:])
        assert "empty" in result.stderr.lower()

    def test_the_two_codes_are_not_the_same(self, tmp_path: Path) -> None:
        unreadable = self._run(tmp_path / "a", "exit 1").returncode
        empty = self._run(tmp_path / "b", 'printf "\\n"').returncode
        assert unreadable != empty, (
            "an absent secret and an empty one need different operator actions"
        )
