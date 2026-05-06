"""Tests for chronicle salience tagging on operational mail events.

Fourth in the *no in-tree emitter sets salience* cleanup series after
stimmung (#2637), m8 day-roll (#2661), and narration_triad (#2669).
``mail_monitor_operational`` is not in the chronicle-ticker source
allow-list, so without ``salience >= 0.7`` operational events
(TLS / DNS / Dependabot) never surface.
"""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("dependabot", 0.9),  # Security alerts top priority.
        ("tls_expiry", 0.85),  # Cert renewal.
        ("dns", 0.8),  # DNS changes.
    ],
)
def test_kind_salience_floor(kind: str, expected: float) -> None:
    from agents.mail_monitor.processors.operational import _OPERATIONAL_EVENT_SALIENCE

    assert _OPERATIONAL_EVENT_SALIENCE[kind] == expected
    # All variants must clear the chronicle-ticker floor (0.7) so the
    # ward surfaces them independent of the source allow-list.
    assert _OPERATIONAL_EVENT_SALIENCE[kind] >= 0.7


def test_unknown_kind_default_below_table() -> None:
    """Unknown operational kinds fall back to a payload-default of 0.75
    inside ``_emit_chronicle`` — not the lookup table itself."""
    from agents.mail_monitor.processors.operational import _OPERATIONAL_EVENT_SALIENCE

    assert "imaginary-kind" not in _OPERATIONAL_EVENT_SALIENCE


def test_table_keys_match_canonical_kinds() -> None:
    """Every constant in ``OPERATIONAL_KIND_*`` should have an entry."""
    from agents.mail_monitor.processors.operational import (
        _OPERATIONAL_EVENT_SALIENCE,
        OPERATIONAL_KIND_DEPENDABOT,
        OPERATIONAL_KIND_DNS,
        OPERATIONAL_KIND_TLS,
    )

    canonical = {OPERATIONAL_KIND_TLS, OPERATIONAL_KIND_DEPENDABOT, OPERATIONAL_KIND_DNS}
    assert canonical <= set(_OPERATIONAL_EVENT_SALIENCE.keys())


def test_dependabot_outranks_tls_outranks_dns() -> None:
    """Salience should rank security > availability > diagnostics."""
    from agents.mail_monitor.processors.operational import (
        _OPERATIONAL_EVENT_SALIENCE,
        OPERATIONAL_KIND_DEPENDABOT,
        OPERATIONAL_KIND_DNS,
        OPERATIONAL_KIND_TLS,
    )

    assert (
        _OPERATIONAL_EVENT_SALIENCE[OPERATIONAL_KIND_DEPENDABOT]
        > _OPERATIONAL_EVENT_SALIENCE[OPERATIONAL_KIND_TLS]
        > _OPERATIONAL_EVENT_SALIENCE[OPERATIONAL_KIND_DNS]
    )
