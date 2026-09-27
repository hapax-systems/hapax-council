"""Check every Codex turn_context against a declared execution descriptor.

Fresh local headless runs bind a frozen declaration in execution_observer and
are rechecked by the methodology dispatch result reader. Other callers can use
check_turn_context; their integration is not implied. Native reports are not
provider truth. The CLI emits each turn, including interactive model changes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterator, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from shared.capability_execution import ExecutionIdentityError, resolve_execution_descriptor
from shared.platform_capability_registry import ExecutionDescriptor


def check_turn_context(
    descriptor: ExecutionDescriptor, payload: Mapping[str, Any], *, route_id: str
) -> dict[str, Any]:
    declared = {"model": str(descriptor.model_id), "effort": str(descriptor.effort)}
    observed = {"model": payload.get("model"), "effort": payload.get("effort")}
    # Missing evidence on one axis must not erase a mismatch observed on another.
    if any(value is not None and value != declared[axis] for axis, value in observed.items()):
        status = "misattributed"
    elif any(value is None for value in observed.values()):
        status = "unverified"
    else:
        status = "matched"
    return {
        "schema": "hapax.codex_execution_identity.v1",
        "route_id": route_id,
        "turn_id": payload.get("turn_id"),
        "status": status,
        "declared": declared,
        "observed": observed,
    }


def check_rollout(
    path: Path, descriptor: ExecutionDescriptor, *, route_id: str
) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError(f"invalid rollout event at line {line_number}")
            if event.get("type") != "turn_context":
                continue
            if not isinstance(event.get("payload"), dict):
                raise ValueError(f"invalid turn_context at line {line_number}")
            receipt = check_turn_context(descriptor, event["payload"], route_id=route_id)
            receipt.update(rollout=str(path), line=line_number, timestamp=event.get("timestamp"))
            yield receipt


def observe_codex_run_identity(
    descriptor: ExecutionDescriptor,
    *,
    route_id: str,
    session_id: str | None,
    native_home: Path,
    workdir: Path,
    launch_started_at: str,
    expected_rollout: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Correlate one fresh local run with its immutable launch declaration.

    This observes native reports, not provider truth or work acceptance. A
    resumed/remote run requires a different observation boundary. Replay pins
    the original byte prefix, so a later append cannot rewrite the earlier run.
    Registry state is deliberately not reloaded here.
    """
    native_home, workdir = native_home.resolve(), workdir.resolve()
    result: dict[str, Any] = {
        "scope": "fresh_local_codex_headless",
        "route_id": route_id,
        "session_id": session_id,
        "declared": descriptor.model_dump(mode="json"),
        "native_home": str(native_home),
        "workdir": str(workdir),
        "launch_started_at": launch_started_at,
        "status": "unverified",
        "turns": [],
        "rollout": None,
        "reason_codes": [],
        "may_authorize": False,
    }

    def refuse(reason: str) -> dict[str, Any]:
        result["reason_codes"] = [reason]
        return result

    def timestamp(value: Any) -> datetime:
        if not isinstance(value, str):
            raise ValueError("missing native timestamp")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("native timestamp has no timezone")
        return parsed

    def unique_object(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate native JSON key")
            obj[key] = value
        return obj

    try:
        if not isinstance(session_id, str) or str(UUID(session_id)) != session_id:
            return refuse("native_session_identity_unavailable")
    except ValueError:
        return refuse("native_session_identity_unavailable")
    try:
        started = timestamp(launch_started_at)
    except ValueError:
        return refuse("native_launch_time_unavailable")
    try:
        sessions = native_home / "sessions"
        candidates = list(sessions.glob(f"*/*/*/rollout-*-{session_id}.jsonl"))
        if len(candidates) != 1:
            return refuse(
                "native_rollout_ambiguous" if candidates else "native_rollout_unavailable"
            )
        path = candidates[0]
        if not path.resolve().is_relative_to(sessions.resolve()):
            return refuse("native_rollout_outside_session_store")
        if expected_rollout is not None:
            size = expected_rollout.get("bytes")
            if (
                expected_rollout.get("path") != str(path)
                or type(size) is not int
                or size <= 0
                or size > path.stat().st_size
            ):
                return refuse("native_rollout_reference_mismatch")
            with path.open("rb") as stream:
                body = stream.read(size)
        else:
            body = path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if expected_rollout is not None and expected_rollout.get("sha256") != digest:
            return refuse("native_rollout_hash_mismatch")
        result["rollout"] = {"path": str(path), "bytes": len(body), "sha256": digest}
    except (OSError, ValueError):
        return refuse("native_rollout_unavailable")

    records = []
    malformed = not body.endswith(b"\n")
    for line in body.splitlines():
        try:
            record = json.loads(line, object_pairs_hook=unique_object)
            if not isinstance(record, dict):
                raise ValueError("native event is not an object")
            records.append(record)
        except (ValueError, UnicodeError):
            malformed = True
    metadata = [r for r in records if r.get("type") == "session_meta"]
    if len(metadata) != 1:
        return refuse("native_rollout_session_metadata_ambiguous")
    meta = metadata[0]
    payload = meta.get("payload")
    if not isinstance(payload, dict) or payload.get("id") != session_id:
        return refuse("native_rollout_session_mismatch")
    try:
        if (
            not isinstance(payload.get("cwd"), str)
            or Path(payload["cwd"]).resolve() != workdir.resolve()
        ):
            return refuse("native_rollout_workdir_mismatch")
        if timestamp(meta.get("timestamp")) < started:
            return refuse("native_rollout_predates_launch")
    except (ValueError, OSError):
        return refuse("native_rollout_malformed")

    for record in records:
        if record.get("type") != "turn_context":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            malformed = True
            continue
        try:
            if timestamp(record.get("timestamp")) < started:
                if "native_turn_predates_launch" not in result["reason_codes"]:
                    result["reason_codes"].append("native_turn_predates_launch")
                continue
        except ValueError:
            malformed = True
            continue
        result["turns"].append(check_turn_context(descriptor, payload, route_id=route_id))
    if malformed:
        result["reason_codes"].append("native_rollout_malformed")
    if not result["turns"]:
        result["reason_codes"].append("native_turn_context_absent")
    if any(turn["status"] == "misattributed" for turn in result["turns"]):
        result["status"] = "misattributed"
    elif not result["reason_codes"] and all(
        turn["status"] == "matched" for turn in result["turns"]
    ):
        result["status"] = "matched"
    else:
        result["reason_codes"].append("native_execution_identity_unverified")
    return result


def recheck_codex_run_identity(
    reported: Any, *, session_id: str | None, owned_native_process: bool
) -> dict[str, Any]:
    """Recompute a result receipt's native claims without reloading registry state.

    The saved declaration and ownership remain producer claims. Native bytes
    corroborate their reported identity; they confer no acceptance or authority.
    Missing original evidence stays unverified even if a rollout appears later.
    """

    def unverified(reason: str) -> dict[str, Any]:
        return {"status": "unverified", "reason_codes": [reason], "may_authorize": False}

    if not owned_native_process:
        return unverified("remote_native_identity_unobserved")
    if not isinstance(reported, dict) or not isinstance(reported.get("rollout"), dict):
        return unverified("native_identity_evidence_unavailable")
    if reported.get("session_id") != session_id:
        return unverified("native_identity_session_mismatch")
    try:
        descriptor = ExecutionDescriptor.model_validate(reported["declared"])
        if not all(
            isinstance(reported.get(key), str) and reported[key]
            for key in ("route_id", "native_home", "workdir", "launch_started_at")
        ):
            return unverified("native_identity_binding_invalid")
        native_home, workdir = Path(reported["native_home"]), Path(reported["workdir"])
        if not native_home.is_absolute() or not workdir.is_absolute():
            return unverified("native_identity_binding_invalid")
        recomputed = observe_codex_run_identity(
            descriptor,
            route_id=reported["route_id"],
            session_id=session_id,
            native_home=native_home,
            workdir=workdir,
            launch_started_at=reported["launch_started_at"],
            expected_rollout=reported["rollout"],
        )
        # JSON comparison retains type distinctions such as true versus 1.
        if json.dumps(reported, sort_keys=True, allow_nan=False) != json.dumps(
            recomputed, sort_keys=True, allow_nan=False
        ):
            recomputed["reason_codes"].append("native_identity_receipt_mismatch")
            if recomputed["status"] == "matched":
                recomputed["status"] = "unverified"
        return recomputed
    except (ValueError, KeyError, TypeError, OSError, RuntimeError):
        return unverified("native_identity_binding_invalid")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route", required=True)
    parser.add_argument("--rollout", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        descriptor = resolve_execution_descriptor(args.route)
        seen, matched = False, True
        for receipt in check_rollout(args.rollout, descriptor, route_id=args.route):
            seen = True
            matched = matched and receipt["status"] == "matched"
            print(json.dumps(receipt, sort_keys=True))
        if not seen:
            print(
                "unverified: rollout contains no turn_context; next action: select the owned "
                "native rollout under CODEX_HOME/sessions after a model turn, then retry",
                file=sys.stderr,
            )
        return 0 if seen and matched else 1
    except (ExecutionIdentityError, OSError, ValueError, KeyError) as exc:
        print(
            f"unverified execution receipt: {exc}; next action: verify the route declaration "
            "and readable native rollout under CODEX_HOME/sessions, then retry",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
