"""The CI grep gate for estate-consumers-off-pass-onto-filestore-20260916.

Operator ruling 2026-09-16, verbatim: "Pass and gopass should never be used going forward to
manage secrets." Coordinator ruling (03:37Z): the gate asserts no INVOCATION of pass —
`pass show|ls|insert`, `PassStore`, `pass_first_line`, `load_first_available_pass_secret`,
`Environment=PASSWORD_STORE_DIR` — and explicitly exempts deny-lists and controls that merely
name the path or the commands (`shared/stream_mode.py` keeps `.password-store` in
DENY_PATH_PREFIXES: the archived stores still exist after the uninstall and must stay
unreadable to streams).

Three things keep this gate honest rather than loud:

- It reads CODE, not prose: comments and docstrings are stripped first (python and shell
  through `tests.conftest.code_without_prose`; `#` comment lines for units, yaml and the
  rest), so a file may quote the ruling that names both tools.
- It matches the argv shape too: `["pass", "show", name]` contains no "pass show" and is
  exactly how the second sweep of this row found seven readers the first sweep missed.
- It proves itself live: a positive sample per shape must match and a negative sample per
  known false positive (`Literal["pass", "fail"]`, `passport`, the deny-list path) must not.

The tests tree has its own rule: nothing may MOCK or EXECUTE pass (argv fakes, `shutil.which`
stubs, fake `.password-store` layouts, the deleted helpers). The bare phrase is not forbidden
there — in tests it is overwhelmingly an absence assertion or a redaction token list.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from tests.conftest import code_without_prose

REPO_ROOT = Path(__file__).resolve().parents[1]

RUNTIME_PREFIXES = ("agents/", "scripts/", "shared/", "systemd/", "hooks/", "docker/", "config/")
RUNTIME_ROOT_FILES = ("process-compose.yaml",)

#: Controls that name the commands AS the thing they scrub or list — never invocations.
CONTROLS: dict[str, str] = {
    "config/durf-coding-panes.yaml": "lists pass invocations as a redaction target for the coding panes",
    "scripts/epistemic_quality_dataset.py": "a redaction regex naming `pass show` as a token to scrub",
}

INVOCATION = re.compile(
    r"""(?x)
      \bpass\s+(show|ls|insert|edit|rm|generate|init|otp|grep)\b
    | \[\s*["']pass["']\s*,\s*["'](show|insert|ls)["']
    | shutil\.which\(\s*["']pass["']\s*\)
    | \bcommand\s+-v\s+pass\b
    | \bwhich\s+pass\b
    | \bPassStore\b
    | \bpass_first_line\b
    | \bload_first_available_pass_secret\b
    | ^\s*Environment=PASSWORD_STORE_DIR
    | ^\s*export\s+PASSWORD_STORE_DIR
    | \bgopass\b
    """,
    re.MULTILINE,
)

#: In tests: the shapes that mock or execute pass. The bare phrase is allowed (see module doc).
TEST_MOCK = re.compile(
    r"""(?x)
      \[\s*["']pass["']\s*,\s*["'](show|insert|ls)["']
    | shutil\.which\(\s*["']pass["']\s*\)
    | \bPassStore\b
    | \bpass_first_line\b
    | \bload_first_available_pass_secret\b
    | /\s*["']\.password-store["']
    | \bgopass\b
    """,
)

#: Test files that name the deny-list path AS the point (stream surfaces must never render it).
TEST_CONTROLS: dict[str, str] = {
    "tests/shared/test_stream_mode_deny_paths.py": "pins DENY_PATH_PREFIXES keeping .password-store unreadable",
    "tests/logos_api/test_stream_mode_transition_matrix.py": "the same deny-list, across stream modes",
    "tests/test_no_pass_invocations.py": "this gate's own samples",
    # The migration's own gates: each names the tokens it forbids, as string literals.
    "tests/scripts/test_lane_launchers_off_pass.py": "a gate naming the tokens it forbids",
    "tests/scripts/test_mcp_wrappers_off_pass.py": "a gate naming the tokens it forbids",
    "tests/scripts/test_service_scripts_off_pass.py": "a gate naming the tokens it forbids",
    "tests/scripts/test_secret_sh.py": "the shell helper's pin, naming the tokens it forbids",
    "tests/shared/test_python_callers_off_pass.py": "a gate naming the tokens it forbids; pins the deny-list path",
    "tests/shared/test_secrets.py": "the resolver's pin, naming the backend it refuses",
}


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, check=True
    ).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def _is_prose_only_path(relative: str) -> bool:
    parts = relative.split("/")
    return (
        "_lineage" in parts
        or parts[0] == "docs"
        or relative.endswith(".md")
        or relative.endswith(".rst")
        or relative.endswith(".txt")
    )


def _code(relative: str) -> str | None:
    path = REPO_ROOT / relative
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None  # binary or unreadable: not a place an invocation can hide
    head = text[:200]
    if relative.endswith(".py") or "python" in head.split("\n", 1)[0]:
        try:
            return code_without_prose(text, language="python")
        except SyntaxError:
            return text
    if relative.endswith(".sh") or "#!/usr/bin/env bash" in head or "#!/bin/bash" in head:
        return code_without_prose(text, language="shell")
    # units, yaml, json, toml, ini: drop whole-line comments; strings stay code
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _runtime_files() -> list[str]:
    files = []
    for relative in _tracked_files():
        if _is_prose_only_path(relative):
            continue
        if relative in RUNTIME_ROOT_FILES or relative.startswith(RUNTIME_PREFIXES):
            files.append(relative)
    return files


def _violations(files: list[str], pattern: re.Pattern[str], controls: dict[str, str]) -> list[str]:
    found: list[str] = []
    for relative in files:
        if relative in controls:
            continue
        code = _code(relative)
        if code is None:
            continue
        for match in pattern.finditer(code):
            line_no = code.count("\n", 0, match.start()) + 1
            found.append(f"{relative}:{line_no}: {match.group(0).strip()}")
    return found


def test_no_pass_invocation_remains_in_the_runtime_tree() -> None:
    files = _runtime_files()
    assert len(files) > 500, "the walk found too few files to be the runtime tree"
    violations = _violations(files, INVOCATION, CONTROLS)
    assert violations == [], "pass is still invoked at:\n  " + "\n  ".join(violations)


def test_every_declared_control_still_exists_and_still_names_pass() -> None:
    """A control that was deleted or rewritten must leave the exemption, not linger as a hole."""
    for relative in CONTROLS:
        code = _code(relative)
        assert code is not None, relative
        assert INVOCATION.search(code), f"{relative} no longer names pass; drop it from CONTROLS"


def test_tests_do_not_mock_or_execute_pass() -> None:
    files = [
        relative
        for relative in _tracked_files()
        if relative.startswith("tests/") and relative.endswith(".py")
    ]
    violations = _violations(files, TEST_MOCK, TEST_CONTROLS)
    assert violations == [], "tests still mock or execute pass at:\n  " + "\n  ".join(violations)


@pytest.mark.parametrize(
    "sample",
    [
        'result = subprocess.run(["pass", "show", key], capture_output=True)',
        "token=$(pass show github/token)",
        "pass insert -m foo/bar",
        'if not shutil.which("pass"):',
        "if ! command -v pass >/dev/null 2>&1; then",
        "store = PassStore()",
        'value="$(pass_first_line foo/bar)"',
        "load_first_available_pass_secret A B",
        "Environment=PASSWORD_STORE_DIR=%h/.password-store",
        'export PASSWORD_STORE_DIR="/home/x/.password-store"',
        "gopass show foo",
    ],
)
def test_the_gate_sees_each_invocation_shape(sample: str) -> None:
    assert INVOCATION.search(sample), sample


@pytest.mark.parametrize(
    "sample",
    [
        'GateState = Literal["pass", "fail", "unknown"]',
        '"passport",',
        'DENY_PATH_PREFIXES = (".password-store",)',
        "hapax-secret --list",
        "pass_key=YOUTUBE_STREAMING_TOKEN_PASS_KEY",
        "the tests pass showing green",
    ],
)
def test_the_gate_ignores_the_known_false_positives(sample: str) -> None:
    assert not INVOCATION.search(sample), sample
