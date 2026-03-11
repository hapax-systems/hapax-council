"""photos.py — Parser for Google Photos metadata.

We only extract metadata (dates, locations, albums, descriptions).
Binary image data is skipped entirely.

Photos Takeout includes JSON metadata files alongside each image:
- photo.jpg.json → metadata for photo.jpg
"""
from __future__ import annotations

import json
import logging
import zipfile
from collections.abc import Iterator
from datetime import datetime

from shared.takeout.models import NormalizedRecord, ServiceConfig, make_record_id

log = logging.getLogger("takeout.photos")


def parse(zf: zipfile.ZipFile, config: ServiceConfig) -> Iterator[NormalizedRecord]:
    """Parse Photos metadata from a Takeout ZIP.

    Only processes .json metadata files, skips all binary image files.
    """
    prefix_options = [
        "Takeout/Google Photos/",
        "Google Photos/",
    ]

    for name in sorted(zf.namelist()):
        if not name.endswith(".json"):
            continue

        matched = False
        for prefix in prefix_options:
            if name.startswith(prefix):
                matched = True
                break

        if not matched:
            continue

        # Skip metadata.json files (album-level metadata)
        if name.endswith("metadata.json") and "/" in name:
            # But process if it's a per-photo metadata file
            pass

        try:
            raw = zf.read(name)
            data = json.loads(raw)
        except (json.JSONDecodeError, KeyError):
            continue

        if not isinstance(data, dict):
            continue

        record = _photo_to_record(data, name, config)
        if record:
            yield record


def _photo_to_record(
    data: dict,
    source_path: str,
    config: ServiceConfig,
) -> NormalizedRecord | None:
    """Convert photo metadata JSON to a NormalizedRecord."""
    title = data.get("title", "")
    if not title:
        return None

    # Description
    description = data.get("description", "")

    # Timestamp
    timestamp = None
    photo_taken = data.get("photoTakenTime", {})
    if photo_taken:
        ts_str = photo_taken.get("timestamp", "")
        if ts_str:
            try:
                timestamp = datetime.fromtimestamp(int(ts_str))
            except (ValueError, OSError):
                pass

    # Location
    location_str = ""
    geo = data.get("geoData", {}) or data.get("geoDataExif", {})
    lat = geo.get("latitude", 0)
    lon = geo.get("longitude", 0)
    if lat and lon and (abs(lat) > 0.001 or abs(lon) > 0.001):
        location_str = f"{lat:.4f}, {lon:.4f}"

    # Build text
    text_parts = [f"Photo: {title}"]
    if description:
        text_parts.append(description)
    if timestamp:
        text_parts.append(f"Taken: {timestamp.isoformat()}")
    if location_str:
        text_parts.append(f"Location: {location_str}")

    # People in photo
    people: list[str] = []
    for person in data.get("people", []):
        name_val = person.get("name", "")
        if name_val:
            people.append(name_val)

    text = "\n".join(text_parts)

    record_id = make_record_id("google", "photos", source_path)

    # Structured fields
    structured: dict = {}
    if lat and lon:
        structured["lat"] = lat
        structured["lon"] = lon
    image_media = data.get("imageMediaMetadata", {})
    if image_media:
        if image_media.get("cameraMake"):
            structured["camera"] = f"{image_media['cameraMake']} {image_media.get('cameraModel', '')}".strip()

    # Modality tags
    modality_tags = list(config.modality_defaults)
    if people:
        modality_tags.append("social")

    return NormalizedRecord(
        record_id=record_id,
        platform="google",
        service="photos",
        title=title,
        text=text,
        content_type="photo",
        timestamp=timestamp,
        modality_tags=modality_tags,
        people=people,
        location=location_str,
        structured_fields=structured,
        data_path=config.data_path,
        source_path=source_path,
    )
