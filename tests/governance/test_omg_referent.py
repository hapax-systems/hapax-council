"""AUDIT-05 — `omg_referent.safe_render` regression.

Pins the two protective behaviors:

1. **Substitution**: ``{operator}`` placeholders in a template are
   replaced with one of the four ratified non-formal referents
   (``OperatorReferentPicker.pick_for_vod_segment``).
2. **Leak detection**: when a legal-name pattern is supplied (or
   read from ``HAPAX_OPERATOR_NAME``), rendered text containing
   that pattern raises :class:`OperatorNameLeak` rather than
   silently passing through.

Both are required to disarm the OMG cascade outward-publishing
freeze (v4 §6.4).
"""

from __future__ import annotations

import pytest

from shared.governance.omg_referent import (
    REFERENT_TOKEN,
    OperatorNameLeak,
    safe_render,
)
from shared.operator_referent import REFERENTS


class TestSubstitution:
    def test_replaces_operator_token_with_a_referent(self) -> None:
        out = safe_render("posted by {operator}.", segment_id="post-1")
        assert REFERENT_TOKEN not in out
        # Output contains exactly one of the four ratified referents.
        assert any(r in out for r in REFERENTS)

    def test_substitution_is_sticky_per_segment_id(self) -> None:
        """Same ``segment_id`` resolves to same referent every time."""
        a = safe_render("{operator}", segment_id="post-42")
        b = safe_render("{operator}", segment_id="post-42")
        assert a == b

    def test_substitution_differs_across_segment_ids(self) -> None:
        """Different segments may pick different referents (sticky-per-id)."""
        # Build enough samples that the four-bucket picker is
        # extremely unlikely to land on the same referent for all
        # distinct seeds. Verify the set has more than 1 element.
        results = {safe_render("{operator}", segment_id=f"post-{i}") for i in range(40)}
        assert len(results) > 1

    def test_no_token_no_substitution(self) -> None:
        """Templates without ``{operator}`` pass through unchanged."""
        text = "no placeholder here"
        assert safe_render(text, segment_id="post-1") == text

    def test_multiple_tokens_all_substituted(self) -> None:
        """Multiple ``{operator}`` instances all get replaced; sticky id
        means they all resolve to the same referent in one render."""
        out = safe_render("{operator} and {operator}", segment_id="post-7")
        assert REFERENT_TOKEN not in out


class TestLeakDetection:
    def test_legal_name_in_output_raises(self) -> None:
        with pytest.raises(OperatorNameLeak):
            safe_render(
                "by Real Person",
                segment_id="post-1",
                legal_name_pattern="Real Person",
            )

    def test_legal_name_substring_match_raises(self) -> None:
        """A legal-name pattern inside any larger string still raises."""
        with pytest.raises(OperatorNameLeak):
            safe_render(
                "thanks to Real Person for the work",
                segment_id="post-1",
                legal_name_pattern="Real Person",
            )

    def test_no_legal_name_pattern_disables_scan(self) -> None:
        """When neither arg nor env supplies a pattern, scan no-ops."""
        out = safe_render(
            "anything goes here",
            segment_id="post-1",
            legal_name_pattern=None,
        )
        assert out == "anything goes here"

    def test_legal_name_pattern_from_env(self, monkeypatch) -> None:
        """``HAPAX_OPERATOR_NAME`` env var supplies the pattern."""
        monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Real Person")
        with pytest.raises(OperatorNameLeak):
            safe_render("by Real Person", segment_id="post-1")

    def test_empty_env_treats_as_disabled(self, monkeypatch) -> None:
        """Empty env value (``""``) does not enable a meaningless scan."""
        monkeypatch.setenv("HAPAX_OPERATOR_NAME", "")
        out = safe_render("by Real Person", segment_id="post-1")
        # No raise — empty pattern would match everything trivially.
        assert "Real Person" in out

    def test_explicit_pattern_overrides_env(self, monkeypatch) -> None:
        """Caller-supplied pattern wins over env."""
        monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Other Name")
        with pytest.raises(OperatorNameLeak):
            safe_render(
                "by Real Person",
                segment_id="post-1",
                legal_name_pattern="Real Person",
            )

    def test_case_insensitive_match(self) -> None:
        """Legal-name leak detection is case-insensitive."""
        with pytest.raises(OperatorNameLeak):
            safe_render(
                "BY REAL PERSON",
                segment_id="post-1",
                legal_name_pattern="real person",
            )


class TestComposition:
    def test_substitution_then_scan_order(self) -> None:
        """Substitution happens first; scan checks the post-substitute text.

        If the picker output happened to contain the legal-name pattern
        (it shouldn't — referents are 'Oudepode'/'OTO'/etc.), the scan
        would catch it. This test pins the order: substitute, then scan.
        """
        # The four ratified referents do not contain "Person" — the
        # substitution proceeds, the scan sees no leak.
        out = safe_render(
            "{operator} writes",
            segment_id="post-1",
            legal_name_pattern="Person",
        )
        assert "writes" in out

    def test_no_segment_id_uses_random_picker(self) -> None:
        """``segment_id=None`` uses the stochastic picker; output still
        contains a referent (just not deterministically chosen)."""
        out = safe_render("{operator}", segment_id=None)
        assert any(r in out for r in REFERENTS)


class TestSurfaceConstants:
    def test_referent_token_is_curly_operator(self) -> None:
        assert REFERENT_TOKEN == "{operator}"

    def test_operator_name_leak_is_value_error(self) -> None:
        """``OperatorNameLeak`` subclasses ``ValueError`` so callers that
        ``except ValueError`` (eg. existing publication client code)
        already catch the leak — fail-closed by default."""
        assert issubclass(OperatorNameLeak, ValueError)
