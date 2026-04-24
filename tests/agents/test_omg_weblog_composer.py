"""Tests for agents/omg_weblog_composer — ytb-OMG8 Phase A."""

from __future__ import annotations

from pathlib import Path

from agents.omg_weblog_composer.composer import (
    WeblogComposer,
    WeblogDraft,
    compose_iso_date_slug,
)


class TestComposeIsoDateSlug:
    def test_2026_04_24(self) -> None:
        assert compose_iso_date_slug("2026-04-24") == "2026-04-24"

    def test_pads_single_digits(self) -> None:
        # ISO-parseable inputs normalize to 10-char slugs.
        from datetime import date

        assert compose_iso_date_slug(date(2026, 4, 7).isoformat()) == "2026-04-07"


class TestWeblogDraft:
    def test_draft_defaults_to_unapproved(self) -> None:
        draft = WeblogDraft(
            iso_date="2026-04-24",
            title_seed="Retro-draft",
            context_summary="",
            placeholder_sections=[],
        )
        assert draft.approved is False

    def test_approved_can_be_set(self) -> None:
        draft = WeblogDraft(
            iso_date="2026-04-24",
            title_seed="t",
            context_summary="",
            placeholder_sections=[],
            approved=True,
        )
        assert draft.approved is True


class TestComposerGracefulSources:
    """Missing source directories must NOT hard-fail the composer."""

    def test_missing_chronicle_dir_ok(self, tmp_path: Path) -> None:
        composer = WeblogComposer(
            chronicle_dir=tmp_path / "nonexistent-chronicle",
            programmes_dir=tmp_path / "nonexistent-programmes",
            precedents_dir=tmp_path / "nonexistent-precedents",
        )
        draft = composer.compose_draft("2026-04-24")
        assert isinstance(draft, WeblogDraft)
        # At least the skeleton sections land even without sources.
        assert len(draft.placeholder_sections) > 0

    def test_missing_dirs_produce_empty_context(self, tmp_path: Path) -> None:
        composer = WeblogComposer(
            chronicle_dir=tmp_path / "a",
            programmes_dir=tmp_path / "b",
            precedents_dir=tmp_path / "c",
        )
        draft = composer.compose_draft("2026-04-24")
        # context_summary is empty-ish when sources are missing
        assert "no chronicle" in draft.context_summary.lower() or draft.context_summary == ""


class TestComposerAggregation:
    def test_chronicle_entries_aggregate(self, tmp_path: Path) -> None:
        chronicle = tmp_path / "chronicle"
        chronicle.mkdir()
        (chronicle / "2026-04-10.md").write_text("# Day 10\n\nsomething\n")
        (chronicle / "2026-04-20.md").write_text("# Day 20\n\nanother\n")
        composer = WeblogComposer(
            chronicle_dir=chronicle,
            programmes_dir=tmp_path / "missing-p",
            precedents_dir=tmp_path / "missing-x",
        )
        draft = composer.compose_draft("2026-04-24")
        # Context summary mentions aggregated count.
        assert "2" in draft.context_summary or "chronicle" in draft.context_summary.lower()

    def test_programmes_aggregate(self, tmp_path: Path) -> None:
        programmes = tmp_path / "programmes"
        programmes.mkdir()
        (programmes / "programme-a.md").write_text("---\nstatus: completed\n---\n# A\n")
        composer = WeblogComposer(
            chronicle_dir=tmp_path / "c",
            programmes_dir=programmes,
            precedents_dir=tmp_path / "p",
        )
        draft = composer.compose_draft("2026-04-24")
        titles = [s.title for s in draft.placeholder_sections]
        assert any("programme" in t.lower() or "arc" in t.lower() for t in titles)


class TestWriteToVault:
    def test_writes_markdown_with_frontmatter(self, tmp_path: Path) -> None:
        composer = WeblogComposer(
            chronicle_dir=tmp_path / "c",
            programmes_dir=tmp_path / "p",
            precedents_dir=tmp_path / "x",
        )
        draft = composer.compose_draft("2026-04-24")
        out_dir = tmp_path / "out"
        path = composer.write_to_vault(draft, out_dir)
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        # YAML frontmatter present
        assert content.startswith("---\n")
        # approved: false on generated drafts
        assert "approved: false" in content

    def test_filename_uses_iso_date(self, tmp_path: Path) -> None:
        composer = WeblogComposer(
            chronicle_dir=tmp_path / "c",
            programmes_dir=tmp_path / "p",
            precedents_dir=tmp_path / "x",
        )
        draft = composer.compose_draft("2026-04-24")
        out_dir = tmp_path / "out"
        path = composer.write_to_vault(draft, out_dir)
        assert path.name == "2026-04-24.md"

    def test_creates_output_dir_if_missing(self, tmp_path: Path) -> None:
        composer = WeblogComposer(
            chronicle_dir=tmp_path / "c",
            programmes_dir=tmp_path / "p",
            precedents_dir=tmp_path / "x",
        )
        draft = composer.compose_draft("2026-04-24")
        out_dir = tmp_path / "deeply" / "nested" / "out"
        assert not out_dir.exists()
        composer.write_to_vault(draft, out_dir)
        assert out_dir.exists()
