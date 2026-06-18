"""CLI entrypoint for the credential watch + auto-prep daemon.

  uv run python -m agents.hapax_cred_monitor          # one-shot tick
  uv run python -m agents.hapax_cred_monitor --once   # explicit one-shot
  uv run python -m agents.hapax_cred_monitor --report # print JSON to stdout

The systemd timer fires the default one-shot mode every five minutes.
The CLI never prints or accepts secret values; it operates exclusively
on entry names and pre-canned remediation strings.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .expiry_probe import collect_expiry_statuses, route_expiry_alerts
from .monitor import DEFAULT_PASS_STORE, compute_delta, walk_pass_store
from .unblocker_report import (
    DEFAULT_CACHE_DIR,
    append_delta_log,
    build_report,
    load_prior_snapshot,
    write_report,
)

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("HAPAX_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(
        prog="agents.hapax_cred_monitor",
        description="Snapshot pass entry names; emit operator-unblocker report.",
    )
    parser.add_argument(
        "--store",
        type=Path,
        default=DEFAULT_PASS_STORE,
        help="Pass store directory (default: ~/.password-store)",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help="State file directory (default: ~/.cache/hapax)",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print JSON report to stdout instead of writing the state file",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single tick and exit (default behavior; flag accepted for systemd clarity)",
    )
    parser.add_argument(
        "--no-expiry-probe",
        action="store_true",
        help="Skip the credential-expiry liveness probe (tailscale node key + rclone remotes).",
    )
    args = parser.parse_args(argv)

    snapshot = walk_pass_store(args.store)
    report = build_report(snapshot)

    if args.report:
        sys.stdout.write(report.to_json() + "\n")
        return 0

    prior = load_prior_snapshot(args.cache_dir)
    if prior is not None:
        delta = compute_delta(prior, snapshot)
        append_delta_log(delta, snapshot.captured_at, args.cache_dir)

    write_report(report, args.cache_dir)

    # Credential-expiry watchdog: alert via the governed P0 intake BEFORE a token dies
    # (the gdrive OAuth refresh token, the Tailscale node key). Best-effort -- a probe
    # failure must never break the name-snapshot tick. The intake coalesces by fingerprint.
    if not args.no_expiry_probe:
        try:
            routed = route_expiry_alerts(collect_expiry_statuses())
            if routed:
                log.info("credential-expiry watchdog routed alerts: %s", ", ".join(routed))
        except Exception:  # noqa: BLE001 - the snapshot tick must survive any probe error
            log.warning("credential-expiry probe failed", exc_info=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
