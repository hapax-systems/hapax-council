"""hapax-sentinel — out-of-band health watchdog for the workstation.

Runs on a Pi (typically pi-4) outside the workstation's blast radius.
Polls the workstation logos API every SENTINEL_POLL_INTERVAL_S seconds.
After SENTINEL_FAIL_THRESHOLD consecutive failures, emits an ntfy
notification. Resets on first success.

Type=simple long-running loop. Failures are logged to journal and to
~/hapax-state/sentinel/last-poll.json so the workstation health check
can read the sentinel's view.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

WORKSTATION_URL = os.environ.get("WORKSTATION_URL", "http://hapax-podium.local:8051")
NTFY_URL = os.environ.get("NTFY_URL", "https://ntfy.sh/hapax-alerts")
POLL_INTERVAL_S = int(os.environ.get("SENTINEL_POLL_INTERVAL_S", "300"))
FAIL_THRESHOLD = int(os.environ.get("SENTINEL_FAIL_THRESHOLD", "3"))
TIMEOUT_S = float(os.environ.get("SENTINEL_TIMEOUT_S", "10"))

STATE_DIR = Path.home() / "hapax-state" / "sentinel"
STATE_FILE = STATE_DIR / "last-poll.json"
ALERT_FLAG = STATE_DIR / "alert-active"


def write_state(payload: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(STATE_FILE)


def poll() -> tuple[bool, str]:
    try:
        req = urllib.request.Request(f"{WORKSTATION_URL}/api/health")
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            data = json.loads(resp.read())
        status = data.get("overall_status", "unknown")
        return True, f"workstation responded: {status}"
    except (TimeoutError, urllib.error.URLError, OSError) as e:
        return False, f"workstation unreachable: {e}"


def alert(message: str) -> None:
    try:
        req = urllib.request.Request(
            NTFY_URL,
            data=message.encode("utf-8"),
            headers={"Title": "hapax-sentinel: workstation down", "Priority": "high"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"sentinel: ntfy alert failed: {e}", file=sys.stderr)


def main() -> None:
    consecutive_failures = 0
    print(
        f"sentinel: polling {WORKSTATION_URL} every {POLL_INTERVAL_S}s, "
        f"alert after {FAIL_THRESHOLD} consecutive failures",
        flush=True,
    )
    while True:
        ok, msg = poll()
        ts = time.time()
        if ok:
            if consecutive_failures >= FAIL_THRESHOLD and ALERT_FLAG.exists():
                alert(f"workstation recovered: {msg}")
                ALERT_FLAG.unlink(missing_ok=True)
            consecutive_failures = 0
            print(f"sentinel: ok — {msg}", flush=True)
        else:
            consecutive_failures += 1
            print(
                f"sentinel: FAIL ({consecutive_failures}/{FAIL_THRESHOLD}) — {msg}",
                flush=True,
            )
            if consecutive_failures == FAIL_THRESHOLD:
                alert(
                    f"workstation has failed {FAIL_THRESHOLD} consecutive polls "
                    f"({FAIL_THRESHOLD * POLL_INTERVAL_S}s): {msg}"
                )
                ALERT_FLAG.parent.mkdir(parents=True, exist_ok=True)
                ALERT_FLAG.touch()
        write_state(
            {
                "ts": ts,
                "ok": ok,
                "message": msg,
                "consecutive_failures": consecutive_failures,
                "alert_active": ALERT_FLAG.exists(),
            }
        )
        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()
