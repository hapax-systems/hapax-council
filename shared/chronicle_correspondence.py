"""Chronicle correspondence annotations.

Enriches chronicle narration events with correspondence_score and
receipt_id linking to the utterance receipt. Builds historical dataset
for narration-to-structure correspondence study.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

RECEIPT_PATH = Path("/dev/shm/hapax-daimonion/utterance-receipt.json")


def read_latest_receipt() -> dict[str, Any] | None:
    """Read the latest utterance receipt from /dev/shm."""
    try:
        if RECEIPT_PATH.exists():
            return json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        _log.debug("Failed to read receipt: %s", e)
    return None


def compute_correspondence_score(
    narration_text: str,
    receipt: dict[str, Any],
) -> float:
    """Compute a basic correspondence score between narration and structural state.

    Checks whether the narration vocabulary aligns with what the
    structural state predicts. Returns 0.0-1.0.
    """
    if not receipt:
        return 0.0

    score = 0.0
    checks = 0

    stimmung = receipt.get("stimmung_region", "")
    du_state = receipt.get("du_state", "")
    gqi = receipt.get("gqi", 0.0)

    lower = narration_text.lower()

    if stimmung == "critical" and any(
        w in lower for w in ["struggling", "difficult", "issue", "problem"]
    ) or stimmung == "nominal" and not any(w in lower for w in ["crisis", "emergency", "critical"]):
        score += 1.0
    elif stimmung:
        score += 0.5
    checks += 1

    if du_state == "GROUNDED" and not any(
        w in lower for w in ["confused", "unclear", "misunderstand"]
    ) or du_state in ("REPAIR_1", "REPAIR_2") and any(
        w in lower for w in ["clarif", "explain", "mean"]
    ):
        score += 1.0
    elif du_state:
        score += 0.5
    checks += 1

    if gqi > 0.7 and not any(w in lower for w in ["lost", "confused", "what"]) or gqi < 0.3 and any(w in lower for w in ["let me", "try again", "rephrase"]):
        score += 1.0
    else:
        score += 0.5
    checks += 1

    return round(score / max(checks, 1), 3)


def annotate_chronicle_event(
    event_payload: dict[str, Any],
    narration_text: str = "",
) -> dict[str, Any]:
    """Add correspondence annotations to a chronicle event payload."""
    receipt = read_latest_receipt()
    receipt_id = receipt.get("utterance_hash", "") if receipt else ""
    correspondence = compute_correspondence_score(narration_text, receipt) if receipt else 0.0

    event_payload["correspondence_score"] = correspondence
    event_payload["receipt_id"] = receipt_id
    event_payload["correspondence_annotated_at"] = time.time()

    return event_payload
