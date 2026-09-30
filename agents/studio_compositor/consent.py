"""Consent enforcement for recording and HLS persistence."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentgov.consent import IdentityMigrationUnavailable
from agentgov.revocation import PurgeResult

from shared.governance.consent import estate_identity_operation, resolve_contract_id

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


def purge_video_recordings(compositor: Any, contract_id: str) -> PurgeResult:
    try:
        with estate_identity_operation():
            return _purge_video_recordings(compositor, contract_id)
    except IdentityMigrationUnavailable as exc:
        return PurgeResult("recordings", 0, failures=(exc.reason,))


def _purge_video_recordings(compositor: Any, contract_id: str) -> PurgeResult:
    contract_id = resolve_contract_id(contract_id) or contract_id
    purged = 0
    failures: list[str] = []
    active_ranges: list[tuple[datetime, datetime | None]] = []
    current_start: datetime | None = None
    try:
        for line in CONSENT_AUDIT_PATH.read_text().splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if "active_contracts" not in entry:
                raise ValueError("audit_malformed")
            contracts = entry["active_contracts"]
            if not isinstance(contracts, list) or any(
                not isinstance(cid, str) for cid in contracts
            ):
                raise ValueError("audit_malformed")
            stamp = datetime.fromisoformat(entry["timestamp"])
            if stamp.tzinfo is None:
                raise ValueError("audit_malformed")
            contract_active = contract_id in {resolve_contract_id(cid) or cid for cid in contracts}
            event = entry["event"]
            if current_start is not None and (event == "recording_paused" or not contract_active):
                if stamp < current_start:
                    raise ValueError("audit_malformed")
                active_ranges.append((current_start, stamp))
                current_start = None
            if contract_active and event == "recording_resumed" and current_start is None:
                current_start = stamp
        if current_start:
            active_ranges.append((current_start, None))
    except IdentityMigrationUnavailable:
        raise
    except Exception:
        log.warning("recording_audit_unreadable")
        return PurgeResult("recordings", purged, failures=("recording_audit_unreadable",))

    if not active_ranges:
        return PurgeResult("recordings", purged)

    def in_range(stamp: datetime) -> bool:
        return any(stamp >= start and (end is None or stamp < end) for start, end in active_ranges)

    try:
        rec_dir = Path(compositor.config.recording.output_dir)
        hls_dir = Path(compositor.config.hls.output_dir)
    except Exception:
        return PurgeResult("recordings", purged, failures=("recording_config_invalid",))
    try:
        for role_dir in list(rec_dir.iterdir()) if rec_dir.exists() else []:
            if not role_dir.is_dir():
                continue
            try:
                for recording in [path for path in role_dir.iterdir() if path.suffix == ".mkv"]:
                    try:
                        stamp = datetime.strptime(recording.stem.split("_")[-2], "%Y%m%d-%H%M%S")
                        if in_range(stamp.replace(tzinfo=UTC)):
                            recording.unlink()
                            purged += 1
                    except (ValueError, IndexError):
                        failures.append("recording_timestamp_invalid")
                    except OSError:
                        failures.append("recording_delete_failed")
            except OSError:
                failures.append("recording_scan_failed")
    except OSError:
        failures.append("recording_scan_failed")

    try:
        for segment in (
            [path for path in hls_dir.iterdir() if path.suffix == ".ts"] if hls_dir.exists() else []
        ):
            try:
                stamp = datetime.fromtimestamp(segment.stat().st_mtime, tz=UTC)
                if in_range(stamp):
                    segment.unlink()
                    purged += 1
            except OSError:
                failures.append("hls_delete_failed")
    except OSError:
        failures.append("hls_scan_failed")
    return PurgeResult("recordings", purged, failures=tuple(failures))
