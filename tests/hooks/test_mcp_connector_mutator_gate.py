"""Tests for the MCP connector mutator receipt gate."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "mcp-connector-mutator-gate.sh"
BASH = Path("/usr/bin/bash") if Path("/usr/bin/bash").exists() else Path("/bin/bash")


def _gate_env(home: Path, role: str | None, extra_env: dict[str, str] | None) -> dict[str, str]:
    # Do not inherit Python import-path flags that can supply the hook's fix.
    env = {
        "HOME": str(home),
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
    }
    if role is not None:
        env["CODEX_THREAD_NAME"] = role
    if extra_env:
        env.update(extra_env)
    return env


def _run_gate(
    payload: dict,
    *,
    home: Path,
    role: str | None = "cx-red",
    cwd: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    env = _gate_env(home, role, extra_env)
    return subprocess.run(
        [str(BASH), str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT if cwd is None else cwd,
        timeout=10,
    )


def _path_without_python(tmp_path: Path) -> str:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("cat", "dirname", "jq"):
        target = shutil.which(name)
        assert target is not None
        (bin_dir / name).symlink_to(target)
    return str(bin_dir)


def _path_without_jq(tmp_path: Path) -> str:
    bin_dir = tmp_path / "bin-no-jq"
    bin_dir.mkdir()
    for name in ("cat", "dirname"):
        target = shutil.which(name)
        assert target is not None
        (bin_dir / name).symlink_to(target)
    return str(bin_dir)


def _run_gate_text(
    payload: str, *, home: Path, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    env = _gate_env(home, "cx-red", extra_env)
    return subprocess.run(
        [str(BASH), str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=10,
    )


def test_read_only_mcp_tool_passes_without_claim(tmp_path: Path) -> None:
    result = _run_gate(
        {
            "tool_name": "mcp__context7__query-docs",
            "tool_input": {"libraryId": "/reactjs/react.dev"},
        },
        home=tmp_path,
    )

    assert result.returncode == 0


def test_python3_absent_read_only_mcp_tool_passes_without_claim(tmp_path: Path) -> None:
    result = _run_gate(
        {
            "tool_name": "mcp__context7__query-docs",
            "tool_input": {"libraryId": "/reactjs/react.dev"},
        },
        home=tmp_path,
        extra_env={"PATH": _path_without_python(tmp_path)},
    )

    assert result.returncode == 0


def test_side_effecting_connector_without_claim_blocks_with_next_action(tmp_path: Path) -> None:
    result = _run_gate(
        {
            "tool_name": "mcp__codex_apps__gmail___forward_emails",
            "tool_input": {"message_ids": ["m1"], "to": "person@example.com"},
        },
        home=tmp_path,
    )

    assert result.returncode == 2
    assert "no claimed task" in result.stderr
    assert "Next action:" in result.stderr


def test_side_effecting_connector_with_claim_requires_route_decision(tmp_path: Path) -> None:
    cache = tmp_path / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-cx-red").write_text("task-1\n", encoding="utf-8")

    result = _run_gate(
        {
            "tool_name": "mcp__codex_apps__gmail___forward_emails",
            "tool_input": {"message_ids": ["m1"], "to": "person@example.com"},
        },
        home=tmp_path,
    )

    assert result.returncode == 2
    assert "route_decision_absent" in result.stderr
    assert "Next action:" in result.stderr


def test_python3_absent_classifier_path_fails_closed(tmp_path: Path) -> None:
    result = _run_gate(
        {
            "tool_name": "mcp__codex_apps__gmail___forward_emails",
            "tool_input": {"message_ids": ["m1"], "to": "person@example.com"},
        },
        home=tmp_path,
        extra_env={"PATH": _path_without_python(tmp_path)},
    )

    assert result.returncode == 2
    assert "connector classifier failed" in result.stderr


def test_jq_absent_blocks_instead_of_passing_empty_tool_name(tmp_path: Path) -> None:
    result = _run_gate(
        {
            "tool_name": "mcp__codex_apps__gmail___forward_emails",
            "tool_input": {"message_ids": ["m1"], "to": "person@example.com"},
        },
        home=tmp_path,
        extra_env={"PATH": _path_without_jq(tmp_path)},
    )

    assert result.returncode == 2
    assert "cannot parse hook payload tool_name" in result.stderr


def test_malformed_hook_payload_blocks_instead_of_passing_empty_tool_name(
    tmp_path: Path,
) -> None:
    result = _run_gate_text("{", home=tmp_path)

    assert result.returncode == 2
    assert "cannot parse hook payload tool_name" in result.stderr


def _caller_fixture(tmp_path: Path, kind: str, claimed: bool) -> tuple[Path, Path]:
    home = tmp_path / "home"
    home.mkdir()
    cwd = tmp_path / "caller"
    cwd.mkdir()
    if kind != "plain":
        package = cwd / "shared"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        if kind in {"spoof_classifier", "spoof_receipt"}:
            classifier_rc = 10 if kind == "spoof_classifier" else 0
            (package / "mcp_connector_policy.py").write_text(
                "import sys\n"
                "if sys.argv[1] == 'is-side-effecting':\n"
                f"    raise SystemExit({classifier_rc})\n"
                "if sys.argv[1] == 'receipt-gate':\n"
                "    print('PRIVATE_FIXTURE_RECEIPT_ACCEPTED')\n"
                "    raise SystemExit(0)\n"
                "raise SystemExit(3)\n",
                encoding="utf-8",
            )
    if claimed:
        cache = home / ".cache" / "hapax"
        cache.mkdir(parents=True)
        (cache / "cc-active-task-cx-red").write_text("private-task\n", encoding="utf-8")
    return home, cwd


def _run_caller_mutator(
    home: Path, cwd: Path, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    assert "PYTHONSAFEPATH" not in _gate_env(home, "cx-red", extra_env)
    return _run_gate(
        {"tool_name": "mcp__codex_apps__gmail___forward_emails", "tool_input": {}},
        home=home,
        cwd=cwd,
        extra_env=extra_env,
    )


def _assert_route_refusal(result: subprocess.CompletedProcess) -> None:
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "route_decision_absent" in result.stderr, result.stderr
    assert "Next action:" in result.stderr
    assert "PRIVATE_FIXTURE_RECEIPT_ACCEPTED" not in result.stdout


@pytest.mark.parametrize("kind", ("plain", "incomplete", "spoof_classifier"))
@pytest.mark.parametrize("claimed", (False, True))
def test_caller_package_cannot_replace_primary_classifier(
    tmp_path: Path, kind: str, claimed: bool
) -> None:
    home, cwd = _caller_fixture(tmp_path, kind, claimed)
    result = _run_caller_mutator(home, cwd)
    if claimed:
        _assert_route_refusal(result)
    else:
        assert result.returncode == 2, (result.stdout, result.stderr)
        assert "no claimed task" in result.stderr, result.stderr
        assert "Next action:" in result.stderr


def test_caller_package_cannot_accept_missing_route_receipt(tmp_path: Path) -> None:
    home, cwd = _caller_fixture(tmp_path, "spoof_receipt", claimed=True)
    _assert_route_refusal(_run_caller_mutator(home, cwd))


def test_incomplete_caller_package_preserves_manifest_read_only_classification(
    tmp_path: Path,
) -> None:
    home, cwd = _caller_fixture(tmp_path, "incomplete", claimed=False)
    result = _run_gate(
        {"tool_name": "mcp__codex_apps__github___fetch_pr_comments", "tool_input": {}},
        home=home,
        cwd=cwd,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("path_kind", ("empty", "cwd", "empty_components", "other"))
def test_explicit_pythonpath_cannot_precede_primary_package(tmp_path: Path, path_kind: str) -> None:
    home, cwd = _caller_fixture(tmp_path, "spoof_classifier", claimed=True)
    other = tmp_path / "other"
    other.mkdir()
    pythonpath = {
        "empty": "",
        "cwd": str(cwd),
        "empty_components": ":" + str(cwd) + ":",
        "other": str(other),
    }[path_kind]
    _assert_route_refusal(_run_caller_mutator(home, cwd, {"PYTHONPATH": pythonpath}))


def test_cwd_stdlib_spoof_not_imported(tmp_path: Path) -> None:
    # Review finding (agy/GLM, 2026-09-11): a caller-supplied PYTHONPATH with a
    # trailing empty component resolves to cwd and precedes stdlib — a cwd
    # json.py would be imported over the real one. The gate now discards the
    # inherited PYTHONPATH and resolves the module from REPO_ROOT itself, so
    # the spoofed stdlib module must not be imported.
    home, cwd = _caller_fixture(tmp_path, "spoof_classifier", claimed=True)
    (cwd / "json.py").write_text("raise SystemExit(99)\n", encoding="utf-8")
    result = _run_caller_mutator(home, cwd, {"PYTHONPATH": f"{cwd}:"})
    assert result.returncode == 2, (result.stdout, result.stderr)
    _assert_route_refusal(result)


def test_python_invocations_carry_safe_path_flag() -> None:
    # Review finding (gemini-1, 2026-09-12 round 2): the PR body documents
    # `python3 -P` (PYTHONSAFEPATH — no unsafe cwd/script-dir prepend) on both
    # gate invocations, but the shipped script omitted the flag. The subshell
    # cd + explicit PYTHONPATH make -P defense-in-depth rather than the primary
    # control, so the durable check is a source pin: both the classifier and
    # the receipt-gate invocation must keep the flag.
    source = HOOK.read_text(encoding="utf-8")
    invocations = [line for line in source.splitlines() if "python3 " in line and "-m " in line]
    assert invocations, "gate script no longer invokes python3 -m directly — re-audit isolation"
    receipt_gate = [line for line in source.splitlines() if 'python3 -P "${args[@]}"' in line]
    assert len(receipt_gate) == 1, source
    assert all("python3 -P " in line for line in invocations), source
