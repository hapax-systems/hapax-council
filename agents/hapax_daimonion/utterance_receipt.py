"""Utterance receipt publisher — structural state alongside every voice output.

Writes atomic JSON to /dev/shm/hapax-daimonion/utterance-receipt.json
on every TTS event. Enables operator correspondence verification:
the operator sees both narration and the structural state it claims
to represent.

All 6 data sources are already computed in-process on ConversationPipeline.
This module collects and writes — no new computation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

RECEIPT_DIR = Path("/dev/shm/hapax-daimonion")
RECEIPT_PATH = RECEIPT_DIR / "utterance-receipt.json"
RECEIPT_LOG_PATH = RECEIPT_DIR / "utterance-receipts.jsonl"


def publish_utterance_receipt(
    *,
    utterance_text: str,
    stimmung_region: str = "",
    du_state: str = "",
    gqi: float = 0.0,
    routing_tier: str = "",
    acceptance_signal: str = "",
    strategy_directive: str = "",
    turn_number: int = 0,
    model_id: str = "",
) -> dict[str, Any]:
    """Publish a structured receipt for the current utterance."""
    utterance_hash = hashlib.sha256(utterance_text.encode()).hexdigest()[:16]

    receipt = {
        "utterance_hash": utterance_hash,
        "turn": turn_number,
        "stimmung_region": stimmung_region,
        "du_state": du_state,
        "gqi": round(gqi, 3),
        "routing_tier": routing_tier,
        "acceptance_signal": acceptance_signal,
        "strategy_directive": strategy_directive,
        "model_id": model_id,
        "published_at": time.time(),
    }

    try:
        RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
        tmp = RECEIPT_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        tmp.replace(RECEIPT_PATH)

        with RECEIPT_LOG_PATH.open("a") as f:
            f.write(json.dumps(receipt) + "\n")
    except Exception as e:
        _log.warning("Failed to publish utterance receipt: %s", e)

    return receipt
