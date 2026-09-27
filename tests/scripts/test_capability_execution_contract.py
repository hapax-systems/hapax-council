"""Execution identity is registry-derived at every invocation boundary."""

from __future__ import annotations

import base64
import importlib.machinery
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

from shared.capability_execution import (
    ExecutionIdentityError,
    claude_execution_binding,
    reject_codex_identity_overrides,
    resolve_execution_descriptor,
)
from shared.capability_execution import (
    main as execution_main,
)
from shared.codex_execution_receipt import check_rollout
from shared.codex_execution_receipt import main as receipt_main
from shared.platform_capability_registry import ExecutionDescriptor, ModelId

REPO_ROOT = Path(__file__).resolve().parents[2]
HEADLESS = REPO_ROOT / "scripts/hapax-codex-headless"
INTERACTIVE = REPO_ROOT / "scripts/hapax-codex"
REGISTRY = REPO_ROOT / "config/platform-capability-registry.json"
LAUNCHERS = (INTERACTIVE, HEADLESS)
IDENTITY_SOURCES = (
    *LAUNCHERS,
    REPO_ROOT / "scripts/hapax-methodology-dispatch",
    REPO_ROOT / "scripts/capability-execution.sh",
    REPO_ROOT / "scripts/hapax-claude-reviewer",
    REPO_ROOT / "scripts/hapax-lane-idle-watchdog",
)


@pytest.mark.parametrize(
    "args",
    [
        ["--route", "codex.headless.full"],
        ["--route", "claude.review.opus", "--", "--model", "opus"],
    ],
)
def test_claude_cli_refuses_foreign_route_and_extra_identity_arguments(args, capsys):
    assert execution_main(["--harness", "claude", *args]) == 9
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "non-Claude route or extra identity arguments" in captured.err
    assert "remedy:" in captured.err


@pytest.mark.parametrize(
    ("axis", "value"),
    [
        ("model_id", "gpt-6-astra"),
        ("effort", "none"),
        ("context_mode", "extended_1m"),
        ("fast_mode", "fast"),
        ("quantization", "exl3_4_0bpw"),
    ],
)
def test_claude_mapping_refuses_every_unimplemented_axis(axis, value):
    declared = {
        "model_id": "claude-opus-4-8",
        "effort": "xhigh",
        "context_mode": "standard",
        "fast_mode": "off",
        "quantization": "none",
    }
    declared[axis] = value
    descriptor = ExecutionDescriptor.model_validate(declared)
    with pytest.raises(ExecutionIdentityError, match="unsupported Claude ExecutionDescriptor"):
        claude_execution_binding(descriptor)


def test_launchers_and_dispatch_have_no_literal_model_ids():
    catalog = [str(model) for model in ModelId if model != ModelId.UNKNOWN]
    for source in IDENTITY_SOURCES:
        text = source.read_text()
        assert not [model for model in catalog if model.lower() in text.lower()], source
        assert not re.search(
            r"(?:gpt-\d|claude-(?:opus|sonnet|haiku|fable)-\d|gemini-\d|glm-\d|qwen\d|mistral-medium-\d)",
            text,
            re.I,
        ), source


def test_codex_config_has_no_identity_defaults():
    config = tomllib.loads((REPO_ROOT / "config/codex/config.toml").read_text())
    assert "model" not in config
    assert "model_reasoning_effort" not in config


def _registry(tmp_path, *, missing=False):
    payload = json.loads(REGISTRY.read_text())
    for route in payload["routes"]:
        if route["route_id"].startswith("codex."):
            if missing:
                route.pop("execution_descriptor")
            else:
                # Change only the descriptor; stale free text MUST have no effect.
                route["execution_descriptor"]["model_id"] = "gpt-5.5"
                route["execution_descriptor"]["effort"] = "low"
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload))
    return path


def _env_with_fake_codex(tmp_path: Path) -> tuple[dict[str, str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_file = tmp_path / "codex-args.txt"
    fake_codex = bin_dir / "codex"
    fake_codex.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                f"printf '%s\\0' \"$*\" >> {shlex.quote(str(args_file.with_suffix('.calls')))}",
                'if [ "${1:-}" = "exec" ] && [[ "$*" == *HAPAX_CODEX_EXEC_AUTH_OK* ]]; then',
                "  printf '%s\\n' "
                + shlex.quote(
                    '{"type":"item.completed","item":{"type":"agent_message","text":"HAPAX_CODEX_EXEC_AUTH_OK"}}'
                ),
                "  exit 0",
                "fi",
                f"printf '%s\\n' \"$@\" > {shlex.quote(str(args_file))}",
                f"printf '%s\\0' \"$@\" > {shlex.quote(str(args_file.with_suffix('.argv')))}",
                "exit 0",
                "",
            ]
        ),
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)

    env = os.environ.copy()
    # All effects are isolated; no claim-plane or safety-gate bypass is used.
    for key in tuple(env):
        if key.startswith(("HAPAX_", "CODEX_")):
            env.pop(key)
    env["HOME"] = str(tmp_path / "home")
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["HAPAX_CODEX_EXEC_AUTH_TIMEOUT_SECONDS"] = "5"
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_HEADLESS_PID_DIR"] = str(tmp_path / "headless-pids")
    env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(REPO_ROOT)
    env["HAPAX_CODEX_TERMINAL"] = "none"
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    return env, args_file


