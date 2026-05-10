"""LRR Phase 2 archive install regression pins.

Delta's 2026-04-14-lrr-phase-2-hls-archive-dormant.md found that
Phase 2 had shipped ``systemd/units/hls-archive-rotate.{service,timer}``
into the repo but the operator had never run ``install-units.sh`` on
the live system — so every HLS segment was deleted at the hlssink2
``max_files=15`` boundary (~60 seconds) with zero observable signal.
The current live-cache boundary is intentionally larger
(``max_files=120``), but archive rotation still runs every 60 seconds so
archival lag stays visible before the live cache needs to evict files.

These pins make three guarantees:

1. The repo still contains both unit files (rename/delete guard).
2. The ``studio-compositor.service`` ExecStartPre chain references
   the archive precheck script so the compositor start path emits
   a WARN if the timer isn't enabled.
3. The precheck script exists, is executable, creates the archive
   dirs, and calls ``systemctl --user is-enabled`` /
   ``is-active`` against the timer — so the check is real, not a
   no-op.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

HLS_TIMER = REPO_ROOT / "systemd" / "units" / "hls-archive-rotate.timer"
HLS_SERVICE = REPO_ROOT / "systemd" / "units" / "hls-archive-rotate.service"
STUDIO_SERVICE = REPO_ROOT / "systemd" / "units" / "studio-compositor.service"
ARCHIVE_PRECHECK = REPO_ROOT / "scripts" / "studio-compositor-archive-precheck.sh"
INSTALL_UNITS = REPO_ROOT / "systemd" / "scripts" / "install-units.sh"


class TestPhase2ArchiveUnitFilesExist:
    def test_hls_rotate_timer_file_present(self) -> None:
        assert HLS_TIMER.is_file(), (
            f"hls-archive-rotate.timer missing at {HLS_TIMER} — "
            "Phase 2 rotation pipeline regression"
        )

    def test_hls_rotate_service_file_present(self) -> None:
        assert HLS_SERVICE.is_file(), (
            f"hls-archive-rotate.service missing at {HLS_SERVICE} — "
            "Phase 2 rotation pipeline regression"
        )

    def test_timer_runs_on_unit_active_sec_interval(self) -> None:
        body = HLS_TIMER.read_text(encoding="utf-8")
        assert "OnUnitActiveSec=60s" in body, (
            "timer cadence must be 60s so segments rotate well before the "
            "current hlssink2 max_files=120 live-cache boundary"
        )


class TestStudioCompositorArchivePrecheckWired:
    def test_precheck_script_exists(self) -> None:
        assert ARCHIVE_PRECHECK.is_file(), f"archive precheck script missing at {ARCHIVE_PRECHECK}"

    def test_precheck_script_is_executable(self) -> None:
        import os

        assert os.access(ARCHIVE_PRECHECK, os.X_OK), (
            "archive precheck script must be executable (chmod +x) so ExecStartPre can invoke it"
        )

    def test_studio_compositor_service_references_precheck(self) -> None:
        body = STUDIO_SERVICE.read_text(encoding="utf-8")
        assert "studio-compositor-archive-precheck.sh" in body, (
            "studio-compositor.service must include an ExecStartPre line "
            "for the archive precheck so the Phase 2 timer install status "
            "is verified on every compositor start"
        )
        assert "ExecStartPre" in body
        # Ensure it's in the ExecStartPre block, not in a comment or
        # ExecStopPost.
        pre_lines = [
            line
            for line in body.splitlines()
            if line.startswith("ExecStartPre=") and "archive-precheck" in line
        ]
        assert len(pre_lines) == 1, (
            f"expected exactly 1 ExecStartPre line for archive precheck, got {len(pre_lines)}"
        )

    def test_service_does_not_delete_hls_cache_on_start(self) -> None:
        """LRR Phase 2 spec §3.2 (item 2) regression pin.

        The old ``ExecStartPre=/usr/bin/find ~/.cache/hapax-compositor/hls -type f -delete``
        line deleted every unrotated HLS segment on every compositor restart,
        defeating the archive rotator. Phase 2 requires the HLS cache to be
        treated as a staging area, not a purge target. This test fires if
        the delete-on-start line is re-introduced (via revert, copy-paste
        from an older branch, or a well-meaning "clean up stale data" PR).
        """
        body = STUDIO_SERVICE.read_text(encoding="utf-8")
        exec_pre_lines = [
            line
            for line in body.splitlines()
            if line.startswith("ExecStartPre=") and "hapax-compositor/hls" in line
        ]
        for line in exec_pre_lines:
            assert "-delete" not in line, (
                f"studio-compositor.service ExecStartPre line deletes HLS cache on "
                f"start, violating LRR Phase 2 spec §3.2: {line!r}. The rotator "
                f"(hls-archive-rotate.timer, 60s cadence) persists segments to the "
                f"archive; wiping the cache on restart breaks the archive pipeline."
            )


class TestArchivePrecheckScriptContents:
    def test_precheck_creates_hls_archive_dir(self) -> None:
        body = ARCHIVE_PRECHECK.read_text(encoding="utf-8")
        assert "mkdir -p" in body
        assert "stream-archive/hls" in body

    def test_precheck_creates_audio_archive_dir(self) -> None:
        body = ARCHIVE_PRECHECK.read_text(encoding="utf-8")
        assert "stream-archive/audio" in body

    def test_precheck_verifies_timer_enabled(self) -> None:
        body = ARCHIVE_PRECHECK.read_text(encoding="utf-8")
        assert "hls-archive-rotate.timer" in body
        assert "is-enabled" in body or "is-active" in body, (
            "precheck must call systemctl --user is-enabled/is-active against "
            "the hls-archive-rotate timer to catch a missing install"
        )

    def test_precheck_is_non_fatal(self) -> None:
        """A broken precheck must never block compositor startup."""
        body = ARCHIVE_PRECHECK.read_text(encoding="utf-8")
        assert "exit 0" in body, (
            "precheck must explicitly exit 0 so a missing timer never "
            "blocks the compositor from starting (livestream uptime > "
            "archive completeness)"
        )


class TestInstallUnitsHandlesNewTimers:
    """install-units.sh must auto-enable newly installed timers.

    The original Phase 2 regression was: install-units.sh was not run
    after merge, so the hls-archive-rotate.timer was never enabled.
    The script's existing behavior already covers this — pin it so
    any refactor that drops auto-enable is caught in CI.
    """

    def test_install_script_exists(self) -> None:
        assert INSTALL_UNITS.is_file(), f"install-units.sh missing at {INSTALL_UNITS}"

    def test_install_script_enables_new_timers(self) -> None:
        body = INSTALL_UNITS.read_text(encoding="utf-8")
        assert "systemctl --user enable" in body, (
            "install-units.sh must auto-enable newly linked timers so a "
            "Phase 2-style 'shipped but not installed' regression cannot "
            "happen again"
        )
