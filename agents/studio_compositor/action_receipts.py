"""Best-effort action receipt writer for compositor acknowledgement paths."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from shared.action_receipt import ActionReceipt, ActionReceiptStatus
from shared.capability_outcome import AuthorityCeiling

log = logging.getLogger(__name__)

DEFAULT_ACTION_RECEIPTS_JSONL = Path("/dev/shm/hapax-compositor/action-receipts.jsonl")


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def receipt_token(value: str) -> str:
    out = []
    for char in value:
        if char.isascii() and (char.isalnum() or char in ".:-_"):
            out.append(char)
        else:
            out.append("-")
    return "".join(out).strip("-")[:160] or "unknown"


def append_action_receipt(
    receipt: ActionReceipt,
    *,
    path: Path | None = None,
) -> None:
    target = path or DEFAULT_ACTION_RECEIPTS_JSONL
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(receipt.model_dump_json() + "\n")
    except Exception:
        log.warning("action receipt append failed", exc_info=True)


def emit_action_receipt(
    *,
    request_id: str | None,
    capability_name: str,
    requested_action: str,
    status: ActionReceiptStatus,
    family: str,
    command_ref: str,
    applied_refs: list[str] | None = None,
    blocked_reasons: list[str] | None = None,
    error_refs: list[str] | None = None,
    target_aperture: str | None = None,
    wcs_refs: list[str] | None = None,
    structural_reflex: bool = False,
    operator_visible_summary: str | None = None,
    path: Path | None = None,
) -> ActionReceipt | None:
    """Construct and append a no-claim action receipt.

    Missing request ids are normalized rather than skipped because the
    receipt itself is the first correlation surface for some legacy writers.
    """

    rid = request_id or f"compositor:{receipt_token(capability_name)}:{int(time.time() * 1000)}"
    applied = list(applied_refs or [])
    blockers = list(blocked_reasons or [])
    errors = list(error_refs or [])
    if status is ActionReceiptStatus.APPLIED:
        target_aperture = target_aperture or f"aperture:compositor:{family}"
        wcs_refs = list(wcs_refs or [f"wcs:compositor:{family}"])
        if not applied:
            applied = [f"{command_ref}:applied"]
    else:
        wcs_refs = list(wcs_refs or [])
    if operator_visible_summary is None:
        if status is ActionReceiptStatus.APPLIED:
            operator_visible_summary = (
                f"{capability_name} applied at {family}; readback is still required "
                "before learning or speech can call it done."
            )
        elif status is ActionReceiptStatus.BLOCKED:
            operator_visible_summary = f"{capability_name} blocked at {family}."
        else:
            operator_visible_summary = f"{capability_name} errored at {family}."
    try:
        created_at = utc_now_iso()
        unique_suffix = str(time.time_ns())
        receipt = ActionReceipt(
            receipt_id=(
                f"ar:compositor:{receipt_token(rid)}:{receipt_token(family)}:"
                f"{status.value}:{unique_suffix}"
            ),
            created_at=created_at,
            request_id=rid,
            capability_name=capability_name,
            requested_action=requested_action,
            status=status,
            target_aperture=target_aperture,
            wcs_refs=wcs_refs,
            command_ref=command_ref,
            applied_refs=applied,
            blocked_reasons=blockers,
            error_refs=errors,
            authority_ceiling=AuthorityCeiling.NO_CLAIM,
            learning_update_allowed=False,
            structural_reflex=structural_reflex,
            readback_required=True,
            operator_visible_summary=operator_visible_summary,
        )
    except Exception:
        log.warning("action receipt construction failed", exc_info=True)
        return None
    append_action_receipt(receipt, path=path)
    return receipt


__all__ = [
    "DEFAULT_ACTION_RECEIPTS_JSONL",
    "append_action_receipt",
    "emit_action_receipt",
    "receipt_token",
    "utc_now_iso",
]
