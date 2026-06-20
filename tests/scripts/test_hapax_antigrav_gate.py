"""Gate-enforcement tests for the antigrav adapter glue (capability-adapter-antigrav-glue):
the shared enable-latch helper, the fail-closed hook wiring, and that the latch is wired into the
launch path. End-to-end latch testing is avoided (it needs heavy worktree/agy/tmux provisioning);
the helper logic is exercised directly and the launcher integration is verified structurally + via
the cleanly-reachable --wire-hooks-only path."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LAUNCHER = REPO / "scripts" / "hapax-antigrav"
HELPER = REPO / "hooks" / "scripts" / "hapax_check_enable_latch.sh"


def _run_helper(runtime: str, env_extra: dict[str, str]) -> int:
    """Source the helper + call hapax_check_enable_latch; return its exit code."""
    script = f'. "{HELPER}"; hapax_check_enable_latch {runtime}'
    return subprocess.run(
        ["bash", "-c", script], env={"HOME": "/nonexistent-home", **env_extra}, capture_output=True
    ).returncode


def _run_launcher(tmp_path, *, latch: str = "absent", config: str = "clean", env_extra=None):
    """Run hapax-antigrav end-to-end far enough to hit the wire + latch, with a stub agy / tmp home
    / tmp config so it never spawns a real IDE or touches the real ~/.gemini. ``latch`` in
    {absent, enabled, allow, disabled}; ``config`` in {clean, foreign}. Returns the CompletedProcess.
    """
    home = tmp_path / "home"
    wd = tmp_path / "wd"
    cfg = tmp_path / "gemini"
    for d in (home, wd, cfg):
        d.mkdir(parents=True, exist_ok=True)
    stub = tmp_path / "agy"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    enable, disable = tmp_path / "enable", tmp_path / "disable"
    if latch in ("enabled",):
        enable.touch()
    if latch in ("disabled",):
        enable.touch()
        disable.touch()
    if config == "foreign":
        (cfg / "hooks.json").write_text('{"PreToolUse": [{"matcher": "foreign", "hooks": []}]}')
    env = {
        "HOME": str(home),
        "PATH": "/usr/bin:/bin",
        "HAPAX_COUNCIL_DIR": str(REPO),
        "HAPAX_ANTIGRAV_BIN": str(stub),
        "HAPAX_ANTIGRAV_CONFIG_DIR": str(cfg),
        "HAPAX_ANTIGRAV_ENABLE_FILE": str(enable),
        "HAPAX_ANTIGRAV_DISABLE_FILE": str(disable),
    }
    if latch == "allow":
        env["HAPAX_ANTIGRAV_ALLOW"] = "1"
    env.update(env_extra or {})
    return subprocess.run(
        [str(LAUNCHER), "--workdir", str(wd), "--no-claim", "--terminal", "current"],
        env=env,
        capture_output=True,
        text=True,
    )


def test_launcher_refuses_interactive_launch_when_latch_absent(tmp_path) -> None:
    # End-to-end: reaches the launch path (wire succeeds on a clean config) then refuses at the latch.
    result = _run_launcher(tmp_path, latch="absent")
    assert result.returncode == 7
    assert "enable-latch" in result.stderr


def test_launcher_refuses_when_disable_file_present(tmp_path) -> None:
    # disable file forces refusal THROUGH the launcher even though the enable file is also present.
    result = _run_launcher(tmp_path, latch="disabled")
    assert result.returncode == 7
    assert "disable latch present" in result.stderr


def test_launcher_proceeds_past_latch_with_enable_file(tmp_path) -> None:
    result = _run_launcher(tmp_path, latch="enabled")
    assert result.returncode != 7  # passed the latch (proceeds to the stubbed agy spawn)


def test_launcher_proceeds_past_latch_with_allow_env(tmp_path) -> None:
    result = _run_launcher(tmp_path, latch="allow")
    assert result.returncode != 7


def test_launcher_fail_closed_on_foreign_hooks_blocks_before_latch(tmp_path) -> None:
    # Foreign hooks.json -> wire refused -> exit 6 (fail-closed) on the normal launch path.
    result = _run_launcher(tmp_path, latch="allow", config="foreign")
    assert result.returncode == 6


def test_launcher_hook_wiring_override_proceeds_past_the_wire(tmp_path) -> None:
    # With the operator override, a refused wire warns + proceeds (no exit 6); latch allowed -> past.
    result = _run_launcher(
        tmp_path,
        latch="allow",
        config="foreign",
        env_extra={"HAPAX_ANTIGRAV_OVERRIDE_HOOK_WIRING": "1"},
    )
    assert result.returncode != 6
    assert "UNGATED" in result.stderr  # the loud override warning fired


def test_helper_default_deny_when_no_latch(tmp_path) -> None:
    rc = _run_helper(
        "antigrav",
        {
            "HAPAX_ANTIGRAV_ENABLE_FILE": str(tmp_path / "enable"),
            "HAPAX_ANTIGRAV_DISABLE_FILE": str(tmp_path / "disable"),
        },
    )
    assert rc == 1  # absent enable -> refuse (default-deny)


def test_helper_allows_when_enable_present(tmp_path) -> None:
    enable = tmp_path / "enable"
    enable.touch()
    rc = _run_helper(
        "antigrav",
        {
            "HAPAX_ANTIGRAV_ENABLE_FILE": str(enable),
            "HAPAX_ANTIGRAV_DISABLE_FILE": str(tmp_path / "disable"),
        },
    )
    assert rc == 0


def test_helper_allow_env_bypasses(tmp_path) -> None:
    rc = _run_helper(
        "antigrav",
        {
            "HAPAX_ANTIGRAV_ENABLE_FILE": str(tmp_path / "enable"),
            "HAPAX_ANTIGRAV_DISABLE_FILE": str(tmp_path / "disable"),
            "HAPAX_ANTIGRAV_ALLOW": "1",
        },
    )
    assert rc == 0


def test_helper_disable_overrides_enable(tmp_path) -> None:
    enable = tmp_path / "enable"
    disable = tmp_path / "disable"
    enable.touch()
    disable.touch()
    rc = _run_helper(
        "antigrav",
        {"HAPAX_ANTIGRAV_ENABLE_FILE": str(enable), "HAPAX_ANTIGRAV_DISABLE_FILE": str(disable)},
    )
    assert rc == 1  # disable present -> refuse even with enable present


def test_wire_hooks_only_fails_closed_on_foreign_hooks_json(tmp_path) -> None:
    config = tmp_path / "gemini"
    config.mkdir()
    (config / "hooks.json").write_text('{"PreToolUse": [{"matcher": "foreign", "hooks": []}]}')
    result = subprocess.run(
        [str(LAUNCHER), "--wire-hooks-only"],
        env={
            "HOME": str(tmp_path),
            "PATH": "/usr/bin:/bin",
            "HAPAX_COUNCIL_DIR": str(REPO),
            "HAPAX_ANTIGRAV_CONFIG_DIR": str(config),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 6  # foreign hooks.json -> wiring refused, fail-closed


def test_latch_is_wired_into_the_launch_path() -> None:
    # Structural: the launch path must call the shared latch helper, OPEN_IDE-gated, exit 7 on refuse.
    src = LAUNCHER.read_text(encoding="utf-8")
    assert "hapax_check_enable_latch antigrav || exit 7" in src
    assert "command -v hapax_check_enable_latch" in src
    # the fail-closed hook-wiring + its documented override are present
    assert "exit 6" in src and "HAPAX_ANTIGRAV_OVERRIDE_HOOK_WIRING" in src
    # the helper is registered in the closure manifest so canonical deployment carries it
    doctor = (REPO / "hooks" / "scripts" / "hooks-doctor.sh").read_text(encoding="utf-8")
    assert "hapax_check_enable_latch.sh" in doctor
