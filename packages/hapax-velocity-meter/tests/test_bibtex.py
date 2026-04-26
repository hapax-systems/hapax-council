"""Tests for BibTeX self-citation."""

from __future__ import annotations

from hapax_velocity_meter.bibtex import bibtex_self_citation


def test_bibtex_includes_methodology_url() -> None:
    text = bibtex_self_citation()
    assert "hapax.weblog.lol/velocity-report-2026-04-25" in text


def test_bibtex_two_entries() -> None:
    text = bibtex_self_citation()
    assert text.count("@") == 2
    assert "@misc{hapax_velocity_2026" in text
    assert "@software{hapax_velocity_meter_2026" in text


def test_bibtex_mentions_polyform() -> None:
    text = bibtex_self_citation()
    assert "PolyForm Strict 1.0.0" in text
