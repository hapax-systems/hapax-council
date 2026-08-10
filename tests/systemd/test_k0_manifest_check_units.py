"""Contract tests for the K0 manifest checker scheduling units + wrapper.

Architecture under test: the .service runs scripts/hapax-k0-manifest-check-run
(from the governed activation worktree), which refreshes a read-only mirror of
reins origin/main and execs the checker with the full --repo-root form against
governed trees only (activation worktree for council, the mirror for reins).
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS = REPO_ROOT / "systemd" / "units"


def _service() -> str:
    return (UNITS / "hapax-k0-manifest-check.service").read_text(encoding="utf-8")


def _timer() -> str:
    return (UNITS / "hapax-k0-manifest-check.timer").read_text(encoding="utf-8")


def _wrapper() -> str:
    return (REPO_ROOT / "scripts" / "hapax-k0-manifest-check-run").read_text(encoding="utf-8")


def test_service_execs_the_wrapper_from_the_activation_worktree() -> None:
    service = _service()
    assert (
        "ExecStart=/home/hapax/.cache/hapax/source-activation/worktree/scripts/hapax-k0-manifest-check-run"
        in service
    )
    # never a mutable dev or vault checkout anywhere in the unit
    assert "projects/hapax-council" not in service
    assert "projects/reins" not in service
    assert "Documents/Personal" not in service


def test_wrapper_uses_full_repo_root_form_against_governed_trees() -> None:
    wrapper = _wrapper()
    assert "--repo-root" in wrapper
    assert "hapax-council=$ACTIVATION" in wrapper
    assert '"reins-dev=$MIRROR"' in wrapper
    assert "--allow-skipped-artifacts" not in wrapper  # never the false-green form


def test_wrapper_checks_reins_from_a_read_only_mirror() -> None:
    wrapper = _wrapper()
    assert "checkout --quiet --detach origin/main" in wrapper
    assert "projects/reins" not in wrapper  # never the mutable local checkout


def test_failure_notification_is_in_the_unit_section() -> None:
    service = _service()
    unit_section = service.split("[Service]")[0]
    assert "OnFailure=notify-failure@" in unit_section


def test_governed_deploy_marker_is_on_the_timer() -> None:
    assert "reform-improve-deploy-activation" in _timer()  # the timer is the enable target


def test_timer_is_daily_persistent_with_jitter() -> None:
    timer = _timer()
    assert "OnCalendar=*-*-* 04:17:00" in timer
    assert "Persistent=true" in timer
    assert "RandomizedDelaySec=" in timer
    assert "Unit=hapax-k0-manifest-check.service" in timer
