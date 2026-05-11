"""Monthly Zenodo clip catalog deposit for citation-graph completeness."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

LEDGER_DIR = Path.home() / "hapax-state" / "auto-clip" / "ledger"
CATALOG_DIR = Path.home() / "hapax-state" / "auto-clip" / "catalogs"


@dataclass(frozen=True)
class CatalogEntry:
    clip_id: str
    timestamp: str
    title: str
    decoder_channel: str
    platforms: list[str]
    urls: list[str]


def collect_month_entries(year: int, month: int) -> list[CatalogEntry]:
    prefix = f"clip-{year:04d}{month:02d}"
    entries: list[CatalogEntry] = []

    if not LEDGER_DIR.is_dir():
        return entries

    for path in sorted(LEDGER_DIR.glob(f"{prefix}*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        candidate = data.get("candidate", {})
        uploads = data.get("uploads", [])
        successful = [u for u in uploads if u.get("success")]

        channels = candidate.get("decoder_channels", ["unknown"])
        entries.append(
            CatalogEntry(
                clip_id=data.get("clip_id", path.stem),
                timestamp=data.get("timestamp", ""),
                title=candidate.get("suggested_title", ""),
                decoder_channel=channels[0] if channels else "unknown",
                platforms=[u["platform"] for u in successful],
                urls=[u["url"] for u in successful if u.get("url")],
            )
        )

    return entries


def build_catalog_metadata(
    entries: list[CatalogEntry],
    year: int,
    month: int,
) -> dict:
    return {
        "title": f"Hapax Auto-Clip Catalog {year:04d}-{month:02d}",
        "upload_type": "dataset",
        "access_right": "open",
        "license": "cc-by-4.0",
        "description": (
            f"Aggregate catalog of {len(entries)} auto-generated Shorts/Reels "
            f"from the Hapax 24/7 ambient broadcast for {year:04d}-{month:02d}. "
            "Each entry maps a detected highlight to its polysemic decoder channel "
            "and platform upload URLs."
        ),
        "creators": [{"name": "Hapax System", "affiliation": "hapax.github.io"}],
        "keywords": ["hapax", "auto-clip", "shorts", "livestream", "catalog"],
        "related_identifiers": [
            {
                "identifier": "https://hapax.github.io",
                "relation": "isPartOf",
                "scheme": "url",
            }
        ],
    }


def write_catalog(year: int, month: int) -> Path | None:
    entries = collect_month_entries(year, month)
    if not entries:
        log.info("No clips found for %04d-%02d", year, month)
        return None

    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    catalog_path = CATALOG_DIR / f"catalog-{year:04d}-{month:02d}.json"

    catalog = {
        "schema_version": 1,
        "period": f"{year:04d}-{month:02d}",
        "generated_at": datetime.now(UTC).isoformat(),
        "entry_count": len(entries),
        "entries": [
            {
                "clip_id": e.clip_id,
                "timestamp": e.timestamp,
                "title": e.title,
                "decoder_channel": e.decoder_channel,
                "platforms": e.platforms,
                "urls": e.urls,
            }
            for e in entries
        ],
        "zenodo_metadata": build_catalog_metadata(entries, year, month),
    }

    catalog_path.write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("Wrote catalog: %s (%d entries)", catalog_path, len(entries))
    return catalog_path
