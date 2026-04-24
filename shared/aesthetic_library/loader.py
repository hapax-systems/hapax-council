"""AestheticLibrary singleton + Asset model.

Computes an in-memory asset index at construction from `_manifest.yaml` and
the per-group `provenance.yaml` files. All lookups are O(1) after init.
Integrity verification re-hashes files on demand.

Override root via `HAPAX_AESTHETIC_LIBRARY_ROOT` env var (primarily for tests).
"""

from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from shared.aesthetic_library.manifest import Manifest, ManifestEntry
from shared.aesthetic_library.provenance import Provenance
from shared.aesthetic_library.web_export import build_web_url

# Council repo root → assets/aesthetic-library/
_REPO_ROOT = Path(__file__).resolve().parents[2]
ASSETS_ROOT_DEFAULT = _REPO_ROOT / "assets"


class Asset(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    source: str
    kind: str
    name: str
    path: Path
    sha256: str
    license: str
    author: str
    source_url: str
    extracted_date: str
    notes: str = ""

    def bytes(self) -> bytes:
        return self.path.read_bytes()

    def text(self) -> str:
        return self.path.read_text(encoding="utf-8")


class AestheticLibrary:
    """Compute-once-at-import, reuse-forever asset index."""

    def __init__(self, root: Path | None = None) -> None:
        if root is None:
            env = os.environ.get("HAPAX_AESTHETIC_LIBRARY_ROOT")
            root = Path(env) if env else ASSETS_ROOT_DEFAULT / "aesthetic-library"
        self.root: Path = root
        self._manifest: Manifest | None = None
        self._provenance_by_source: dict[str, Provenance] = {}
        self._assets: list[Asset] = []
        self._by_triple: dict[tuple[str, str, str], Asset] = {}
        if self.root.is_dir():
            self._load()

    def _load(self) -> None:
        manifest_path = self.root / "_manifest.yaml"
        if not manifest_path.is_file():
            return
        self._manifest = Manifest.load(manifest_path)

        # Load provenance per source group (one provenance.yaml per source subtree).
        for source in {entry.source for entry in self._manifest.assets}:
            prov_path = self.root / source / "provenance.yaml"
            if prov_path.is_file():
                self._provenance_by_source[source] = Provenance.load(prov_path)

        for entry in self._manifest.assets:
            asset_path = (self.root / entry.path).resolve()
            asset = Asset(
                source=entry.source,
                kind=entry.kind,
                name=entry.name,
                path=asset_path,
                sha256=entry.sha256,
                license=entry.license,
                author=entry.author,
                source_url=entry.source_url,
                extracted_date=entry.extracted_date,
                notes=entry.notes,
            )
            self._assets.append(asset)
            self._by_triple[(entry.source, entry.kind, entry.name)] = asset

    def get(self, source: str, kind: str, name: str) -> Asset:
        try:
            return self._by_triple[(source, kind, name)]
        except KeyError as e:
            raise KeyError(f"asset not found: source={source!r} kind={kind!r} name={name!r}") from e

    def list(self, source: str | None = None, kind: str | None = None) -> list[Asset]:
        out = self._assets
        if source is not None:
            out = [a for a in out if a.source == source]
        if kind is not None:
            out = [a for a in out if a.kind == kind]
        return list(out)

    def attribution_for(self, asset: Asset) -> str:
        prov = self._provenance_by_source.get(asset.source)
        if prov and prov.attribution_line:
            return prov.attribution_line
        return f"{asset.author} ({asset.license})"

    def all_licenses(self) -> dict[str, list[Asset]]:
        groups: dict[str, list[Asset]] = defaultdict(list)
        for asset in self._assets:
            groups[asset.license].append(asset)
        return dict(groups)

    def verify_integrity(self) -> list[str]:
        drifted: list[str] = []
        if self._manifest is None:
            return drifted
        for entry in self._manifest.assets:
            asset_path = self.root / entry.path
            if not asset_path.is_file():
                drifted.append(f"{entry.path} (missing)")
                continue
            actual = hashlib.sha256(asset_path.read_bytes()).hexdigest()
            if actual != entry.sha256:
                drifted.append(
                    f"{entry.path} (sha mismatch: manifest {entry.sha256[:12]}… "
                    f"actual {actual[:12]}…)"
                )
        return drifted

    def manifest_entries(self) -> list[ManifestEntry]:
        return list(self._manifest.assets) if self._manifest else []

    def web_url(self, asset: Asset) -> str:
        return build_web_url(self.root, asset.path, asset.sha256)


_library: AestheticLibrary | None = None


def library() -> AestheticLibrary:
    global _library
    if _library is None:
        _library = AestheticLibrary()
    return _library
