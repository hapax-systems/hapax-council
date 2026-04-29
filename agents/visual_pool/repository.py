"""Fail-closed local visual pool for Sierpinski frame sources.

The pool is rooted at ``~/hapax-pool/visual/`` and is intentionally local:
no network fetch, no playlist extraction, no multi-operator state. Assets
are selected only when a well-formed YAML sidecar proves broadcast posture,
content-risk tier, source class, and aesthetic tags.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import time
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared.affordance import ContentRisk

log = logging.getLogger(__name__)

DEFAULT_VISUAL_POOL_ROOT = Path.home() / "hapax-pool" / "visual"
DEFAULT_SIERPINSKI_TAGS: tuple[str, ...] = ("sierpinski", "abstract", "texture")
DEFAULT_MAX_CONTENT_RISK: ContentRisk = "tier_1_platform_cleared"
DEFAULT_REFRESH_S = 15.0

SUPPORTED_FRAME_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png"})
TIER_DIRECTORIES: dict[str, ContentRisk] = {
    "operator-cuts": "tier_0_owned",
    "storyblocks": "tier_1_platform_cleared",
    "internet-archive": "tier_2_provenance_known",
    "sample-source": "tier_4_risky",
}
NEVER_BROADCAST_DIRECTORIES = frozenset({"sample-source"})

_CONTENT_RISK_RANK: dict[ContentRisk, int] = {
    "tier_0_owned": 0,
    "tier_1_platform_cleared": 1,
    "tier_2_provenance_known": 2,
    "tier_3_uncertain": 3,
    "tier_4_risky": 4,
}
_CONTENT_RISK_VALUES = frozenset(_CONTENT_RISK_RANK)


class VisualPoolSidecar(BaseModel):
    """Required sidecar metadata for one local visual asset.

    Missing or malformed sidecars are not selected. The selector does not infer
    public safety from directory names alone; the directory tier and sidecar
    content-risk must both be coherent.
    """

    model_config = ConfigDict(extra="forbid")

    content_risk: ContentRisk
    source: str = Field(min_length=1)
    broadcast_safe: bool
    aesthetic_tags: list[str] = Field(min_length=1)
    motion_density: float = Field(ge=0.0, le=1.0)
    color_palette: list[str] = Field(default_factory=list)
    duration_seconds: float = Field(ge=0.0)
    title: str | None = None
    license: str | None = None
    provenance_url: str | None = None

    @field_validator("source")
    @classmethod
    def _normalize_source(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("visual pool source is required")
        return normalized

    @field_validator("aesthetic_tags")
    @classmethod
    def _normalize_aesthetic_tags(cls, values: list[str]) -> list[str]:
        seen: dict[str, None] = {}
        for raw in values:
            tag = _normalize_tag(raw)
            if tag:
                seen.setdefault(tag, None)
        if not seen:
            raise ValueError("visual pool aesthetic_tags must include at least one tag")
        return list(seen)

    @field_validator("color_palette")
    @classmethod
    def _normalize_color_palette(cls, values: list[str]) -> list[str]:
        seen: dict[str, None] = {}
        for raw in values:
            tag = _normalize_tag(raw)
            if tag:
                seen.setdefault(tag, None)
        return list(seen)


class VisualPoolAsset(BaseModel):
    """Validated asset plus its sidecar and derived provenance token."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    path: Path
    sidecar_path: Path
    tier_directory: str
    metadata: VisualPoolSidecar
    sha256: str
    provenance_token: str

    @property
    def frame_loadable(self) -> bool:
        return self.path.suffix.lower() in SUPPORTED_FRAME_EXTENSIONS


