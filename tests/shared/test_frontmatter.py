"""Direct unit coverage for the canonical frontmatter parser.

``shared/frontmatter.py`` is named the estate's canonical frontmatter parser and
has consumers well beyond the SDLC path (``sdlc_task_store``, ``vault_utils``,
``publication_hardening``). Its fence rule was rewritten during PR #4669 after
the close-path snapshot was found dropping a task's declared review requirement,
and until now the only pin was an indirect end-to-end assertion through
``_snapshot``.

These are the parser's own boundary cases, so a future edit here cannot regress
the two parsers back into disagreeing about what a fence is — which is what
produced the closure trap in the first place.
"""

from __future__ import annotations

import pytest

from shared.frontmatter import parse_frontmatter_with_diagnostics
from shared.sdlc_lifecycle import frontmatter_state_from_text, is_frontmatter_fence


class TestFenceGrammar:
    """``---`` at column 0, followed by end-of-line or whitespace. Nothing else.

    Three review rounds each corrected one row of this table by adjusting a
    predicate, and each correction broke a different row: ``startswith``
    admitted the mapping key, ``strip()`` admitted the indented line,
    ``rstrip() == "---"`` rejected the comment. One grammar, stated once.
    """

    @pytest.mark.parametrize("line", ["---", "--- ", "---\t", "--- # task metadata", "---\t# note"])
    def test_recognized(self, line: str) -> None:
        assert is_frontmatter_fence(line) is True

    @pytest.mark.parametrize(
        "line",
        [
            "---extra: abc",  # a legal mapping key, not a marker
            "----",
            "  ---",  # indented: scalar content inside a literal block
            "\t---",
            "",
            "task_id: x",
            "-- -",
        ],
    )
    def test_rejected(self, line: str) -> None:
        assert is_frontmatter_fence(line) is False


class TestCanonicalParserBoundaries:
    def test_commented_opening_fence_is_parsed(self) -> None:
        """``--- # task metadata`` is a supported header and must not disarm."""
        text = "--- # task metadata\nquality_floor: frontier_review_required\n---\nbody\n"

        result = parse_frontmatter_with_diagnostics(text)

        assert result.error_kind is None
        assert result.frontmatter == {"quality_floor": "frontier_review_required"}

    def test_dash_prefixed_key_does_not_close_the_block(self) -> None:
        text = (
            "---\ntask_id: x\n---extra: abc\n"
            "review_requirement:\n  independent_review_required: true\n---\nbody\n"
        )

        result = parse_frontmatter_with_diagnostics(text)

        assert result.error_kind is None
        assert result.frontmatter is not None
        assert result.frontmatter["---extra"] == "abc"
        assert result.frontmatter["review_requirement"] == {"independent_review_required": True}

    def test_indented_dashes_in_a_literal_scalar_do_not_close_the_block(self) -> None:
        text = (
            "---\ntask_id: x\ndescription: |\n  ---\n"
            "review_requirement:\n  independent_review_required: true\n---\nbody\n"
        )

        result = parse_frontmatter_with_diagnostics(text)

        assert result.error_kind is None
        assert result.frontmatter is not None
        assert "review_requirement" in result.frontmatter

    def test_adjacent_fences_are_empty_frontmatter(self) -> None:
        result = parse_frontmatter_with_diagnostics("---\n---\nbody\n")

        assert result.error_kind is None
        assert result.frontmatter == {}

    def test_body_offset_survives_a_fence_with_trailing_whitespace(self) -> None:
        result = parse_frontmatter_with_diagnostics("---\ntask_id: x\n--- \nbody line\n")

        assert result.error_kind is None
        assert result.body.startswith("body line")

    def test_missing_closing_fence_is_diagnosed(self) -> None:
        result = parse_frontmatter_with_diagnostics("---\ntask_id: x\nbody with no close\n")

        assert result.error_kind == "missing_closing_marker"

    def test_document_without_frontmatter_is_diagnosed(self) -> None:
        result = parse_frontmatter_with_diagnostics("plain body\n")

        assert result.error_kind == "missing_frontmatter"


class TestParserAgreement:
    """Both parsers must answer the fence question identically.

    They are separate implementations for a real reason — the close gate runs
    under a bare ``python3`` and must not import pydantic — so the guarantee has
    to be a test, not an assumption.
    """

    @pytest.mark.parametrize(
        "text",
        [
            "---\ntask_id: x\n---\nbody\n",
            "--- # task metadata\ntask_id: x\n---\nbody\n",
            "---\ntask_id: x\n---extra: abc\nkeep: 1\n---\nbody\n",
            "---\ntask_id: x\ndescription: |\n  ---\nkeep: 1\n---\nbody\n",
            "---\n---\nbody\n",
            "---\n\n---\nbody\n",
            "---\ntask_id: x\n--- \nbody\n",
            "plain body\n",
        ],
    )
    def test_both_parsers_extract_the_same_mapping(self, text: str) -> None:
        canonical = parse_frontmatter_with_diagnostics(text)
        sdlc_mapping, _ = frontmatter_state_from_text(text)

        assert (canonical.frontmatter or {}) == sdlc_mapping
