"""Operator attestation identifiers shared by dispatch gates."""

from __future__ import annotations

import hashlib
import json

OPERATOR_ATTESTATION_RULING = "RULING-REINS-OPERATOR-ATTESTATION-20260701"


def expected_operator_attestation_ref(
    *,
    origin_surface: str,
    task_id: str,
    lane: str,
    ruling: str = OPERATOR_ATTESTATION_RULING,
) -> str:
    """Return the Crow-chat operator attestation ref bound to origin, task, lane, and ruling."""

    origin = origin_surface.strip()
    payload = {
        "origin_surface": origin,
        "task_id": task_id.strip(),
        "lane": lane.strip(),
        "ruling": ruling.strip(),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:32]
    return f"operator-attestation:reins:{origin}:{digest}"
