"""Consent enforcement for recording and HLS persistence."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import CONSENT_AUDIT_PATH

log = logging.getLogger(__name__)


def log_consent_event(compositor: Any, event: str, allowed: bool) -> None:
    """Append a consent event to the JSONL audit trail."""
    with compositor._overlay_state._lock:
        contracts = list(compositor._overlay_state._data.active_contracts)

    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event": event,
        "consent_allowed": allowed,
        "active_contracts": contracts,
        "recording_cameras": list(compositor._recording_valves.keys()),
        "hls_active": compositor._hls_valve is not None,
    }

    try:
        CONSENT_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONSENT_AUDIT_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        log.debug("Failed to write consent audit log")


def disable_persistence(compositor: Any) -> None:
    """Consent withdrawn -- finalize segments then drop recording/HLS buffers."""
    log.warning("Consent persistence DENIED — stopping recording and HLS")
    for _role, mux in compositor._recording_muxes.items():
        try:
            mux.emit("split-now")
        except Exception:
            pass
    for valve in compositor._recording_valves.values():
        valve.set_property("drop", True)
    if compositor._hls_valve is not None:
        compositor._hls_valve.set_property("drop", True)
    with compositor._recording_status_lock:
        for role in compositor._recording_status:
            compositor._recording_status[role] = "consent-blocked"
    log_consent_event(compositor, "recording_paused", allowed=False)


def enable_persistence(compositor: Any) -> None:
    """Consent restored -- resume recording and HLS."""
    log.info("Consent persistence ALLOWED — resuming recording and HLS")
    for valve in compositor._recording_valves.values():
        valve.set_property("drop", False)
    if compositor._hls_valve is not None:
        compositor._hls_valve.set_property("drop", False)
    with compositor._recording_status_lock:
        for role in compositor._recording_status:
            if compositor._recording_status[role] == "consent-blocked":
                compositor._recording_status[role] = "active"
    log_consent_event(compositor, "recording_resumed", allowed=True)

    Gst = compositor._Gst
    if Gst is None:
        return
    with compositor._overlay_state._lock:
        contracts = list(compositor._overlay_state._data.active_contracts)
    contract_str = ",".join(contracts) if contracts else "operator-only"

    for role, mux in compositor._recording_muxes.items():
        try:
            inner_mux = mux.get_property("muxer")
            if inner_mux is None:
                inner_mux = mux
            tag_list = Gst.TagList.new_empty()
            tag_list.add_value(
                Gst.TagMergeMode.REPLACE,
                Gst.TAG_EXTENDED_COMMENT,
                f"consent-contracts={contract_str}",
            )
            tag_list.add_value(
                Gst.TagMergeMode.REPLACE,
                Gst.TAG_COMMENT,
                f"Consent: {'granted' if contracts else 'operator-only'}",
            )
            inner_mux.merge_tags(tag_list, Gst.TagMergeMode.REPLACE)
        except Exception:
            log.debug("Failed to set consent tags on %s", role)


def purge_video_recordings(compositor: Any, contract_id: str) -> int:
    """Purge video recording segments associated with a revoked consent contract."""
    purged = 0
    rec_dir = Path(compositor.config.recording.output_dir)

    active_ranges: list[tuple[str, str | None]] = []
    current_start: str | None = None

    try:
        if CONSENT_AUDIT_PATH.exists():
            for line in CONSENT_AUDIT_PATH.read_text().splitlines():
                if not line.strip():
                    continue
                entry = json.loads(line)
                if contract_id in entry.get("active_contracts", []):
                    if entry["event"] == "recording_resumed" and current_start is None:
                        current_start = entry["timestamp"]
                    elif entry["event"] == "recording_paused" and current_start:
                        active_ranges.append((current_start, entry["timestamp"]))
                        current_start = None
            if current_start:
                active_ranges.append((current_start, None))
    except Exception:
        log.warning("Failed to read consent audit for purge")
        return 0

    if not active_ranges:
        return 0

    if rec_dir.exists():
        for role_dir in rec_dir.iterdir():
            if not role_dir.is_dir():
                continue
            for mkv_file in role_dir.glob("*.mkv"):
                try:
                    name_parts = mkv_file.stem.split("_")
                    ts_str = name_parts[-2]
                    file_time = datetime.strptime(ts_str, "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
                    file_iso = file_time.isoformat()
                    for start, end in active_ranges:
                        if file_iso >= start and (end is None or file_iso <= end):
                            mkv_file.unlink()
                            purged += 1
                            log.info(
                                "Purged recording: %s (contract %s revoked)", mkv_file, contract_id
                            )
                            break
                except (ValueError, IndexError):
                    continue

    hls_dir = Path(compositor.config.hls.output_dir)
    if hls_dir.exists():
        for ts_file in hls_dir.glob("*.ts"):
            try:
                mtime = datetime.fromtimestamp(ts_file.stat().st_mtime, tz=UTC)
                mtime_iso = mtime.isoformat()
                for start, end in active_ranges:
                    if mtime_iso >= start and (end is None or mtime_iso <= end):
                        ts_file.unlink()
                        purged += 1
                        log.info("Purged HLS segment: %s", ts_file)
                        break
            except OSError:
                continue

    return purged
