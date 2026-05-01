"""Regression pins for the tabbyapi-hermes8b second-instance retirement.

The Hermes 3 8B parallel-pivot was abandoned operator-side on 2026-04-15
(drop #62 §14, commit 2bc6aec17). The systemd unit and drop-in were
retained as audit-trail reference material for several weeks but were
never deployed and never had operator-ratified GPU pinning. Retirement
ratified 2026-04-30 (cc-task ``retire-tabbyapi-hermes8b-audit-unit``).

These pins lock the retirement in:

1. The unit and drop-in are gone from ``systemd/units/`` so
   ``hapax-post-merge-deploy`` does not reinstall them.
2. The unit name is in the ``DECOMMISSIONED_UNITS`` array in
   ``install-units.sh`` so existing linked symlinks (and the linked
   drop-in directory) on already-deployed hosts get cleaned, disabled,
   and masked on next install run.
3. The ``remove_decommissioned_unit`` function in install-units.sh
   handles drop-in directory cleanup, not just top-level symlinks —
   the hermes8b unit shipped with a drop-in and other future
   decommissions may too.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
INSTALL_SCRIPT = REPO_ROOT / "systemd" / "scripts" / "install-units.sh"


def test_hermes8b_unit_file_removed() -> None:
    assert not (UNITS_DIR / "tabbyapi-hermes8b.service").exists(), (
        "tabbyapi-hermes8b.service must not exist under systemd/units; "
        "the second-instance Hermes pivot was abandoned 2026-04-15"
    )


def test_hermes8b_dropin_dir_removed() -> None:
    assert not (UNITS_DIR / "tabbyapi-hermes8b.service.d").exists(), (
        "tabbyapi-hermes8b.service.d/ must not exist under systemd/units; "
        "the GPU-pin drop-in was retained only as TODO scaffold for the "
        "operator-decision-required deploy that never happened"
    )


def test_install_units_marks_hermes8b_decommissioned() -> None:
    body = INSTALL_SCRIPT.read_text(encoding="utf-8")
    assert "tabbyapi-hermes8b.service" in body, (
        "install-units.sh must list tabbyapi-hermes8b.service in "
        "DECOMMISSIONED_UNITS so existing linked symlinks on already-"
        "deployed hosts get cleaned up on next install run"
    )


def test_install_units_cleans_decommissioned_dropin_dirs() -> None:
    """The hermes8b decommission needs drop-in dir cleanup, not just the
    top-level unit symlink — the unit shipped with a ``.service.d/``
    directory containing the gpu-pin.conf TODO scaffold."""
    body = INSTALL_SCRIPT.read_text(encoding="utf-8")
    assert 'dropin_dir="$DEST_DIR/${name}.d"' in body, (
        "remove_decommissioned_unit must compute the drop-in dir path"
    )
    assert 'rm -rf "$dropin_dir"' in body, (
        "remove_decommissioned_unit must rm -rf the drop-in dir so "
        "stale conf symlinks don't survive the unit retirement"
    )
