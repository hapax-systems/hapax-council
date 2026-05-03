"""Tests for cc-task hapax-logos-decommission-cleanup.

Pins the cleanup contract: the maintenance scripts that previously probed
or gated on the decommissioned Tauri/WebKit hapax-logos surface must no
longer treat it as a live dependency. These regressions are easy to
re-introduce with a copy-paste of an old script template, so the tests
exist to break that loop.

Out of scope (deliberate, per the cc-task body):
- visual-audit.sh / smoke-test.sh decom validators that explicitly assert
  the surface is absent are kept — those make the decom obvious by
  enforcing it, not by treating logos as live.
- DECOMMISSIONED_UNITS in install-units.sh — same role, kept.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"


def test_freshness_check_no_longer_probes_retired_units() -> None:
    """scripts/freshness-check.sh must not iterate retired Tauri/WebKit units.

    The legacy `for unit in hapax-logos.service hapax-build-reload.path
    logos-dev.service` loop was ambiguous — it printed an "ok" line for
    every successful run, masking the fact that those units have been
    retired for weeks. smoke-test.sh now owns decom enforcement and
    install-units.sh's DECOMMISSIONED_UNITS owns absence guarantees;
    freshness-check.sh has no remaining role here.
    """
    content = (SCRIPTS_DIR / "freshness-check.sh").read_text()
    assert "for unit in hapax-logos.service" not in content, (
        "freshness-check.sh still iterates retired Tauri/WebKit units; "
        "the loop was retired in cc-task hapax-logos-decommission-cleanup. "
        "smoke-test.sh enforces decom; freshness-check.sh shouldn't probe."
    )


def test_post_merge_smoke_no_dependent_component_gate() -> None:
    """hapax-post-merge-smoke must not gate on hapax-logos crates changing.

    The `gate_dependent_component` function ran when files under
    `hapax-logos/crates/hapax-visual/*` or `hapax-logos/crates/hapax-imagination/*`
    changed. With the Tauri/WebKit hapax-logos surface decommissioned and
    the imagination binary built via the kept-for-compat
    hapax-rebuild-logos.timer chain (which has its own provenance check
    in smoke-test.sh), the gate was never going to fire and added
    confusion about whether the surface was still live.
    """
    content = (SCRIPTS_DIR / "hapax-post-merge-smoke").read_text()
    assert "gate_dependent_component" not in content, (
        "gate_dependent_component must be removed (function definition AND "
        "the call); the hapax-logos crate paths it watched are no longer "
        "live consumer dependencies."
    )
    assert "hapax-logos/crates/hapax-visual/" not in content, (
        "hapax-logos/crates/hapax-visual/* path must not appear in the post-merge smoke gates."
    )


def test_post_merge_deploy_comment_clarifies_logos_decom() -> None:
    """The hapax-post-merge-deploy header comment must reflect that the
    rebuild-logos timer now only builds hapax-imagination.

    The original comment `hapax-logos/** → rebuild-logos.timer` was
    correct when the Tauri preview was the rebuild target. After
    decom, the timer was repurposed to build hapax-imagination
    only — the comment must call that out so future operators don't
    re-investigate the same dead-end.
    """
    content = (SCRIPTS_DIR / "hapax-post-merge-deploy").read_text()
    assert "hapax-rebuild-logos.timer" in content, (
        "comment should mention hapax-rebuild-logos.timer (kept-for-compat name)"
    )
    assert "hapax-imagination" in content, (
        "comment should mention what the timer actually builds (hapax-imagination)"
    )
    assert "decommissioned" in content.lower() or "decom" in content.lower(), (
        "comment should make the hapax-logos decommission state obvious"
    )
