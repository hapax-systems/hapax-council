import fcntl
import json
import os
import subprocess
import textwrap
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-claude-headless"
VISIBLE = REPO_ROOT / "scripts" / "hapax-claude"


def _stub_bin(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text("#!/usr/bin/env bash\n" + textwrap.dedent(body))
    path.chmod(0o755)


def _headless_env(home: Path, bin_dir: Path, pipe_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    # Host-independence: a remotely-dispatched test runner (appendix lanes)
    # carries its OWN dispatch/identity env; scrub it so the launcher under
    # test sees only what each test sets explicitly.
    for var in (
        "HAPAX_DISPATCH_HOST",
        "HAPAX_DISPATCH_HOST_FALLBACK",
        "HAPAX_SESSION_ID",
        "CLAUDE_CODE_SESSION_ID",
        "HAPAX_AGENT_ROLE",
        "HAPAX_AGENT_NAME",
        "CLAUDE_ROLE",
        "HAPAX_WORKTREE_ROLE",
        "HAPAX_METHODOLOGY_DISPATCH_TASK",
        "HAPAX_METHODOLOGY_DISPATCH_EXTERNAL",
        "HAPAX_METHODOLOGY_DISPATCH_PROFILE",
        "HAPAX_METHODOLOGY_DISPATCH_REDEMPTION_TOKEN",
        "HAPAX_METHODOLOGY_DISPATCH_MESSAGE_ID",
        "HAPAX_METHODOLOGY_DISPATCH_ROUTE_DECISION_REF",
        "HAPAX_METHODOLOGY_DISPATCH_AUTHORITY_CASE",
        "HAPAX_METHODOLOGY_DISPATCH_PARENT_SPEC",
        "HAPAX_CLAUDE_BIN",
        "HAPAX_CLAUDE_BIN_PATH",
        "NPM_CONFIG_PREFIX",
    ):
        env.pop(var, None)
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    env["HAPAX_CLAUDE_HEADLESS_ALLOW"] = "1"
    # Don't re-exec into a real systemd scope from the test sandbox.
    env["HAPAX_SDLC_SLICE_ATTACH"] = "0"
    env["HAPAX_CLAUDE_HEADLESS_PIPE_DIR"] = str(pipe_dir)
    # Fast loop so a respawn regression spins (and is caught by the timeout)
    # rather than waiting 30s between iterations.
    env["HAPAX_CLAUDE_HEADLESS_RESTART_BACKOFF_SECONDS"] = "0"
    return env


def _write_activation_redemption_stub(home: Path, marker: Path) -> None:
    stub = (
        home
        / ".cache"
        / "hapax"
        / "source-activation"
        / "worktree"
        / "shared"
        / "governance"
        / "dispatch_redemption.py"
    )
    stub.parent.mkdir(parents=True)
    (stub.parents[1] / "__init__.py").write_text("", encoding="utf-8")
    (stub.parent / "__init__.py").write_text("", encoding="utf-8")
    stub.write_text(
        "from pathlib import Path\n"
        "import os\n"
        "Path(os.environ['HAPAX_TEST_ACTIVATION_IMPORT_MARKER']).write_text("
        "'imported\\n', encoding='utf-8')\n"
        "class LaunchRedemptionContext:\n"
        "    def __init__(self, **kwargs): pass\n"
        "class LaunchRedemptionRequest:\n"
        "    def __init__(self, **kwargs): pass\n"
        "class Response:\n"
        "    ok = False\n"
        "    reason = 'socket_unavailable:test'\n"
        "def redeem_launch_via_socket(_request):\n"
        "    return Response()\n",
        encoding="utf-8",
    )
    marker.parent.mkdir(parents=True, exist_ok=True)


def test_headless_defaults_to_disabled_without_governed_enable(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = "/usr/bin:/bin"
    env.pop("HAPAX_CLAUDE_HEADLESS_ALLOW", None)
    env.pop("HAPAX_CLAUDE_HEADLESS_ENABLE_FILE", None)

    result = subprocess.run(
        [str(SCRIPT), "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 77
    assert "disabled until governed enable exists" in result.stderr


def test_headless_source_prepends_workdir_scripts_to_path() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'PATH="$WORKDIR/scripts:$PATH"' in text, (
        "headless wrapper must prepend $WORKDIR/scripts to PATH"
    )


def test_headless_source_contains_no_generic_work_pool_prompt() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "claim the next" not in text
    assert "highest-WSJF" not in text
    assert "Never stop" not in text
    assert "governed initial message required" in text
    assert "refusing mutating launch without --task" in text
    assert "Do not create, select, or claim other work from the task pool." in text
    assert "--task TASK_ID" in text
    assert "HAPAX_METHODOLOGY_DISPATCH_TASK" in text


def test_claude_headless_scrubs_dispatch_redemption_binding_after_redeem() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "scrub_dispatch_redemption_binding_env()" in text
    assert "validate_dispatch_redemption_authority\n  scrub_dispatch_redemption_binding_env" in text
    for name in (
        "HAPAX_METHODOLOGY_DISPATCH_REDEMPTION_TOKEN",
        "HAPAX_METHODOLOGY_DISPATCH_MESSAGE_ID",
        "HAPAX_METHODOLOGY_DISPATCH_ROUTE_DECISION_REF",
        "HAPAX_METHODOLOGY_DISPATCH_AUTHORITY_CASE",
        "HAPAX_METHODOLOGY_DISPATCH_PARENT_SPEC",
    ):
        assert f"unset {name}" in text


def test_claude_headless_external_workdir_fails_closed_without_redemption_binding(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "reins"
    workdir.mkdir(parents=True)
    fake_capability = tmp_path / "same-user-capability.json"
    fake_capability.write_text('{"kind":"dispatch","capability_id":"fake"}\n', encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude_called = tmp_path / "claude-called"
    _stub_bin(bin_dir, "claude", f": > {claude_called}\nexit 0\n")
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_CLAUDE_HEADLESS_WORKDIR"] = str(workdir)
    env["HAPAX_METHODOLOGY_DISPATCH_CAPABILITY"] = str(fake_capability)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 17
    assert "missing dispatch redemption binding env" in result.stderr
    assert "requires live methodology dispatch redemption" in result.stderr
    assert not claude_called.exists()


def test_claude_headless_outside_projects_workdir_fails_closed_without_redemption_binding(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    workdir = tmp_path / "outside" / "reins"
    workdir.mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude_called = tmp_path / "claude-called"
    _stub_bin(bin_dir, "claude", f": > {claude_called}\nexit 0\n")
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_CLAUDE_HEADLESS_WORKDIR"] = str(workdir)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 17
    assert "missing dispatch redemption binding env" in result.stderr
    assert "requires live methodology dispatch redemption" in result.stderr
    assert not claude_called.exists()


def test_claude_headless_external_workdir_requires_live_redemption_authority(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "reins"
    workdir.mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude_called = tmp_path / "claude-called"
    _stub_bin(bin_dir, "claude", f": > {claude_called}\nexit 0\n")
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_CLAUDE_HEADLESS_WORKDIR"] = str(workdir)
    # A self-minted token with full binding env still fails closed: redemption
    # happens at the fixed governor socket, which no caller can pre-create.
    env["HAPAX_METHODOLOGY_DISPATCH_REDEMPTION_TOKEN"] = "self-minted"
    env["HAPAX_METHODOLOGY_DISPATCH_MESSAGE_ID"] = "019f-fake"
    env["HAPAX_METHODOLOGY_DISPATCH_ROUTE_DECISION_REF"] = "route-decision:fake"
    env["HAPAX_METHODOLOGY_DISPATCH_AUTHORITY_CASE"] = "CASE-CAPACITY-ROUTING-001"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 17
    assert "dispatch redemption refused" in result.stderr
    assert "requires live methodology dispatch redemption" in result.stderr
    assert not claude_called.exists()


def test_claude_headless_external_workdir_redeems_before_spoofed_lifecycle_scripts(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "reins"
    workdir.mkdir(parents=True)
    (workdir / "scripts").mkdir()
    spoofed_claim = tmp_path / "spoofed-cc-claim-called"
    spoofed_mkdir = tmp_path / "spoofed-mkdir-called"
    _stub_bin(workdir / "scripts", "cc-claim", f": > {spoofed_claim}\nexit 0\n")
    _stub_bin(workdir / "scripts", "cc-close", "exit 0\n")
    _stub_bin(workdir / "scripts", "mkdir", f': > {spoofed_mkdir}\nexec /usr/bin/mkdir "$@"\n')

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude_called = tmp_path / "claude-called"
    _stub_bin(bin_dir, "claude", f": > {claude_called}\nexit 0\n")
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_CLAUDE_HEADLESS_WORKDIR"] = str(workdir)
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 17
    assert "missing dispatch redemption binding env" in result.stderr
    assert "requires live methodology dispatch redemption" in result.stderr
    assert not spoofed_claim.exists()
    assert not spoofed_mkdir.exists()
    assert not claude_called.exists()


def test_claude_headless_redemption_ignores_python_override(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "reins"
    workdir.mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude_called = tmp_path / "claude-called"
    _stub_bin(bin_dir, "claude", f": > {claude_called}\nexit 0\n")
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_CLAUDE_HEADLESS_WORKDIR"] = str(workdir)
    env["HAPAX_REDEMPTION_PYTHON"] = "/bin/true"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 17
    assert "missing dispatch redemption binding env" in result.stderr
    assert "requires live methodology dispatch redemption" in result.stderr
    assert not claude_called.exists()


def test_claude_headless_plain_copy_uses_source_activation_verifier(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "reins"
    workdir.mkdir(parents=True)
    deployed = home / ".local" / "bin" / "hapax-claude-headless"
    deployed.parent.mkdir(parents=True)
    deployed.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    deployed.chmod(0o755)
    marker = tmp_path / "activation-imported"
    _write_activation_redemption_stub(home, marker)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude_called = tmp_path / "claude-called"
    _stub_bin(bin_dir, "claude", f": > {claude_called}\nexit 0\n")
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_CLAUDE_HEADLESS_WORKDIR"] = str(workdir)
    env["HAPAX_COUNCIL_DIR"] = str(tmp_path / "attacker-council")
    env["HAPAX_TEST_ACTIVATION_IMPORT_MARKER"] = str(marker)
    env["HAPAX_METHODOLOGY_DISPATCH_REDEMPTION_TOKEN"] = "self-minted"
    env["HAPAX_METHODOLOGY_DISPATCH_MESSAGE_ID"] = "019f-fake"
    env["HAPAX_METHODOLOGY_DISPATCH_ROUTE_DECISION_REF"] = "route-decision:fake"
    env["HAPAX_METHODOLOGY_DISPATCH_AUTHORITY_CASE"] = "CASE-CAPACITY-ROUTING-001"

    result = subprocess.run(
        [str(deployed), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 17
    assert marker.read_text(encoding="utf-8") == "imported\n"
    assert "cannot import dispatch redemption verifier" not in result.stderr
    assert "dispatch redemption refused: socket_unavailable:test" in result.stderr
    assert not claude_called.exists()


def test_claude_headless_redemption_ignores_caller_council_dir_stub(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "reins"
    workdir.mkdir(parents=True)
    attacker_root = tmp_path / "attacker-council"
    attacker_imported = tmp_path / "attacker-redemption-imported"
    stub = attacker_root / "shared" / "governance" / "dispatch_redemption.py"
    stub.parent.mkdir(parents=True)
    stub.write_text(
        "from pathlib import Path\n"
        f"Path({str(attacker_imported)!r}).write_text('imported\\n', encoding='utf-8')\n"
        "class LaunchRedemptionContext:\n"
        "    def __init__(self, **kwargs): pass\n"
        "class LaunchRedemptionRequest:\n"
        "    def __init__(self, **kwargs): pass\n"
        "class Response:\n"
        "    ok = True\n"
        "    reason = 'ok'\n"
        "def redeem_launch_via_socket(_request):\n"
        "    return Response()\n",
        encoding="utf-8",
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude_called = tmp_path / "claude-called"
    _stub_bin(bin_dir, "claude", f": > {claude_called}\nexit 0\n")
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_CLAUDE_HEADLESS_WORKDIR"] = str(workdir)
    env["HAPAX_COUNCIL_DIR"] = str(attacker_root)
    env["HAPAX_METHODOLOGY_DISPATCH_REDEMPTION_TOKEN"] = "self-minted"
    env["HAPAX_METHODOLOGY_DISPATCH_MESSAGE_ID"] = "019f-fake"
    env["HAPAX_METHODOLOGY_DISPATCH_ROUTE_DECISION_REF"] = "route-decision:fake"
    env["HAPAX_METHODOLOGY_DISPATCH_AUTHORITY_CASE"] = "CASE-CAPACITY-ROUTING-001"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 17
    assert "dispatch redemption refused" in result.stderr
    assert "requires live methodology dispatch redemption" in result.stderr
    assert not attacker_imported.exists()
    assert not claude_called.exists()


def test_claude_headless_redemption_ignores_path_readlink_spoof(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "reins"
    workdir.mkdir(parents=True)
    attacker_root = tmp_path / "attacker-council"
    attacker_imported = tmp_path / "attacker-redemption-imported"
    stub = attacker_root / "shared" / "governance" / "dispatch_redemption.py"
    stub.parent.mkdir(parents=True)
    stub.write_text(
        "from pathlib import Path\n"
        f"Path({str(attacker_imported)!r}).write_text('imported\\n', encoding='utf-8')\n"
        "class LaunchRedemptionContext:\n"
        "    def __init__(self, **kwargs): pass\n"
        "class LaunchRedemptionRequest:\n"
        "    def __init__(self, **kwargs): pass\n"
        "class Response:\n"
        "    ok = True\n"
        "    reason = 'ok'\n"
        "def redeem_launch_via_socket(_request):\n"
        "    return Response()\n",
        encoding="utf-8",
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_readlink_called = tmp_path / "fake-readlink-called"
    claude_called = tmp_path / "claude-called"
    _stub_bin(bin_dir, "claude", f": > {claude_called}\nexit 0\n")
    scripts_dir = workdir / "scripts"
    scripts_dir.mkdir()
    _stub_bin(
        scripts_dir,
        "readlink",
        f"""
        : > "{fake_readlink_called}"
        printf '%s\\n' "{attacker_root / "scripts" / "hapax-claude-headless"}"
        exit 0
        """,
    )
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_CLAUDE_HEADLESS_WORKDIR"] = str(workdir)
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["HAPAX_METHODOLOGY_DISPATCH_REDEMPTION_TOKEN"] = "self-minted"
    env["HAPAX_METHODOLOGY_DISPATCH_MESSAGE_ID"] = "019f-fake"
    env["HAPAX_METHODOLOGY_DISPATCH_ROUTE_DECISION_REF"] = "route-decision:fake"
    env["HAPAX_METHODOLOGY_DISPATCH_AUTHORITY_CASE"] = "CASE-CAPACITY-ROUTING-001"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 17
    assert "dispatch redemption refused" in result.stderr
    assert "requires live methodology dispatch redemption" in result.stderr
    assert not fake_readlink_called.exists()
    assert not attacker_imported.exists()
    assert not claude_called.exists()


def test_claude_headless_council_symlink_to_external_tree_still_requires_redemption(
    tmp_path: Path,
) -> None:
    # A council-prefixed SPELLING of an external tree must classify by what it
    # resolves to (pwd -P), matching dispatcher-side is_external_project_worktree:
    # the symlink name must not exempt the launch from redemption.
    home = tmp_path / "home"
    real_workdir = home / "projects" / "reins"
    real_workdir.mkdir(parents=True)
    council_spelling = home / "projects" / "hapax-council--reins"
    council_spelling.symlink_to(real_workdir)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude_called = tmp_path / "claude-called"
    _stub_bin(bin_dir, "claude", f": > {claude_called}\nexit 0\n")
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_CLAUDE_HEADLESS_WORKDIR"] = str(council_spelling)
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["HAPAX_METHODOLOGY_DISPATCH_REDEMPTION_TOKEN"] = "self-minted"
    env["HAPAX_METHODOLOGY_DISPATCH_MESSAGE_ID"] = "019f-fake"
    env["HAPAX_METHODOLOGY_DISPATCH_ROUTE_DECISION_REF"] = "route-decision:fake"
    env["HAPAX_METHODOLOGY_DISPATCH_AUTHORITY_CASE"] = "CASE-CAPACITY-ROUTING-001"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 17
    assert "dispatch redemption refused" in result.stderr
    assert "requires live methodology dispatch redemption" in result.stderr
    assert not claude_called.exists()


def test_headless_source_supports_governed_model_profile_env() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'MODEL="${HAPAX_CLAUDE_MODEL:-}"' in text
    assert 'CLAUDE_ARGS+=(--model "$MODEL")' in text


def test_headless_uses_npm_global_claude_fallback(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude_args = tmp_path / "claude-args.txt"
    npm_bin = home / ".npm-global" / "bin"
    npm_bin.mkdir(parents=True)
    _stub_bin(
        npm_bin,
        "claude",
        f'printf "%s\\n" "$@" > {claude_args}\n: > {claim_file}\nexit 0\n',
    )
    env = _headless_env(home, bin_dir, tmp_path / "pipe")

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert claude_args.exists()


def test_headless_honors_explicit_claude_bin_override(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude_args = tmp_path / "claude-args.txt"
    explicit_bin = tmp_path / "explicit" / "claude"
    explicit_bin.parent.mkdir()
    _stub_bin(
        explicit_bin.parent,
        "claude",
        f'printf "%s\\n" "$@" > {claude_args}\n: > {claim_file}\nexit 0\n',
    )
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_CLAUDE_BIN"] = str(explicit_bin)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert claude_args.exists()


def test_headless_rejects_invalid_explicit_claude_bin_override(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fallback_marker = tmp_path / "fallback-used"
    _stub_bin(bin_dir, "claude", f"touch {fallback_marker}\nexit 0\n")
    explicit_bin = tmp_path / "explicit" / "claude"
    explicit_bin.parent.mkdir()
    explicit_bin.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    explicit_bin.chmod(0o644)
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_CLAUDE_BIN"] = str(explicit_bin)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 4
    assert "configured Claude binary is not executable" in result.stderr
    assert not fallback_marker.exists()


def test_appendix_hop_passes_remote_args_without_shell_interpolation(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exploit = tmp_path / "logos-url-shell-injection"
    claude_args = tmp_path / "claude-args.txt"
    _stub_bin(
        bin_dir,
        "ssh",
        """remote_cmd="${@: -1}"
case "$remote_cmd" in
  HAPAX_REMOTE_PAYLOAD=*)
    echo 'fish: Expected a variable name after this $' >&2
    exit 127
    ;;
esac
if [[ "$remote_cmd" == *"\\$'"* ]]; then
  echo 'fish: Expected a variable name after this $' >&2
  exit 127
fi
exec bash -c "$remote_cmd"
""",
    )
    _stub_bin(
        bin_dir,
        "gh",
        'if [ "$1" = "auth" ] && [ "$2" = "status" ]; then exit 0; fi\nexit 1\n',
    )
    _stub_bin(
        bin_dir,
        "claude",
        f'printf "%s\\n" "$@" > {claude_args}\n: > {claim_file}\nexit 0\n',
    )
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"
    env["HAPAX_DISPATCH_LOGOS_URL"] = f"http://podium.invalid/api; touch {exploit}"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert not exploit.exists()
    args = claude_args.read_text(encoding="utf-8").splitlines()
    assert args[:5] == [
        "-p",
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
    ]


def test_appendix_short_alias_is_local_on_appendix(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ssh_called = tmp_path / "ssh-called"
    claude_args = tmp_path / "claude-args.txt"
    _stub_bin(
        bin_dir,
        "hostname",
        """
case "${1:-}" in
  -s|-f) printf '%s\n' hapax-appendix ;;
  *) printf '%s\n' hapax-appendix ;;
esac
""",
    )
    _stub_bin(
        bin_dir,
        "ssh",
        f": > {ssh_called}\necho 'ssh should not be called for local appendix alias' >&2\nexit 99\n",
    )
    _stub_bin(
        bin_dir,
        "claude",
        f'printf "%s\\n" "$@" > {claude_args}\n: > {claim_file}\nexit 0\n',
    )
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_DISPATCH_HOST"] = "appendix"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert not ssh_called.exists()
    assert claude_args.exists()


def test_appendix_local_ip_skips_ssh_on_appendix(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ssh_called = tmp_path / "ssh-called"
    claude_args = tmp_path / "claude-args.txt"
    _stub_bin(
        bin_dir,
        "hostname",
        """
case "${1:-}" in
  -s|-f) printf '%s\n' hapax-appendix ;;
  -I) printf '%s\n' '192.168.68.50 10.0.0.50' ;;
  *) printf '%s\n' hapax-appendix ;;
esac
""",
    )
    _stub_bin(
        bin_dir,
        "ssh",
        f": > {ssh_called}\necho 'ssh should not be called for local appendix IP' >&2\nexit 99\n",
    )
    _stub_bin(
        bin_dir,
        "claude",
        f'printf "%s\\n" "$@" > {claude_args}\n: > {claim_file}\nexit 0\n',
    )
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_DISPATCH_HOST"] = "192.168.68.50"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert not ssh_called.exists()
    assert claude_args.exists()


def test_visible_claude_launcher_requires_task_or_readonly() -> None:
    text = VISIBLE.read_text(encoding="utf-8")

    assert "--task TASK_ID|--readonly" in text
    assert "refusing mutating visible lane without governed task binding" in text
    assert "hapax-methodology-dispatch" in text
    assert "HAPAX_METHODOLOGY_DISPATCH_TASK" in text
    assert 'CLAUDE_TASK="$CLAIMED_TASK"' in text


def test_headless_refuses_without_task_or_existing_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude = bin_dir / "claude"
    claude.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    claude.chmod(0o755)
    env = os.environ.copy()
    # A governed lane running this suite carries its own dispatch task binding;
    # the launcher would adopt it at CLAUDE_TASK init and skip the no-task guard.
    env.pop("HAPAX_METHODOLOGY_DISPATCH_TASK", None)
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    env["HAPAX_CLAUDE_HEADLESS_ALLOW"] = "1"
    env["HAPAX_SDLC_SLICE_ATTACH"] = "0"
    # Sandbox the launcher lock/pipe dir so a live beta lane on the host doesn't
    # trip the duplicate-launcher guard (exit 16) before the no-task guard (15).
    env["HAPAX_CLAUDE_HEADLESS_PIPE_DIR"] = str(tmp_path / "pipe")

    result = subprocess.run(
        [str(SCRIPT), "beta", "Task: fake\nAuthorityCase: fake\nParent spec: fake"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 15
    assert "without --task" in result.stderr


# ---------------------------------------------------------------------------
# Dispatch idempotency (bug #3): refuse a second live launcher for a lane.
# The reboot storm + naive re-dispatch + the supervisor firing during a
# restart-backoff window otherwise stack zombie wrappers that fight over the
# lane-keyed $ROLE.stdin / $ROLE.pid and re-inject restart prompts forever.
# ---------------------------------------------------------------------------


def test_headless_source_has_launcher_idempotency_guard() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "flock -n" in text
    assert "refusing duplicate launcher" in text


def test_headless_refuses_duplicate_launcher_for_live_lane(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    pipe_dir = tmp_path / "pipe"
    pipe_dir.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub_bin(bin_dir, "claude", "exit 0\n")
    env = _headless_env(home, bin_dir, pipe_dir)

    # Simulate a live incumbent wrapper by holding the lane launcher lock.
    lock_path = pipe_dir / "beta.launcher.lock"
    lock_fd = open(lock_path, "w")  # noqa: SIM115 — held for the subprocess lifetime
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        result = subprocess.run(
            [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

    assert result.returncode == 16, result.stderr
    assert "refusing duplicate launcher" in result.stderr


def test_headless_acquires_launcher_lock_when_lane_free(tmp_path: Path) -> None:
    """When no incumbent holds the lock, the wrapper proceeds (and self-heals)."""
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-beta").write_text("task-x\n")
    pipe_dir = tmp_path / "pipe"
    pipe_dir.mkdir()
    counter = tmp_path / "calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # claude exits immediately and clears the claim (simulating a closed task),
    # so the lane is free and the loop tears down cleanly on the first pass.
    _stub_bin(
        bin_dir,
        "claude",
        f"echo x >> {counter}\n: > {cache / 'cc-active-task-beta'}\nexit 0\n",
    )
    env = _headless_env(home, bin_dir, pipe_dir)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert counter.read_text().count("x") == 1


# ---------------------------------------------------------------------------
# Merge-aware teardown (bug #2): the respawn loop must stop once its task is
# closed (claim cleared / note left active/ / terminal status) or its PR merged
# — not re-inject a generic restart prompt forever.
# ---------------------------------------------------------------------------


def test_headless_source_has_merge_aware_teardown() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "task_is_terminal" in text
    assert "stopping respawn loop" in text


def test_headless_stops_respawning_when_claim_cleared(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n")
    pipe_dir = tmp_path / "pipe"
    pipe_dir.mkdir()
    counter = tmp_path / "calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Simulate cc-close: the lane finishes, clearing its claim file, then exits.
    _stub_bin(bin_dir, "claude", f"echo x >> {counter}\n: > {claim_file}\nexit 0\n")
    env = _headless_env(home, bin_dir, pipe_dir)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "stopping respawn loop" in result.stdout
    assert counter.read_text().count("x") == 1  # exactly one claude run, no zombie


def test_headless_stops_respawning_when_note_status_terminal(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-beta").write_text("task-x\n")  # claim stays
    vault = tmp_path / "vault"
    (vault / "active").mkdir(parents=True)
    (vault / "active" / "task-x-test.md").write_text("---\ntask_id: task-x\nstatus: done\n---\n")
    pipe_dir = tmp_path / "pipe"
    pipe_dir.mkdir()
    counter = tmp_path / "calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub_bin(bin_dir, "claude", f"echo x >> {counter}\nexit 0\n")  # leaves claim
    env = _headless_env(home, bin_dir, pipe_dir)
    env["HAPAX_CC_TASK_ROOT"] = str(vault)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "stopping respawn loop" in result.stdout
    assert counter.read_text().count("x") == 1


def test_headless_stops_respawning_when_pr_merged(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-beta").write_text("task-x\n")
    vault = tmp_path / "vault"
    (vault / "active").mkdir(parents=True)
    (vault / "active" / "task-x-test.md").write_text(
        "---\ntask_id: task-x\nstatus: pr_open\npr: 555\n---\n"
    )
    pipe_dir = tmp_path / "pipe"
    pipe_dir.mkdir()
    counter = tmp_path / "calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub_bin(bin_dir, "claude", f"echo x >> {counter}\nexit 0\n")
    # gh stub reports the linked PR as merged.
    _stub_bin(bin_dir, "gh", "echo MERGED\n")
    env = _headless_env(home, bin_dir, pipe_dir)
    env["HAPAX_CC_TASK_ROOT"] = str(vault)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "stopping respawn loop" in result.stdout
    assert counter.read_text().count("x") == 1


# ---------------------------------------------------------------------------
# Out-of-band self-reap (the zombie-launcher bug): the launcher holds the FIFO
# write-end open (exec 3<>), so a persistent stream-json claude NEVER sees EOF,
# `wait` never returns, and the post-turn task_is_terminal teardown is dead code.
# The fix is an out-of-band watchdog that polls task terminality WHILE claude is
# alive and SIGTERMs the child when the task closes/merges — independent of EOF.
# ---------------------------------------------------------------------------


def test_headless_source_has_out_of_band_self_reap() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "self-reaping" in text
    assert "TERMINAL_POLL" in text or "HAPAX_CLAUDE_HEADLESS_TERMINAL_POLL_SECONDS" in text


def test_headless_self_reaps_terminal_task_while_claude_persists(tmp_path: Path) -> None:
    """The core fix: with a PERSISTENT claude (never exits → `wait` would block
    forever), the launcher must still tear down when the task goes terminal,
    driven by the out-of-band poll rather than the (unreachable) EOF path.

    If the watchdog were absent the launcher would hang on `wait` for the full
    `sleep 600` and the 20s subprocess timeout would fail the test.
    """
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-beta").write_text("task-x\n")  # claim stays
    vault = tmp_path / "vault"
    (vault / "active").mkdir(parents=True)
    # Terminal status from the start: the first out-of-band poll detects it.
    (vault / "active" / "task-x-test.md").write_text("---\ntask_id: task-x\nstatus: done\n---\n")
    pipe_dir = tmp_path / "pipe"
    pipe_dir.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # claude that NEVER exits on its own (the production behavior the bug needs):
    # it must be SIGTERM'd by the out-of-band watchdog.
    _stub_bin(bin_dir, "claude", "exec sleep 600\n")
    env = _headless_env(home, bin_dir, pipe_dir)
    env["HAPAX_CC_TASK_ROOT"] = str(vault)
    env["HAPAX_CLAUDE_HEADLESS_TERMINAL_POLL_SECONDS"] = "0.3"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "self-reaping" in result.stdout
    assert "stopping respawn loop" in result.stdout


def test_headless_self_reap_keeps_persistent_claude_alive_while_task_live(tmp_path: Path) -> None:
    """The watchdog must NOT reap a persistent claude while the task is still
    live — it only acts once the task is terminal. With a live task the launcher
    blocks (claude never exits), so we assert it TIMES OUT (no premature reap)."""
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-beta").write_text("task-x\n")
    vault = tmp_path / "vault"
    (vault / "active").mkdir(parents=True)
    (vault / "active" / "task-x-test.md").write_text(
        "---\ntask_id: task-x\nstatus: in_progress\n---\n"
    )
    pipe_dir = tmp_path / "pipe"
    pipe_dir.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub_bin(bin_dir, "claude", "exec sleep 600\n")
    env = _headless_env(home, bin_dir, pipe_dir)
    env["HAPAX_CC_TASK_ROOT"] = str(vault)
    env["HAPAX_CLAUDE_HEADLESS_TERMINAL_POLL_SECONDS"] = "0.3"

    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run(
            [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=4,
        )
    # Reap the still-running launcher + its sleep child (own session) so the
    # sandbox doesn't leak processes.
    subprocess.run(["pkill", "-TERM", "-f", "sleep 600"], check=False)


# ---------------------------------------------------------------------------
# Stale-lock handling on startup: a SIGKILL'd launcher skips its EXIT trap,
# stranding the pidfile. The OFD flock still releases on death, so a free lock
# is reacquired normally; but a genuinely-held lock must never be stolen just
# because the recorded pid looks stale.
# ---------------------------------------------------------------------------


def test_headless_source_has_stale_lock_handling() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "stale" in text.lower()
    # On flock failure the incumbent's liveness is verified before refusing.
    assert "kill -0" in text


def test_headless_refuses_when_lock_held_even_with_stale_pidfile(tmp_path: Path) -> None:
    """A live holder of the lock must still be refused (no false steal) even when
    the recorded launcher pid is dead/stale."""
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    pipe_dir = tmp_path / "pipe"
    pipe_dir.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub_bin(bin_dir, "claude", "exit 0\n")
    env = _headless_env(home, bin_dir, pipe_dir)

    # A dead/stale pid in the pidfile (pid 2^31-1 is never live).
    (pipe_dir / "beta.launcher.pid").write_text("2147483647\n")
    # A LIVE incumbent holds the lock (Python fd held for the subprocess lifetime).
    lock_path = pipe_dir / "beta.launcher.lock"
    lock_fd = open(lock_path, "w")  # noqa: SIM115
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        result = subprocess.run(
            [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

    assert result.returncode == 16, result.stderr
    assert "refusing duplicate launcher" in result.stderr


# ---------------------------------------------------------------------------
# Drift check (AC3): the committed launcher is the authoritative source — the
# incident was the committed launcher REGRESSING below the deployed runtime (a
# 190-line strip that dropped flock + teardown while the deployed copy had the
# 292-line fix). source-activation only ever deploys FROM git, so pinning the
# committed launcher's fix markers (+ a line-count floor) in CI keeps committed
# and deployed from diverging in the dangerous direction. A byte-equality test
# vs the deployed symlink is intentionally NOT used: it false-fails for the whole
# merged-not-yet-deployed window (the pinned release copy lags main).
# ---------------------------------------------------------------------------


def test_committed_launcher_pins_zombie_reap_fix_markers() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    # flock idempotency + named launcher pidfile
    assert "flock -n" in text
    assert "LAUNCHER_PIDFILE" in text
    # merge-aware terminal detection + out-of-band self-reap
    assert "task_is_terminal" in text
    assert "self-reaping" in text
    assert "stopping respawn loop" in text
    # Line-count floor: the regression stripped the launcher to ~190 lines. The
    # full launcher (flock + teardown + out-of-band self-reap) is well over 250.
    assert len(text.splitlines()) >= 250, "launcher appears stripped — regression risk"


# ---------------------------------------------------------------------------
# Session identity through the dispatch boundary (taxonomy-a3-session-identity):
# the launcher mints HAPAX_SESSION_ID per spawn, but before the fix the G2
# remote hop dropped every identity var at the SSH boundary — the appendix
# claude resolved a DIFFERENT session id (CLAUDE_CODE_SESSION_ID), the
# session-keyed claim file existed only podium-side, and the dispatch proof
# witnessed the exec by pid alone. The lane then hit cc-claim exit-4 walls
# (see relay receipts epsilon-claim-rejected.yaml, zeta-claim-rejected.yaml).
# The identity thread must survive the hop: payload env -> remote exec ->
# marker + claim materialization on the exec host -> session-stamped proof.
# ---------------------------------------------------------------------------


def test_headless_mint_fallback_is_never_pid_derived() -> None:
    """Claim-by-pid unrepresentable: the retired `<role>-$$` fallback minted
    pid-shaped session ids that cc-claim now refuses to key."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert '"$ROLE" "$$"' not in text, "launcher session-id fallback mints pid-shaped ids"


def test_headless_preamble_carries_session_identity() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "Session identity: role=$ROLE session_id=$SESSION_UUID" in text


def test_appendix_hop_threads_session_identity_end_to_end(tmp_path: Path) -> None:
    """E2E canary: fake ssh executes the remote command locally (same HOME),
    so the assertions cover the full chain — launcher mint -> payload env ->
    remote exec env -> exec-host marker/claim materialization -> proof."""
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude_env = tmp_path / "claude-env.txt"
    # Simulate the real SSH env boundary: the remote shell never inherits the
    # launcher's exports, so identity can ONLY arrive via the exec payload.
    _stub_bin(
        bin_dir,
        "ssh",
        'remote_cmd="${@: -1}"\n'
        "exec env -u HAPAX_SESSION_ID -u HAPAX_AGENT_INTERFACE -u HAPAX_AGENT_NAME"
        " -u HAPAX_AGENT_ROLE -u CLAUDE_ROLE -u HAPAX_WORKTREE_ROLE"
        ' -u HAPAX_METHODOLOGY_DISPATCH_TASK bash -c "$remote_cmd"\n',
    )
    _stub_bin(
        bin_dir,
        "gh",
        'if [ "$1" = "auth" ] && [ "$2" = "status" ]; then exit 0; fi\nexit 1\n',
    )
    # The "remote" claude dumps its env, then clears the legacy claim so the
    # respawn loop tears down after one pass.
    _stub_bin(bin_dir, "claude", f"env > {claude_env}\n: > {claim_file}\nexit 0\n")
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr

    # One session id, minted by the launcher, recorded in the role marker.
    markers = sorted(cache.glob("session-role-*"))
    assert len(markers) == 1, f"expected exactly one session marker, got {markers}"
    sid = markers[0].name.removeprefix("session-role-")
    assert markers[0].read_text().strip() == "beta"

    # The exec-side claude carries the SAME identity the launcher minted.
    claude_vars = dict(
        line.split("=", 1) for line in claude_env.read_text().splitlines() if "=" in line
    )
    assert claude_vars.get("HAPAX_SESSION_ID") == sid
    assert claude_vars.get("HAPAX_AGENT_ROLE") == "beta"
    assert claude_vars.get("CLAUDE_ROLE") == "beta"
    assert claude_vars.get("HAPAX_METHODOLOGY_DISPATCH_TASK") == "task-x"

    # The session-keyed claim materialized on the exec host (cc-claim was
    # skipped — the pre-seeded legacy claim matched — so only the remote
    # materialization path can have written it), single-line format.
    keyed = cache / f"cc-active-task-beta-{sid}"
    assert keyed.read_text(encoding="utf-8") == "task-x\n"
    epoch_sidecar = cache / f"cc-claim-epoch-beta-{sid}"
    epoch, _, sidecar_task = epoch_sidecar.read_text(encoding="utf-8").strip().partition(" ")
    assert epoch.isdigit()
    assert sidecar_task == "task-x"

    # The dispatch proof witnesses the session, not just the pid.
    proofs = sorted((cache / "orchestration" / "dispatch-host-proofs").glob("*.json"))
    assert proofs, "remote exec must write a dispatch proof"
    proof = json.loads(proofs[-1].read_text(encoding="utf-8"))
    assert proof["session_id"] == sid
    assert proof["role"] == "beta"
    assert proof["task_id"] == "task-x"
    assert proof["claim_materialized"] is True


# ---------------------------------------------------------------------------
# task_is_terminal: claim-stamp drift must not reap a fresh live lane.
# 2026-07-01 eta/ndcvb-phase1 incident: cc-claim's note stamp landed partially
# (claimed_at key absent in the authored note), cc-hygiene H1 reverted the
# note to offered/unassigned 13s later, and the assigned-mismatch branch
# returned terminal — SIGTERMing a healthy freshly-launched worker.
# ---------------------------------------------------------------------------


def _run_task_is_terminal_result(
    tmp_path: Path,
    *,
    cache_task: str | None,
    note_status: str,
    note_assigned: str,
    cache_age_s: int = 0,
    note_pr: int | None = None,
    gh_state: str = "",
    legacy_cache: bool = False,
    sidecar_task: str | None = None,
    session_keyed_cache: bool = False,
    legacy_cache_task: str | None = None,
    older_matching_session_cache: bool = False,
    epoch_check_bypass: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Extract task_is_terminal() from the launcher and drive it with fixtures.

    Returns the bash exit code: 0 = terminal (lane reaped), 1 = live.

    ``cache_age_s`` ages the claim EPOCH recorded in the task-bound
    ``cc-claim-epoch-*`` sidecar while the claim file's mtime stays fresh —
    deliberately simulating the cc-task-gate lease-keep-alive ``touch`` that
    makes mtime useless as a claim-age witness. ``legacy_cache`` writes no
    sidecar (non-conforming-writer shape). ``sidecar_task`` overrides the
    task id recorded in the sidecar (stale-sidecar shape).
    """
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True, exist_ok=True)
    note = tmp_path / "note.md"
    pr_line = f"pr: {note_pr}\n" if note_pr is not None else ""
    note.write_text(
        f"---\nstatus: {note_status}\nassigned_to: {note_assigned}\n{pr_line}---\n",
        encoding="utf-8",
    )
    sid = "9b6ba5ca-513c-41aa-9900-d3026b42aad1"
    old_sid = "00000000-0000-4000-8000-000000000001"
    claim_file = cache / "cc-active-task-eta"
    session_claim_file = cache / f"cc-active-task-eta-{sid}"
    active_claim_file = session_claim_file if session_keyed_cache else claim_file
    sidecar = (
        cache / f"cc-claim-epoch-eta-{sid}" if session_keyed_cache else cache / "cc-claim-epoch-eta"
    )
    sidecar.unlink(missing_ok=True)
    if older_matching_session_cache:
        older_claim = cache / f"cc-active-task-eta-{old_sid}"
        older_sidecar = cache / f"cc-claim-epoch-eta-{old_sid}"
        older_claim.write_text("task-under-test\n", encoding="utf-8")
        older_sidecar.write_text(f"{int(time.time()) - 3600} task-under-test\n", encoding="utf-8")
    if legacy_cache_task is not None:
        claim_file.write_text(legacy_cache_task + "\n", encoding="utf-8")
    if cache_task is not None:
        active_claim_file.write_text(cache_task + "\n", encoding="utf-8")
        if legacy_cache:
            if cache_age_s:
                aged = time.time() - cache_age_s
                os.utime(active_claim_file, (aged, aged))
        else:
            epoch = int(time.time()) - cache_age_s
            bound_task = sidecar_task if sidecar_task is not None else cache_task
            sidecar.write_text(f"{epoch} {bound_task}\n", encoding="utf-8")
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("task_is_terminal()")
    end = text.index("\n}\n", start) + 3
    func = text[start:end]
    gh_stub = f'gh() {{ echo "{gh_state}"; }}' if gh_state else "gh() { return 1; }"
    harness = "\n".join(
        [
            "set -u",
            f'HOME="{home}"',
            'ROLE="eta"',
            f'CLAIM_FILE="{claim_file}"',
            f'SESSION_CLAIM_FILE="{session_claim_file}"',
            f'HAPAX_CLAIM_EPOCH_CHECK_BYPASS="{1 if epoch_check_bypass else 0}"',
            f'find_active_note() {{ echo "{note}"; }}',
            gh_stub,
            func,
            'task_is_terminal "task-under-test"',
        ]
    )
    result = subprocess.run(["bash", "-c", harness], text=True, capture_output=True, check=False)
    assert result.returncode in (0, 1), result.stderr
    return result


def _run_task_is_terminal(
    tmp_path: Path,
    *,
    cache_task: str | None,
    note_status: str,
    note_assigned: str,
    cache_age_s: int = 0,
    note_pr: int | None = None,
    gh_state: str = "",
    legacy_cache: bool = False,
    sidecar_task: str | None = None,
    session_keyed_cache: bool = False,
    legacy_cache_task: str | None = None,
    older_matching_session_cache: bool = False,
    epoch_check_bypass: bool = False,
) -> int:
    """Return the bash exit code: 0 = terminal (lane reaped), 1 = live."""
    result = _run_task_is_terminal_result(
        tmp_path,
        cache_task=cache_task,
        note_status=note_status,
        note_assigned=note_assigned,
        cache_age_s=cache_age_s,
        note_pr=note_pr,
        gh_state=gh_state,
        legacy_cache=legacy_cache,
        sidecar_task=sidecar_task,
        session_keyed_cache=session_keyed_cache,
        legacy_cache_task=legacy_cache_task,
        older_matching_session_cache=older_matching_session_cache,
        epoch_check_bypass=epoch_check_bypass,
    )
    return result.returncode


def test_terminal_check_survives_claim_stamp_drift(tmp_path: Path) -> None:
    """Matching claim cache + ghost-reverted note (offered/unassigned) = LIVE."""
    rc = _run_task_is_terminal(
        tmp_path,
        cache_task="task-under-test",
        note_status="offered",
        note_assigned="unassigned",
    )
    assert rc == 1


def test_terminal_check_reaps_reassignment_even_with_fresh_cache(
    tmp_path: Path,
) -> None:
    """assigned_to naming ANOTHER ROLE is definitive terminal even while our
    cache is fresh — the gate touches the cache before any check (lease
    keep-alive), so a reassigned old lane attempting gated writes keeps its
    own cache fresh; an mtime bound alone could never reap it."""
    rc = _run_task_is_terminal(
        tmp_path,
        cache_task="task-under-test",
        note_status="claimed",
        note_assigned="some-other-role",
        cache_age_s=0,
    )
    assert rc == 0


def test_terminal_check_reaps_long_unassigned_despite_gate_heartbeat(
    tmp_path: Path,
) -> None:
    """The H1-revert indeterminate shape is bounded by the claim EPOCH in the
    cache content — the harness keeps mtime fresh (the gate's lease
    keep-alive touch), so this proves the bound is heartbeat-immune: a lane
    sitting on a long-unassigned task reaps even while it keeps writing."""
    rc = _run_task_is_terminal(
        tmp_path,
        cache_task="task-under-test",
        note_status="offered",
        note_assigned="unassigned",
        cache_age_s=3600,
    )
    assert rc == 0


@pytest.mark.parametrize("note_assigned", ["", "null", "none", "~", "[]", '"null"'])
def test_terminal_check_treats_nullish_assignee_as_unassigned(
    tmp_path: Path, note_assigned: str
) -> None:
    """Nullish YAML spellings are the unassigned drift shape, not a named role."""
    rc = _run_task_is_terminal(
        tmp_path,
        cache_task="task-under-test",
        note_status="offered",
        note_assigned=note_assigned,
        cache_age_s=3600,
    )
    assert rc == 0


def test_terminal_check_reaps_sidecarless_cache(tmp_path: Path) -> None:
    """No mtime fallback: mtime is heartbeat-refreshed by the gate, so a
    matching cache with NO sidecar (non-conforming writer) reaps in the
    unassigned-drift shape rather than living unbounded."""
    result = _run_task_is_terminal_result(
        tmp_path,
        cache_task="task-under-test",
        note_status="offered",
        note_assigned="unassigned",
        legacy_cache=True,
    )
    assert result.returncode == 0
    assert "no valid task-bound epoch sidecar" in result.stderr
    assert "non-conforming writer" in result.stderr


def test_terminal_check_ignores_stale_sidecar_bound_to_other_task(tmp_path: Path) -> None:
    """A sidecar naming a DIFFERENT task (stale leftover from an earlier
    claim) must not vouch for this claim — the lane reaps."""
    result = _run_task_is_terminal_result(
        tmp_path,
        cache_task="task-under-test",
        note_status="offered",
        note_assigned="unassigned",
        sidecar_task="an-earlier-task",
    )
    assert result.returncode == 0
    assert "sidecar names task=an-earlier-task" in result.stderr
    assert "stale sidecar" in result.stderr


def test_terminal_check_logs_expired_unassigned_claim(tmp_path: Path) -> None:
    result = _run_task_is_terminal_result(
        tmp_path,
        cache_task="task-under-test",
        note_status="offered",
        note_assigned="unassigned",
        cache_age_s=3600,
    )
    assert result.returncode == 0
    assert "exceeds grace=600s" in result.stderr
    assert "stale unassigned claim" in result.stderr


def test_terminal_check_uses_session_keyed_epoch_sidecar(tmp_path: Path) -> None:
    result = _run_task_is_terminal_result(
        tmp_path,
        cache_task="task-under-test",
        note_status="offered",
        note_assigned="unassigned",
        session_keyed_cache=True,
    )
    assert result.returncode == 1
    assert "session-keyed:cc-active-task-eta-" in result.stderr
    assert "treating as indeterminate" in result.stderr


def test_terminal_check_prefers_matching_session_cache_over_repointed_legacy(
    tmp_path: Path,
) -> None:
    result = _run_task_is_terminal_result(
        tmp_path,
        cache_task="task-under-test",
        note_status="offered",
        note_assigned="unassigned",
        session_keyed_cache=True,
        legacy_cache_task="newer-task-on-shared-role",
    )
    assert result.returncode == 1
    assert "session-keyed:cc-active-task-eta-" in result.stderr
    assert "treating as indeterminate" in result.stderr


def test_terminal_check_prefers_exact_session_over_older_same_task_lease(
    tmp_path: Path,
) -> None:
    result = _run_task_is_terminal_result(
        tmp_path,
        cache_task="task-under-test",
        note_status="offered",
        note_assigned="unassigned",
        session_keyed_cache=True,
        older_matching_session_cache=True,
    )
    assert result.returncode == 1
    assert "session-keyed:cc-active-task-eta-9b6ba5ca-" in result.stderr
    assert "treating as indeterminate" in result.stderr


def test_terminal_check_epoch_bypass_keeps_matching_cache_live(tmp_path: Path) -> None:
    result = _run_task_is_terminal_result(
        tmp_path,
        cache_task="task-under-test",
        note_status="offered",
        note_assigned="unassigned",
        legacy_cache=True,
        epoch_check_bypass=True,
    )
    assert result.returncode == 1
    assert "HAPAX_CLAIM_EPOCH_CHECK_BYPASS=1" in result.stderr
    assert "repair the writer" in result.stderr


def test_terminal_check_epoch_bypass_still_reaps_merged_pr(tmp_path: Path) -> None:
    result = _run_task_is_terminal_result(
        tmp_path,
        cache_task="task-under-test",
        note_status="offered",
        note_assigned="unassigned",
        note_pr=4242,
        gh_state="MERGED",
        legacy_cache=True,
        epoch_check_bypass=True,
    )
    assert result.returncode == 0
    assert "HAPAX_CLAIM_EPOCH_CHECK_BYPASS=1" in result.stderr


def test_terminal_check_reaps_when_cache_repointed(tmp_path: Path) -> None:
    """Cache naming a DIFFERENT task is the definitive moved-on signal."""
    rc = _run_task_is_terminal(
        tmp_path,
        cache_task="a-different-task",
        note_status="claimed",
        note_assigned="some-other-role",
    )
    assert rc == 0


def test_terminal_check_reaps_done_note(tmp_path: Path) -> None:
    rc = _run_task_is_terminal(
        tmp_path,
        cache_task="task-under-test",
        note_status="done",
        note_assigned="eta",
    )
    assert rc == 0


def test_terminal_check_reaps_foreign_assignee_when_cache_stale(tmp_path: Path) -> None:
    """Reassignment to a named role reaps regardless of cache age."""
    rc = _run_task_is_terminal(
        tmp_path,
        cache_task="task-under-test",
        note_status="claimed",
        note_assigned="some-other-role",
        cache_age_s=3600,
    )
    assert rc == 0


def test_terminal_check_reaps_foreign_assignee_with_no_cache(tmp_path: Path) -> None:
    """Missing cache + foreign assignee is the genuinely-reassigned shape."""
    rc = _run_task_is_terminal(
        tmp_path,
        cache_task=None,
        note_status="claimed",
        note_assigned="some-other-role",
    )
    assert rc == 0


def test_terminal_check_reaps_unassigned_note_with_no_cache(tmp_path: Path) -> None:
    result = _run_task_is_terminal_result(
        tmp_path,
        cache_task=None,
        note_status="offered",
        note_assigned="unassigned",
    )
    assert result.returncode == 0
    assert "no matching claim cache" in result.stderr
    assert "rerun cc-claim" in result.stderr


def test_terminal_check_indeterminate_still_reaps_merged_pr(tmp_path: Path) -> None:
    """The drift-survival fall-through still honors the merged-PR terminal."""
    rc = _run_task_is_terminal(
        tmp_path,
        cache_task="task-under-test",
        note_status="offered",
        note_assigned="unassigned",
        note_pr=4242,
        gh_state="MERGED",
    )
    assert rc == 0
