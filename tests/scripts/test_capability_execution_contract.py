"""Execution identity is registry-derived at every invocation boundary."""

from __future__ import annotations

import base64
import importlib.machinery
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

from shared.capability_execution import (
    ExecutionIdentityError,
    reject_codex_identity_overrides,
    resolve_execution_descriptor,
)
from shared.codex_execution_receipt import check_rollout
from shared.codex_execution_receipt import main as receipt_main
from shared.platform_capability_registry import ModelId

REPO_ROOT = Path(__file__).resolve().parents[2]
HEADLESS = REPO_ROOT / "scripts/hapax-codex-headless"
INTERACTIVE = REPO_ROOT / "scripts/hapax-codex"
REGISTRY = REPO_ROOT / "config/platform-capability-registry.json"
LAUNCHERS = (INTERACTIVE, HEADLESS)
IDENTITY_SOURCES = (
    *LAUNCHERS,
    REPO_ROOT / "scripts/hapax-methodology-dispatch",
    REPO_ROOT / "scripts/capability-execution.sh",
    REPO_ROOT / "scripts/hapax-lane-idle-watchdog",
)


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


def _launch(launcher, env, route="codex.headless.full", extra=()):
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
            str(REPO_ROOT),
            "--terminal",
            "none",
        ]
    if extra:
        args += ["--", *extra]
    return subprocess.run(
        [str(launcher), *args], capture_output=True, text=True, env=env, timeout=20
    )


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
    "failure", ["missing_descriptor", "missing_registry", "unknown_route", "missing_runtime"]
)
def test_missing_descriptor_is_refused_before_invocation(tmp_path, launcher, failure):
    env, args_file = _env_with_fake_codex(tmp_path)
    path = _registry(tmp_path, missing=failure == "missing_descriptor")
    if failure == "missing_registry":
        path.unlink()
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
    assert not args_file.with_suffix(".calls").exists()


@pytest.mark.parametrize(
    "args",
    [
        ["--model", "external"],
        ["-mexternal"],
        ["--model=external"],
        ["-c", 'model="external"'],
        ["--config=model_reasoning_effort=high"],
        ["-cmodel=external"],
        ["-c=model=external"],
        ["-c=model_reasoning_effort=low"],
        ["--profile", "external"],
        ["--oss"],
        ["-c", 'profiles.test."model"="external"'],
    ],
)
def test_model_and_effort_overrides_are_refused(args):
    with pytest.raises(ExecutionIdentityError, match="remedy:"):
        reject_codex_identity_overrides(args)


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


@pytest.mark.parametrize("contents", ["", '{"type":"turn_context","payload":{}}\n', "broken\n"])
def test_incomplete_receipt_never_claims_a_match(tmp_path, contents):
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text(contents)
    assert receipt_main(["--route", "codex.headless.full", "--rollout", str(rollout)]) != 0


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