class LocalVisualPool:
    """Scanner, selector, and ingestion helper for ``~/hapax-pool/visual``."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root).expanduser() if root is not None else DEFAULT_VISUAL_POOL_ROOT

    def ensure_layout(self) -> None:
        """Create the visual pool directory scaffold and README."""
        self.root.mkdir(parents=True, exist_ok=True)
        for dirname in TIER_DIRECTORIES:
            (self.root / dirname).mkdir(parents=True, exist_ok=True)
        readme = self.root / "README.md"
        if not readme.exists():
            readme.write_text(_layout_readme(), encoding="utf-8")

    def ingest(
        self,
        source_path: Path | str,
        *,
        tier_directory: str,
        aesthetic_tags: list[str],
        motion_density: float,
        color_palette: list[str] | None = None,
        duration_seconds: float = 0.0,
        source: str | None = None,
        content_risk: ContentRisk | None = None,
        broadcast_safe: bool | None = None,
        title: str | None = None,
        license: str | None = None,
        provenance_url: str | None = None,
        slug: str | None = None,
        force: bool = False,
    ) -> VisualPoolAsset:
        """Copy a local frame asset into the pool and write its YAML sidecar."""
        src = Path(source_path).expanduser()
        if not src.is_file():
            raise FileNotFoundError(f"visual pool ingest source missing: {src}")
        suffix = src.suffix.lower()
        if suffix not in SUPPORTED_FRAME_EXTENSIONS:
            raise ValueError(
                f"unsupported Sierpinski frame asset extension {suffix!r}; "
                f"supported: {sorted(SUPPORTED_FRAME_EXTENSIONS)}"
            )
        if tier_directory not in TIER_DIRECTORIES:
            raise ValueError(f"unknown visual pool tier directory: {tier_directory}")

        expected_risk = TIER_DIRECTORIES[tier_directory]
        risk = content_risk if content_risk is not None else expected_risk
        safe = (
            tier_directory not in NEVER_BROADCAST_DIRECTORIES
            if broadcast_safe is None
            else broadcast_safe
        )
        asset_slug = _slugify(slug or src.stem)

        self.ensure_layout()
        dest = self.root / tier_directory / f"{asset_slug}{suffix}"
        sidecar_path = dest.with_suffix(".yaml")
        if not force and (dest.exists() or sidecar_path.exists()):
            raise FileExistsError(f"visual pool asset already exists: {dest}")

        shutil.copy2(src, dest)
        sidecar = VisualPoolSidecar(
            content_risk=risk,
            source=source or tier_directory,
            broadcast_safe=safe,
            aesthetic_tags=aesthetic_tags,
            motion_density=motion_density,
            color_palette=color_palette or [],
            duration_seconds=duration_seconds,
            title=title or src.stem,
            license=license,
            provenance_url=provenance_url,
        )
        sidecar_path.write_text(
            yaml.safe_dump(sidecar.model_dump(exclude_none=True), sort_keys=False),
            encoding="utf-8",
        )
        asset = self._asset_from_path(dest)
        if asset is None:
            raise ValueError(f"ingested asset failed visual pool validation: {dest}")
        return asset

    def scan(self) -> list[VisualPoolAsset]:
        """Return every valid, frame-loadable visual-pool asset."""
        if not self.root.exists():
            return []
        assets: list[VisualPoolAsset] = []
        for tier_directory in TIER_DIRECTORIES:
            tier_root = self.root / tier_directory
            if not tier_root.is_dir():
                continue
            for path in sorted(tier_root.rglob("*")):
                if path.suffix.lower() not in SUPPORTED_FRAME_EXTENSIONS:
                    continue
                asset = self._asset_from_path(path)
                if asset is not None:
                    assets.append(asset)
        return assets

    def select(
        self,
        *,
        aesthetic_tags: list[str] | tuple[str, ...] = DEFAULT_SIERPINSKI_TAGS,
        max_content_risk: ContentRisk = DEFAULT_MAX_CONTENT_RISK,
        slot_id: int = 0,
    ) -> VisualPoolAsset | None:
        """Select one broadcast-safe asset by aesthetic tag and risk ceiling."""
        requested = {_normalize_tag(tag) for tag in aesthetic_tags if _normalize_tag(tag)}
        max_rank = _CONTENT_RISK_RANK[max_content_risk]

        ranked: list[tuple[int, int, str, VisualPoolAsset]] = []
        for asset in self.scan():
            if not asset.frame_loadable:
                continue
            if asset.tier_directory in NEVER_BROADCAST_DIRECTORIES:
                continue
            if not asset.metadata.broadcast_safe:
                continue
            risk_rank = _CONTENT_RISK_RANK[asset.metadata.content_risk]
            if risk_rank > max_rank:
                continue
            asset_tags = set(asset.metadata.aesthetic_tags)
            matches = len(requested & asset_tags) if requested else 0
            if requested and matches == 0:
                continue
            ranked.append((-matches, risk_rank, str(asset.path), asset))

        if not ranked:
            return None
        ranked.sort(key=lambda item: (item[0], item[1], item[2]))
        return ranked[slot_id % len(ranked)][3]

    def _asset_from_path(self, path: Path) -> VisualPoolAsset | None:
        try:
            resolved = path.expanduser().resolve()
            rel = resolved.relative_to(self.root.expanduser().resolve())
        except (OSError, ValueError):
            log.debug("visual pool asset outside root skipped: %s", path)
            return None
        if len(rel.parts) < 2:
            return None
        tier_directory = rel.parts[0]
        expected_risk = TIER_DIRECTORIES.get(tier_directory)
        if expected_risk is None:
            return None
        sidecar_path = resolved.with_suffix(".yaml")
        try:
            raw = yaml.safe_load(sidecar_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return None
            metadata = VisualPoolSidecar.model_validate(raw)
        except Exception:
            log.debug("visual pool sidecar invalid or missing: %s", sidecar_path, exc_info=True)
            return None
        if tier_directory != "sample-source" and metadata.content_risk != expected_risk:
            log.debug(
                "visual pool sidecar tier mismatch for %s: directory=%s sidecar=%s",
                resolved,
                expected_risk,
                metadata.content_risk,
            )
            return None
        if tier_directory == "sample-source" and metadata.broadcast_safe:
            return None
        digest = _sha256(resolved)
        return VisualPoolAsset(
            path=resolved,
            sidecar_path=sidecar_path,
            tier_directory=tier_directory,
            metadata=metadata,
            sha256=digest,
            provenance_token=f"visual:hapax-pool:{digest}",
        )


class LocalVisualPoolSelector:
    """Small cache around :class:`LocalVisualPool` for hot Sierpinski ticks."""

    def __init__(
        self,
        *,
        root: Path | str | None = None,
        aesthetic_tags: list[str] | tuple[str, ...] | None = None,
        max_content_risk: ContentRisk | None = None,
        refresh_s: float = DEFAULT_REFRESH_S,
    ) -> None:
        self.pool = LocalVisualPool(root)
        self.aesthetic_tags = tuple(aesthetic_tags or tags_from_env())
        self.max_content_risk = max_content_risk or content_risk_from_env()
        self.refresh_s = refresh_s
        self._assets: list[VisualPoolAsset] = []
        self._loaded_at = 0.0

    def select(self, slot_id: int = 0) -> VisualPoolAsset | None:
        now = time.monotonic()
        if now - self._loaded_at > self.refresh_s:
            self._assets = self.pool.scan()
            self._loaded_at = now
        return _select_from_assets(
            self._assets,
            aesthetic_tags=self.aesthetic_tags,
            max_content_risk=self.max_content_risk,
            slot_id=slot_id,
        )


def tags_from_env() -> tuple[str, ...]:
    """Return Sierpinski aesthetic tags from env or the safe default set."""
    import os

    raw = os.environ.get("HAPAX_SIERPINSKI_AESTHETIC_TAGS", "")
    tags = [_normalize_tag(chunk) for chunk in raw.split(",") if _normalize_tag(chunk)]
    return tuple(tags) if tags else DEFAULT_SIERPINSKI_TAGS


def content_risk_from_env() -> ContentRisk:
    """Return the Sierpinski risk ceiling from env, failing closed on typos."""
    import os

    raw = os.environ.get("HAPAX_SIERPINSKI_MAX_CONTENT_RISK", "").strip().lower()
    if raw in _CONTENT_RISK_VALUES:
        return cast("ContentRisk", raw)
    return DEFAULT_MAX_CONTENT_RISK


def _select_from_assets(
    assets: list[VisualPoolAsset],
    *,
    aesthetic_tags: list[str] | tuple[str, ...],
    max_content_risk: ContentRisk,
    slot_id: int,
) -> VisualPoolAsset | None:
    requested = {_normalize_tag(tag) for tag in aesthetic_tags if _normalize_tag(tag)}
    max_rank = _CONTENT_RISK_RANK[max_content_risk]
    ranked: list[tuple[int, int, str, VisualPoolAsset]] = []
    for asset in assets:
        if asset.tier_directory in NEVER_BROADCAST_DIRECTORIES:
            continue
        if not asset.metadata.broadcast_safe:
            continue
        risk_rank = _CONTENT_RISK_RANK[asset.metadata.content_risk]
        if risk_rank > max_rank:
            continue
        matches = len(requested & set(asset.metadata.aesthetic_tags)) if requested else 0
        if requested and matches == 0:
            continue
        ranked.append((-matches, risk_rank, str(asset.path), asset))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    return ranked[slot_id % len(ranked)][3]


def _normalize_tag(value: Any) -> str:
    return re.sub(r"[^a-z0-9_.-]+", "-", str(value).strip().lower()).strip("-")


def _slugify(value: str) -> str:
    slug = _normalize_tag(value)
    if not slug:
        raise ValueError("visual pool asset slug is empty")
    return slug


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _layout_readme() -> str:
    return """# Hapax Visual Pool

Local visual assets for Sierpinski and future provenance-aware visual sources.

Directory policy:

- `operator-cuts/`: tier_0_owned, operator-owned footage or generated frames.
- `storyblocks/`: tier_1_platform_cleared, platform-cleared paid stock.
- `internet-archive/`: tier_2_provenance_known, verified public-domain material.
- `sample-source/`: never broadcast; DAW/reference material only.

Each frame asset must have a same-stem `.yaml` sidecar with:

```yaml
content_risk: tier_0_owned
source: operator-cuts
broadcast_safe: true
aesthetic_tags: [sierpinski, texture]
motion_density: 0.4
color_palette: [cyan, magenta]
duration_seconds: 0
```

Malformed or missing sidecars fail closed and are not selected.
"""
