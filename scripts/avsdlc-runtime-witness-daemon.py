#!/usr/bin/env python3
"""avsdlc-runtime-witness-daemon — the AVSDLC CI-analogue for live AV.

An INDEPENDENT, always-on observer (NOT an ExecStartPre on any broadcast unit —
a fail-closed gate at the live darkplaces restart would crash-loop air, since
the asset install runs inside ``hapax-darkplaces-v4l2.service`` ExecStart with
``Restart=always``). It periodically runs ``screwm-cns-witness --emit-receipt``,
which signs a per-content-hash :class:`AVWitnessReceipt` over the deployed
gamedir bytes (a genuine PASS requires OBS MOVING). The release gate VERIFIES
those receipts; this daemon is the only legitimate minter.

On a GREEN->RED transition it raises a P0 (ntfy) and writes a RED state file so
a regression on air is observable even though notify-failure@ is neutered and
the hardware watchdog is disarmed. Exit-code contract of the witness: 0 = PASS,
2 = FAIL (freeze / stale producer / causality break).
"""

from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

WITNESS = Path(__file__).resolve().parent / "screwm-cns-witness.py"
DEFAULT_STATE = Path.home() / ".cache/hapax/avsdlc/runtime-witness-state.json"

_RUNNING = True


def _stop(_signum: int, _frame: object) -> None:
    global _RUNNING
    _RUNNING = False


def _notify_p0(title: str, body: str) -> None:
    """Best-effort P0 — never let a notification failure crash the daemon."""
    try:
        from shared.notify import notify  # type: ignore[import-not-found]

        notify(title, body, priority="urgent", tags="rotating_light")
    except Exception:  # noqa: BLE001 — degrade silently; the state file is the durable signal.
        print(f"P0 (un-notified): {title} — {body}", file=sys.stderr)


def _write_state(path: Path, status: str, exit_code: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "status": status,
                "witness_exit": exit_code,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        ),
        encoding="utf-8",
    )


def run_once(receipt_out: str, label: str, timeout_s: float) -> int:
    """Run the witness with --emit-receipt; return its exit code (3 on launch error)."""
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(WITNESS),
                "--label",
                label,
                "--emit-receipt",
                "--receipt-out",
                receipt_out,
            ],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        if proc.stdout:
            print(proc.stdout, end="")
        # Forward stderr on ANY non-zero exit — including a RED (2), so the
        # witness's own explanation is not dropped when investigating a page.
        if proc.returncode != 0 and proc.stderr:
            print(proc.stderr, file=sys.stderr, end="")
        return proc.returncode
    except subprocess.TimeoutExpired:
        print("witness timed out", file=sys.stderr)
        return 3
    except Exception as e:  # noqa: BLE001 — a launch failure is infra, not a RED verdict.
        print(f"witness launch failed: {e}", file=sys.stderr)
        return 3


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=120.0, help="Seconds between observations.")
    ap.add_argument("--timeout", type=float, default=90.0, help="Per-run witness timeout.")
    ap.add_argument(
        "--receipt-out",
        default=str(Path.home() / ".cache/hapax/avsdlc/runtime-witness-receipt.json"),
    )
    ap.add_argument("--state", default=str(DEFAULT_STATE))
    ap.add_argument("--once", action="store_true", help="Run a single observation and exit.")
    args = ap.parse_args(argv)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    state_path = Path(args.state)
    last_status = "UNKNOWN"
    blind_streak = 0
    blind_threshold = 3

    while _RUNNING:
        code = run_once(args.receipt_out, "runtime-daemon", args.timeout)
        # exit 2 = witness FAIL (freeze/stale/culprit). 3 = launch/infra error
        # (advisory, not a RED air verdict). 0 = PASS.
        if code == 0:
            status = "GREEN"
        elif code == 2:
            status = "RED"
        else:
            status = "INFRA"

        if status == "INFRA":
            # A witness that cannot observe is not "green" — a prolonged blind
            # spell around a live broadcast is itself P0-worthy. Escalate once,
            # rather than silently inheriting a stale past status.
            blind_streak += 1
            if blind_streak == blind_threshold:
                _write_state(state_path, "BLIND", code)
                _notify_p0(
                    "AVSDLC runtime witness: BLIND",
                    f"witness could not observe for {blind_streak} consecutive cycles "
                    f"(exit {code}) — live AV is currently unwitnessed.",
                )
        else:
            blind_streak = 0
            _write_state(state_path, status, code)
            if status == "RED" and last_status != "RED":
                _notify_p0(
                    "AVSDLC runtime witness: RED on air",
                    f"screwm-cns-witness FAIL (exit {code}) — live AV regression "
                    f"(freeze / stale producer / causality break).",
                )
            last_status = status

        if args.once:
            return 0 if status == "GREEN" else (2 if status == "RED" else 3)
        # interruptible sleep
        slept = 0.0
        while _RUNNING and slept < args.interval:
            time.sleep(min(2.0, args.interval - slept))
            slept += 2.0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
