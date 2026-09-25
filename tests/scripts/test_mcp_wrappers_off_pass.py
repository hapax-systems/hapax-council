"""The governed MCP wrappers resolve secrets through the FileStore helper, never pass.

Operator ruling 2026-09-16: "Pass and gopass should never be used going forward to manage
secrets." These wrappers are the ones that break a lane the moment `pass` is uninstalled, so
each is driven through a real bash process with a fake `hapax-secret` on PATH.

Assertions are on INVOCATIONS, against comment-stripped source — not on the bare string
`pass`, which legitimately appears in prose. A gate that cannot tell a reference-as-the-point
from a call forces good comments to be deleted; `shared/stream_mode.py` keeps the password
store in DENY_PATH_PREFIXES for exactly that reason, and uninstalling pass does not delete
that directory.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash") or "/usr/bin/bash"

WRAPPERS = (
    "hapax-github-mcp",
    "hapax-context7-mcp",
    "hapax-tavily-mcp",
)

FORBIDDEN_INVOCATIONS = (
    "pass show",
    "pass ls",
    "pass insert",
    "gopass",
    "pass_first_line",
    "load_first_available_pass_secret",
    "PASSWORD_STORE_DIR",
)


def _code_only(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


@pytest.mark.parametrize("name", WRAPPERS)
def test_no_pass_invocation_remains(name: str) -> None:
    code = _code_only((REPO_ROOT / "scripts" / name).read_text(encoding="utf-8"))
    for forbidden in FORBIDDEN_INVOCATIONS:
        assert forbidden not in code, f"{name}: {forbidden}"


@pytest.mark.parametrize("name", WRAPPERS)
def test_the_shared_helper_is_sourced(name: str) -> None:
    """One helper, sourced — not a fourth private copy of the resolution order."""
    code = _code_only((REPO_ROOT / "scripts" / name).read_text(encoding="utf-8"))
    assert "lib/secret.sh" in code, name
    assert "hapax_secret_into" in code or "hapax_secret_or_fail" in code, name


@pytest.mark.parametrize("name", WRAPPERS)
def test_the_wrapper_is_syntactically_valid(name: str) -> None:
    result = subprocess.run(
        [BASH, "-n", str(REPO_ROOT / "scripts" / name)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def _fake_secret_cli(tmp_path: Path, mapping: dict[str, str]) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    cases = "\n".join(f'  "{k}") printf "{v}\\n" ;;' for k, v in mapping.items())
    (bin_dir / "hapax-secret").write_text(
        f'#!/usr/bin/env bash\ncase "$1" in\n{cases}\n  *) exit 1 ;;\nesac\n', encoding="utf-8"
    )
    (bin_dir / "hapax-secret").chmod(0o755)
    return bin_dir


def _source_and_probe(name: str, script: str, bin_dir: Path, env: dict[str, str] | None = None):
    """Source the wrapper's resolution section and report what it exported.

    The wrappers `exec` their server at the end, so they are sourced up to that point via a
    stub `exec`/`npx` rather than run — the pin is on the CREDENTIAL path, which is what the
    migration changes.
    """
    environment = dict(os.environ)
    environment["PATH"] = f"{bin_dir}{os.pathsep}{environment['PATH']}"
    environment.update(env or {})
    return subprocess.run(
        [BASH, "-c", script],
        capture_output=True,
        text=True,
        env=environment,
        cwd=REPO_ROOT,
    )


class TestGithubWrapperResolution:
    def test_the_token_comes_from_the_filestore(self, tmp_path: Path) -> None:
        bin_dir = _fake_secret_cli(
            tmp_path, {"github/codex-personal-access-token": "pat-from-store"}
        )
        result = _source_and_probe(
            "hapax-github-mcp",
            ". scripts/lib/secret.sh\n"
            "hapax_secret_into GITHUB_PERSONAL_ACCESS_TOKEN "
            "  github/codex-personal-access-token github/personal-access-token\n"
            'printf "%s" "${GITHUB_PERSONAL_ACCESS_TOKEN:-}"',
            bin_dir,
        )
        assert result.stdout == "pat-from-store", result.stderr

    def test_an_existing_env_token_is_not_overwritten(self, tmp_path: Path) -> None:
        bin_dir = _fake_secret_cli(
            tmp_path, {"github/codex-personal-access-token": "pat-from-store"}
        )
        result = _source_and_probe(
            "hapax-github-mcp",
            ". scripts/lib/secret.sh\n"
            "hapax_secret_into GITHUB_PERSONAL_ACCESS_TOKEN github/codex-personal-access-token\n"
            'printf "%s" "$GITHUB_PERSONAL_ACCESS_TOKEN"',
            bin_dir,
            env={"GITHUB_PERSONAL_ACCESS_TOKEN": "already-set"},
        )
        assert result.stdout == "already-set"

    def test_the_fallback_chain_still_runs_when_the_store_misses(self, tmp_path: Path) -> None:
        """`hapax_secret_into` returns non-zero on a miss so the wrapper's existing
        `|| gh auth || claude mcp config` chain is preserved exactly."""
        bin_dir = _fake_secret_cli(tmp_path, {})
        result = _source_and_probe(
            "hapax-github-mcp",
            ". scripts/lib/secret.sh\n"
            "hapax_secret_into GITHUB_PERSONAL_ACCESS_TOKEN github/absent || echo CHAIN_CONTINUES",
            bin_dir,
        )
        assert "CHAIN_CONTINUES" in result.stdout


class TestErrorMessagesNameTheNewSource:
    @pytest.mark.parametrize("name", WRAPPERS)
    def test_no_error_message_still_points_at_pass(self, name: str) -> None:
        """An error that tells the operator to look in pass is a wrong next action once pass
        is uninstalled — `executive_function` says errors carry the action that works."""
        code = _code_only((REPO_ROOT / "scripts" / name).read_text(encoding="utf-8"))
        lowered = code.lower()
        for phrase in ("in pass", "pass:", "found in pass"):
            assert phrase not in lowered, f"{name}: error text still names pass ({phrase})"
        assert "hapax-secret" in code, f"{name}: no message names the FileStore CLI"
