"""Check every Codex turn_context against a declared execution descriptor.

Integration point: quota telemetry can call check_turn_context when it reads a
turn_context, preserving the returned declared/observed/status with that turn's
spend receipt. Do not infer the served model from a lane name or launcher argv.
The CLI emits JSON for every turn, including changes within interactive sessions.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from shared.capability_execution import ExecutionIdentityError, resolve_execution_descriptor
from shared.platform_capability_registry import ExecutionDescriptor


def check_turn_context(
    descriptor: ExecutionDescriptor, payload: Mapping[str, Any], *, route_id: str
) -> dict[str, Any]:
    declared = {"model": str(descriptor.model_id), "effort": str(descriptor.effort)}
    observed = {"model": payload.get("model"), "effort": payload.get("effort")}
    status = "matched" if observed == declared else "misattributed"
    if any(value is None for value in observed.values()):
        status = "unverified"
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route", required=True)
    parser.add_argument("--rollout", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        descriptor = resolve_execution_descriptor(args.route)
        receipts = list(check_rollout(args.rollout, descriptor, route_id=args.route))
        for receipt in receipts:
            print(json.dumps(receipt, sort_keys=True))
        if not receipts:
            print("unverified: rollout contains no turn_context", file=sys.stderr)
        return 0 if receipts and all(r["status"] == "matched" for r in receipts) else 1
    except (ExecutionIdentityError, OSError, ValueError, KeyError) as exc:
        print(f"unverified execution receipt: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