def _launch(launcher, env, route="codex.headless.full", extra=(), workdir=None):
    if launcher == HEADLESS:
        args = [
            "--execution-route",
            route,
            "--task",
            "task-x",
            "--no-claim",
            "--force",
            "cx-amber",
            "governed prompt",
        ]
    else:
        args = [
            "--execution-route",
            route,
            "--session",
            "cx-amber",
            "--slot",
            "alpha",
            "--cd",
            str(workdir or REPO_ROOT),
            "--terminal",
            "none",
        ]
    if extra:
        args += ["--", *extra]
    return subprocess.run(
        [str(launcher), *args], capture_output=True, text=True, env=env, timeout=20
    )


@pytest.mark.parametrize("launcher", LAUNCHERS)
@pytest.mark.parametrize("layout", ["ordinary", "with spaces", "relocated release"])
def test_both_launchers_deliver_exact_common_configuration(tmp_path, launcher, layout):
    cell = tmp_path / layout
    cell.mkdir()
    env, args_file = _env_with_fake_codex(cell)
    workdir = cell / "working directory"
    workdir.mkdir()
    env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(workdir)
    env["LOGOS_BASE_URL"] = "http://127.0.0.1:1/isolated-api"
    source = REPO_ROOT
    if layout == "relocated release":
        source = cell / "selected source"
        source.mkdir()
        shutil.copytree(REPO_ROOT / "scripts", source / "scripts")
        for name in ("shared", "config", "hooks"):
            (source / name).symlink_to(REPO_ROOT / name, target_is_directory=True)
        (source / ".venv").symlink_to(Path(sys.executable).parent.parent, target_is_directory=True)
        env["HAPAX_SOURCE_ACTIVATE_WORKTREE"] = str(source)
        env["HAPAX_COUNCIL_DIR"] = str(source)

    result = _launch(launcher, env, workdir=workdir)
    assert result.returncode == 0, result.stderr
    observed = args_file.with_suffix(".argv").read_bytes().split(b"\0")
    assert observed.pop() == b""
    argv = [arg.decode() for arg in observed]
    home = env["HOME"]
    hook = source / "hooks/scripts/codex-hook-adapter.sh"
    # Literal expectations pin the native child boundary, independently of the helper.
    settings = [
        'approval_policy="never"',
        'sandbox_mode="danger-full-access"',
        f'projects."{home}/projects".trust_level="trusted"',
        f'projects."{workdir}".trust_level="trusted"',
        f'hooks.SessionStart=[{{command="{hook}",timeout=20,statusMessage="Loading Hapax context"}}]',
        f'hooks.PreToolUse=[{{command="{hook}",timeout=20,include_apply_patch_tool=true,statusMessage="Hapax guardrails"}}]',
        f'hooks.PostToolUse=[{{command="{hook}",timeout=20,include_apply_patch_tool=true,statusMessage="Hapax audit"}}]',
        f'hooks.Stop=[{{command="{hook}",timeout=20,statusMessage="Writing Hapax session summary"}}]',
        f'mcp_servers.hapax.command="{home}/.local/bin/uv"',
        f'mcp_servers.hapax.args=["--directory","{home}/projects/hapax-mcp","run","hapax-mcp"]',
        f'mcp_servers.hapax.env.LOGOS_BASE_URL="{env["LOGOS_BASE_URL"]}"',
    ]
    common = [part for setting in settings for part in ("-c", setting)]
    start = argv.index(settings[0]) - 1
    assert argv[start : start + len(common)] == common
    for setting in settings:
        key = setting.split("=", 1)[0] + "="
        assert [arg for arg in argv if arg.startswith(key)] == [setting]


@pytest.mark.parametrize("launcher", LAUNCHERS)
@pytest.mark.parametrize("route", ["codex.headless.full", "codex.headless.spark"])
def test_invocation_carries_exact_descriptor(tmp_path, launcher, route):
    env, args_file = _env_with_fake_codex(tmp_path)
    registry = _registry(tmp_path)
    env["HAPAX_PLATFORM_CAPABILITY_REGISTRY"] = str(registry)
    result = _launch(launcher, env, route)
    assert result.returncode == 0, result.stderr
    descriptor = resolve_execution_descriptor(route, registry_path=registry)
    expected = [
        "-c",
        f'model="{descriptor.model_id}"',
        "-c",
        f'model_reasoning_effort="{descriptor.effort}"',
    ]
    argv = args_file.read_text().splitlines()
    assert [arg for arg in argv if arg.startswith(("model=", "model_reasoning_effort="))] == [
        expected[1],
        expected[3],
    ]
    for call in args_file.with_suffix(".calls").read_text().rstrip("\0").split("\0"):
        assert expected[1] in call and expected[3] in call  # includes auth probes


