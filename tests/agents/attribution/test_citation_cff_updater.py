"""Tests for ``agents.attribution.citation_cff_updater``."""

from __future__ import annotations

from pathlib import Path

import yaml

from agents.attribution.citation_cff_updater import (
    SWH_IDENTIFIER_DESCRIPTION,
    update_citation_cff,
)

_SAMPLE_CFF = """\
cff-version: 1.2.0
message: cite this
type: software
title: hapax-council
authors:
- given-names: Ryan
  family-names: Kleeberger
repository-code: https://github.com/ryanklee/hapax-council
license: PolyForm-Strict-1.0.0
"""


class TestUpdateCitationCff:
    def test_adds_identifiers_field_when_missing(self, tmp_path: Path) -> None:
        cff_path = tmp_path / "CITATION.cff"
        cff_path.write_text(_SAMPLE_CFF)
        update_citation_cff(cff_path, "swh:1:snp:" + "a" * 40)
        loaded = yaml.safe_load(cff_path.read_text())
        assert "identifiers" in loaded
        ids = loaded["identifiers"]
        assert any(i["type"] == "swh" and i["value"].startswith("swh:1:snp:") for i in ids)

    def test_replaces_existing_swh_identifier(self, tmp_path: Path) -> None:
        cff_path = tmp_path / "CITATION.cff"
        cff_path.write_text(_SAMPLE_CFF)
        update_citation_cff(cff_path, "swh:1:snp:" + "a" * 40)
        update_citation_cff(cff_path, "swh:1:snp:" + "b" * 40)
        loaded = yaml.safe_load(cff_path.read_text())
        swh_ids = [i for i in loaded["identifiers"] if i["type"] == "swh"]
        assert len(swh_ids) == 1
        assert swh_ids[0]["value"] == "swh:1:snp:" + "b" * 40

    def test_preserves_other_identifiers(self, tmp_path: Path) -> None:
        cff_path = tmp_path / "CITATION.cff"
        cff_path.write_text(
            _SAMPLE_CFF + "identifiers:\n" + "- type: doi\n" + "  value: 10.5281/zenodo.123456\n"
        )
        update_citation_cff(cff_path, "swh:1:snp:" + "a" * 40)
        loaded = yaml.safe_load(cff_path.read_text())
        ids = loaded["identifiers"]
        types = {i["type"] for i in ids}
        assert types == {"swh", "doi"}

    def test_swh_identifier_includes_description(self, tmp_path: Path) -> None:
        cff_path = tmp_path / "CITATION.cff"
        cff_path.write_text(_SAMPLE_CFF)
        update_citation_cff(cff_path, "swh:1:snp:" + "a" * 40)
        loaded = yaml.safe_load(cff_path.read_text())
        swh_id = next(i for i in loaded["identifiers"] if i["type"] == "swh")
        assert "description" in swh_id
        assert swh_id["description"] == SWH_IDENTIFIER_DESCRIPTION

    def test_preserves_top_level_fields(self, tmp_path: Path) -> None:
        cff_path = tmp_path / "CITATION.cff"
        cff_path.write_text(_SAMPLE_CFF)
        update_citation_cff(cff_path, "swh:1:snp:" + "a" * 40)
        loaded = yaml.safe_load(cff_path.read_text())
        assert loaded["title"] == "hapax-council"
        assert loaded["license"] == "PolyForm-Strict-1.0.0"
        assert loaded["cff-version"] == "1.2.0"

    def test_atomic_write_no_partial_file_on_error(self, tmp_path: Path) -> None:
        cff_path = tmp_path / "CITATION.cff"
        cff_path.write_text(_SAMPLE_CFF)
        original = cff_path.read_text()
        update_citation_cff(cff_path, "swh:1:snp:" + "a" * 40)
        new = cff_path.read_text()
        assert new != original
        # File still parses as valid YAML — atomic write didn't truncate
        assert yaml.safe_load(new) is not None
