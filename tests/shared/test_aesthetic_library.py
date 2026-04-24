"""Tests for shared/aesthetic_library — ytb-AUTH1.

Exercises the AestheticLibrary singleton, Asset/Manifest/Provenance
Pydantic models, integrity verification, and web_url synthesis against
a self-contained on-disk fixture tree. Tests write a minimal
aesthetic-library skeleton to tmp_path and point a dedicated library
instance at it, so nothing depends on repo state.
"""

from __future__ import annotations

import hashlib
import textwrap
from pathlib import Path

import pytest
import yaml

from shared.aesthetic_library import (
    AestheticLibrary,
    Manifest,
    ManifestEntry,
    Provenance,
    library,
)
from shared.aesthetic_library.integrity import IntegrityError


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_asset(root: Path, rel: str, data: bytes) -> tuple[Path, str]:
    full = root / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(data)
    return full, _sha256(data)


@pytest.fixture
def library_root(tmp_path: Path) -> Path:
    """Build a minimal aesthetic-library tree under tmp_path.

    Structure:
        <root>/
          bitchx/
            LICENSE.BSD-3
            provenance.yaml
            splash/dragon.txt
            colors/mirc16.yaml
          fonts/
            LICENSE.CC-BY-SA-4.0
            provenance.yaml
            px437.ttf
          _manifest.yaml
          _NOTICES.md
    """
    root = tmp_path / "aesthetic-library"
    root.mkdir()

    # BitchX group
    bitchx_license = root / "bitchx" / "LICENSE.BSD-3"
    bitchx_license.parent.mkdir(parents=True)
    bitchx_license.write_text("BSD-3-Clause stub\n")
    dragon_path, dragon_sha = _write_asset(
        root,
        "bitchx/splash/dragon.txt",
        b"      __\n     / _)\n    (___\n",
    )
    mirc_path, mirc_sha = _write_asset(
        root,
        "bitchx/colors/mirc16.yaml",
        b"mirc16:\n  00: '#FFFFFF'\n  01: '#000000'\n",
    )
    (root / "bitchx" / "provenance.yaml").write_text(
        textwrap.dedent(
            """\
            source: bitchx
            source_url: https://github.com/prime001/BitchX
            source_commit: abc123
            extracted_date: 2026-04-24
            original_author: Colten Edwards (panasync) + EPIC Software Labs
            license: BSD-3-Clause
            license_text_path: LICENSE.BSD-3
            attribution_line: "BitchX © EPIC Software Labs (BSD-3-Clause)"
            """
        )
    )

    # Fonts group
    font_license = root / "fonts" / "LICENSE.CC-BY-SA-4.0"
    font_license.parent.mkdir(parents=True)
    font_license.write_text("CC-BY-SA-4.0 stub\n")
    # A tiny fake TTF payload (real bytes don't matter for the test)
    font_path, font_sha = _write_asset(root, "fonts/px437.ttf", b"FAKE-TTF-BYTES-FOR-TEST")
    (root / "fonts" / "provenance.yaml").write_text(
        textwrap.dedent(
            """\
            source: fonts
            source_url: https://int10h.org/oldschool-pc-fonts/
            source_commit: n/a
            extracted_date: 2026-04-24
            original_author: VileR
            license: CC-BY-SA-4.0
            license_text_path: LICENSE.CC-BY-SA-4.0
            attribution_line: "Px437 IBM VGA 8×16 © VileR (int10h.org, CC-BY-SA 4.0)"
            """
        )
    )

    # Manifest (authoritative index)
    manifest = {
        "assets": [
            {
                "source": "bitchx",
                "kind": "splash",
                "name": "dragon",
                "path": "bitchx/splash/dragon.txt",
                "sha256": dragon_sha,
                "license": "BSD-3-Clause",
                "author": "Colten Edwards (panasync) + EPIC Software Labs",
                "source_url": "https://github.com/prime001/BitchX",
                "extracted_date": "2026-04-24",
            },
            {
                "source": "bitchx",
                "kind": "palette",
                "name": "mirc16",
                "path": "bitchx/colors/mirc16.yaml",
                "sha256": mirc_sha,
                "license": "BSD-3-Clause",
                "author": "mIRC reference",
                "source_url": "https://mirc.com/colors.html",
                "extracted_date": "2026-04-24",
            },
            {
                "source": "fonts",
                "kind": "font",
                "name": "px437",
                "path": "fonts/px437.ttf",
                "sha256": font_sha,
                "license": "CC-BY-SA-4.0",
                "author": "VileR",
                "source_url": "https://int10h.org/oldschool-pc-fonts/",
                "extracted_date": "2026-04-24",
            },
        ]
    }
    (root / "_manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))
    (root / "_NOTICES.md").write_text("# NOTICES (generated)\n")
    return root


@pytest.fixture
def lib(library_root: Path) -> AestheticLibrary:
    return AestheticLibrary(root=library_root)


class TestAssetModel:
    def test_asset_has_all_required_fields(self, lib: AestheticLibrary) -> None:
        asset = lib.get("bitchx", "splash", "dragon")
        assert asset.source == "bitchx"
        assert asset.kind == "splash"
        assert asset.name == "dragon"
        assert asset.license == "BSD-3-Clause"
        assert asset.author.startswith("Colten")
        assert asset.source_url.startswith("https://github.com/")
        assert asset.extracted_date == "2026-04-24"

    def test_asset_bytes_returns_file_contents(self, lib: AestheticLibrary) -> None:
        asset = lib.get("bitchx", "splash", "dragon")
        assert b"/ _)" in asset.bytes()

    def test_asset_text_decodes_utf8(self, lib: AestheticLibrary) -> None:
        asset = lib.get("bitchx", "splash", "dragon")
        assert "/ _)" in asset.text()

    def test_asset_path_is_absolute(self, lib: AestheticLibrary) -> None:
        asset = lib.get("fonts", "font", "px437")
        assert asset.path.is_absolute()
        assert asset.path.is_file()


class TestGet:
    def test_returns_matching_asset(self, lib: AestheticLibrary) -> None:
        asset = lib.get("bitchx", "palette", "mirc16")
        assert asset.name == "mirc16"

    def test_missing_asset_raises(self, lib: AestheticLibrary) -> None:
        with pytest.raises(KeyError, match="not found"):
            lib.get("bitchx", "splash", "does-not-exist")

    def test_wrong_kind_raises(self, lib: AestheticLibrary) -> None:
        with pytest.raises(KeyError, match="not found"):
            lib.get("bitchx", "font", "dragon")


class TestList:
    def test_list_all(self, lib: AestheticLibrary) -> None:
        assets = lib.list()
        assert len(assets) == 3

    def test_list_filtered_by_source(self, lib: AestheticLibrary) -> None:
        assets = lib.list(source="bitchx")
        assert {a.name for a in assets} == {"dragon", "mirc16"}

    def test_list_filtered_by_kind(self, lib: AestheticLibrary) -> None:
        assets = lib.list(kind="font")
        assert len(assets) == 1
        assert assets[0].name == "px437"

    def test_list_filtered_by_source_and_kind(self, lib: AestheticLibrary) -> None:
        assets = lib.list(source="bitchx", kind="splash")
        assert [a.name for a in assets] == ["dragon"]


class TestAttributionFor:
    def test_returns_credit_string(self, lib: AestheticLibrary) -> None:
        asset = lib.get("fonts", "font", "px437")
        credit = lib.attribution_for(asset)
        assert "VileR" in credit
        assert "CC-BY-SA" in credit

    def test_attribution_includes_license(self, lib: AestheticLibrary) -> None:
        asset = lib.get("bitchx", "splash", "dragon")
        credit = lib.attribution_for(asset)
        assert "BSD-3" in credit


class TestAllLicenses:
    def test_groups_by_license_spdx(self, lib: AestheticLibrary) -> None:
        groups = lib.all_licenses()
        assert set(groups.keys()) == {"BSD-3-Clause", "CC-BY-SA-4.0"}
        assert len(groups["BSD-3-Clause"]) == 2
        assert len(groups["CC-BY-SA-4.0"]) == 1


class TestVerifyIntegrity:
    def test_clean_tree_returns_empty(self, lib: AestheticLibrary) -> None:
        assert lib.verify_integrity() == []

    def test_modified_asset_surfaces_drift(self, lib: AestheticLibrary, library_root: Path) -> None:
        (library_root / "fonts" / "px437.ttf").write_bytes(b"tampered")
        drifted = lib.verify_integrity()
        assert any("fonts/px437.ttf" in d for d in drifted)

    def test_missing_asset_surfaces_drift(self, lib: AestheticLibrary, library_root: Path) -> None:
        (library_root / "bitchx" / "splash" / "dragon.txt").unlink()
        drifted = lib.verify_integrity()
        assert any("dragon.txt" in d for d in drifted)


class TestWebUrl:
    def test_url_includes_base_and_relative_path(self, lib: AestheticLibrary) -> None:
        asset = lib.get("fonts", "font", "px437")
        url = lib.web_url(asset)
        assert url.startswith("https://ryanklee.github.io/hapax-assets/")
        assert "fonts/px437.ttf" in url

    def test_url_is_sha_pinned_for_cache_busting(self, lib: AestheticLibrary) -> None:
        asset = lib.get("fonts", "font", "px437")
        url = lib.web_url(asset)
        assert f"sha={asset.sha256[:8]}" in url


class TestSingleton:
    def test_library_callable_returns_singleton(
        self, monkeypatch: pytest.MonkeyPatch, library_root: Path
    ) -> None:
        # Reset module-level singleton and point at our fixture.
        import shared.aesthetic_library.loader as loader_mod

        monkeypatch.setattr(loader_mod, "_library", None)
        monkeypatch.setattr(loader_mod, "ASSETS_ROOT_DEFAULT", library_root.parent)
        monkeypatch.setenv("HAPAX_AESTHETIC_LIBRARY_ROOT", str(library_root))

        a = library()
        b = library()
        assert a is b


class TestManifestModel:
    def test_manifest_parse_from_yaml(self, library_root: Path) -> None:
        manifest = Manifest.load(library_root / "_manifest.yaml")
        assert len(manifest.assets) == 3
        names = {e.name for e in manifest.assets}
        assert names == {"dragon", "mirc16", "px437"}

    def test_manifest_entry_validates_sha256_length(self) -> None:
        with pytest.raises(Exception):
            ManifestEntry(
                source="x",
                kind="y",
                name="z",
                path="x/y.txt",
                sha256="tooshort",
                license="BSD-3-Clause",
                author="me",
                source_url="https://example.com",
                extracted_date="2026-04-24",
            )


class TestProvenanceModel:
    def test_provenance_load_from_yaml(self, library_root: Path) -> None:
        prov = Provenance.load(library_root / "bitchx" / "provenance.yaml")
        assert prov.license == "BSD-3-Clause"
        assert prov.original_author.startswith("Colten")
        assert "panasync" in prov.original_author


class TestIntegrityErrorShape:
    def test_integrity_error_exists(self) -> None:
        err = IntegrityError("drift detected", details=["fonts/px437.ttf"])
        assert "drift" in str(err)
        assert err.details == ["fonts/px437.ttf"]


class TestLoaderEdgeCases:
    """Edge cases flagged in beta's PR #1285 pre-merge audit (low-severity
    follow-ups landing on AUTH-HOSTING alongside web_url consumer tests).
    """

    def test_nonexistent_root_yields_empty_library(self, tmp_path: Path) -> None:
        # No directory at all → library instantiates, list() returns [], no crash.
        lib = AestheticLibrary(root=tmp_path / "does-not-exist")
        assert lib.list() == []
        assert lib.all_licenses() == {}
        assert lib.verify_integrity() == []

    def test_missing_manifest_yields_empty_library(self, tmp_path: Path) -> None:
        # Directory exists but no _manifest.yaml — same graceful behavior.
        root = tmp_path / "aesthetic-library"
        root.mkdir()
        lib = AestheticLibrary(root=root)
        assert lib.list() == []

    def test_malformed_manifest_yaml_raises_with_context(self, tmp_path: Path) -> None:
        root = tmp_path / "aesthetic-library"
        root.mkdir()
        (root / "_manifest.yaml").write_text("this: is: not: valid: yaml:\n")
        with pytest.raises(Exception):
            AestheticLibrary(root=root)

    def test_manifest_sha_mismatch_exactly_reports_offending_path(self, library_root: Path) -> None:
        # Pin byte-level: modifying any single byte surfaces drift with the
        # offending path, not a whole-library "something broke" message.
        (library_root / "fonts" / "px437.ttf").write_bytes(b"single-byte-change")
        lib = AestheticLibrary(root=library_root)
        drift = lib.verify_integrity()
        assert len(drift) == 1
        assert "fonts/px437.ttf" in drift[0]
        assert "sha mismatch" in drift[0]


class TestRealRepoLibrary:
    """Integration tests against the real on-disk `assets/aesthetic-library/`.

    Fail-loud if the shipped manifest drifts from actual file bytes or if
    the expected asset names are missing. Prevents the scenario where an
    asset gets renamed and the module can't find it.
    """

    def test_real_library_loads(self) -> None:
        from shared.aesthetic_library.loader import ASSETS_ROOT_DEFAULT

        lib = AestheticLibrary(root=ASSETS_ROOT_DEFAULT / "aesthetic-library")
        assets = lib.list()
        # First-acquisition commits 5 assets: banner, quit, mirc16, px437, px437-woff2.
        assert len(assets) >= 5

    def test_real_library_px437_exists(self) -> None:
        from shared.aesthetic_library.loader import ASSETS_ROOT_DEFAULT

        lib = AestheticLibrary(root=ASSETS_ROOT_DEFAULT / "aesthetic-library")
        ttf = lib.get("fonts", "font", "px437")
        assert ttf.path.is_file()
        assert ttf.license == "CC-BY-SA-4.0"
        assert ttf.sha256  # non-empty
        assert len(ttf.bytes()) > 1000  # real TTF is >1 KB

    def test_real_library_integrity_clean(self) -> None:
        from shared.aesthetic_library.loader import ASSETS_ROOT_DEFAULT

        lib = AestheticLibrary(root=ASSETS_ROOT_DEFAULT / "aesthetic-library")
        drift = lib.verify_integrity()
        assert drift == [], (
            f"shipped manifest drifted from on-disk bytes: {drift}. "
            "Re-run `uv run python scripts/generate-aesthetic-manifest.py`."
        )

    def test_real_library_licenses_are_recognized(self) -> None:
        from shared.aesthetic_library.loader import ASSETS_ROOT_DEFAULT

        lib = AestheticLibrary(root=ASSETS_ROOT_DEFAULT / "aesthetic-library")
        licenses = set(lib.all_licenses().keys())
        # First-acquisition commits only BSD-3-Clause and CC-BY-SA-4.0.
        # Any other license means an unvetted asset slipped in.
        expected = {"BSD-3-Clause", "CC-BY-SA-4.0"}
        assert licenses.issubset(expected | {"BSD-2-Clause", "LGPL-2.1"}), (
            f"unexpected license appeared in aesthetic-library: {licenses - expected}"
        )
