"""Session conductor CLI entry point.

Usage:
    uv run python -m agents.session_conductor start [--role alpha|beta]
    uv run python -m agents.session_conductor stop
    uv run python -m agents.session_conductor status
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

PID_DIR = Path.home() / ".cache" / "hapax" / "conductor"
STATE_DIR = Path("/dev/shm")
SOCK_DIR = Path(f"/run/user/{os.getuid()}")

PARENT_WATCHDOG_INTERVAL = 30  # seconds


def _pid_file(role: str) -> Path:
    return PID_DIR / f"conductor-{role}.pid"


def _state_file(role: str) -> Path:
    return STATE_DIR / f"conductor-{role}-state.json"


def _sock_path(role: str) -> Path:
    return SOCK_DIR / f"conductor-{role}.sock"


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------


def cmd_start(args: argparse.Namespace) -> None:
    from shared.log_setup import configure_logging

    configure_logging(agent=f"session-conductor-{args.role}")

    from agents.session_conductor.protocol import ConductorServer
    from agents.session_conductor.rules import RuleRegistry
    from agents.session_conductor.rules.convergence import ConvergenceRule
    from agents.session_conductor.rules.epic import EpicRule
    from agents.session_conductor.rules.focus import FocusRule
    from agents.session_conductor.rules.relay import RelayRule
    from agents.session_conductor.rules.smoke import SmokeRule
    from agents.session_conductor.rules.spawn import SpawnRule
    from agents.session_conductor.state import SessionState
    from agents.session_conductor.topology import load_topology

    topology = load_topology()

    state = SessionState(
        session_id=f"{args.role}-{os.getpid()}",
        pid=os.getpid(),
        started_at=datetime.now(),
    )

    registry = RuleRegistry()
    registry.register(FocusRule(topology))
    registry.register(ConvergenceRule(topology))
    registry.register(EpicRule(topology, state))
    registry.register(RelayRule(topology, state, role=args.role))
    registry.register(SmokeRule(topology, state))
    registry.register(SpawnRule(topology, state))

    state_path = _state_file(args.role)
    sock_path = _sock_path(args.role)

    server = ConductorServer(
        state=state,
        registry=registry,
        state_path=state_path,
        sock_path=sock_path,
    )

    # Write PID file
    PID_DIR.mkdir(parents=True, exist_ok=True)
    pid_file = _pid_file(args.role)
    pid_file.write_text(str(os.getpid()))
    log.info("Session conductor started (role=%s, pid=%d)", args.role, os.getpid())

    loop = asyncio.new_event_loop()

    def _handle_sigterm(signum: int, frame: object) -> None:
        log.info("Received signal %d — shutting down", signum)
        # Write final relay status if relay rule exists
        for rule in registry._rules:
            if hasattr(rule, "write_final_status"):
                rule.write_final_status()  # type: ignore[attr-defined]
        server.shutdown()

    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)

    parent_pid = os.getppid()

    async def _watchdog() -> None:
        """Shutdown if parent process dies."""
        while True:
            await asyncio.sleep(PARENT_WATCHDOG_INTERVAL)
            try:
                os.kill(parent_pid, 0)  # Signal 0 checks existence
            except ProcessLookupError:
                log.warning("Parent process %d gone — shutting down", parent_pid)
                server.shutdown()
                return

    async def _main() -> None:
        asyncio.create_task(_watchdog())
        await server.start()

    try:
        loop.run_until_complete(_main())
    finally:
        # Cleanup
        try:
            pid_file.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            sock_path.unlink(missing_ok=True)
        except OSError:
            pass
        loop.close()


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------


def cmd_stop(args: argparse.Namespace) -> None:
    pid_file = _pid_file(args.role)
    if not pid_file.exists():
        print(f"No PID file found for role '{args.role}' at {pid_file}", file=sys.stderr)
        sys.exit(1)

    pid_str = pid_file.read_text().strip()
    try:
        pid = int(pid_str)
    except ValueError:
        print(f"Invalid PID in file: {pid_str!r}", file=sys.stderr)
        sys.exit(1)

    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to conductor pid {pid}")
    except ProcessLookupError:
        print(f"Process {pid} not found (already dead?)", file=sys.stderr)
        pid_file.unlink(missing_ok=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def cmd_status(args: argparse.Namespace) -> None:
    state_path = _state_file(args.role)
    if not state_path.exists():
        print(json.dumps({"error": f"No state file at {state_path}"}))
        sys.exit(1)

    try:
        raw = json.loads(state_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    summary = {
        "session_id": raw.get("session_id"),
        "pid": raw.get("pid"),
        "started_at": raw.get("started_at"),
        "epic_phase": raw.get("epic_phase"),
        "smoke_test_active": raw.get("smoke_test_active"),
        "in_flight_files": raw.get("in_flight_files", []),
        "children_count": len(raw.get("children", [])),
        "last_relay_sync": raw.get("last_relay_sync"),
    }
    print(json.dumps(summary, indent=2))


# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m agents.session_conductor",
        description="Session conductor — multi-session coordination and rule enforcement.",
    )
    parser.add_argument(
        "--role",
        default="alpha",
        choices=["alpha", "beta"],
        help="Session role (default: alpha)",
    )

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    sub.add_parser("start", help="Start the conductor daemon")
    sub.add_parser("stop", help="Stop the conductor daemon (send SIGTERM)")
    sub.add_parser("status", help="Print JSON status summary from /dev/shm")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "start": cmd_start,
        "stop": cmd_stop,
        "status": cmd_status,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
