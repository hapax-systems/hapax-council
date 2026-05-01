"""Tests for ``agents.citable_nexus.datacite_snapshot``."""

from __future__ import annotations

import json

from agents.citable_nexus.datacite_snapshot import (
    SNAPSHOT_DIR_ENV,
    DataCiteSnapshot,
    read_latest_snapshot,
)


def _write_snapshot(path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _real_shape_payload(num_works: int = 1) -> dict:
    """Mirrors the schema seen in 2026-05-01.json on the test host."""
    return {
        "data": {
            "person": {
                "id": "https://orcid.org/0009-0001-5146-4548",
                "works": {
                    "totalCount": num_works,
                    "nodes": [
                        {
                            "id": f"https://doi.org/10.5281/zenodo.{i}",
                            "doi": f"10.5281/zenodo.{i}",
                            "relatedIdentifiers": [
                                {
                                    "relatedIdentifier": "https://hapax.research",
                                    "relationType": "IsRelatedTo",
                                }
                            ],
                            "citations": {"totalCount": i},
                        }
                        for i in range(1, num_works + 1)
                    ],
                },
            }
        }
    }


# ── Snapshot-dir resolution ──────────────────────────────────────────


class TestSnapshotDirResolution:
    def test_returns_unavailable_when_dir_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv(SNAPSHOT_DIR_ENV, str(tmp_path / "nonexistent"))
        snap = read_latest_snapshot()
        assert snap.available is False
        assert snap.snapshot_date is None
        assert snap.works == []

    def test_returns_unavailable_when_dir_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv(SNAPSHOT_DIR_ENV, str(tmp_path))
        # No JSON files in tmp_path.
        snap = read_latest_snapshot()
        assert snap.available is False

    def test_picks_latest_iso_filename(self, tmp_path, monkeypatch):
        monkeypatch.setenv(SNAPSHOT_DIR_ENV, str(tmp_path))
        _write_snapshot(tmp_path / "2026-04-29.json", _real_shape_payload(1))
        _write_snapshot(tmp_path / "2026-05-01.json", _real_shape_payload(2))
        _write_snapshot(tmp_path / "2026-04-30.json", _real_shape_payload(3))
        snap = read_latest_snapshot()
        assert snap.snapshot_date == "2026-05-01"


# ── Snapshot parsing ──────────────────────────────────────────────────


class TestSnapshotParsing:
    def test_parses_real_shape_payload(self, tmp_path, monkeypatch):
        monkeypatch.setenv(SNAPSHOT_DIR_ENV, str(tmp_path))
        _write_snapshot(tmp_path / "2026-05-01.json", _real_shape_payload(2))
        snap = read_latest_snapshot()
        assert snap.available is True
        assert snap.orcid_url == "https://orcid.org/0009-0001-5146-4548"
        assert len(snap.works) == 2
        assert snap.works[0].doi == "10.5281/zenodo.1"
        assert snap.works[0].landing_page_url == "https://doi.org/10.5281/zenodo.1"

    def test_parses_citation_count(self, tmp_path, monkeypatch):
        monkeypatch.setenv(SNAPSHOT_DIR_ENV, str(tmp_path))
        _write_snapshot(tmp_path / "2026-05-01.json", _real_shape_payload(3))
        snap = read_latest_snapshot()
        # Payload generator sets citation count to i for the i-th work.
        assert snap.works[0].citation_count == 1
        assert snap.works[2].citation_count == 3

    def test_parses_related_identifiers(self, tmp_path, monkeypatch):
        monkeypatch.setenv(SNAPSHOT_DIR_ENV, str(tmp_path))
        _write_snapshot(tmp_path / "2026-05-01.json", _real_shape_payload(1))
        snap = read_latest_snapshot()
        assert len(snap.works[0].related_identifiers) == 1
        rel = snap.works[0].related_identifiers[0]
        assert rel.related_identifier == "https://hapax.research"
        assert rel.relation_type == "IsRelatedTo"

    def test_handles_zero_works(self, tmp_path, monkeypatch):
        monkeypatch.setenv(SNAPSHOT_DIR_ENV, str(tmp_path))
        _write_snapshot(
            tmp_path / "2026-05-01.json",
            {
                "data": {
                    "person": {
                        "id": "https://orcid.org/0009-0001-5146-4548",
                        "works": {"totalCount": 0, "nodes": []},
                    }
                }
            },
        )
        snap = read_latest_snapshot()
        assert snap.available is True
        assert snap.works == []

    def test_handles_malformed_json(self, tmp_path, monkeypatch):
        monkeypatch.setenv(SNAPSHOT_DIR_ENV, str(tmp_path))
        (tmp_path / "2026-05-01.json").write_text("not json", encoding="utf-8")
        snap = read_latest_snapshot()
        assert snap.available is False

    def test_handles_missing_doi_field(self, tmp_path, monkeypatch):
        monkeypatch.setenv(SNAPSHOT_DIR_ENV, str(tmp_path))
        _write_snapshot(
            tmp_path / "2026-05-01.json",
            {
                "data": {
                    "person": {
                        "id": "https://orcid.org/0009-0001-5146-4548",
                        "works": {
                            "totalCount": 2,
                            "nodes": [
                                {"doi": "10.5281/zenodo.1"},
                                {},  # node missing doi
                            ],
                        },
                    }
                }
            },
        )
        snap = read_latest_snapshot()
        # The empty node is dropped; the well-formed one is kept.
        assert len(snap.works) == 1
        assert snap.works[0].doi == "10.5281/zenodo.1"

    def test_handles_missing_person_block(self, tmp_path, monkeypatch):
        monkeypatch.setenv(SNAPSHOT_DIR_ENV, str(tmp_path))
        _write_snapshot(tmp_path / "2026-05-01.json", {"data": {}})
        snap = read_latest_snapshot()
        assert snap.available is True  # file existed and parsed
        assert snap.works == []
        assert snap.orcid_url is None


# ── Renderer integration ──────────────────────────────────────────────


class TestRendererIntegration:
    def test_render_deposits_with_snapshot(self, tmp_path, monkeypatch):
        monkeypatch.setenv(SNAPSHOT_DIR_ENV, str(tmp_path))
        _write_snapshot(tmp_path / "2026-05-01.json", _real_shape_payload(2))

        from agents.citable_nexus.renderer import render_deposits_page

        page = render_deposits_page()
        assert page.path == "/deposits"
        assert "Tracked works (2)" in page.body_html
        assert "10.5281/zenodo.1" in page.body_html
        assert "10.5281/zenodo.2" in page.body_html
        assert "https://orcid.org/0009-0001-5146-4548" in page.body_html

    def test_render_deposits_placeholder_when_absent(self, tmp_path, monkeypatch):
        monkeypatch.setenv(SNAPSHOT_DIR_ENV, str(tmp_path / "nonexistent"))

        from agents.citable_nexus.renderer import render_deposits_page

        page = render_deposits_page()
        assert page.path == "/deposits"
        assert "snapshot-placeholder" in page.body_html
        assert "configure-orcid.sh" in page.body_html

    def test_render_deposits_accepts_injected_snapshot(self):
        """Test path: tests can pass a fixture snapshot directly."""
        from agents.citable_nexus.renderer import render_deposits_page

        snapshot = DataCiteSnapshot(
            snapshot_date="2026-05-01",
            orcid_url="https://orcid.org/test",
            works=[],
        )
        page = render_deposits_page(snapshot)
        assert page.path == "/deposits"
        assert "Tracked works (0)" in page.body_html
        # zero-works path emits the "tracks zero works" sentinel
        assert "tracks zero works" in page.body_html

    def test_render_site_includes_deposits(self, tmp_path, monkeypatch):
        monkeypatch.setenv(SNAPSHOT_DIR_ENV, str(tmp_path))
        _write_snapshot(tmp_path / "2026-05-01.json", _real_shape_payload(1))

        from agents.citable_nexus.renderer import render_site

        site = render_site()
        assert "/deposits" in site.pages
        assert site.pages["/deposits"].startswith("<!doctype html>")
        assert "10.5281/zenodo.1" in site.pages["/deposits"]
