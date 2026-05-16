"""Chronicle correspondence annotations."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)
RECEIPT_PATH = Path("/dev/shm/hapax-daimonion/utterance-receipt.json")


def read_latest_receipt() -> dict[str, Any] | None:
    try:
        if RECEIPT_PATH.exists():
            return json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        _log.debug("Failed to read receipt: %s", e)
    return None


def compute_correspondence_score(narration_text: str, receipt: dict[str, Any]) -> float:
    if not receipt:
        return 0.0
    score, checks = 0.0, 0
    stimmung = receipt.get("stimmung_region", "")
    du_state = receipt.get("du_state", "")
    gqi = receipt.get("gqi", 0.0)
    lower = narration_text.lower()

    if stimmung == "critical" and any(w in lower for w in ["struggling", "difficult", "issue"]):
        score += 1.0
    elif stimmung == "nominal" and not any(w in lower for w in ["crisis", "emergency"]):
        score += 1.0
    elif stimmung:
        score += 0.5
    checks += 1

    if du_state == "GROUNDED" and not any(w in lower for w in ["confused", "unclear"]):
        score += 1.0
    elif du_state in ("REPAIR_1", "REPAIR_2") and any(w in lower for w in ["clarif", "explain"]):
        score += 1.0
    elif du_state:
        score += 0.5
    checks += 1

    if gqi > 0.7 and not any(w in lower for w in ["lost", "confused"]):
        score += 1.0
    elif gqi < 0.3 and any(w in lower for w in ["let me", "try again"]):
        score += 1.0
    else:
        score += 0.5
    checks += 1

    return round(score / max(checks, 1), 3)


def annotate_chronicle_event(
    event_payload: dict[str, Any], narration_text: str = ""
) -> dict[str, Any]:
    receipt = read_latest_receipt()
    event_payload["correspondence_score"] = (
        compute_correspondence_score(narration_text, receipt) if receipt else 0.0
    )
    event_payload["receipt_id"] = receipt.get("utterance_hash", "") if receipt else ""
    event_payload["correspondence_annotated_at"] = time.time()
    return event_payload
