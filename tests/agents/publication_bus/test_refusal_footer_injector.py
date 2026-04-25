"""Tests for ``agents.publication_bus.refusal_footer_injector``."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from agents.publication_bus.refusal_footer_injector import (
    MAX_ACTIVE_REFUSALS_IN_FOOTER,
    RefusalEntry,
    inject_footer,
    load_refusals,
    render_footer,
)

# ── load_refusals ──────────────────────────────────────────────────────


class TestLoadRefusals:
    def test_missing_index_returns_empty(self, tmp_path: Path) -> None:
        """When the index file is absent, returns empty list (no raise)."""
        nonexistent = tmp_path / "nonexistent" / "index.json"
        result = load_refusals(index_path=nonexistent)
        assert result == []

    def test_invalid_json_returns_empty(self, tmp_path: Path) -> None:
        """Malformed JSON returns empty (degraded operation, not raise)."""
        path = tmp_path / "index.json"
        path.write_text("not valid json {")
        assert load_refusals(index_path=path) == []

    def test_non_list_root_returns_empty(self, tmp_path: Path) -> None:
        """Schema mismatch (object root vs array root) returns empty."""
        path = tmp_path / "index.json"
        path.write_text('{"slug": "x"}')
        assert load_refusals(index_path=path) == []

    def test_well_formed_entries_load(self, tmp_path: Path) -> None:
        path = tmp_path / "index.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "slug": "bandcamp-no-upload-api",
                        "title": "Bandcamp upload — refused (no API)",
                        "date": "2026-04-25",
                    },
                    {
                        "slug": "discogs-tos-forbids",
                        "title": "Discogs submission — refused (ToS)",
                        "date": "2026-04-24",
                        "doi": "10.5281/zenodo.123",
                    },
                ]
            )
        )
        result = load_refusals(index_path=path)
        assert len(result) == 2
        assert result[0].slug == "bandcamp-no-upload-api"
        assert result[1].doi == "10.5281/zenodo.123"

    def test_invalid_entry_skipped(self, tmp_path: Path) -> None:
        """Entries missing required fields are skipped, valid ones kept."""
        path = tmp_path / "index.json"
        path.write_text(
            json.dumps(
                [
                    {"slug": "ok", "title": "Ok", "date": "2026-04-25"},
                    {"slug": "missing-title-and-date"},  # invalid
                    "not-an-object",  # invalid
                    {"slug": "ok2", "title": "Ok 2", "date": "2026-04-24"},
                ]
            )
        )
        result = load_refusals(index_path=path)
        assert len(result) == 2
        assert {e.slug for e in result} == {"ok", "ok2"}


# ── render_footer ──────────────────────────────────────────────────────


class TestRenderFooter:
    def test_empty_refusals_renders_placeholder(self) -> None:
        today = datetime(2026, 4, 25, tzinfo=UTC)
        out = render_footer([], today=today)
        assert "Constitutional disclosure" in out
        assert "2026-04-25" in out
        assert "(no active refusals registered yet" in out

    def test_single_refusal_appears(self) -> None:
        today = datetime(2026, 4, 25, tzinfo=UTC)
        entries = [
            RefusalEntry(
                slug="bandcamp",
                title="Bandcamp upload — refused (no API)",
                date="2026-04-25",
            )
        ]
        out = render_footer(entries, today=today)
        assert "Bandcamp upload — refused (no API)" in out

    def test_doi_appended_when_present(self) -> None:
        today = datetime(2026, 4, 25, tzinfo=UTC)
        entries = [
            RefusalEntry(
                slug="discogs",
                title="Discogs submission — refused (ToS)",
                date="2026-04-25",
                doi="10.5281/zenodo.999",
            )
        ]
        out = render_footer(entries, today=today)
        assert "Discogs submission — refused (ToS) (10.5281/zenodo.999)" in out

    def test_capped_at_max_active(self) -> None:
        """Footer enumerates at most MAX_ACTIVE_REFUSALS_IN_FOOTER entries."""
        today = datetime(2026, 4, 25, tzinfo=UTC)
        # Generate one more entry than the cap allows.
        entries = [
            RefusalEntry(
                slug=f"refusal-{i}",
                title=f"Refusal {i}",
                date=f"2026-04-{(i % 28) + 1:02d}",
            )
            for i in range(MAX_ACTIVE_REFUSALS_IN_FOOTER + 5)
        ]
        out = render_footer(entries, today=today)
        # Count actual list items (lines starting with "- ").
        line_count = sum(
            1 for line in out.split("\n") if line.startswith("- ") and "Refusal" in line
        )
        assert line_count == MAX_ACTIVE_REFUSALS_IN_FOOTER

    def test_newest_first_ordering(self) -> None:
        """Entries are ordered newest-first by date in the rendered footer."""
        today = datetime(2026, 4, 25, tzinfo=UTC)
        entries = [
            RefusalEntry(slug="old", title="Older", date="2026-01-01"),
            RefusalEntry(slug="new", title="Newer", date="2026-04-20"),
            RefusalEntry(slug="mid", title="Middle", date="2026-03-15"),
        ]
        out = render_footer(entries, today=today)
        new_pos = out.index("Newer")
        mid_pos = out.index("Middle")
        old_pos = out.index("Older")
        assert new_pos < mid_pos < old_pos

    def test_includes_long_non_engagement_clause(self) -> None:
        """The footer always carries the LONG NON_ENGAGEMENT_CLAUSE."""
        today = datetime(2026, 4, 25, tzinfo=UTC)
        out = render_footer([], today=today)
        assert "Refusal Brief" in out
        assert "hapax.omg.lol/refusal" in out

    def test_includes_index_link(self) -> None:
        today = datetime(2026, 4, 25, tzinfo=UTC)
        out = render_footer([], today=today)
        assert "docs/refusal-briefs/" in out
        assert "github.com/ryanklee/hapax-council" in out


# ── inject_footer ──────────────────────────────────────────────────────


class TestInjectFooter:
    def test_appends_footer_to_description(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "nonexistent.json"
        out = inject_footer(
            "Body of the deposit.",
            refusals_path=nonexistent,
            today=datetime(2026, 4, 25, tzinfo=UTC),
        )
        assert out.startswith("Body of the deposit.")
        assert "Constitutional disclosure" in out

    def test_preserves_description_text(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "nonexistent.json"
        body = "First paragraph.\n\nSecond paragraph."
        out = inject_footer(
            body,
            refusals_path=nonexistent,
            today=datetime(2026, 4, 25, tzinfo=UTC),
        )
        assert "First paragraph." in out
        assert "Second paragraph." in out

    def test_separator_between_body_and_footer(self, tmp_path: Path) -> None:
        """The footer is separated from the body by ``---`` per Markdown."""
        nonexistent = tmp_path / "nonexistent.json"
        out = inject_footer(
            "Body.",
            refusals_path=nonexistent,
            today=datetime(2026, 4, 25, tzinfo=UTC),
        )
        body_pos = out.index("Body.")
        sep_pos = out.index("---")
        disclosure_pos = out.index("Constitutional disclosure")
        assert body_pos < sep_pos < disclosure_pos

    def test_consumes_real_refusals_index(self, tmp_path: Path) -> None:
        path = tmp_path / "index.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "slug": "bandcamp-no-upload-api",
                        "title": "Bandcamp upload — refused (no API)",
                        "date": "2026-04-25",
                    }
                ]
            )
        )
        out = inject_footer(
            "Body.",
            refusals_path=path,
            today=datetime(2026, 4, 25, tzinfo=UTC),
        )
        assert "Bandcamp upload — refused (no API)" in out
