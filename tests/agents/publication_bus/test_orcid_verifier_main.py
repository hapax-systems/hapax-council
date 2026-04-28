"""Tests for ``agents.publication_bus.orcid_verifier.main`` (Phase 2)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agents.publication_bus.orcid_verifier import (
    load_recent_concept_dois,
    main,
)

_OK_RESPONSE = {
    "group": [
        {
            "external-ids": {
                "external-id": [
                    {"external-id-type": "doi", "external-id-value": "10.5281/zenodo.111"},
                ]
            }
        },
    ]
}


class TestLoadRecentConceptDois:
    def test_loads_one_per_line(self, tmp_path: Path) -> None:
        path = tmp_path / "concept-dois.txt"
        path.write_text("10.5281/zenodo.111\n10.5281/zenodo.222\n")
        result = load_recent_concept_dois(path=path)
        assert result == {"10.5281/zenodo.111", "10.5281/zenodo.222"}

    def test_strips_blank_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "concept-dois.txt"
        path.write_text("10.5281/zenodo.111\n\n  \n10.5281/zenodo.222\n")
        result = load_recent_concept_dois(path=path)
        assert result == {"10.5281/zenodo.111", "10.5281/zenodo.222"}

    def test_missing_file_returns_empty_set(self, tmp_path: Path) -> None:
        result = load_recent_concept_dois(path=tmp_path / "missing.txt")
        assert result == set()


class TestMain:
    @patch("agents.publication_bus.orcid_verifier.operator_orcid", return_value=None)
    def test_no_orcid_returns_0(self, _mock_operator_orcid: MagicMock) -> None:
        # No ORCID configured → daemon-friendly no-op
        assert main() == 0

    @pytest.fixture
    def with_orcid(self) -> Iterator[None]:
        with patch(
            "agents.publication_bus.orcid_verifier.operator_orcid",
            return_value="0000-0001-2345-6789",
        ):
            yield

    @patch("agents.publication_bus.orcid_verifier.fetch_orcid_works")
    def test_fetch_failure_returns_0(
        self,
        mock_fetch: MagicMock,
        with_orcid: None,
    ) -> None:
        mock_fetch.return_value = None
        # Even on fetch failure, daemon exits cleanly for systemd
        assert main() == 0

    @patch("agents.publication_bus.orcid_verifier.fetch_orcid_works")
    def test_success_path_returns_0(
        self,
        mock_fetch: MagicMock,
        with_orcid: None,
    ) -> None:
        mock_fetch.return_value = _OK_RESPONSE
        assert main() == 0
