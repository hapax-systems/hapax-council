"""Correspondence API — latest utterance receipt + correspondence score."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter

_log = logging.getLogger(__name__)
router = APIRouter(prefix="/correspondence", tags=["correspondence"])

RECEIPT_PATH = Path("/dev/shm/hapax-daimonion/utterance-receipt.json")
FEEDBACK_PATH = Path("/dev/shm/hapax-daimonion/acceptance-feedback.jsonl")


@router.get("")
async def get_correspondence() -> dict[str, Any]:
    receipt: dict[str, Any] = {}
    if RECEIPT_PATH.exists():
        try:
            receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            _log.warning("Failed to read receipt: %s", e)

    recent: list[dict[str, Any]] = []
    if FEEDBACK_PATH.exists():
        try:
            lines = FEEDBACK_PATH.read_text(encoding="utf-8").strip().split("\n")
            recent = [json.loads(line) for line in lines[-5:] if line.strip()]
        except Exception as e:
            _log.warning("Failed to read acceptance log: %s", e)

    return {"receipt": receipt, "recent_acceptance": recent, "has_receipt": bool(receipt)}
