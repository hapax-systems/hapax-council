"""Auto-generated prior-work-section tests.

Coverage:

1. ``PriorWorkEntry.render_line`` formats DOI + title + year + cite-count.
2. ``load_latest_snapshot`` returns None on missing dir / empty dir /
   corrupt JSON; returns parsed snapshot when valid.
3. ``extract_prior_work_entries`` projects DataCite GraphQL nodes;
   skips nodes without DOI; handles missing/malformed shape.
4. ``render_prior_work_section`` returns the placeholder on no
   snapshot / empty snapshot; renders bullets when entries exist;
   sorts citation-count DESC by default; honors ``max_entries`` cap.
"""

from __future__ import annotations

import json
from pathlib import Path

from agents.playwright_grant_submission_runner.prior_work import (
    PRIOR_WORK_PLACEHOLDER,
    PriorWorkEntry,
    extract_prior_work_entries,
    load_latest_snapshot,
    render_prior_work_section,
)


def _snapshot(works: list[dict]) -> dict:
    """Build a minimal DataCite GraphQL snapshot matching the mirror shape."""
    return {"data": {"person": {"works": {"nodes": works}}}}


def _work(
    *,
    doi: str = "10.5281/zenodo.1234",
    title: str = "Sample work",
    year: int = 2026,
    citations: int = 0,
    publisher: str = "Zenodo",
) -> dict:
    return {
        "doi": doi,
        "titles": [{"title": title}],
        "publicationYear": year,
        "publisher": publisher,
        "citations": {"totalCount": citations},
    }


# ── PriorWorkEntry.render_line ────────────────────────────────────────


class TestRenderLine:
    def test_full_entry(self) -> None:
        line = PriorWorkEntry(
            doi="10.5281/zenodo.1",
            title="Refused: vendor portals",
            publication_year=2026,
            citation_count=5,
            publisher="Zenodo",
        ).render_line()
        assert "Refused: vendor portals" in line
        assert "10.5281/zenodo.1" in line
        assert "(2026)" in line
        assert "Zenodo" in line
        assert "cited 5×" in line

    def test_no_year_omits_year(self) -> None:
        line = PriorWorkEntry(doi="x", title="y").render_line()
        assert "(" not in line  # no year parens

    def test_zero_citations_omits_cite_suffix(self) -> None:
        line = PriorWorkEntry(doi="x", title="y", publication_year=2026).render_line()
        assert "cited" not in line


# ── load_latest_snapshot ─────────────────────────────────────────────


class TestLoadLatestSnapshot:
    def test_missing_dir_returns_none(self, tmp_path: Path) -> None:
        assert load_latest_snapshot(tmp_path / "nonexistent") is None

    def test_empty_dir_returns_none(self, tmp_path: Path) -> None:
        assert load_latest_snapshot(tmp_path) is None

    def test_corrupt_json_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / "2026-05-04.json").write_text("not-json")
        assert load_latest_snapshot(tmp_path) is None

    def test_returns_latest_snapshot_by_filename(self, tmp_path: Path) -> None:
        (tmp_path / "2026-05-01.json").write_text(json.dumps(_snapshot([])))
        latest = _snapshot([_work(doi="latest")])
        (tmp_path / "2026-05-04.json").write_text(json.dumps(latest))
        assert load_latest_snapshot(tmp_path) == latest


# ── extract_prior_work_entries ───────────────────────────────────────


class TestExtractEntries:
    def test_extracts_doi_title_year_cite_publisher(self) -> None:
        snap = _snapshot([_work(doi="10.5281/zenodo.42", title="Hi", year=2026, citations=3)])
        entries = extract_prior_work_entries(snap)
        assert len(entries) == 1
        e = entries[0]
        assert e.doi == "10.5281/zenodo.42"
        assert e.title == "Hi"
        assert e.publication_year == 2026
        assert e.citation_count == 3
        assert e.publisher == "Zenodo"

    def test_skips_nodes_without_doi(self) -> None:
        snap = _snapshot(
            [
                _work(doi="10.5281/zenodo.1"),
                {"titles": [{"title": "no-doi"}]},
            ]
        )
        entries = extract_prior_work_entries(snap)
        assert len(entries) == 1

    def test_handles_missing_person_shape(self) -> None:
        assert extract_prior_work_entries({}) == []
        assert extract_prior_work_entries({"data": {}}) == []
        assert extract_prior_work_entries({"data": {"person": None}}) == []

    def test_handles_string_publication_year(self) -> None:
        snap = _snapshot([{"doi": "x", "publicationYear": "2026", "titles": []}])
        entries = extract_prior_work_entries(snap)
        assert entries[0].publication_year == 2026

    def test_handles_non_numeric_publication_year(self) -> None:
        snap = _snapshot([{"doi": "x", "publicationYear": "not-a-year", "titles": []}])
        entries = extract_prior_work_entries(snap)
        assert entries[0].publication_year is None


# ── render_prior_work_section ────────────────────────────────────────


class TestRenderSection:
    def test_no_snapshot_returns_placeholder(self, tmp_path: Path) -> None:
        out = render_prior_work_section(mirror_dir=tmp_path)
        assert out == PRIOR_WORK_PLACEHOLDER

    def test_empty_snapshot_returns_placeholder(self, tmp_path: Path) -> None:
        (tmp_path / "2026-05-04.json").write_text(json.dumps(_snapshot([])))
        out = render_prior_work_section(mirror_dir=tmp_path)
        assert out == PRIOR_WORK_PLACEHOLDER

    def test_renders_bullets_for_each_entry(self, tmp_path: Path) -> None:
        snap = _snapshot([_work(doi="a"), _work(doi="b")])
        (tmp_path / "2026-05-04.json").write_text(json.dumps(snap))
        out = render_prior_work_section(mirror_dir=tmp_path)
        assert "10.5281/zenodo.1234" not in out  # default doi clobbered
        assert out.count("\n- ") == 1  # 2 entries → 1 leading + 1 inner newline
        assert out.count("- **Sample work**") == 2

    def test_sorts_by_citations_desc_by_default(self, tmp_path: Path) -> None:
        snap = _snapshot(
            [
                _work(doi="low", title="LowCite", citations=2),
                _work(doi="high", title="HighCite", citations=10),
                _work(doi="mid", title="MidCite", citations=5),
            ]
        )
        (tmp_path / "2026-05-04.json").write_text(json.dumps(snap))
        out = render_prior_work_section(mirror_dir=tmp_path)
        # HighCite first, MidCite second, LowCite third.
        assert out.index("HighCite") < out.index("MidCite") < out.index("LowCite")

    def test_caps_at_max_entries(self, tmp_path: Path) -> None:
        snap = _snapshot([_work(doi=f"d-{i}") for i in range(40)])
        (tmp_path / "2026-05-04.json").write_text(json.dumps(snap))
        out = render_prior_work_section(mirror_dir=tmp_path, max_entries=5)
        assert out.count("- **") == 5

    def test_preserves_order_when_sort_disabled(self, tmp_path: Path) -> None:
        snap = _snapshot(
            [
                _work(doi="a", title="A", citations=1),
                _work(doi="b", title="B", citations=10),
            ]
        )
        (tmp_path / "2026-05-04.json").write_text(json.dumps(snap))
        out = render_prior_work_section(mirror_dir=tmp_path, sort_by_citations=False)
        # Native order: A before B.
        assert out.index("**A**") < out.index("**B**")
