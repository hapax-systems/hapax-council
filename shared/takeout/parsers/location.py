"""location.py — Parser for Google Location History / Maps data.

Location History Takeout can have millions of raw GPS pings.
Strategy: prefer Semantic Location History (place visits, activity segments)
over raw coordinates. Aggregate by day + place.

Formats:
- Semantic Location History/{year}/{month}.json — place visits + activity segments
- Records.json — raw coordinate pings (legacy format)
"""
from __future__ import annotations

import json
import logging
import zipfile
from collections import defaultdict
from collections.abc import Iterator
from datetime import datetime

from shared.takeout.models import NormalizedRecord, ServiceConfig, make_record_id

log = logging.getLogger("takeout.location")


def parse(zf: zipfile.ZipFile, config: ServiceConfig) -> Iterator[NormalizedRecord]:
    """Parse location data from a Takeout ZIP.

    Prefers Semantic Location History over raw Records.json.
    """
    prefix_options = [
        "Takeout/Location History/",
        "Location History/",
    ]

    semantic_files: list[str] = []
    records_file: str | None = None

    for name in sorted(zf.namelist()):
        for prefix in prefix_options:
            if not name.startswith(prefix):
                continue

            rel = name[len(prefix):]
            if rel.startswith("Semantic Location History/") and name.endswith(".json"):
                semantic_files.append(name)
            elif rel == "Records.json" or rel == "Location History.json":
                records_file = name
            break

    # Prefer semantic location data
    if semantic_files:
        for sf in semantic_files:
            yield from _parse_semantic(zf, sf, config)
    elif records_file:
        yield from _parse_raw_records(zf, records_file, config)


def _parse_semantic(
    zf: zipfile.ZipFile,
    path: str,
    config: ServiceConfig,
) -> Iterator[NormalizedRecord]:
    """Parse Semantic Location History JSON.

    Contains placeVisit and activitySegment objects.
    """
    try:
        raw = zf.read(path)
        data = json.loads(raw)
    except (json.JSONDecodeError, KeyError) as e:
        log.warning("Failed to parse %s: %s", path, e)
        return

    timeline = data.get("timelineObjects", [])
    if not timeline:
        return

    for obj in timeline:
        if "placeVisit" in obj:
            record = _place_visit_to_record(obj["placeVisit"], path, config)
            if record:
                yield record
        elif "activitySegment" in obj:
            record = _activity_segment_to_record(obj["activitySegment"], path, config)
            if record:
                yield record


def _place_visit_to_record(
    visit: dict,
    source_path: str,
    config: ServiceConfig,
) -> NormalizedRecord | None:
    """Convert a place visit to a NormalizedRecord."""
    location_info = visit.get("location", {})
    name = location_info.get("name", "")
    address = location_info.get("address", "")
    place_id = location_info.get("placeId", "")

    if not name and not address:
        return None

    location_str = name or address

    # Timestamps
    start_ts = _parse_location_time(
        visit.get("duration", {}).get("startTimestamp", "")
    )
    end_ts = _parse_location_time(
        visit.get("duration", {}).get("endTimestamp", "")
    )

    # Duration in minutes
    duration_min = None
    if start_ts and end_ts:
        duration_min = int((end_ts - start_ts).total_seconds() / 60)

    # Coordinates
    lat = location_info.get("latitudeE7")
    lon = location_info.get("longitudeE7")

    # Build text
    text_parts = [f"Place: {location_str}"]
    if address and address != name:
        text_parts.append(f"Address: {address}")
    if start_ts:
        text_parts.append(f"Arrived: {start_ts.isoformat()}")
    if duration_min:
        text_parts.append(f"Duration: {duration_min} minutes")

    text = "\n".join(text_parts)
    source_key = f"{place_id or location_str}:{visit.get('duration', {}).get('startTimestamp', '')}"
    record_id = make_record_id("google", "location", source_key)

    structured: dict = {}
    if duration_min:
        structured["duration_minutes"] = duration_min
    if lat and lon:
        structured["lat"] = lat / 1e7
        structured["lon"] = lon / 1e7
    if place_id:
        structured["place_id"] = place_id

    return NormalizedRecord(
        record_id=record_id,
        platform="google",
        service="maps",
        title=f"Visit: {location_str}",
        text=text,
        content_type="location",
        timestamp=start_ts,
        modality_tags=list(config.modality_defaults),
        location=location_str,
        structured_fields=structured,
        data_path=config.data_path,
        source_path=source_path,
    )


