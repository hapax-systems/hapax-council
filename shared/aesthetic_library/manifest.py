"""Manifest models — authoritative index of assets in `assets/aesthetic-library/`.

The on-disk `_manifest.yaml` carries the canonical SHA-256 per asset. Runtime
integrity verification re-hashes each file and compares against the manifest
to detect drift.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, field_validator

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ManifestEntry(BaseModel):
    source: str
    kind: str
    name: str
    path: str
    sha256: str
    license: str
    author: str
    source_url: str
    extracted_date: str
    notes: str = ""

    @field_validator("sha256")
    @classmethod
    def _validate_sha256(cls, v: str) -> str:
        if not _SHA256_RE.match(v):
            raise ValueError(f"sha256 must be 64 lowercase hex chars, got {v!r}")
        return v

    @field_validator("extracted_date", mode="before")
    @classmethod
    def _coerce_date_to_string(cls, v: Any) -> str:
        if isinstance(v, (date, datetime)):
            return v.isoformat()[:10]
        return v


class Manifest(BaseModel):
    assets: list[ManifestEntry]

    @classmethod
    def load(cls, path: Path) -> Manifest:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls.model_validate(raw)

    def entry_for(self, source: str, kind: str, name: str) -> ManifestEntry | None:
        for entry in self.assets:
            if entry.source == source and entry.kind == kind and entry.name == name:
                return entry
        return None