@pytest.mark.parametrize("launcher", LAUNCHERS)
@pytest.mark.parametrize(
    "failure",
    [
        "missing_descriptor",
        "missing_registry",
        "directory_registry",
        "unknown_route",
        "missing_runtime",
    ],
)
def test_missing_descriptor_is_refused_before_invocation(tmp_path, launcher, failure):
    env, args_file = _env_with_fake_codex(tmp_path)
    path = _registry(tmp_path, missing=failure == "missing_descriptor")
    if failure == "missing_registry":
        path.unlink()
    if failure == "directory_registry":
        path.unlink()
        path.mkdir()
    env["HAPAX_PLATFORM_CAPABILITY_REGISTRY"] = str(path)
    if failure == "missing_runtime":
        council = tmp_path / "unprovisioned-council"
        (council / "scripts").mkdir(parents=True)
        (council / "scripts/capability-execution.sh").write_bytes(
            (REPO_ROOT / "scripts/capability-execution.sh").read_bytes()
        )
        env["HAPAX_COUNCIL_DIR"] = str(council)
    route = "codex.headless.absent" if failure == "unknown_route" else "codex.headless.full"
    result = _launch(launcher, env, route)
    assert result.returncode == 9, result.stderr
    assert "remedy:" in result.stderr
    if failure == "missing_runtime":
        assert str(council / ".venv/bin/python") in result.stderr
    assert not args_file.with_suffix(".calls").exists()


@pytest.mark.parametrize(
    "args",
    [
        ["--model", "external"],
        ["-m", "external"],
        ["-mexternal"],
        ["--model=external"],
        ["-c", 'model="external"'],
        ["--config=model_reasoning_effort=high"],
        ["-cmodel=external"],
        ["-c=model=external"],
        ["-c=model_reasoning_effort=low"],
        ["--profile", "external"],
        ["-p", "external"],
        ["-pexternal"],
        ["--oss"],
        ["-c", 'profiles.test."model"="external"'],
    ],
)
def test_model_and_effort_overrides_are_refused(args):
    with pytest.raises(ExecutionIdentityError, match="remedy:"):
        reject_codex_identity_overrides(args)


@pytest.mark.parametrize("launcher", LAUNCHERS)
def test_launcher_preserves_non_identity_arguments(tmp_path, launcher):
    env, args_file = _env_with_fake_codex(tmp_path)
    extra = ["--sandbox", "workspace-write", "-c", "features.web_search_request=true"]
    result = _launch(launcher, env, extra=extra)
    assert result.returncode == 0, result.stderr
    argv = args_file.read_text().splitlines()
    assert any(argv[index : index + len(extra)] == extra for index in range(len(argv)))


@pytest.mark.parametrize("launcher", LAUNCHERS)
def test_launcher_refuses_cli_override(tmp_path, launcher):
    env, args_file = _env_with_fake_codex(tmp_path)
    result = _launch(launcher, env, extra=["-c", 'model="external"'])
    assert result.returncode == 9
    assert not args_file.with_suffix(".calls").exists()


def test_turn_context_mismatch_is_misattributed(tmp_path, capsys):
    descriptor = resolve_execution_descriptor("codex.headless.full")
    model, effort = str(descriptor.model_id), str(descriptor.effort)
    contexts = [(model, effort), ("changed-model", effort), (model, "low"), (model, effort)]
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text(
        "".join(
            json.dumps({"type": "turn_context", "payload": {"model": m, "effort": e}}) + "\n"
            for m, e in contexts
        )
    )
    receipts = list(check_rollout(rollout, descriptor, route_id="codex.headless.full"))
    assert [r["status"] for r in receipts] == [
        "matched",
        "misattributed",
        "misattributed",
        "matched",
    ]
    assert receipts[1]["declared"] == {"model": model, "effort": effort}
    assert receipts[1]["observed"] == {"model": "changed-model", "effort": effort}
    assert receipts[2]["observed"] == {"model": model, "effort": "low"}
    assert receipt_main(["--route", "codex.headless.full", "--rollout", str(rollout)]) == 1
    emitted = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert emitted == receipts


def test_checker_emits_known_mismatch_before_later_malformed_line(tmp_path, capsys):
    path = tmp_path / "rollout.jsonl"
    path.write_text(
        json.dumps({"type": "turn_context", "payload": {"model": "different", "effort": "low"}})
        + "\nbroken\n"
    )
    assert receipt_main(["--route", "codex.headless.full", "--rollout", str(path)]) == 2
    captured = capsys.readouterr()
    emitted = [json.loads(line) for line in captured.out.splitlines()]
    assert len(emitted) == 1
    assert emitted[0]["status"] == "misattributed"
    assert "next action:" in captured.err


