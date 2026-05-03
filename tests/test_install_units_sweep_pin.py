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


class TestServiceDropInInstall:
    """LRR Phase 3 regression pins for the ``*.service.d/`` drop-in
    handling added to install-units.sh.

    Before Phase 3, the script only walked top-level ``*.service``,
    ``*.timer``, ``*.target``, ``*.path`` files under ``systemd/units/``.
    Drop-in directories (``systemd/units/*.service.d/``) were silently
    ignored, so the existing ``audio-recorder.service.d/archive-path.conf``
    and ``contact-mic-recorder.service.d/archive-path.conf`` entries
    were never installed. Phase 3 adds ``tabbyapi.service.d/gpu-pin.conf``
    and ``hapax-daimonion.service.d/gpu-pin.conf`` and MUST install them
    for the Option α → γ partition reconciliation to take effect.

    Historical note: the hapax-daimonion drop-in was originally mis-
    placed on ``hapax-dmn.service.d/`` in PR #811 because beta's
    supplement labeled the GPU-holding service as "hapax-dmn" while
    the actual unit holding the GPU memory is ``hapax-daimonion.service``
    (``-m agents.hapax_daimonion``). ``hapax-dmn.service`` runs
    ``agents.dmn`` which is CPU-only. PR #814 corrected the target.

    These pins lock the drop-in walk in so any future refactor that
    drops it is caught in CI.
    """

    def test_script_walks_service_d_directories(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        assert "*.service.d" in body, (
            "install-units.sh must iterate *.service.d drop-in directories"
        )

    def test_script_creates_destination_service_d_dir(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        assert "mkdir -p " in body
        assert "dest_dropin_dir" in body, (
            "drop-in install must ensure the destination .d directory exists"
        )

    def test_script_symlinks_individual_conf_files(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        assert "ln -sf" in body
        # Look for the specific drop-in loop
        assert '"$conf" "$dest_conf"' in body, (
            "drop-in loop must link each .conf individually, not the parent dir"
        )

    def test_script_reloads_daemon_when_dropins_change(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        assert "dropin_changed" in body
        assert '"$dropin_changed" -gt 0' in body, (
            "daemon-reload must be gated on dropin_changed so idempotent re-runs don't spam reloads"
        )


class TestPhase3DropInsPresent:
    """LRR Phase 3 item 1 regression pins: the two new drop-ins shipped
    in this PR for partition reconciliation α → γ must exist in the
    repo and contain the expected environment variables.
    """

    TABBYAPI_DROPIN = REPO_ROOT / "systemd" / "units" / "tabbyapi.service.d" / "gpu-pin.conf"
    HAPAX_DAIMONION_DROPIN = (
        REPO_ROOT / "systemd" / "units" / "hapax-daimonion.service.d" / "gpu-pin.conf"
    )
    HAPAX_DMN_DROPIN_WRONG = (
        REPO_ROOT / "systemd" / "units" / "hapax-dmn.service.d" / "gpu-pin.conf"
    )

    def test_tabbyapi_dropin_exists(self) -> None:
        assert self.TABBYAPI_DROPIN.is_file(), (
            f"tabbyapi gpu-pin drop-in missing at {self.TABBYAPI_DROPIN} — "
            "Phase 3 partition reconciliation requires it"
        )

    def test_hapax_daimonion_dropin_exists(self) -> None:
        assert self.HAPAX_DAIMONION_DROPIN.is_file(), (
            f"hapax-daimonion gpu-pin drop-in missing at {self.HAPAX_DAIMONION_DROPIN} — "
            "Phase 3 partition reconciliation requires it"
        )

    def test_hapax_dmn_dropin_not_present(self) -> None:
        """PR #814 regression pin: the old mis-placed drop-in must not
        come back. ``hapax-dmn.service`` is CPU-only and any GPU-pin
        drop-in here is a no-op that misleads future readers."""
        assert not self.HAPAX_DMN_DROPIN_WRONG.exists(), (
            f"Stale hapax-dmn drop-in found at {self.HAPAX_DMN_DROPIN_WRONG}. "
            "hapax-dmn.service (agents.dmn) is CPU-only; the GPU-pin drop-in "
            "belongs on hapax-daimonion.service.d/ instead."
        )

    def test_tabbyapi_dropin_declares_option_gamma(self) -> None:
        body = self.TABBYAPI_DROPIN.read_text(encoding="utf-8")
        assert "[Service]" in body
        assert "CUDA_DEVICE_ORDER=PCI_BUS_ID" in body, (
            "tabbyapi drop-in must pin CUDA_DEVICE_ORDER=PCI_BUS_ID before any "
            "CUDA_VISIBLE_DEVICES line, or the device-index-to-card mapping "
            "inverts (see Phase 3 spec §1.1)"
        )
        assert "CUDA_VISIBLE_DEVICES=0,1" in body, (
            "tabbyapi drop-in must expose both GPUs under Option γ"
        )

    def test_hapax_daimonion_dropin_pinned_to_gpu_0(self) -> None:
        body = self.HAPAX_DAIMONION_DROPIN.read_text(encoding="utf-8")
        assert "[Service]" in body
        assert "CUDA_DEVICE_ORDER=PCI_BUS_ID" in body, (
            "hapax-daimonion drop-in must pin CUDA_DEVICE_ORDER=PCI_BUS_ID for the "
            "same reason as tabbyapi (see Phase 3 spec §1.1)"
        )
        assert "CUDA_VISIBLE_DEVICES=0" in body, (
            "hapax-daimonion drop-in must pin to GPU 0 (5060 Ti) under Option γ"
        )

    def test_tabbyapi_service_timeout_180(self) -> None:
        """Phase 3 item 8: TimeoutStartSec held at 180 s as substrate-swap headroom.

        Qwen 9B alone would fit a 120 s timeout, but 180 s is preserved as
        conservative headroom so any future substrate swap with a longer
        safetensors-shard load path does not silently start failing under
        a too-tight default.
        """
        svc = REPO_ROOT / "systemd" / "units" / "tabbyapi.service"
        body = svc.read_text(encoding="utf-8")
        assert "TimeoutStartSec=180" in body, (
            "tabbyapi.service TimeoutStartSec must be 180 s as substrate-swap "
            "headroom (Qwen 9B fits under this; longer-loading substrates need it)"
        )


class TestServiceAutoEnableList:
    """24h auditor batch 2026-05-02 finding #13 regression pins.

    Five service units shipped without auto-enable (PRs #2220, #2221, #2223,
    #2235, #2252) lived dormant on the operator workstation because the
    installer only auto-enabled timer units. ``hapax-preset-bias-heartbeat.service``
    (PR #2239) was superseded by the parametric-modulation heartbeat per memory
    ``feedback_no_presets_use_parametric_modulation`` and must be disabled+masked
    on subsequent installs.

    These pins lock in the AUTO_ENABLE_SERVICES array and the
    DECOMMISSIONED_UNITS membership so a future refactor that drops either
    is caught in CI.
    """

    EXPECTED_AUTO_ENABLE = (
        "hapax-bt-firmware-watchdog.service",
        "hapax-xhci-death-watchdog.service",
        "hapax-private-broadcast-leak-guard.service",
        "hapax-broadcast-egress-loopback-producer.service",
        "hapax-parametric-modulation-heartbeat.service",
    )

    def test_auto_enable_array_declared(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        assert "AUTO_ENABLE_SERVICES=(" in body, (
            "install-units.sh must declare the AUTO_ENABLE_SERVICES bash array "
            "so persistent-daemon services ship enabled by default"
        )

    def test_each_audit_service_in_auto_enable(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        for svc in self.EXPECTED_AUTO_ENABLE:
            assert svc in body, (
                f"AUTO_ENABLE_SERVICES must include {svc} per 24h audit batch "
                f"2026-05-02 finding #13 (feedback_features_on_by_default)"
            )

    def test_auto_enable_loop_uses_enable_now(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        # The auto-enable loop must use ``enable --now`` (so the daemon starts
        # immediately, not just on next boot). Look for the loop body.
        lines = body.splitlines()
        loop_started = False
        loop_uses_enable_now = False
        for line in lines:
            if "AUTO_ENABLE_SERVICES" in line and "for " in line:
                loop_started = True
                continue
            if loop_started and "systemctl --user enable --now" in line:
                if "$service_name" in line:
                    loop_uses_enable_now = True
                    break
            # Stop scanning if we hit the next top-level block before finding it
            if loop_started and line.startswith("# ") and "AUTO_ENABLE" not in line:
                break
        assert loop_uses_enable_now, (
            "AUTO_ENABLE_SERVICES loop must call ``systemctl --user enable --now "
            "<service>`` so shipped services start immediately, not on next boot"
        )

    def test_auto_enable_honors_skip_env_var(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        # The auto-enable block must respect SKIP_TIMER_ENABLE (shared escape
        # hatch) so operators have a quiet-install option during incident
        # response.
        assert "${SKIP_TIMER_ENABLE:-0}" in body
        # The skip path should at minimum mention auto-enabling
        assert "skipped auto-enabling" in body, (
            "SKIP_TIMER_ENABLE branch must announce that auto-enable was skipped "
            "so the operator notices the deferred work"
        )

    def test_auto_enable_skips_missing_units(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        # Defense-in-depth: auto-enable loop must skip + WARN if a listed unit
        # isn't on disk (covers the 'renamed unit but forgot to update array'
        # case). Look for the file-existence guard inside the loop.
        assert 'if [ ! -f "$REPO_DIR/$service_name" ]' in body, (
            "auto-enable loop must guard against missing unit files with a WARN, not a hard failure"
        )

    def test_auto_enable_skips_decommissioned_units(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        # If somebody puts a unit in both lists by mistake, prefer the
        # decommissioned semantics (disabled+masked). The loop must check.
        assert 'if is_decommissioned_unit "$service_name"' in body, (
            "auto-enable loop must defer to DECOMMISSIONED_UNITS to prevent "
            "double-bookkeeping mistakes"
        )


class TestAuditedUnitsExist:
    """Sanity pins: the unit files referenced by AUTO_ENABLE_SERVICES must
    exist in the repo. Catches the case where the array lists a unit that
    has been renamed or moved without updating the installer."""

    UNITS_DIR = REPO_ROOT / "systemd" / "units"
    EXPECTED_UNITS = (
        "hapax-bt-firmware-watchdog.service",
        "hapax-xhci-death-watchdog.service",
        "hapax-private-broadcast-leak-guard.service",
        "hapax-broadcast-egress-loopback-producer.service",
        "hapax-parametric-modulation-heartbeat.service",
        # Decommissioned but file must still be present so the disable+mask
        # path has something to act on.
    )

    def test_each_unit_file_present(self) -> None:
        for unit in self.EXPECTED_UNITS:
            path = self.UNITS_DIR / unit
            assert path.is_file(), (
                f"Expected unit file {path} to exist — install-units.sh "
                f"AUTO_ENABLE_SERVICES / DECOMMISSIONED_UNITS references it"
            )