def _activity_segment_to_record(
    segment: dict,
    source_path: str,
    config: ServiceConfig,
) -> NormalizedRecord | None:
    """Convert an activity segment (transit) to a NormalizedRecord."""
    activity_type = segment.get("activityType", "UNKNOWN")

    start_ts = _parse_location_time(
        segment.get("duration", {}).get("startTimestamp", "")
    )
    end_ts = _parse_location_time(
        segment.get("duration", {}).get("endTimestamp", "")
    )

    # Skip very short activities
    if start_ts and end_ts:
        duration_min = int((end_ts - start_ts).total_seconds() / 60)
        if duration_min < 5:
            return None
    else:
        duration_min = None

    # Start/end locations
    start_loc = segment.get("startLocation", {})
    end_loc = segment.get("endLocation", {})

    title = f"Transit: {activity_type.replace('_', ' ').title()}"
    text_parts = [title]
    if duration_min:
        text_parts.append(f"Duration: {duration_min} minutes")
    distance = segment.get("distance")
    if distance:
        text_parts.append(f"Distance: {distance}m")

    text = "\n".join(text_parts)
    source_key = f"segment:{activity_type}:{segment.get('duration', {}).get('startTimestamp', '')}"
    record_id = make_record_id("google", "location", source_key)

    structured: dict = {"activity_type": activity_type}
    if duration_min:
        structured["duration_minutes"] = duration_min
    if distance:
        structured["distance_meters"] = distance

    return NormalizedRecord(
        record_id=record_id,
        platform="google",
        service="maps",
        title=title,
        text=text,
        content_type="location",
        timestamp=start_ts,
        modality_tags=list(config.modality_defaults),
        structured_fields=structured,
        data_path=config.data_path,
        source_path=source_path,
    )


LARGE_FILE_THRESHOLD = 200 * 1024 * 1024  # 200MB


def _parse_raw_records(
    zf: zipfile.ZipFile,
    path: str,
    config: ServiceConfig,
) -> Iterator[NormalizedRecord]:
    """Parse raw Records.json with GPS pings.

    Aggregates by day + approximate location to reduce volume.

    Warning: Large Records.json files (>200MB) are loaded entirely into
    memory. Consider splitting the export or increasing available RAM.
    """
    # Memory guard: warn about large files before loading
    info = zf.getinfo(path)
    uncompressed_size = info.file_size
    if uncompressed_size > LARGE_FILE_THRESHOLD:
        size_mb = uncompressed_size / (1024 * 1024)
        log.warning(
            "Large location file: %s is %.0fMB (uncompressed). "
            "This will be loaded entirely into memory. "
            "Consider splitting your Takeout export if memory is constrained.",
            path, size_mb,
        )

    try:
        raw = zf.read(path)
        data = json.loads(raw)
    except (json.JSONDecodeError, KeyError) as e:
        log.warning("Failed to parse %s: %s", path, e)
        return

    locations = data.get("locations", [])
    if not locations:
        return

    # Aggregate by date
    by_date: defaultdict[str, list[dict]] = defaultdict(list)
    for loc in locations:
        ts_str = loc.get("timestamp", loc.get("timestampMs", ""))
        ts = _parse_location_time(ts_str)
        if ts:
            date_key = ts.strftime("%Y-%m-%d")
            by_date[date_key].append(loc)

    for date_str, locs in sorted(by_date.items()):
        record_id = make_record_id("google", "location_raw", date_str)
        text = f"Location data: {len(locs)} points on {date_str}"

        try:
            ts = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            ts = None

        yield NormalizedRecord(
            record_id=record_id,
            platform="google",
            service="maps",
            title=f"Location: {date_str} ({len(locs)} points)",
            text=text,
            content_type="location",
            timestamp=ts,
            modality_tags=list(config.modality_defaults),
            structured_fields={"point_count": len(locs), "date": date_str},
            data_path=config.data_path,
            source_path=path,
        )


def _parse_location_time(ts_str: str) -> datetime | None:
    """Parse various location timestamp formats."""
    if not ts_str:
        return None

    # ISO format: "2025-06-15T10:30:00.000Z"
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(ts_str, fmt)
        except ValueError:
            continue

    # Milliseconds since epoch
    if ts_str.isdigit():
        try:
            return datetime.fromtimestamp(int(ts_str) / 1000)
        except (ValueError, OSError):
            pass

    # ISO fallback
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None