def test_dispatch_refuses_cross_route_identity_with_next_action():
    with pytest.raises(ExecutionIdentityError, match="remedy:") as error:
        _dispatch().launch_descriptor("codex.headless.full", "codex.headless.spark")
    assert "codex.headless.spark" in str(error.value)
    assert "codex.headless.full" in str(error.value)


@pytest.mark.parametrize(
    ("payload", "expected_status"),
    [
        ({"model": "changed-model"}, "misattributed"),
        ({"effort": "changed-effort"}, "misattributed"),
        ({"model": "changed-model", "effort": None}, "misattributed"),
        ({"model": None, "effort": "changed-effort"}, "misattributed"),
        ({"model": "declared"}, "unverified"),
        ({"effort": "declared"}, "unverified"),
        ({}, "unverified"),
    ],
)
def test_partial_turn_observation_preserves_known_mismatch(
    tmp_path, capsys, payload, expected_status
):
    descriptor = resolve_execution_descriptor("codex.headless.full")
    declared = {"model": str(descriptor.model_id), "effort": str(descriptor.effort)}
    payload = {
        key: declared[key] if value == "declared" else value for key, value in payload.items()
    }
    rollout = tmp_path / "partial-rollout.jsonl"
    rollout.write_text(json.dumps({"type": "turn_context", "payload": payload}) + "\n")
    assert receipt_main(["--route", "codex.headless.full", "--rollout", str(rollout)]) == 1
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["status"] == expected_status
    assert receipt["observed"] == {axis: payload.get(axis) for axis in ("model", "effort")}
    assert receipt["declared"] == declared


@pytest.mark.parametrize("contents", ["", '{"type":"turn_context","payload":{}}\n', "broken\n"])
def test_incomplete_receipt_never_claims_a_match(tmp_path, contents):
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text(contents)
    assert receipt_main(["--route", "codex.headless.full", "--rollout", str(rollout)]) != 0


def test_captured_native_turn_context_uses_observed_field_names():
    rollout = REPO_ROOT / "tests/fixtures/codex-native-turn-context-0.155.1.jsonl"
    events = [json.loads(line) for line in rollout.read_text().splitlines()]
    assert events[0]["payload"]["cli_version"] == "0.155.1"
    descriptor = ExecutionDescriptor(model_id="gpt-6-astra", effort="xhigh")
    receipt = next(check_rollout(rollout, descriptor, route_id="captured-native-trial"))
    assert receipt["status"] == "matched"
    assert receipt["observed"] == {"model": "gpt-6-astra", "effort": "xhigh"}
    changed = descriptor.model_copy(update={"effort": "low"})
    mismatch = next(check_rollout(rollout, changed, route_id="captured-native-trial"))
    assert mismatch["status"] == "misattributed"


@pytest.mark.parametrize("contents", [None, "", "broken\n"])
def test_receipt_cli_failure_names_next_action(tmp_path, capsys, contents):
    rollout = tmp_path / "rollout.jsonl"
    if contents is not None:
        rollout.write_text(contents)
    assert receipt_main(["--route", "codex.headless.full", "--rollout", str(rollout)]) != 0
    assert "next action:" in capsys.readouterr().err.lower()


@pytest.mark.parametrize(
    "output",
    [
        "[]",
        '[""]',
        "{}",
        "broken",
        '["-c", 3]',
        '["-c", "a\\nb"]',
        json.dumps(["-c", 'approval_policy="never"']),
        json.dumps(["-c", 'model="named"', "-c", 'approval_policy="never"']),
        json.dumps(["-c", 'model="named"', "-c", 'model="named"']),
        json.dumps(["-c", 'model="named"', "--other", 'model_reasoning_effort="low"']),
        json.dumps(["-c", 'model=""', "-c", 'model_reasoning_effort="low"']),
        json.dumps(["-c", 'model="named"', "-c", "model_reasoning_effort=null"]),
    ],
)
def test_identity_helper_refuses_malformed_resolver_output(tmp_path, output):
    try:
        output = json.dumps(
            {"argv": json.loads(output), "descriptor": {"model_id": "named", "effort": "low"}}
        )
    except ValueError:
        pass
    result = _identity_helper_output(tmp_path, output)
    assert result.returncode == 9
    assert "next action:" in result.stderr.lower()


