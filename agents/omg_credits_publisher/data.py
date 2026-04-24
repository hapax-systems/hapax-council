"""Data assembly for the credits page.

Reads the aesthetic library's `_manifest.yaml` + per-source
`provenance.yaml` files and builds a structured `CreditsModel`
the Jinja template consumes. No rendering happens here.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from shared.aesthetic_library.loader import AestheticLibrary


class CreditsAsset(BaseModel):
    """One row in the credits table — the outward-facing attribution
    record for a single ingested asset."""

    source: str
    kind: str
    name: str
    path: str  # repo-relative path within aesthetic-library/
    author: str
    license: str
    source_url: str
    extracted_date: str
    attribution_line: str


class CreditsModel(BaseModel):
    """Rendering payload passed to the Jinja template. Sorted for
    deterministic template output."""

    assets: list[CreditsAsset]
    licenses_present: list[str]


def build_credits_model(library_root: Path) -> CreditsModel:
    """Read the library at `library_root` and build the credits model.

    Empty library (missing root, missing manifest) → empty model;
    callers treat empty-model as "nothing to publish."
    """
    lib = AestheticLibrary(root=library_root)
    manifest_entries = lib.manifest_entries()
    if not manifest_entries:
        return CreditsModel(assets=[], licenses_present=[])

    credits_assets: list[CreditsAsset] = []
    for entry in manifest_entries:
        asset = lib.get(entry.source, entry.kind, entry.name)
        attribution = lib.attribution_for(asset)
        credits_assets.append(
            CreditsAsset(
                source=entry.source,
                kind=entry.kind,
                name=entry.name,
                path=entry.path,
                author=entry.author,
                license=entry.license,
                source_url=entry.source_url,
                extracted_date=entry.extracted_date,
                attribution_line=attribution,
            )
        )

    # Sort deterministically: by license, then source, then name.
    credits_assets.sort(key=lambda a: (a.license, a.source, a.name))
    licenses_present = sorted({a.license for a in credits_assets})

    return CreditsModel(assets=credits_assets, licenses_present=licenses_present)
