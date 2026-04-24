"""Web URL synthesis — SHA-pinned URLs to the GitHub Pages asset CDN.

Consumed by omg.lol surfaces (ytb-OMG2/3/4/8, ytb-OMG-CREDITS) via
`library().web_url(asset)`. The CDN itself is stood up in ytb-AUTH-HOSTING;
this module only builds the URL string and is safe to import regardless.
"""

from __future__ import annotations

from pathlib import Path

CDN_BASE_URL = "https://ryanklee.github.io/hapax-assets"


def build_web_url(library_root: Path, asset_path: Path, sha256: str) -> str:
    rel = asset_path.relative_to(library_root)
    return f"{CDN_BASE_URL}/{rel.as_posix()}?sha={sha256[:8]}"
