"""Tests for ``agents.attribution.bibtex_collector`` orchestration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from agents.attribution.bibtex_collector import (
    DEFAULT_BIBTEX_PATH,
    collect_all_bibtex,
)
from agents.attribution.swhids_yaml import SwhidRecord, save_swhids


class TestCollectAllBibtex:
    @patch("agents.attribution.bibtex_collector.fetch_bibtex")
    def test_writes_bibtex_concatenation(
        self,
        mock_fetch,
        tmp_path: Path,
    ) -> None:
        swhids_path = tmp_path / "swhids.yaml"
        bibtex_path = tmp_path / "bibtex.bib"
        save_swhids(
            {
                "repo-a": SwhidRecord(
                    slug="repo-a",
                    repo_url="https://github.com/ryanklee/a",
                    swhid="swh:1:snp:" + "a" * 40,
                    visit_status="done",
                ),
                "repo-b": SwhidRecord(
                    slug="repo-b",
                    repo_url="https://github.com/ryanklee/b",
                    swhid="swh:1:snp:" + "b" * 40,
                    visit_status="done",
                ),
            },
            path=swhids_path,
        )
        mock_fetch.side_effect = ["@software{a, ...}", "@software{b, ...}"]
        collect_all_bibtex(swhids_path=swhids_path, bibtex_path=bibtex_path)
        text = bibtex_path.read_text()
        assert "@software{a" in text
        assert "@software{b" in text

    @patch("agents.attribution.bibtex_collector.fetch_bibtex")
    def test_skips_records_without_swhid(
        self,
        mock_fetch,
        tmp_path: Path,
    ) -> None:
        swhids_path = tmp_path / "swhids.yaml"
        bibtex_path = tmp_path / "bibtex.bib"
        save_swhids(
            {
                "repo-a": SwhidRecord(
                    slug="repo-a",
                    repo_url="https://github.com/ryanklee/a",
                    swhid=None,
                    visit_status="ongoing",
                ),
            },
            path=swhids_path,
        )
        collect_all_bibtex(swhids_path=swhids_path, bibtex_path=bibtex_path)
        mock_fetch.assert_not_called()
        # bibtex path may or may not be written; if written, empty.
        if bibtex_path.exists():
            assert bibtex_path.read_text().strip() == ""

    @patch("agents.attribution.bibtex_collector.fetch_bibtex")
    def test_skips_records_when_fetch_returns_none(
        self,
        mock_fetch,
        tmp_path: Path,
    ) -> None:
        swhids_path = tmp_path / "swhids.yaml"
        bibtex_path = tmp_path / "bibtex.bib"
        save_swhids(
            {
                "repo-a": SwhidRecord(
                    slug="repo-a",
                    repo_url="https://github.com/ryanklee/a",
                    swhid="swh:1:snp:" + "a" * 40,
                    visit_status="done",
                ),
                "repo-b": SwhidRecord(
                    slug="repo-b",
                    repo_url="https://github.com/ryanklee/b",
                    swhid="swh:1:snp:" + "b" * 40,
                    visit_status="done",
                ),
            },
            path=swhids_path,
        )
        # First repo fetches OK, second returns None (404 from SWH)
        mock_fetch.side_effect = ["@software{a, ...}", None]
        collect_all_bibtex(swhids_path=swhids_path, bibtex_path=bibtex_path)
        text = bibtex_path.read_text()
        assert "@software{a" in text
        assert "@software{b" not in text

    @patch("agents.attribution.bibtex_collector.update_citation_cff")
    @patch("agents.attribution.bibtex_collector.fetch_bibtex")
    def test_updates_repo_citation_cff_when_path_provided(
        self,
        mock_fetch,
        mock_update_cff,
        tmp_path: Path,
    ) -> None:
        swhids_path = tmp_path / "swhids.yaml"
        bibtex_path = tmp_path / "bibtex.bib"
        cff_dir = tmp_path / "repos"
        cff_dir.mkdir()
        cff_path = cff_dir / "hapax-council" / "CITATION.cff"
        cff_path.parent.mkdir()
        cff_path.write_text("cff-version: 1.2.0\ntitle: hapax-council\n")
        save_swhids(
            {
                "hapax-council": SwhidRecord(
                    slug="hapax-council",
                    repo_url="https://github.com/ryanklee/hapax-council",
                    swhid="swh:1:snp:" + "a" * 40,
                    visit_status="done",
                ),
            },
            path=swhids_path,
        )
        mock_fetch.return_value = "@software{hc, ...}"
        collect_all_bibtex(
            swhids_path=swhids_path,
            bibtex_path=bibtex_path,
            citation_cff_root=cff_dir,
        )
        mock_update_cff.assert_called_once()
        called_args = mock_update_cff.call_args[0]
        assert called_args[0] == cff_path
        assert called_args[1] == "swh:1:snp:" + "a" * 40

    def test_default_bibtex_path_is_under_hapax_state(self) -> None:
        assert DEFAULT_BIBTEX_PATH.name == "bibtex.bib"
        assert "attribution" in DEFAULT_BIBTEX_PATH.parts
