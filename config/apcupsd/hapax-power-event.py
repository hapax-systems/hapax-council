#!/usr/bin/env python3
"""Record and notify Hapax UPS power events from apcupsd hooks."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_AUDIT_LOG = "/var/log/hapax/ups-power-events.jsonl"
DEFAULT_NTFY_URL = "http://localhost:8090/hapax-alerts"
DEFAULT_APCACCESS = "/usr/bin/apcaccess"

EVENT_TEXT = {
    "onbattery": {
        "title": "UPS ON BATTERY - podium",
        "message": "SRT3000XLA on battery. apcupsd shuts down at 20%/5min remaining.",
        "priority": "urgent",
    },
    "offbattery": {
        "title": "UPS power restored - podium",
        "message": "Mains back; SRT3000XLA recharging.",
        "priority": "default",
    },
}


@dataclass
class Delivery:
    attempted: bool
    ok: bool
    status: int | None = None
    error: str = ""


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def parse_apcaccess(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        out[key.strip()] = value.strip()
    return out


def read_apcaccess(path: str) -> tuple[dict[str, str], str]:
    if not path:
        return {}, "disabled"
    try:
        proc = subprocess.run(
            [path, "status"], capture_output=True, text=True, timeout=3, check=False
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {}, f"{type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        return {}, (proc.stderr or proc.stdout).strip() or f"rc={proc.returncode}"
    return parse_apcaccess(proc.stdout), ""


def post_ntfy(url: str, title: str, message: str, priority: str, timeout_s: float) -> Delivery:
    if not url:
        return Delivery(attempted=False, ok=True, error="ntfy disabled")
    req = urllib.request.Request(
        url,
        data=message.encode("utf-8"),
        headers={
            "Title": title,
            "Priority": priority,
            "Tags": "warning",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return Delivery(attempted=True, ok=200 <= resp.status < 300, status=resp.status)
    except urllib.error.HTTPError as exc:
        return Delivery(attempted=True, ok=False, status=exc.code, error=str(exc))
    except OSError as exc:
        return Delivery(attempted=True, ok=False, error=f"{type(exc).__name__}: {exc}")


def append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o640)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, sort_keys=True) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event", choices=sorted(EVENT_TEXT))
    parser.add_argument("apcupsd_args", nargs="*", help="arguments passed through by apccontrol")
    parser.add_argument(
        "--audit-log", default=os.environ.get("HAPAX_UPS_AUDIT_LOG", DEFAULT_AUDIT_LOG)
    )
    parser.add_argument(
        "--ntfy-url", default=os.environ.get("HAPAX_UPS_NTFY_URL", DEFAULT_NTFY_URL)
    )
    parser.add_argument(
        "--apcaccess", default=os.environ.get("HAPAX_UPS_APCACCESS", DEFAULT_APCACCESS)
    )
    parser.add_argument(
        "--timeout", type=float, default=float(os.environ.get("HAPAX_UPS_NTFY_TIMEOUT", "5"))
    )
    parser.add_argument("--no-ntfy", action="store_true", help="record only; do not send ntfy")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    text = EVENT_TEXT[args.event]
    apc, apc_error = read_apcaccess(args.apcaccess)
    base_record = {
        "schema": "hapax.ups_power_event.v1",
        "event": args.event,
        "apcupsd_args": args.apcupsd_args,
        "title": text["title"],
        "message": text["message"],
        "priority": text["priority"],
        "ntfy_url": args.ntfy_url,
        "apcaccess": apc,
        "apcaccess_error": apc_error,
        "pid": os.getpid(),
    }
    intent_audit_error = ""
    try:
        append_jsonl(
            Path(args.audit_log),
            {
                **base_record,
                "phase": "intent",
                "recorded_at": utc_now(),
                "monotonic_s": time.monotonic(),
            },
        )
    except OSError as exc:
        intent_audit_error = f"{type(exc).__name__}: {exc}"
        print(
            "hapax-power-event: failed to append intent audit log: "
            f"{exc}; provenance degraded, continuing UPS notification; next action: check /var/log/hapax permissions and rerun "
            "scripts/install-apcupsd-power-alerts --install --verify-live",
            file=sys.stderr,
        )
    delivery = post_ntfy(
        "" if args.no_ntfy else args.ntfy_url,
        text["title"],
        text["message"],
        text["priority"],
        args.timeout,
    )
    record = {
        **base_record,
        "phase": "delivery",
        "recorded_at": utc_now(),
        "delivery": asdict(delivery),
        "provenance_degraded": bool(intent_audit_error),
        "intent_audit_error": intent_audit_error,
        "monotonic_s": time.monotonic(),
    }
    try:
        append_jsonl(Path(args.audit_log), record)
    except OSError as exc:
        print(
            "hapax-power-event: failed to append delivery audit log: "
            f"{exc}; next action: check /var/log/hapax permissions and rerun "
            "scripts/install-apcupsd-power-alerts --install --verify-live",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
