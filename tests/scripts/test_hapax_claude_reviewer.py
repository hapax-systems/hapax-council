from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "scripts" / "hapax-claude-reviewer"


@pytest.fixture(autouse=True)
def _select_test_release(monkeypatch):
    monkeypatch.setenv("HAPAX_SOURCE_ACTIVATE_WORKTREE", str(REPO_ROOT))


def _fake_claude(path: Path) -> None:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "Path = __import__('pathlib').Path\n"
        "argv = sys.argv[1:]\n"
        "required_pairs = {\n"
        "    '--model': os.environ.get('HAPAX_FAKE_EXPECTED_MODEL', 'claude-opus-4-8'),\n"
        "    '--effort': os.environ.get('HAPAX_FAKE_EXPECTED_EFFORT', 'xhigh'),\n"
        "    '--tools': '',\n"
        "    '--allowedTools': '',\n"
        "    '--permission-mode': 'manual',\n"
        "    '--mcp-config': '{\"mcpServers\":{}}',\n"
        "}\n"
        "for key, value in required_pairs.items():\n"
        "    if key not in argv or argv[argv.index(key) + 1] != value:\n"
        "        print(f'missing required pair {key}={value!r}', file=sys.stderr)\n"
        "        sys.exit(13)\n"
        "for flag in ('--safe-mode', '--disable-slash-commands', '--no-session-persistence', '--strict-mcp-config'):\n"
        "    if flag not in argv:\n"
        "        print(f'missing required flag {flag}', file=sys.stderr)\n"
        "        sys.exit(13)\n"
        "if '--disallowedTools' not in argv:\n"
        "    print('missing disallowed tools', file=sys.stderr)\n"
        "    sys.exit(13)\n"
        "Path(os.environ['HAPAX_FAKE_CLAUDE_ARGV']).write_text(\n"
        "    json.dumps(argv), encoding='utf-8'\n"
        ")\n"
        "Path(os.environ['HAPAX_FAKE_CLAUDE_STDIN']).write_text(\n"
        "    sys.stdin.read(), encoding='utf-8'\n"
        ")\n"
        "if os.environ.get('HAPAX_FAKE_CLAUDE_ENV'):\n"
        "    Path(os.environ['HAPAX_FAKE_CLAUDE_ENV']).write_text(json.dumps({k:os.environ.get(k) for k in ['CLAUDE_CODE_EFFORT_LEVEL','CLAUDE_CODE_DISABLE_FAST_MODE']}))\n"
        "print('```yaml')\n"
        "print('verdict: accept')\n"
        "print('findings: []')\n"
        "print('checklist: {}')\n"
        "print('```')\n",
        encoding="utf-8",
    )
    path.chmod(0o700)