def _identity_helper_output(tmp_path, output, *, inspect_binding=False):
    runtime = tmp_path / "runtime"
    (runtime / "scripts").mkdir(parents=True)
    helper = runtime / "scripts/capability-execution.sh"
    helper.write_bytes((REPO_ROOT / "scripts/capability-execution.sh").read_bytes())
    python = runtime / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(
        '#!/usr/bin/env bash\nif [[ "$1" == -I && "${3:-}" == *runpy.run_module* ]]; then\n'
        f"  printf '%s' {shlex.quote(output)}\n  exit 0\nfi\n"
        f'exec {shlex.quote(sys.executable)} "$@"\n'
    )
    python.chmod(0o755)
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; EXECUTION_ROUTE=fixture; CODEX_EXTRA=(); bind_codex_execution || exit $?; '
            + (
                'printf "%s\\n" "$HAPAX_CODEX_EXECUTION_ARGS" '
                '"$HAPAX_CODEX_EXECUTION_DESCRIPTOR" "${CODEX_EXECUTION_ARGS[@]}"'
                if inspect_binding
                else ""
            ),
            "fixture",
            str(helper),
        ],
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "descriptor",
    [
        None,
        [],
        {},
        {"model_id": "different", "effort": "low"},
        {"model_id": "named", "effort": "high"},
    ],
)
def test_identity_helper_refuses_inconsistent_launch_snapshot(tmp_path, descriptor):
    output = json.dumps(
        {
            "argv": ["-c", 'model="named"', "-c", 'model_reasoning_effort="low"'],
            "descriptor": descriptor,
        }
    )
    result = _identity_helper_output(tmp_path, output)
    assert result.returncode == 9
    assert "next action:" in result.stderr.lower()


@pytest.mark.parametrize("model,effort", [("", "low"), ("named", None), (3, "low")])
def test_identity_helper_refuses_consistent_invalid_identity(tmp_path, model, effort):
    output = json.dumps(
        {
            "argv": [
                "-c",
                f"model={json.dumps(model)}",
                "-c",
                f"model_reasoning_effort={json.dumps(effort)}",
            ],
            "descriptor": {"model_id": model, "effort": effort},
        }
    )
    result = _identity_helper_output(tmp_path, output)
    assert result.returncode == 9
    assert "next action:" in result.stderr.lower()


def test_identity_helper_ignores_caller_python_modules(tmp_path):
    env, _ = _env_with_fake_codex(tmp_path)
    env["HAPAX_PLATFORM_CAPABILITY_REGISTRY"] = str(_registry(tmp_path))
    (tmp_path / "json.py").write_text('raise RuntimeError("ambient JSON module loaded")\n')
    env["PYTHONPATH"] = str(tmp_path)
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; EXECUTION_ROUTE=codex.headless.full; CODEX_EXTRA=(); '
            'bind_codex_execution || exit $?; printf "%s\\n" "${CODEX_EXECUTION_ARGS[@]}"',
            "fixture",
            str(REPO_ROOT / "scripts/capability-execution.sh"),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert 'model="gpt-5.5"' in result.stdout.splitlines()
    assert 'model_reasoning_effort="low"' in result.stdout.splitlines()


@pytest.mark.parametrize(
    "case", ["matched", "registry_changed", "wrong_session", "mismatched_model"]
)
def test_headless_identity_reaches_result_reader_with_frozen_declaration(tmp_path, case):
    env, _ = _env_with_fake_codex(tmp_path)
    registry = _registry(tmp_path)
    env["HAPAX_PLATFORM_CAPABILITY_REGISTRY"] = str(registry)
    receipt = tmp_path / "lifecycle.json"
    env["HAPAX_NATIVE_LIFECYCLE_RECEIPT"] = str(receipt)
    native = tmp_path / "bin/codex"
    script = native.read_text()
    # Preserve the controlled authentication sentinel path, then replace only
    # the actual execution child's exit with native-shaped independent events.
    prefix, suffix = script.rsplit("exit 0\n", 1)
    assert not suffix.strip()
    native.write_text(
        prefix
        + f"exec {shlex.quote(sys.executable)} - \"$@\" <<'PY'\n"
        + f"case = {case!r}\nregistry_path = {str(registry)!r}\n"
        + """
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
sid = "01900000-1234-7000-8000-123456789abc"
values = dict(arg.split("=", 1) for arg in sys.argv[1:] if arg.startswith(("model=", "model_reasoning_effort=")))
model = json.loads(values["model"])
effort = json.loads(values["model_reasoning_effort"])
if case == "registry_changed":
    path = Path(registry_path)
    payload = json.loads(path.read_text())
    for route in payload["routes"]:
        if route["route_id"] == "codex.headless.full":
            route["execution_descriptor"]["model_id"] = "gpt-6-astra"
            route["execution_descriptor"]["effort"] = "xhigh"
    path.write_text(json.dumps(payload))
now = datetime.now(timezone.utc).isoformat()
path = Path.home() / ".codex/sessions/2026/09/21" / f"rollout-controlled-{sid}.jsonl"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text("".join(json.dumps(event) + "\\n" for event in [
    {"type": "session_meta", "timestamp": now,
     "payload": {"id": "wrong-run" if case == "wrong_session" else sid, "cwd": os.getcwd()}},
    {"type": "turn_context", "timestamp": now,
     "payload": {"model": "gpt-6-astra" if case == "mismatched_model" else model, "effort": effort}},
]))
for event in [{"type": "thread.started", "thread_id": sid}, {"type": "turn.started"}, {"type": "turn.completed"}]:
    print(json.dumps(event))
PY
"""
    )
    result = _launch(HEADLESS, env)
    assert result.returncode == 0, result.stderr
    observed, reference = _dispatch().read_native_lifecycle_receipt(receipt, platform="codex")
    assert observed["complete"] is True
    identity = observed["execution_identity"]
    assert (
        identity["status"]
        == {
            "matched": "matched",
            "registry_changed": "matched",
            "wrong_session": "unverified",
            "mismatched_model": "misattributed",
        }[case]
    )
    assert identity["declared"]["model_id"] == "gpt-5.5"
    assert identity["declared"]["effort"] == "low"
    assert identity["may_authorize"] is False
    assert reference is not None


