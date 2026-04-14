"""install-units.sh regression pins.

Delta 2026-04-14-systemd-timer-enablement-gap.md identified that 14
of 51 council timers were in linked-but-not-enabled state because the
install script only enabled *newly* linked timers, not existing linked
ones. This test pins:

1. The script has a sweep that finds linked-but-not-enabled timers
   and runs ``systemctl --user enable`` on them.
2. The script aborts when run from any worktree other than primary
   alpha (to prevent the runtime bug where running from a temporary
   worktree re-links every systemd symlink to the worktree path).
3. The script uses idempotent ``enable`` in the sweep (not
   ``enable --now``) so dormant timers come up on their natural
   schedule rather than firing synchronously during install.
4. The override env var ``ALLOW_NONSTANDARD_REPO`` is present for
   intentional testing.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SCRIPT = REPO_ROOT / "systemd" / "scripts" / "install-units.sh"


class TestInstallUnitsScriptExists:
    def test_script_present(self) -> None:
        assert INSTALL_SCRIPT.is_file(), f"install-units.sh missing at {INSTALL_SCRIPT}"

    def test_script_is_bash(self) -> None:
        first_line = INSTALL_SCRIPT.read_text(encoding="utf-8").splitlines()[0]
        assert "bash" in first_line


class TestPrimaryWorktreeGuard:
    """Guard against the ``install-units.sh from worktree`` footgun.

    Running install-units.sh from a non-primary worktree re-links every
    systemd user unit to that worktree's path. When the worktree is
    later removed, every symlink becomes dangling and services fail to
    start. The guard blocks this by default; ``ALLOW_NONSTANDARD_REPO=1``
    is the escape hatch for intentional testing.
    """

    def test_script_checks_expected_primary(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        assert "EXPECTED_PRIMARY" in body
        assert '${HOME}/projects/hapax-council"' in body, (
            "expected primary worktree path must be the canonical alpha path"
        )

    def test_script_aborts_on_nonstandard_repo(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        assert 'if [ "$PROJECT_DIR" != "$EXPECTED_PRIMARY" ]' in body
        assert "exit 1" in body

    def test_script_has_override_env_var(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        assert "ALLOW_NONSTANDARD_REPO" in body, (
            "must expose an override env var for intentional non-primary runs"
        )


class TestTimerEnablementSweep:
    """Pin the delta 2026-04-14-systemd-timer-enablement-gap fix."""

    def test_script_sweeps_existing_linked_timers(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        assert "sweep" in body.lower(), (
            "script must explicitly sweep existing linked-but-not-enabled timers"
        )
        assert "enabled_in_sweep" in body

    def test_sweep_skips_already_enabled_timers(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        assert "timers.target.wants" in body, (
            "sweep must check .wants/ for existing enablement before calling enable"
        )

    def test_sweep_uses_plain_enable_not_enable_now(self) -> None:
        """Sweep path uses ``enable`` without ``--now`` so dormant timers
        fire on natural schedule, not synchronously at install time."""
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        # The sweep block should contain a systemctl --user enable call
        # that is NOT enable --now. We check the general shape: there
        # must be at least one enable call without --now in the sweep
        # section.
        lines = body.splitlines()
        sweep_started = False
        sweep_has_plain_enable = False
        for line in lines:
            if "for timer_file in" in line:
                sweep_started = True
            if sweep_started and "systemctl --user enable " in line:
                # Strip comments / strings — look for --now literal
                code_part = line.split("#", 1)[0]
                if "enable --now" not in code_part and '"$timer_name"' in code_part:
                    sweep_has_plain_enable = True
                    break
            if sweep_started and "done" in line and "for " not in line:
                break
        assert sweep_has_plain_enable, (
            "sweep loop must call ``systemctl --user enable <timer>`` without --now"
        )

    def test_sweep_runs_daemon_reload_after_enabling(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        assert "daemon-reload" in body
        # Sweep block must daemon-reload after it enables anything.
        assert 'enabled_in_sweep" -gt 0' in body, (
            "sweep must conditionally run daemon-reload only when it actually enabled something"
        )

    def test_existing_newly_linked_timer_flow_still_works(self) -> None:
        """The original ``new_timers`` + ``enable --now`` path must survive."""
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        assert "new_timers" in body
        assert "enable --now" in body, (
            "first-install path still needs enable --now so freshly linked timers start immediately"
        )
