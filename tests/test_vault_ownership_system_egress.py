"""System-directory egress filter (OQ-9).

``write_to_vault`` writes the wholly daemon-owned ``30-system/`` tree, so its guard
must NOT drop frontmatter for daemon-generated or unrecognised note types — only for
a genuine operator note type mistakenly routed through it. Regression for the
over-aggressive first cut that refused every key on an unknown type, blanking the
frontmatter of legitimate system writes.
"""

from __future__ import annotations

from shared.vault_ownership import filter_system_egress


def test_daemon_note_type_passes_through() -> None:
    fm = {"type": "briefing", "headline": "x", "generated_at": "t"}
    assert filter_system_egress("briefing", fm) == fm


def test_unknown_note_type_passes_through() -> None:
    fm = {"type": "test", "version": 1}
    assert filter_system_egress("test", fm) == fm


def test_none_note_type_passes_through() -> None:
    fm = {"anything": 1}
    assert filter_system_egress(None, fm) == fm


def test_operator_note_type_is_still_filtered() -> None:
    # A measure note routed through the system writer: operator keys refused.
    out = filter_system_egress("measure", {"status": "completed", "title": "operator"}, warn=False)
    assert out == {"status": "completed"}


def test_returns_independent_copy() -> None:
    fm = {"type": "digest", "x": 1}
    out = filter_system_egress("digest", fm)
    out["x"] = 2
    assert fm["x"] == 1