def test_interactive_reentry_keeps_selected_source_release(tmp_path):
    env, calls = _env_with_fake_codex(tmp_path)
    activation = tmp_path / "selected-release"
    (activation / "scripts").mkdir(parents=True)
    shutil.copytree(
        REPO_ROOT / "shared",
        activation / "shared",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (activation / "config").mkdir()
    shutil.copy2(_registry(tmp_path), activation / "config/platform-capability-registry.json")
    (activation / ".venv").symlink_to(Path(sys.executable).parent.parent, target_is_directory=True)
    shutil.copy2(
        REPO_ROOT / "scripts/capability-execution.sh",
        activation / "scripts/capability-execution.sh",
    )
    shutil.copy2(INTERACTIVE, activation / "scripts/hapax-codex")
    (activation / "scripts/lib").mkdir()
    shutil.copy2(REPO_ROOT / "scripts/lib/secret.sh", activation / "scripts/lib/secret.sh")
    binding = tmp_path / "activation-link"
    binding.symlink_to(activation, target_is_directory=True)
    env["HAPAX_SOURCE_ACTIVATE_WORKTREE"] = str(binding)
    env["PYTHONPATH"] = str(REPO_ROOT)
    tmux = tmp_path / "bin/tmux"
    runner_copy = tmp_path / "observed-runner"
    tmux.write_text(
        '#!/usr/bin/env bash\ncase "$1" in\nhas-session) exit 1;;\nnew-session)\n'
        f'  cp "${{@: -1}}" {shlex.quote(str(runner_copy))}\n'
        # Deployment advances between parent validation and child re-entry.
        f"  rm {shlex.quote(str(binding))}\n"
        f"  ln -s {shlex.quote(str(REPO_ROOT))} {shlex.quote(str(binding))}\n"
        # A pre-existing server does not inherit the invoking client's override.
        '  env -u HAPAX_SOURCE_ACTIVATE_WORKTREE bash "${@: -1}";;\n*) exit 0;;\nesac\n'
    )
    tmux.chmod(0o755)
    result = subprocess.run(
        [
            str(INTERACTIVE),
            "--session",
            "cx-amber",
            "--slot",
            "alpha",
            "--cd",
            str(REPO_ROOT),
            "--terminal",
            "tmux",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    argv = calls.read_text().splitlines()
    assert 'model="gpt-5.5"' in argv
    assert 'model_reasoning_effort="low"' in argv
    child = next(line for line in runner_copy.read_text().splitlines() if line.startswith("exec "))
    assert shlex.split(child)[1] == str(activation / "scripts/hapax-codex")


def _codex_idle(pane):
    text = (REPO_ROOT / "scripts/hapax-lane-idle-watchdog").read_text()
    start = text.index("is_codex_idle() {")
    end = text.index("\n}\n", start) + 3
    result = subprocess.run(
        ["bash", "-c", text[start:end] + '\nis_codex_idle "$1"', "test", pane], capture_output=True
    )
    return result.returncode == 0


@pytest.mark.parametrize("footer", ["", "gpt-5.5 ~/projects/test", "future-engine ~/projects/test"])
def test_watchdog_idle_is_independent_of_model(footer):
    assert _codex_idle("› \n" + footer)
    assert not _codex_idle("Working (2s)\n› \n" + footer)
    assert not _codex_idle("still streaming\n" + footer)


def _dispatch():
    loader = importlib.machinery.SourceFileLoader(
        "descriptor_dispatch", str(REPO_ROOT / "scripts/hapax-methodology-dispatch")
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


@pytest.mark.parametrize("profile", ["full", "spark"])
def test_dispatch_passes_selected_descriptor_route(tmp_path, monkeypatch, profile):
    mod = _dispatch()
    calls = []
    route = mod.PLATFORM_PATHS[("codex", "headless", profile)]
    validation = mod.Validation(True, "ok", None, None, False)
    with (
        patch.object(
            mod, "_sliced_call", side_effect=lambda args, env: calls.append((args, env)) or 0
        ),
        patch.object(mod, "allow_codex_p0_local_dispatch_fallback", return_value=False),
        patch.object(mod, "effective_dispatch_host", return_value="local"),
    ):
        assert mod.launch_codex_headless("task-x", "cx-amber", "prompt", validation, route) == 0
    args, env = calls[0]
    assert args[args.index("--execution-route") + 1] == f"codex.headless.{profile}"
    assert not any(arg.startswith("model=") for arg in args)


def test_codex_dispatch_carries_variant_and_lifecycle_together(tmp_path, monkeypatch):
    mod = _dispatch()
    registry = _registry(tmp_path)
    payload = json.loads(registry.read_text())
    for item in payload["routes"]:
        if item["route_id"] == "codex.headless.full":
            item.setdefault("descriptor_variants", []).append(
                {"variant_id": "receipt-test", "knobs_override": {"effort": "high"}}
            )
    registry.write_text(json.dumps(payload))
    recorded = tmp_path / "child.json"
    launcher = tmp_path / "launcher"
    launcher.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        f"Path({str(recorded)!r}).write_text(json.dumps({{"
        "'args': sys.argv[1:], 'receipt': os.environ['HAPAX_NATIVE_LIFECYCLE_RECEIPT']"
        "}))\n"
    )
    launcher.chmod(0o755)
    monkeypatch.setenv("HAPAX_PLATFORM_CAPABILITY_REGISTRY", str(registry))
    monkeypatch.setenv("HAPAX_METHODOLOGY_CODEX_HEADLESS", str(launcher))
    monkeypatch.setattr(mod, "_sliced_call", lambda args, env: subprocess.call(args, env=env))
    monkeypatch.setattr(mod, "allow_codex_p0_local_dispatch_fallback", lambda *args: False)
    monkeypatch.setattr(mod, "effective_dispatch_host", lambda *args: "local")
    receipt = tmp_path / "native.json"
    selected = "codex.headless.full#receipt-test"
    assert (
        mod.launch_codex_headless(
            "task-x",
            "cx-amber",
            "prompt",
            mod.Validation(True, "ok", None, None, False),
            mod.PLATFORM_PATHS[("codex", "headless", "full")],
            execution_route=selected,
            lifecycle_receipt=receipt,
        )
        == 0
    )
    child = json.loads(recorded.read_text())
    assert child["args"][:2] == ["--execution-route", selected]
    assert child["receipt"] == str(receipt)


def test_dispatch_rejects_missing_descriptor(tmp_path, monkeypatch):
    mod = _dispatch()
    monkeypatch.setenv("HAPAX_PLATFORM_CAPABILITY_REGISTRY", str(_registry(tmp_path, missing=True)))
    route = mod.PLATFORM_PATHS[("codex", "headless", "full")]
    with patch.object(mod, "_sliced_call") as launch:
        assert (
            mod.launch_codex_headless(
                "task-x", "cx-amber", "prompt", mod.Validation(True, "ok", None, None, False), route
            )
            == 9
        )
        launch.assert_not_called()


@pytest.mark.parametrize("launcher", LAUNCHERS)
def test_remote_auth_probe_carries_descriptor(tmp_path, launcher):
    env, args_file = _env_with_fake_codex(tmp_path)
    text = launcher.read_text()
    start = text.index("REMOTE_PREFLIGHT_PY='") + len("REMOTE_PREFLIGHT_PY='")
    code = text[start : text.index("'\n", start)]
    descriptor = resolve_execution_descriptor("codex.headless.full")
    expected = [
        "-c",
        f'model="{descriptor.model_id}"',
        "-c",
        f'model_reasoning_effort="{descriptor.effort}"',
    ]
    payload = {
        "required_dirs": [],
        "executables": [],
        "binaries": ["codex"],
        "workdir": str(tmp_path),
        "execution_args": expected,
    }
    env["HAPAX_REMOTE_PAYLOAD"] = base64.b64encode(json.dumps(payload).encode()).decode()
    result = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
    calls = args_file.with_suffix(".calls").read_text().rstrip("\0").split("\0")
    assert len(calls) == 1
    assert expected[1] in calls[0] and expected[3] in calls[0]


def test_descriptor_variant_and_supply_fingerprint(tmp_path):
    from shared.platform_capability_registry import (
        build_supply_vector,
        load_platform_capability_registry,
    )

    path = _registry(tmp_path)
    registry = load_platform_capability_registry(path)
    route = registry.require("codex.headless.full")
    assert build_supply_vector(route).route.model_fingerprint == "gpt-5.5"
    payload = json.loads(path.read_text())
    for item in payload["routes"]:
        if item["route_id"] == "codex.headless.full":
            item.setdefault("descriptor_variants", []).append(
                {"variant_id": "test-effort", "knobs_override": {"effort": "high"}}
            )
    path.write_text(json.dumps(payload))
    assert (
        resolve_execution_descriptor("codex.headless.full#test-effort", registry_path=path).effort
        == "high"
    )


@pytest.mark.parametrize("platform", ["claude", "vibe"])
def test_dispatch_other_harnesses_derive_identity(tmp_path, monkeypatch, platform):
    mod = _dispatch()
    calls = []
    registry = json.loads(REGISTRY.read_text())
    for item in registry["routes"]:
        if item["route_id"] == f"{platform}.headless.full":
            item["execution_descriptor"]["model_id"] = "gpt-5.5"  # sentinel, never served
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setenv("HAPAX_PLATFORM_CAPABILITY_REGISTRY", str(path))
    monkeypatch.setenv("HAPAX_METHODOLOGY_VIBE_LAUNCHER", str(REPO_ROOT / "scripts/hapax-vibe"))
    with (
        patch.object(
            mod, "_sliced_call", side_effect=lambda args, env: calls.append((args, env)) or 0
        ),
        patch.object(mod, "lane_worktree", return_value=tmp_path),
        patch.object(mod, "effective_dispatch_host", return_value="local"),
    ):
        if platform == "claude":
            result = mod.launch_claude_headless(
                "task-x", "lane", "prompt", mod.PLATFORM_PATHS[(platform, "headless", "full")]
            )
        else:
            result = mod.launch_vibe_headless(
                "task-x", "lane", "prompt", mod.Validation(True, "ok", None, None, False)
            )
    assert result == 0
    args, env = calls[0]
    assert env["HAPAX_CLAUDE_MODEL" if platform == "claude" else "VIBE_ACTIVE_MODEL"] == "gpt-5.5"


@pytest.mark.parametrize("launcher", LAUNCHERS)
@pytest.mark.parametrize(
    "binding", ["default_activation", "explicit_activation", "missing_activation"]
)
def test_installed_codex_identity_uses_activated_source_before_provider(
    tmp_path, launcher, binding
):
    env, calls = _env_with_fake_codex(tmp_path)
    native_home = Path(env["HOME"])
    installed = native_home / ".local/bin" / launcher.name
    installed.parent.mkdir(parents=True)
    installed.write_bytes(launcher.read_bytes())
    installed.chmod(0o755)
    # Match the existing installed launcher's sibling library, without invoking
    # credentials. This library is sourced before interactive argument parsing.
    (installed.parent / "lib").mkdir(exist_ok=True)
    (installed.parent / "lib/secret.sh").write_bytes(
        (REPO_ROOT / "scripts/lib/secret.sh").read_bytes()
    )
    env.pop("HAPAX_COUNCIL_DIR")
    env.pop("HAPAX_CODEX_HEADLESS_ALLOW")
    activation = native_home / ".cache/hapax/source-activation/worktree"
    activation.parent.mkdir(parents=True)
    if binding != "missing_activation":
        activation.symlink_to(REPO_ROOT, target_is_directory=True)
    if binding == "explicit_activation":
        # The declared activation must not inherit the legacy primary's runtime.
        env["HAPAX_COUNCIL_DIR"] = str(tmp_path / "stale-primary")
        env["HAPAX_SOURCE_ACTIVATE_WORKTREE"] = str(activation)
    if launcher == HEADLESS:
        args = ["--task", "fixture-only", "cx-amber", ""]
        expected = "governed initial message required"
        rc = 5
    else:
        args = ["--session", "not-a-codex-lane", "--terminal", "none"]
        expected = "invalid session"
        rc = 2
    result = subprocess.run(
        [str(installed), *args], env=env, cwd=tmp_path, text=True, capture_output=True
    )
    if binding == "missing_activation":
        assert result.returncode == 9
        assert "identity source unavailable" in result.stderr
        assert "hapax-source-activate" in result.stderr
    else:
        assert result.returncode == rc, result.stderr
        assert expected in result.stderr
    assert not calls.exists()
    assert not calls.with_suffix(".calls").exists()


def test_identity_helper_exports_one_binding_to_env_and_argv(tmp_path):
    descriptor = ExecutionDescriptor(model_id="gpt-5.5", effort="low").model_dump(mode="json")
    argv = ["-c", 'model="gpt-5.5"', "-c", 'model_reasoning_effort="low"']
    result = _identity_helper_output(
        tmp_path, json.dumps({"argv": argv, "descriptor": descriptor}), inspect_binding=True
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert json.loads(lines[0]) == argv
    assert json.loads(lines[1]) == descriptor
    assert lines[2:] == argv


@pytest.mark.parametrize("with_descriptor", [False, True])
def test_resolver_cli_preserves_argv_only_wire_format(
    tmp_path, monkeypatch, capsys, with_descriptor
):
    from shared.capability_execution import main

    monkeypatch.setenv("HAPAX_PLATFORM_CAPABILITY_REGISTRY", str(_registry(tmp_path)))
    args = ["--route", "codex.headless.full"]
    if with_descriptor:
        args.append("--with-descriptor")
    assert main(args) == 0
    output = json.loads(capsys.readouterr().out)
    expected = ["-c", 'model="gpt-5.5"', "-c", 'model_reasoning_effort="low"']
    if with_descriptor:
        assert output["argv"] == expected
        assert output["descriptor"] == ExecutionDescriptor(
            model_id="gpt-5.5", effort="low"
        ).model_dump(mode="json")
    else:
        assert output == expected
