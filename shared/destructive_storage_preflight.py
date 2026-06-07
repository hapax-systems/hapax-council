"""Fail-closed destructive-storage preflight.

The preflight is a witness/gate, never an actuator. It refuses to pass unless a
fresh, same-host storage receipt and a narrow WipeAuth agree on target host,
machine anchor, serial, by-id, filesystem UUID, PARTUUID, mountpoint, and SMART
state. A PASS is permission to continue a separately authorized manual workflow;
this module never formats, mounts, wipes, or edits devices.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from shared.host_storage_inventory import collect


class SmartHealth(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class PreflightDecision(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class ApprovedAgainst(BaseModel):
    fs_uuid: str
    by_id: str
    partuuid: str
    mountpoint: str


class WipeAuth(BaseModel):
    """Operator-minted authorization token. Values are identifiers, not secrets."""

    target_host: str
    serial: str
    machine_id: str
    approved_against: ApprovedAgainst
    expires_at: datetime
    approval_ref: str | None = None

    @model_validator(mode="after")
    def _expires_at_is_aware(self) -> WipeAuth:
        if self.expires_at.tzinfo is None:
            raise ValueError("WipeAuth.expires_at must include a timezone")
        return self


class DestructiveStoragePreflightRequest(BaseModel):
    target_host: str
    serial: str
    wipe_auth: WipeAuth
    live_receipt: dict[str, Any]
    receipt_emitted_at_approval: bool = False
    smart_health: SmartHealth = SmartHealth.UNKNOWN
    smart_override_ref: str | None = None
    registry_edit_in_same_change: bool = False
    now: datetime | None = None


class PreflightFailure(BaseModel):
    predicate: str
    message: str
    next_action: str


class DestructiveStoragePreflightResult(BaseModel):
    decision: PreflightDecision
    target_host: str
    predicates_checked: list[str] = Field(default_factory=list)
    failures: list[PreflightFailure] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.decision == PreflightDecision.PASS


def evaluate_preflight(
    request: DestructiveStoragePreflightRequest,
) -> DestructiveStoragePreflightResult:
    failures: list[PreflightFailure] = []
    checked: list[str] = []

    def check(predicate: str, ok: bool, message: str, next_action: str) -> None:
        checked.append(predicate)
        if not ok:
            failures.append(
                PreflightFailure(
                    predicate=predicate,
                    message=message,
                    next_action=next_action,
                )
            )

    now = request.now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    receipt = request.live_receipt
    witness = receipt.get("evidence_witness") or {}
    auth = request.wipe_auth

    check(
        "mutation_surface_separation",
        not request.registry_edit_in_same_change,
        "registry edit and destructive operation are in the same change",
        "split registry edits and destructive preflight into separate governed changes",
    )
    check(
        "auth_target_matches_request",
        auth.target_host == request.target_host and auth.serial == request.serial,
        "WipeAuth does not match the requested target host and serial",
        "mint a WipeAuth for this exact target host and device identity",
    )
    check(
        "auth_not_expired",
        auth.expires_at > now,
        "WipeAuth is expired",
        "mint a fresh WipeAuth after re-running the live preflight",
    )
    check(
        "receipt_emitted_at_approval",
        request.receipt_emitted_at_approval,
        "receipt was supplied as cached/historical input",
        "run this preflight on the target host so it emits its own live receipt",
    )
    check(
        "live_same_host_local_receipt",
        _is_live_same_host_receipt(receipt, request.target_host),
        "receipt is missing, stale, host-mismatched, non-local, or SSH-only",
        "run the guard locally on the target host and re-emit the receipt",
    )
    check(
        "machine_id_same_channel",
        witness.get("machine_id") == auth.machine_id
        and bool(witness.get("captured_in_same_command"))
        and bool(witness.get("anchor_verified")),
        "machine_id/root anchor did not match the WipeAuth in the same command stream",
        "re-run the preflight locally and mint WipeAuth against the observed machine_id",
    )

    device = _find_device(receipt, request.serial)
    check(
        "serial_present_on_target",
        device is not None,
        "requested serial is not present in the target-host receipt",
        "stop; re-check target host and serial before any destructive action",
    )

    approved_by_id = auth.approved_against.by_id
    check(
        "by_id_is_canonical_device_identity",
        not _weak_by_id_alias(approved_by_id),
        "approved by-id path is an alias class that cannot be the second identifier",
        "use the model/serial by-id path for the target device",
    )
    check(
        "by_id_chain_matches_live_device",
        bool(device) and approved_by_id in set(device.get("by_id") or []),
        "approved by-id path is not present on the live target device",
        "readlink the by-id path on the target host and refresh WipeAuth",
    )

    fs = _find_filesystem(device, auth.approved_against.fs_uuid) if device else None
    check(
        "fs_uuid_bound_to_live_mount",
        fs is not None and auth.approved_against.mountpoint in (fs.get("mountpoints") or []),
        "approved filesystem UUID is not bound to the live receipt's mountpoint",
        "use the live receipt's findmnt/lsblk mount row as the mount authority",
    )
    check(
        "partuuid_anchor_matches",
        bool(fs) and (fs.get("partuuid") or "") == auth.approved_against.partuuid,
        "approved PARTUUID does not match the live filesystem row",
        "refresh the live receipt and mint WipeAuth against the observed PARTUUID",
    )
    check(
        "two_identifier_subsystems",
        bool(device)
        and bool(fs)
        and bool(request.serial)
        and bool(approved_by_id)
        and bool(auth.approved_against.fs_uuid)
        and bool(auth.approved_against.partuuid),
        "preflight does not have both device-intrinsic and filesystem identifiers",
        "provide serial/by-id plus fs UUID/PARTUUID/mountpoint from the live receipt",
    )
    check(
        "smart_health_pass_or_override",
        request.smart_health == SmartHealth.PASSED or bool(request.smart_override_ref),
        "SMART health did not pass and no explicit override was supplied",
        "run SMART on the target host or provide a governed override reference",
    )

    return DestructiveStoragePreflightResult(
        decision=PreflightDecision.FAIL if failures else PreflightDecision.PASS,
        target_host=request.target_host,
        predicates_checked=checked,
        failures=failures,
    )


def _is_live_same_host_receipt(receipt: dict[str, Any], target_host: str) -> bool:
    hp = receipt.get("host_provenance") or {}
    return (
        receipt.get("evidence_class") == "live"
        and receipt.get("recency_class") == "live"
        and receipt.get("locality_class") == "same_host"
        and hp.get("transport") == "local"
        and hp.get("intent_host") == target_host
        and hp.get("exec_host") == target_host
        and hp.get("evidence_host") == target_host
        and receipt.get("exit_code") == 0
        and bool((receipt.get("collectors") or {}).get("lsblk", {}).get("ran"))
    )


def _find_device(receipt: dict[str, Any], serial: str) -> dict[str, Any] | None:
    for device in receipt.get("devices") or []:
        if device.get("serial") == serial:
            return device
    return None


def _find_filesystem(device: dict[str, Any] | None, fs_uuid: str) -> dict[str, Any] | None:
    if not device:
        return None
    for fs in device.get("filesystems") or []:
        if fs.get("uuid") == fs_uuid:
            return fs
    return None


_NAMESPACE_ALIAS_RE = re.compile(r"_\\d+$")


def _weak_by_id_alias(by_id: str) -> bool:
    base = Path(by_id).name
    return base.startswith(("eui.", "wwn-")) or bool(_NAMESPACE_ALIAS_RE.search(base))


def _load_json(path: str) -> Any:
    return json.loads(Path(path).read_text())


def _build_request_from_args(args: argparse.Namespace) -> DestructiveStoragePreflightRequest:
    auth = WipeAuth.model_validate(_load_json(args.wipe_auth_json))
    if args.receipt_json:
        receipt = _load_json(args.receipt_json)
        emitted = bool(args.allow_fixture_receipt)
    else:
        receipt = collect([args.target_host])[args.target_host]
        emitted = True
    return DestructiveStoragePreflightRequest(
        target_host=args.target_host,
        serial=args.serial,
        wipe_auth=auth,
        live_receipt=receipt,
        receipt_emitted_at_approval=emitted,
        smart_health=SmartHealth(args.smart_health),
        smart_override_ref=args.smart_override_ref,
        registry_edit_in_same_change=args.registry_edit_in_same_change,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed destructive storage preflight witness (never actuator)."
    )
    parser.add_argument("--target-host", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--wipe-auth-json", required=True)
    parser.add_argument("--receipt-json")
    parser.add_argument(
        "--allow-fixture-receipt",
        action="store_true",
        help="Testing only: treat --receipt-json as emitted at approval time.",
    )
    parser.add_argument(
        "--smart-health",
        choices=[s.value for s in SmartHealth],
        default=SmartHealth.UNKNOWN.value,
    )
    parser.add_argument("--smart-override-ref")
    parser.add_argument("--registry-edit-in-same-change", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    try:
        request = _build_request_from_args(args)
        result = evaluate_preflight(request)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        result = DestructiveStoragePreflightResult(
            decision=PreflightDecision.FAIL,
            target_host=args.target_host,
            predicates_checked=["request_parse_or_receipt_emit"],
            failures=[
                PreflightFailure(
                    predicate="request_parse_or_receipt_emit",
                    message=type(exc).__name__,
                    next_action="fix request JSON or run the guard on the target host",
                )
            ],
        )

    payload = result.model_dump(mode="json")
    print(json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if result.passed else 2


_PYDANTIC_VALIDATORS = (WipeAuth._expires_at_is_aware,)


__all__ = [
    "ApprovedAgainst",
    "DestructiveStoragePreflightRequest",
    "DestructiveStoragePreflightResult",
    "PreflightDecision",
    "PreflightFailure",
    "SmartHealth",
    "WipeAuth",
    "evaluate_preflight",
    "main",
]
