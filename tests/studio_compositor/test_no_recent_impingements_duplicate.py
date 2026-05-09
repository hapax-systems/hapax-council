"""2026-04-23 Gemini-audit Phase 3 regression pin.

The compositor-embedded recent-impingements publisher (PR #1209) was a
duplicate of the dedicated systemd unit
``hapax-recent-impingements.service`` and read the wrong JSONL key
(``salience`` instead of ``strength``), leaving empty-string entries in
``/dev/shm/hapax-compositor/recent-impingements.json`` on the live
broadcast.

The single writer for that SHM path is the systemd producer at
``scripts/hapax-recent-impingements-producer``. Any reintroduction of a
compositor-embedded publisher re-introduces the race.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).parents[2]
_STUDIO_COMPOSITOR = _REPO_ROOT / "agents" / "studio_compositor"


def test_orphan_publisher_module_does_not_exist() -> None:
    """``agents/studio_compositor/recent_impingements_publisher.py`` is forbidden."""
    orphan = _STUDIO_COMPOSITOR / "recent_impingements_publisher.py"
    assert not orphan.exists(), (
        f"{orphan} reappeared. This module duplicates "
        "scripts/hapax-recent-impingements-producer + its systemd unit "
        "and caused a live SHM race. If a compositor-embedded variant is "
        "truly needed, delete the systemd unit first."
    )


def test_compositor_does_not_import_orphan_publisher() -> None:
    """Compositor must not import from ``recent_impingements_publisher``."""
    compositor = _STUDIO_COMPOSITOR / "compositor.py"
    text = compositor.read_text()
    assert "recent_impingements_publisher" not in text, (
        "compositor.py still references the removed recent_impingements_publisher "
        "module. The systemd unit hapax-recent-impingements.service is the "
        "single writer for /dev/shm/hapax-compositor/recent-impingements.json."
    )
    assert "RecentImpingementsPublisher" not in text, (
        "compositor.py still references the removed RecentImpingementsPublisher class."
    )


def test_ward_publisher_schemas_still_available_as_contract_surface() -> None:
    """The shared schemas file survives as a contract surface for future callers.

    The systemd producer currently inlines its own dict shape; the
    pydantic models in ``shared/ward_publisher_schemas`` document the
    wire contract. Keeping the schema module enables future consumers
    (ticker ward, Prometheus exporter, etc.) to type-check their reads.
    """
    from shared.ward_publisher_schemas import RecentImpingementEntry

    fields = set(RecentImpingementEntry.model_fields.keys())
    assert fields == {"path", "value", "family"}, (
        "Schema drifted from the systemd producer's on-disk keys. "
        "Update scripts/hapax-recent-impingements-producer or this schema."
    )
