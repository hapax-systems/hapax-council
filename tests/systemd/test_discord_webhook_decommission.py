"""Regression pins for the ``discord-webhook`` surface + systemd unit retirement.

The Discord cross-surface webhook poster was retired 2026-05-01 per cc-task
``discord-public-event-activation-or-retire``. The constitutional refusal
predates the retirement by several days (``leverage-REFUSED-discord-community``
ratified 2026-04-26) — the retirement closes the drift between the refusal-brief
posture and the still-deployed webhook agent.

These pins lock the retirement in:

1. The systemd unit and its `.service.d/` (if any) are gone from
   ``systemd/units/`` so ``hapax-post-merge-deploy`` does not reinstall them.
2. The unit is in ``DECOMMISSIONED_UNITS`` in ``install-units.sh`` so already-
   linked symlinks on deployed hosts get cleaned, disabled, and masked.
3. The canonical surface registry has ``discord-webhook`` at ``REFUSED`` tier
   pointing at the existing ``leverage-discord-community.md`` brief, NOT at
   FULL_AUTO with a dispatch entry.
4. The orchestrator's runtime dispatch registry (``FULL_AUTO`` +
   ``CONDITIONAL_ENGAGE`` only) does not include ``discord-webhook`` —
   ``REFUSED`` surfaces must be quarantined from runtime fanout.
5. The cross-surface module entry exits with the retirement message instead
   of starting the daemon — guards against operator accidentally running
   ``python -m agents.cross_surface`` post-retirement.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
INSTALL_SCRIPT = REPO_ROOT / "systemd" / "scripts" / "install-units.sh"


def test_discord_webhook_unit_file_removed() -> None:
    assert not (UNITS_DIR / "hapax-discord-webhook.service").exists(), (
        "hapax-discord-webhook.service must not exist under systemd/units; "
        "the surface was retired 2026-05-01 per leverage-REFUSED-discord-community"
    )


def test_discord_webhook_unit_dropin_dir_removed() -> None:
    assert not (UNITS_DIR / "hapax-discord-webhook.service.d").exists(), (
        "hapax-discord-webhook.service.d/ must not exist under systemd/units; "
        "no drop-in survives the unit retirement"
    )


def test_install_units_marks_discord_webhook_decommissioned() -> None:
    body = INSTALL_SCRIPT.read_text(encoding="utf-8")
    assert "hapax-discord-webhook.service" in body, (
        "install-units.sh must list hapax-discord-webhook.service in "
        "DECOMMISSIONED_UNITS so existing linked symlinks on already-"
        "deployed hosts get cleaned up + disabled + masked on next install run"
    )


def test_discord_webhook_surface_registry_is_refused() -> None:
    """Canonical surface registry must classify discord-webhook as REFUSED."""
    from agents.publication_bus.surface_registry import (
        SURFACE_REGISTRY,
        AutomationStatus,
    )

    spec = SURFACE_REGISTRY["discord-webhook"]
    assert spec.automation_status == AutomationStatus.REFUSED, (
        f"discord-webhook must be REFUSED tier, got {spec.automation_status}"
    )
    assert spec.dispatch_entry is None, (
        "REFUSED surfaces must not carry a dispatch_entry (the orchestrator "
        "would otherwise import the retired agent module)"
    )
    assert spec.refusal_link == "docs/refusal-briefs/leverage-discord-community.md", (
        "discord-webhook refusal_link must point at the canonical leverage-discord-community brief"
    )


def test_discord_webhook_quarantined_from_orchestrator_dispatch() -> None:
    """The orchestrator's runtime dispatch registry must not contain
    discord-webhook (REFUSED surfaces are filtered out by is_engageable)."""
    from agents.publication_bus.surface_registry import dispatch_registry

    runtime = dispatch_registry()
    assert "discord-webhook" not in runtime, (
        "discord-webhook must not appear in the runtime dispatch registry; "
        "REFUSED-tier surfaces are quarantined from orchestrator fanout"
    )


def test_cross_surface_main_entry_exits_with_refusal() -> None:
    """`python -m agents.cross_surface` must refuse to start, not silently
    invoke the retired Discord poster main()."""
    body = (REPO_ROOT / "agents" / "cross_surface" / "__main__.py").read_text(encoding="utf-8")
    assert "REFUSAL_MESSAGE" in body, (
        "cross_surface __main__ must define a refusal message constant"
    )
    assert "sys.exit(2)" in body, (
        "cross_surface __main__ must exit non-zero on invocation post-retirement"
    )
    assert "from agents.cross_surface.discord_webhook import main" not in body, (
        "cross_surface __main__ must not import the retired daemon main()"
    )
