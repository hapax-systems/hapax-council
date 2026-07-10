#!/usr/bin/python3
"""Record and notify Hapax UPS power events from apcupsd hooks."""

from __future__ import annotations

import argparse
import errno
import fcntl
import json
import math
import os
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_AUDIT_LOG = "/var/log/hapax/ups-power-events.jsonl"
DEFAULT_NTFY_URL = "http://localhost:8090/hapax-alerts"
DEFAULT_NTFY_TIMEOUT_S = 5.0
DEFAULT_APCACCESS = "/usr/bin/apcaccess"
DEFAULT_APCACCESS_TIMEOUT_S = 3.0
SHUTDOWN_IO_TIMEOUT_S = 1.0

EVENT_TEXT = {
    "onbattery": {
        "title": "UPS transfer to battery - podium",
        "message": (
            "SRT3000XLA reports battery operation. This transfer event does not itself "
            "request host shutdown; apcupsd emits a separate shutdown event below 20% "
            "charge or 5 minutes remaining."
        ),
        "priority": "urgent",
        "shutdown_requested": None,
        "event_requests_shutdown": False,
    },
    "offbattery": {
        "title": "UPS power restored - podium",
        "message": (
            "UPS input restored. This event does not determine whether shutdown was previously "
            "requested."
        ),
        "priority": "default",
        "shutdown_requested": None,
        "event_requests_shutdown": None,
    },
    "doshutdown": {
        "title": "UPS REQUESTED HOST SHUTDOWN - podium",
        "message": (
            "apcupsd crossed a configured battery threshold and is requesting host shutdown now."
        ),
        "priority": "max",
        "shutdown_requested": True,
        "event_requests_shutdown": True,
    },
}

APC_MESSAGE_FIELDS = ("STATUS", "BCHARGE", "TIMELEFT", "TONBATT", "NUMXFERS", "LINEV")


@dataclass
class Delivery:
    attempted: bool
    ok: bool
    status: int | None = None
    error: str = ""


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def positive_finite_timeout(value: str | float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("timeout must be a positive finite number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("timeout must be a positive finite number")
    return parsed


def ntfy_timeout_default() -> float:
    try:
        return positive_finite_timeout(os.environ.get("HAPAX_UPS_NTFY_TIMEOUT", "5"))
    except argparse.ArgumentTypeError:
        return DEFAULT_NTFY_TIMEOUT_S


def redact_ntfy_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return "invalid-destination"
    if not parsed.scheme or not hostname:
        return "invalid-destination"
    safe_host = f"[{hostname}]" if ":" in hostname else hostname
    safe_netloc = f"{safe_host}:{port}" if port is not None else safe_host
    return urllib.parse.urlunsplit((parsed.scheme, safe_netloc, "", "", ""))


def redact_delivery_error(url: str, exc: BaseException) -> str:
    rendered = f"{type(exc).__name__}: {exc}"
    return rendered.replace(url, redact_ntfy_url(url)) if url else rendered


def parse_apcaccess(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        out[key.strip()] = value.strip()
    return out


def read_apcaccess(
    path: str, *, timeout_s: float = DEFAULT_APCACCESS_TIMEOUT_S
) -> tuple[dict[str, str], str]:
    if not path:
        return {}, "disabled"
    try:
        proc = subprocess.run(
            [path, "status"], capture_output=True, text=True, timeout=timeout_s, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {}, f"{type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        return {}, (proc.stderr or proc.stdout).strip() or f"rc={proc.returncode}"
    return parse_apcaccess(proc.stdout), ""


def format_ntfy_message(base_message: str, apc: dict[str, str], recorded_at: str) -> str:
    fields = [f"{key}={apc[key]}" for key in APC_MESSAGE_FIELDS if apc.get(key)]
    telemetry = ", ".join(fields) if fields else "apcaccess=unavailable"
    return f"{base_message}\nobserved_at={recorded_at}\n{telemetry}"


def post_ntfy(url: str, title: str, message: str, priority: str, timeout_s: float) -> Delivery:
    if not url:
        return Delivery(attempted=False, ok=False, error="ntfy disabled")
    try:
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
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return Delivery(attempted=True, ok=200 <= resp.status < 300, status=resp.status)
    except urllib.error.HTTPError as exc:
        return Delivery(
            attempted=True,
            ok=False,
            status=exc.code,
            error=redact_delivery_error(url, exc),
        )
    except (OSError, ValueError, OverflowError) as exc:
        return Delivery(attempted=True, ok=False, error=redact_delivery_error(url, exc))


def append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(
        path,
        os.O_APPEND | os.O_CLOEXEC | os.O_CREAT | os.O_NOFOLLOW | os.O_WRONLY,
        0o640,
    )
    try:
        inode = os.fstat(fd)
        # Production apcupsd hooks run as root; non-root ownership supports
        # unprivileged dry-runs and the isolated regression suite.
        expected_uid = os.geteuid()
        if not stat.S_ISREG(inode.st_mode) or inode.st_uid != expected_uid or inode.st_nlink != 1:
            raise OSError(
                errno.EPERM,
                "unsafe UPS audit log inode; expected one regular file owned by the hook uid",
                path,
            )
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, blob)
    finally:
        os.close(fd)


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
    parser.add_argument("--timeout", type=positive_finite_timeout, default=ntfy_timeout_default())
    parser.add_argument("--no-ntfy", action="store_true", help="record only; do not send ntfy")
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args, extra_args = parser.parse_known_args(argv)
    unknown_options = [arg for arg in extra_args if arg.startswith("-")]
    if unknown_options:
        parser.error(f"unrecognized arguments: {' '.join(unknown_options)}")
    args.apcupsd_args.extend(extra_args)
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    text = EVENT_TEXT[args.event]
    io_timeout_s = (
        min(args.timeout, SHUTDOWN_IO_TIMEOUT_S) if args.event == "doshutdown" else args.timeout
    )
    apcaccess_timeout_s = (
        SHUTDOWN_IO_TIMEOUT_S if args.event == "doshutdown" else DEFAULT_APCACCESS_TIMEOUT_S
    )
    apc, apc_error = read_apcaccess(args.apcaccess, timeout_s=apcaccess_timeout_s)
    observed_at = utc_now()
    message = format_ntfy_message(text["message"], apc, observed_at)
    base_record = {
        "schema": "hapax.ups_power_event.v1",
        "event": args.event,
        "apcupsd_args": args.apcupsd_args,
        "title": text["title"],
        "message": message,
        "priority": text["priority"],
        "policy_owner": "apcupsd",
        "shutdown_requested": text["shutdown_requested"],
        "event_requests_shutdown": text["event_requests_shutdown"],
        "ntfy_url": redact_ntfy_url(args.ntfy_url),
        "apcaccess": apc,
        "apcaccess_error": apc_error,
        "apcaccess_timeout_s": apcaccess_timeout_s,
        "notification_timeout_s": io_timeout_s,
        "pid": os.getpid(),
        "observed_at": observed_at,
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
        message,
        text["priority"],
        io_timeout_s,
    )
    if delivery.attempted and not delivery.ok:
        print(
            "hapax-power-event: UPS notification delivery failed: "
            f"{delivery.error}; next action: verify the local ntfy service and endpoint, then rerun "
            "scripts/install-apcupsd-power-alerts --install --verify-live",
            file=sys.stderr,
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