@pytest.mark.parametrize("model_assertion", [None, "claude-opus-4-8"])
def test_claude_reviewer_binds_declared_identity_and_disables_tools(
    tmp_path: Path, model_assertion: str | None
) -> None:
    fake = tmp_path / "claude"
    argv_path = tmp_path / "argv.json"
    stdin_path = tmp_path / "stdin.txt"
    env_path = tmp_path / "environment.json"
    _fake_claude(fake)

    env = {
        **os.environ,
        "HAPAX_FAKE_CLAUDE_ARGV": str(argv_path),
        "HAPAX_FAKE_CLAUDE_STDIN": str(stdin_path),
        "HAPAX_FAKE_CLAUDE_ENV": str(env_path),
    }
    assertion_args = ["--model", model_assertion] if model_assertion is not None else []
    result = subprocess.run(
        [sys.executable, str(WRAPPER), "--claude-bin", str(fake), *assertion_args],
        input="review packet",
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "```yaml\nverdict: accept\nfindings: []\nchecklist: {}\n```\n"
    assert stdin_path.read_text(encoding="utf-8") == "review packet"
    assert json.loads(env_path.read_text()) == {
        "CLAUDE_CODE_EFFORT_LEVEL": "xhigh",
        "CLAUDE_CODE_DISABLE_FAST_MODE": "1",
    }
    argv = json.loads(argv_path.read_text(encoding="utf-8"))
    assert argv[:5] == ["-p", "--model", "claude-opus-4-8", "--effort", "xhigh"]
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--allowedTools") + 1] == ""
    disallowed = argv[argv.index("--disallowedTools") + 1]
    assert "Bash" in disallowed
    assert "Read" in disallowed
    assert "LS" not in disallowed
    assert "MultiEdit" not in disallowed
    assert "NotebookRead" not in disallowed
    assert argv[argv.index("--permission-mode") + 1] == "manual"
    assert "--safe-mode" in argv
    assert "--disable-slash-commands" in argv
    assert "--no-session-persistence" in argv
    assert argv[argv.index("--mcp-config") + 1] == '{"mcpServers":{}}'
    assert "--strict-mcp-config" in argv
    system_prompt = argv[argv.index("--append-system-prompt") + 1]
    assert "exactly one fenced yaml" in system_prompt
    assert "invalid-output" in system_prompt
    assert "Do all reasoning silently" in system_prompt

    # Join the actual subprocess arguments to the declared route. Blind review
    # deliberately excludes the ambient instructions used by worker sessions.
    from shared.platform_capability_registry import NativeLoadSet

    registry = json.loads((REPO_ROOT / "config/platform-capability-registry.json").read_text())
    route = next(item for item in registry["routes"] if item["route_id"] == "claude.review.opus")
    declared = NativeLoadSet.model_validate(route["native_load_set"])
    assert len(declared.files) == 1
    configured = declared.files[0]
    assert (configured.root, configured.path, configured.kind) == (
        "native_home",
        "settings.json",
        "configuration",
    )
    assert configured.sha256 is None and configured.required is False
    assert declared.plugins == declared.skills == declared.mcp == []
    # Safe mode retains managed-policy hooks; an empty hook claim would exceed
    # the wrapper's evidence. No native load observation is made by this stub.
    assert declared.hooks is None
    assert declared.loading_flags == [
        "--safe-mode",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--strict-mcp-config",
    ]
    # Review every argument at this boundary: an added setting, directory or
    # instruction option must not pass just because the declared flags remain.
    assert argv == [
        "-p",
        "--model",
        "claude-opus-4-8",
        "--effort",
        "xhigh",
        "--tools",
        "",
        "--allowedTools",
        "",
        "--disallowedTools",
        disallowed,
        "--permission-mode",
        "manual",
        "--safe-mode",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--strict-mcp-config",
        "--append-system-prompt",
        system_prompt,
    ]
    assert "scripts/hapax-claude-reviewer" in declared.source_refs


def test_claude_reviewer_prefers_hapax_claude_bin_over_legacy_env(tmp_path: Path) -> None:
    preferred = tmp_path / "preferred-claude"
    legacy = tmp_path / "legacy-claude"
    argv_path = tmp_path / "argv.json"
    stdin_path = tmp_path / "stdin.txt"
    _fake_claude(preferred)
    legacy.write_text("#!/usr/bin/env bash\nexit 99\n", encoding="utf-8")
    legacy.chmod(0o700)

    env = {
        **os.environ,
        "HAPAX_CLAUDE_BIN": str(preferred),
        "CLAUDE_BIN": str(legacy),
        "HAPAX_FAKE_CLAUDE_ARGV": str(argv_path),
        "HAPAX_FAKE_CLAUDE_STDIN": str(stdin_path),
    }
    result = subprocess.run(
        [sys.executable, str(WRAPPER)],
        input="review packet",
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr
    assert argv_path.exists()
    assert stdin_path.read_text(encoding="utf-8") == "review packet"


def test_claude_reviewer_rejects_model_override(tmp_path: Path) -> None:
    fake = tmp_path / "claude"
    _fake_claude(fake)

    result = subprocess.run(
        [sys.executable, str(WRAPPER), "--claude-bin", str(fake), "--model", "sonnet"],
        input="review packet",
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 64
    assert "model must match the review route descriptor" in result.stderr
    assert "rerun without --model" in result.stderr


@pytest.mark.parametrize("effort", ["low", "high"])
def test_review_child_uses_descriptor_despite_stale_text_and_environment(tmp_path, effort):
    registry = json.loads((REPO_ROOT / "config/platform-capability-registry.json").read_text())
    route = next(item for item in registry["routes"] if item["route_id"] == "claude.review.opus")
    # Change only the declaration. The wrapper must not use the profile name,
    # the registry's free text, the caller's effort, or its cwd as identity.
    route["execution_descriptor"]["effort"] = effort
    route["execution_descriptor"]["model_id"] = "claude-sonnet-4-6"
    config = tmp_path / "registry.json"
    config.write_text(json.dumps(registry))
    fake = tmp_path / "claude"
    _fake_claude(fake)
    captured = tmp_path / "env.json"
    argv_path = tmp_path / "argv.json"
    result = subprocess.run(
        [sys.executable, str(WRAPPER), "--claude-bin", str(fake)],
        input="review packet",
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={
            **os.environ,
            "HAPAX_PLATFORM_CAPABILITY_REGISTRY": str(config),
            "CLAUDE_CODE_EFFORT_LEVEL": "max",
            "CLAUDE_CODE_DISABLE_FAST_MODE": "0",
            "HAPAX_FAKE_EXPECTED_EFFORT": effort,
            "HAPAX_FAKE_EXPECTED_MODEL": "claude-sonnet-4-6",
            "HAPAX_FAKE_CLAUDE_ENV": str(captured),
            "HAPAX_FAKE_CLAUDE_ARGV": str(argv_path),
            "HAPAX_FAKE_CLAUDE_STDIN": str(tmp_path / "stdin.txt"),
        },
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(captured.read_text()) == {
        "CLAUDE_CODE_EFFORT_LEVEL": effort,
        "CLAUDE_CODE_DISABLE_FAST_MODE": "1",
    }
    argv = json.loads(argv_path.read_text())
    assert argv[argv.index("--effort") + 1] == effort
    assert argv[argv.index("--model") + 1] == "claude-sonnet-4-6"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("execution_descriptor", None),
        ("model_id", "gpt-6-astra"),
        ("effort", "none"),
        ("context_mode", "extended_1m"),
        ("fast_mode", "fast"),
        ("quantization", "exl3_4_0bpw"),
    ],
)
def test_review_refuses_invalid_or_unmapped_descriptor_before_native_spawn(tmp_path, field, value):
    registry = json.loads((REPO_ROOT / "config/platform-capability-registry.json").read_text())
    route = next(item for item in registry["routes"] if item["route_id"] == "claude.review.opus")
    if field == "execution_descriptor":
        route.pop(field)
    else:
        route["execution_descriptor"][field] = value
    config = tmp_path / "registry.json"
    config.write_text(json.dumps(registry))
    fake = tmp_path / "claude"
    marker = tmp_path / "native-called"
    fake.write_text(
        f"#!/usr/bin/env python3\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\n"
    )
    fake.chmod(0o700)
    result = subprocess.run(
        [sys.executable, str(WRAPPER), "--claude-bin", str(fake)],
        input="review packet",
        capture_output=True,
        text=True,
        env={**os.environ, "HAPAX_PLATFORM_CAPABILITY_REGISTRY": str(config)},
        timeout=20,
    )
    assert result.returncode == 9, result.stderr
    assert "refusing undeclared invocation" in result.stderr
    assert not marker.exists()
    assert result.stdout == ""


@pytest.mark.parametrize(
    "binding",
    ["default", "explicit", "legacy_explicit", "missing", "invalid_explicit", "invalid_legacy"],
)
def test_copied_installed_reviewer_uses_declared_source(tmp_path, binding):
    home = tmp_path / "home"
    installed = home / ".local/bin/hapax-claude-reviewer"
    installed.parent.mkdir(parents=True)
    shutil.copy2(WRAPPER, installed)
    assert not installed.is_symlink()
    activation = home / ".cache/hapax/source-activation/worktree"
    activation.parent.mkdir(parents=True)
    if binding != "missing":
        activation.symlink_to(REPO_ROOT, target_is_directory=True)
    # A usable legacy primary must never substitute for a missing activation.
    primary = home / "projects/hapax-council"
    primary.parent.mkdir()
    primary.symlink_to(REPO_ROOT, target_is_directory=True)
    fake = tmp_path / "claude"
    _fake_claude(fake)
    env = {
        **os.environ,
        "HOME": str(home),
        "HAPAX_FAKE_CLAUDE_ARGV": str(tmp_path / "argv.json"),
        "HAPAX_FAKE_CLAUDE_STDIN": str(tmp_path / "stdin.txt"),
    }
    for key in ("HAPAX_SOURCE_ACTIVATE_WORKTREE", "HAPAX_COUNCIL_DIR"):
        env.pop(key, None)
    if binding == "explicit":
        env["HAPAX_SOURCE_ACTIVATE_WORKTREE"] = str(activation)
        env["HAPAX_COUNCIL_DIR"] = str(tmp_path / "unprovisioned-primary")
    elif binding == "legacy_explicit":
        activation.rename(home / "explicit-release")
        env["HAPAX_COUNCIL_DIR"] = str(home / "explicit-release")
    elif binding == "invalid_explicit":
        env["HAPAX_SOURCE_ACTIVATE_WORKTREE"] = str(tmp_path / "unprovisioned-explicit")
        env["HAPAX_COUNCIL_DIR"] = str(activation)
    elif binding == "invalid_legacy":
        env["HAPAX_COUNCIL_DIR"] = str(tmp_path / "unprovisioned-explicit")
    result = subprocess.run(
        [sys.executable, str(installed), "--claude-bin", str(fake)],
        input="installed review packet",
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
        timeout=20,
    )
    if binding in {"missing", "invalid_explicit", "invalid_legacy"}:
        assert result.returncode == 9
        assert "missing descriptor runtime" in result.stderr
        assert not (tmp_path / "argv.json").exists()
    else:
        assert result.returncode == 0, result.stderr
        assert (tmp_path / "stdin.txt").read_text() == "installed review packet"
        assert (tmp_path / "argv.json").exists()


def test_review_resolver_isolates_imports_in_selected_physical_release(tmp_path):
    launcher = tmp_path / "reviewer"
    launcher.symlink_to(WRAPPER)
    poison = tmp_path / "shared"
    poison.mkdir()
    (poison / "__init__.py").write_text("raise RuntimeError('ambient shared imported')\n")
    imported = tmp_path / "ambient-startup-imported"
    (tmp_path / "sitecustomize.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        f"if '-c' in sys.orig_argv: Path({str(imported)!r}).touch()\n"
    )
    # The resolver is itself a -c invocation: removing -I must trip this
    # marker. The wrapper and fake native executable are file invocations.
    env = {**os.environ, "PYTHONPATH": str(tmp_path)}
    # Prove the startup fixture runs without isolation before testing that the
    # actual wrapper's resolver excludes it. A dormant poison proves nothing.
    subprocess.run([sys.executable, "-c", "pass"], env=env, check=True, timeout=10)
    assert imported.exists()
    imported.unlink()
    fake = tmp_path / "claude"
    _fake_claude(fake)
    result = subprocess.run(
        [sys.executable, str(launcher), "--claude-bin", str(fake)],
        input="review packet",
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={
            **env,
            "HAPAX_FAKE_CLAUDE_ARGV": str(tmp_path / "argv.json"),
            "HAPAX_FAKE_CLAUDE_STDIN": str(tmp_path / "stdin.txt"),
        },
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "argv.json").exists()
    assert not imported.exists()


def test_review_resolver_freezes_activation_target_before_subprocess(tmp_path, monkeypatch):
    activation = tmp_path / "activation"
    activation.symlink_to(REPO_ROOT, target_is_directory=True)
    monkeypatch.setenv("HAPAX_SOURCE_ACTIVATE_WORKTREE", str(activation))
    loader = importlib.machinery.SourceFileLoader("reviewer_activation_test", str(WRAPPER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    original_run = subprocess.run
    calls = []

    def move_activation_then_run(command, **kwargs):
        calls.append(command)
        activation.unlink()
        activation.symlink_to(tmp_path / "unprovisioned-next-release", target_is_directory=True)
        return original_run(command, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", move_activation_then_run)
    binding = module._execution_binding()
    assert len(calls) == 1
    assert calls[0][0] == str(REPO_ROOT / ".venv/bin/python")
    assert calls[0][4] == str(REPO_ROOT)
    assert binding["argv"] == ["--model", "claude-opus-4-8", "--effort", "xhigh"]


@pytest.mark.parametrize(
    "resolver_output",
    [
        None,
        "[]",
        '{"argv":["--model","opus"]}',
        json.dumps(
            {
                "descriptor": {
                    "model_id": "claude-opus-4-8",
                    "effort": "xhigh",
                    "context_mode": "standard",
                    "fast_mode": "off",
                    "quantization": "none",
                },
                "argv": ["--model", "claude-opus-4-8", "--effort", "xhigh"],
                "env": {"CLAUDE_CODE_EFFORT_LEVEL": "low", "CLAUDE_CODE_DISABLE_FAST_MODE": "1"},
            }
        ),
    ],
)
def test_review_refuses_missing_runtime_or_malformed_binding(tmp_path, resolver_output):
    root = tmp_path / "release"
    script = root / "scripts/hapax-claude-reviewer"
    script.parent.mkdir(parents=True)
    shutil.copy2(WRAPPER, script)
    if resolver_output is not None:
        python = root / ".venv/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text(f"#!{sys.executable}\nprint({resolver_output!r})\n")
        python.chmod(0o700)
    native = tmp_path / "native"
    marker = tmp_path / "native-called"
    native.write_text(
        f"#!{sys.executable}\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\n"
    )
    native.chmod(0o700)
    result = subprocess.run(
        [sys.executable, str(script), "--claude-bin", str(native)],
        input="review packet",
        capture_output=True,
        text=True,
        env={**os.environ, "HAPAX_SOURCE_ACTIVATE_WORKTREE": str(root)},
        timeout=20,
    )
    assert result.returncode == 9, result.stderr
    assert "refusing undeclared invocation" in result.stderr
    assert not marker.exists()
    assert result.stdout == ""


@pytest.mark.parametrize(
    "failure", [OSError("fixture launch error"), subprocess.TimeoutExpired("resolver", 15)]
)
def test_resolver_system_failure_refuses_with_remedy(monkeypatch, capsys, failure):
    loader = importlib.machinery.SourceFileLoader("reviewer_failure_test", str(WRAPPER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    calls = []

    def fail_external_resolution(command, **kwargs):
        calls.append(command)
        raise failure

    # Inject at the external subprocess boundary, not the binding predicate.
    monkeypatch.setattr(module.subprocess, "run", fail_external_resolution)
    assert module.main([]) == 9
    assert len(calls) == 1 and "shared.capability_execution" in calls[0][3]
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "refusing undeclared invocation" in captured.err
    assert "next action: repair the selected release descriptor/runtime" in captured.err


def test_resolver_nonzero_without_diagnostic_refuses_with_remedy(tmp_path):
    root = tmp_path / "release"
    wrapper = root / "scripts/hapax-claude-reviewer"
    wrapper.parent.mkdir(parents=True)
    shutil.copy2(WRAPPER, wrapper)
    python = root / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(f"#!{sys.executable}\nimport sys\nsys.exit(8)\n")
    python.chmod(0o700)
    result = subprocess.run(
        [sys.executable, str(wrapper)],
        capture_output=True,
        text=True,
        input="packet",
        env={**os.environ, "HAPAX_SOURCE_ACTIVATE_WORKTREE": str(root)},
        timeout=20,
    )
    assert result.returncode == 9
    assert "descriptor resolver failed without a diagnostic" in result.stderr
    assert "next action: repair the selected release descriptor/runtime" in result.stderr
    assert result.stdout == ""


def test_claude_reviewer_missing_binary_path_is_legible(tmp_path: Path) -> None:
    missing = tmp_path / "missing-claude"

    result = subprocess.run(
        [sys.executable, str(WRAPPER), "--claude-bin", str(missing)],
        input="review packet",
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "failed to launch" in result.stderr
    assert str(missing) in result.stderr
    assert "HAPAX_CLAUDE_BIN" in result.stderr
    assert "rerun the review dispatch" in result.stderr


def test_local_claude_cli_help_documents_no_tools_surface() -> None:
    claude_bin = os.environ.get("HAPAX_CLAUDE_BIN") or os.environ.get("CLAUDE_BIN") or "claude"
    if shutil.which(claude_bin) is None and not Path(claude_bin).exists():
        pytest.skip("local Claude CLI is not installed")

    result = subprocess.run(
        [claude_bin, "--help"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    help_text = result.stdout
    normalized_help = " ".join(help_text.split())
    assert "--tools <tools...>" in help_text
    assert 'Use "" to disable all tools' in normalized_help
    assert "--allowedTools" in help_text
    assert "--disallowedTools" in help_text
    assert "--safe-mode" in help_text
    assert "--disable-slash-commands" in help_text
    assert "--no-session-persistence" in help_text
    assert "--strict-mcp-config" in help_text
    assert '"manual"' in help_text


def test_claude_reviewer_omits_child_stdout_on_nonzero_exit(tmp_path: Path) -> None:
    fake = tmp_path / "claude"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "print('quota wall text that must not become review stdout')\n"
        "print('rate limited', file=sys.stderr)\n"
        "sys.exit(42)\n",
        encoding="utf-8",
    )
    fake.chmod(0o700)

    result = subprocess.run(
        [sys.executable, str(WRAPPER), "--claude-bin", str(fake)],
        input="review packet",
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 42
    assert result.stdout == ""
    assert "rate limited" in result.stderr
    assert "claude single-line stdout omitted from classifier" in result.stderr
    assert "quota wall text that must not become review stdout" not in result.stderr
    assert "stdout omitted" in result.stderr
    assert "single-line stdout is represented only by a wrapper-authored" in result.stderr


def test_claude_reviewer_preserves_stdout_only_quota_wall_for_classifier(
    tmp_path: Path,
) -> None:
    fake = tmp_path / "claude"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        'print("You\'ve hit your weekly limit - resets 5pm (America/Chicago)")\n'
        "sys.exit(75)\n",
        encoding="utf-8",
    )
    fake.chmod(0o700)

    result = subprocess.run(
        [sys.executable, str(WRAPPER), "--claude-bin", str(fake)],
        input="review packet",
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 75
    assert result.stdout == ""
    assert "claude stdout quota-wall diagnostic observed" in result.stderr
    assert "weekly limit" not in result.stderr
    assert "stdout omitted" in result.stderr


def test_claude_reviewer_preserves_single_line_stdout_diagnostic_with_child_stderr(
    tmp_path: Path,
) -> None:
    fake = tmp_path / "claude"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "print('non-quota stderr noise', file=sys.stderr)\n"
        'print("You\'ve hit your weekly limit - resets 5pm (America/Chicago)")\n'
        "sys.exit(75)\n",
        encoding="utf-8",
    )
    fake.chmod(0o700)

    result = subprocess.run(
        [sys.executable, str(WRAPPER), "--claude-bin", str(fake)],
        input="review packet",
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 75
    assert result.stdout == ""
    assert "non-quota stderr noise" in result.stderr
    assert "claude stdout quota-wall diagnostic observed" in result.stderr
    assert "weekly limit" not in result.stderr


def test_claude_reviewer_timeout_terminates_child_process_group(tmp_path: Path) -> None:
    fake = tmp_path / "claude"
    marker = tmp_path / "process-group.txt"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import os, subprocess, sys, time\n"
        "from pathlib import Path\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "Path(os.environ['HAPAX_FAKE_CLAUDE_PROCESS_GROUP']).write_text(\n"
        "    f'{os.getpgrp()}\\n{os.getpid()}\\n{child.pid}\\n', encoding='utf-8'\n"
        ")\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    fake.chmod(0o700)

    result = subprocess.run(
        [
            sys.executable,
            str(WRAPPER),
            "--claude-bin",
            str(fake),
            "--timeout-seconds",
            "0.2",
        ],
        input="review packet",
        capture_output=True,
        text=True,
        env={**os.environ, "HAPAX_FAKE_CLAUDE_PROCESS_GROUP": str(marker)},
        cwd=REPO_ROOT,
        timeout=10,
    )

    assert result.returncode == 124
    assert result.stdout == ""
    assert "process group terminated" in result.stderr
    pgid = int(marker.read_text(encoding="utf-8").splitlines()[0])
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        live = subprocess.run(
            ["ps", "-o", "pid=,stat=,cmd=", "-g", str(pgid)],
            capture_output=True,
            text=True,
            check=False,
        )
        pytest.fail(f"Claude reviewer left live process-group members:\n{live.stdout}")


def test_claude_reviewer_sigterm_terminates_child_process_group(tmp_path: Path) -> None:
    fake = tmp_path / "claude"
    marker = tmp_path / "process-group.txt"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import os, subprocess, sys, time\n"
        "from pathlib import Path\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "Path(os.environ['HAPAX_FAKE_CLAUDE_PROCESS_GROUP']).write_text(\n"
        "    f'{os.getpgrp()}\\n{os.getpid()}\\n{child.pid}\\n', encoding='utf-8'\n"
        ")\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    fake.chmod(0o700)

    proc = subprocess.Popen(
        [sys.executable, str(WRAPPER), "--claude-bin", str(fake)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "HAPAX_FAKE_CLAUDE_PROCESS_GROUP": str(marker)},
        cwd=REPO_ROOT,
    )
    assert proc.stdin is not None
    proc.stdin.write("review packet")
    proc.stdin.close()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not marker.exists():
        time.sleep(0.05)
    assert marker.exists()
    pgid = int(marker.read_text(encoding="utf-8").splitlines()[0])

    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=10)
    assert proc.returncode == 128 + signal.SIGTERM
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        live = subprocess.run(
            ["ps", "-o", "pid=,stat=,cmd=", "-g", str(pgid)],
            capture_output=True,
            text=True,
            check=False,
        )
        pytest.fail(f"Claude reviewer left live process-group members:\n{live.stdout}")


def test_claude_reviewer_invalid_timeout_env_is_legible(tmp_path: Path) -> None:
    fake = tmp_path / "claude"
    _fake_claude(fake)
    argv_path = tmp_path / "argv.json"
    stdin_path = tmp_path / "stdin.txt"

    result = subprocess.run(
        [sys.executable, str(WRAPPER), "--claude-bin", str(fake)],
        input="review packet",
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HAPAX_CLAUDE_REVIEWER_TIMEOUT_SECONDS": "20m",
            "HAPAX_FAKE_CLAUDE_ARGV": str(argv_path),
            "HAPAX_FAKE_CLAUDE_STDIN": str(stdin_path),
        },
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr
    assert "invalid HAPAX_CLAUDE_REVIEWER_TIMEOUT_SECONDS" in result.stderr
    assert "using default 1140s" in result.stderr


# --- M99: the tool-intent turn end ----------------------------------------------------
# The seat runs with `--tools ""`. A reply that plans a read ("Let me inspect the classifier
# source…") ends its one-shot turn with no verdict, which no parser can rescue. Captured bytes:
# claude-1 on #4740 at 5f1f60154 (dev15, 2026-09-25).
TOOL_INTENT_REPLY = (
    REPO_ROOT / "tests/fixtures/review-reply-claude-4740-5f1f60154-tool-intent-turn-end.txt"
).read_text(encoding="utf-8")
FENCED_ACCEPT = "```yaml\nverdict: accept\nfindings: []\nchecklist: {}\n```\n"
_BINDING = {
    "descriptor": {"model_id": "claude-opus-4-8"},
    "argv": ["--model", "claude-opus-4-8", "--effort", "xhigh"],
    "env": {},
}


def _load_wrapper(name: str):
    loader = importlib.machinery.SourceFileLoader(name, str(WRAPPER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _scripted_claude(
    monkeypatch, module, replies: list[tuple[int, str]], *, seconds_per_call: float = 0.0
) -> list[dict]:
    """Replace the child with scripted (returncode, stdout) replies; record every call.

    A fake monotonic clock advances ``seconds_per_call`` per child run, so the shared
    deadline is observable exactly.
    """

    calls: list[dict] = []
    clock = [1000.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])

    def run(cmd, *, prompt, timeout_seconds, execution_env):
        calls.append({"cmd": list(cmd), "prompt": prompt, "timeout_seconds": timeout_seconds})
        clock[0] += seconds_per_call
        if len(calls) > len(replies):
            raise AssertionError(f"unexpected claude invocation #{len(calls)}")
        returncode, stdout = replies[len(calls) - 1]
        return subprocess.CompletedProcess(cmd, returncode, stdout, "")

    monkeypatch.setattr(module, "_execution_binding", lambda: _BINDING)
    monkeypatch.setattr(module, "_run_claude", run)
    monkeypatch.setattr(module.sys, "stdin", io.StringIO("review packet"))
    return calls


def test_the_captured_reply_names_no_verdict() -> None:
    module = _load_wrapper("reviewer_m99_predicate")
    assert module._reply_names_no_verdict(TOOL_INTENT_REPLY)
    assert module._reply_names_no_verdict("")
    assert module._reply_names_no_verdict("   \n")


@pytest.mark.parametrize(
    "reply",
    [
        FENCED_ACCEPT,
        "```yaml\nverdict: block\nfindings: []\nchecklist: {}\n```\n",
        # the parser, not the wrapper, judges a verdict wrapped in prose or a sentinel
        "Here is my review.\n```yaml\nverdict: accept\nfindings: []\n```\n<!-- done -->",
        # fence-free raw YAML is a verdict the dispatcher can parse
        "verdict: accept-with-findings\nfindings: []\nchecklist: {}\n",
        '  "verdict": block\n',
        # a malformed verdict is still a verdict: re-asking would shop for a different one
        "```yaml\nverdict: [unterminated\n```\n",
    ],
)
def test_a_reply_that_names_a_verdict_is_never_reasked(monkeypatch, capsys, reply) -> None:
    module = _load_wrapper("reviewer_m99_verdict")
    calls = _scripted_claude(monkeypatch, module, [(0, reply)])

    assert module.main([]) == 0
    assert len(calls) == 1
    out = capsys.readouterr()
    assert out.out == reply
    assert out.err == ""


@pytest.mark.parametrize("returncode", [1, 2, 124, 137])
def test_a_nonzero_exit_is_never_reasked(monkeypatch, capsys, returncode) -> None:
    # A quota wall, launch failure or timeout is the CLI speaking; a re-ask would spend into
    # the wall and could launder it into a review.
    module = _load_wrapper("reviewer_m99_nonzero")
    calls = _scripted_claude(monkeypatch, module, [(returncode, TOOL_INTENT_REPLY)])

    assert module.main([]) == returncode
    assert len(calls) == 1
    out = capsys.readouterr()
    assert out.out == ""
    # stderr carries the wrapper's nonzero diagnostic and nothing from the re-ask path
    assert "claude exited nonzero" in out.err
    assert module.REASK_DIAGNOSTIC not in out.err
    assert module.REASK_SKIPPED_DIAGNOSTIC not in out.err
    # the model's (untrusted) stdout is never laundered into stderr either
    assert "Let me inspect" not in out.err


def test_a_second_reply_with_no_verdict_is_returned_without_a_third_attempt(
    monkeypatch, capsys
) -> None:
    module = _load_wrapper("reviewer_m99_bounded")
    calls = _scripted_claude(monkeypatch, module, [(0, TOOL_INTENT_REPLY), (0, TOOL_INTENT_REPLY)])

    assert module.main([]) == 0
    assert len(calls) == 2
    out = capsys.readouterr()
    assert out.out == TOOL_INTENT_REPLY
    assert out.err.count(module.REASK_DIAGNOSTIC) == 1


def test_no_reask_when_the_shared_deadline_leaves_too_little_time(monkeypatch, capsys) -> None:
    module = _load_wrapper("reviewer_m99_deadline")
    calls = _scripted_claude(monkeypatch, module, [(0, TOOL_INTENT_REPLY)])

    assert module.main(["--timeout-seconds", str(module.REASK_MIN_REMAINING_SECONDS - 1)]) == 0
    assert len(calls) == 1
    out = capsys.readouterr()
    assert out.out == TOOL_INTENT_REPLY
    assert module.REASK_SKIPPED_DIAGNOSTIC in out.err


def test_a_reply_with_no_verdict_is_reasked_once_under_the_same_route(monkeypatch, capsys) -> None:
    module = _load_wrapper("reviewer_m99_reask")
    calls = _scripted_claude(
        monkeypatch, module, [(0, TOOL_INTENT_REPLY), (0, FENCED_ACCEPT)], seconds_per_call=100.0
    )

    assert module.main(["--timeout-seconds", "600"]) == 0
    assert len(calls) == 2
    # same binary, model, effort, tool denial and system prompt: a re-ask never changes route
    assert calls[1]["cmd"] == calls[0]["cmd"]
    # the packet is replayed whole, followed by the correction; the first reply is not echoed
    assert calls[1]["prompt"].startswith("review packet")
    assert module.REASK_CORRECTION in calls[1]["prompt"]
    assert TOOL_INTENT_REPLY not in calls[1]["prompt"]
    # one deadline for both calls: the first run spent 100 s of 600, so the re-ask gets 500
    assert calls[0]["timeout_seconds"] == 600
    assert calls[1]["timeout_seconds"] == 500
    out = capsys.readouterr()
    assert out.out == FENCED_ACCEPT
    assert out.err.count(module.REASK_DIAGNOSTIC) == 1


def test_system_prompt_states_the_seat_has_no_tools_and_the_packet_is_complete() -> None:
    module = _load_wrapper("reviewer_m99_prompt")
    prompt = " ".join(module.STRICT_REVIEW_SYSTEM_PROMPT.split())
    assert "You have no tools" in prompt
    assert "the packet is the complete evidence" in prompt
    assert "Never announce an inspection" in prompt
    # the correction restates the same contract for the one re-ask
    assert "You have no tools" in module.REASK_CORRECTION


@pytest.mark.skipif(
    os.environ.get("HAPAX_RUN_CLAUDE_REVIEWER_REAL_SMOKE") != "1",
    reason="real Claude CLI no-tools probe is opt-in and uses local subscription quota",
)
def test_claude_reviewer_real_cli_no_tools_probe() -> None:
    result = subprocess.run(
        [sys.executable, str(WRAPPER)],
        input=(
            "No-tools probe. Do not use or request a shell. If a Bash tool is "
            "available, it would be unsafe to use it here. Emit only the strict "
            "review YAML: verdict accept, findings [], checklist {}."
        ),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=180,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.startswith("```yaml\n")
    assert result.stdout.endswith("\n```\n")
    assert "tool_use" not in result.stdout.lower()
    assert "bash" not in result.stdout.lower()


@pytest.mark.skipif(
    os.environ.get("HAPAX_RUN_CLAUDE_REVIEWER_REAL_SMOKE") != "1",
    reason="real Claude CLI tool-surface probe is opt-in and uses local subscription quota",
)
def test_claude_cli_reports_empty_tools_with_wrapper_equivalent_flags() -> None:
    prompt = (
        "Use the actual Bash tool to run exactly: printf "
        "HAPAX_CLAUDE_TOOL_PROBE_20260709. If no actual Bash tool is available, "
        "say exactly NO_ACTUAL_TOOL_AVAILABLE. Do not simulate tool output."
    )
    common = [
        "claude",
        "-p",
        "--verbose",
        "--model",
        "claude-opus-4-8",
        "--effort",
        "xhigh",
        "--safe-mode",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--strict-mcp-config",
        "--output-format",
        "stream-json",
    ]
    result = subprocess.run(
        [
            *common,
            "--tools",
            "",
            "--allowedTools",
            "",
            "--disallowedTools",
            "Agent,Bash,Edit,Glob,Grep,NotebookEdit,Read,Task,TodoWrite,WebFetch,WebSearch,Write",
            "--permission-mode",
            "manual",
            prompt,
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=180,
    )

    assert result.returncode == 0, result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    init = next(
        event
        for event in events
        if event.get("type") == "system" and event.get("subtype") == "init"
    )
    assert init["tools"] == []
    assert init["mcp_servers"] == []
    tool_uses = [
        item
        for event in events
        for item in event.get("message", {}).get("content", [])
        if item.get("type") == "tool_use"
    ]
    assert tool_uses == []
    result_event = next(event for event in events if event.get("type") == "result")
    assert result_event["result"] == "NO_ACTUAL_TOOL_AVAILABLE"
