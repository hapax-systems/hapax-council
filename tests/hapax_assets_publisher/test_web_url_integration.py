"""Integration test — ytb-AUTH-HOSTING consumes AUTH1's web_url synthesis.

Verifies that the AestheticLibrary's web_url() method produces URLs that
would resolve against the ryanklee.github.io/hapax-assets CDN once the
publisher daemon has rsynced assets to the external repo.
"""

from __future__ import annotations

from shared.aesthetic_library.loader import ASSETS_ROOT_DEFAULT, AestheticLibrary
from shared.aesthetic_library.web_export import CDN_BASE_URL


class TestWebUrlEndToEnd:
    def test_cdn_base_url_points_at_hapax_assets(self) -> None:
        assert CDN_BASE_URL == "https://ryanklee.github.io/hapax-assets"

    def test_real_asset_produces_valid_cdn_url(self) -> None:
        lib = AestheticLibrary(root=ASSETS_ROOT_DEFAULT / "aesthetic-library")
        asset = lib.get("fonts", "font", "px437-woff2")
        url = lib.web_url(asset)

        assert url.startswith("https://ryanklee.github.io/hapax-assets/")
        assert url.endswith(f"?sha={asset.sha256[:8]}")
        assert "fonts/Px437_IBM_VGA_8x16.woff2" in url

    def test_each_asset_gets_unique_sha_pin(self) -> None:
        lib = AestheticLibrary(root=ASSETS_ROOT_DEFAULT / "aesthetic-library")
        urls = {lib.web_url(a) for a in lib.list()}
        # Every asset has a distinct URL (either path or SHA differs).
        assert len(urls) == len(lib.list())
