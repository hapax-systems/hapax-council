"""Session conductor CLI entry point.

Usage:
    uv run python -m agents.session_conductor start [--role alpha|beta|cx-red]
    uv run python -m agents.session_conductor stop
    uv run python -m agents.session_conductor status
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import logging
import os
import signal
import sys
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from agents.session_conductor.lifecycle import ProcessIdentity, process_identity, watch_owner

log = logging.getLogger(__name__)

PID_DIR = Path.home() / ".cache" / "hapax" / "conductor"
STATE_DIR = Path("/dev/shm")
SOCK_DIR = Path(f"/run/user/{os.getuid()}")

PARENT_WATCHDOG_INTERVAL = 1  # seconds; bounded cleanup after the native lane exits


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
    # Keep the lock inode: unlinking it permits a second writer to lock a new one.
    # It covers PID/socket/state and relay writes, including final shutdown.
    PID_DIR.mkdir(parents=True, exist_ok=True)
    with (PID_DIR / f"conductor-{args.role}.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log.info("Conductor already owns role %s; leaving it untouched", args.role)
            return
        _run_conductor(args)


def _run_conductor(args: argparse.Namespace) -> None:
    if (args.owner_pid is None) != (args.owner_start_ticks is None):
        raise ValueError("owner-pid and owner-start-ticks must be supplied together")
    if args.owner_pid is not None:
        owner = ProcessIdentity(args.owner_pid, args.owner_start_ticks)
    elif os.environ.get("HAPAX_AGENT_INTERFACE") == "codex":
        raise ValueError("Codex conductor requires an observed native process owner")
    else:
        owner = process_identity(os.getppid())
    if owner is None or process_identity(owner.pid) != owner:
        raise ValueError("conductor owner is gone or unobserved; no sidecar started")

    from agents._log_setup import configure_logging

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
        session_id=args.session_id or f"conductor-{args.role}-{os.getpid()}",
        session_id_kind=args.session_id_kind if args.session_id else "conductor",
        native_session_id=args.native_session_id,
        owner_pid=owner.pid,
        owner_start_ticks=owner.start_ticks,
        pid=os.getpid(),
        started_at=datetime.now(UTC),
    )

    registry = RuleRegistry()
    registry.register(FocusRule(topology))
    registry.register(ConvergenceRule(topology, state=state))
    registry.register(EpicRule(topology, state))
    registry.register(RelayRule(topology, state, role=args.role))
    registry.register(SmokeRule(topology, state))
    spawn_rule = SpawnRule(topology, state)
    registry.register(spawn_rule)

    # C2: a child claims only the manifest its launcher named (M103: never "any pending").
    claimed = spawn_rule.claim_pending_manifest(
        state, manifest_id=os.environ.get("HAPAX_CONDUCTOR_SPAWN_MANIFEST")
    )
    if claimed:
        log.info("Claimed spawn manifest: topic=%s", claimed.get("topic", "unknown"))

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
    stop_requested = False

    def _handle_sigterm(signum: int, frame: object) -> None:
        nonlocal stop_requested
        log.info("Received signal %d — shutting down", signum)
        stop_requested = True
        server.shutdown()

    previous_term = signal.signal(signal.SIGTERM, _handle_sigterm)
    previous_int = signal.signal(signal.SIGINT, _handle_sigterm)

    async def _main() -> None:
        if stop_requested:
            return
        watcher = asyncio.create_task(
            watch_owner(owner, server.shutdown, interval=PARENT_WATCHDOG_INTERVAL)
        )
        try:
            await server.start()
        finally:
            watcher.cancel()
            with suppress(asyncio.CancelledError):
                await watcher

    try:
        loop.run_until_complete(_main())
    finally:
        # Every exit path, including owner death, publishes the same final state.
        for rule in registry._rules:
            if hasattr(rule, "write_final_status"):
                rule.write_final_status()  # type: ignore[attr-defined]
            if hasattr(rule, "write_completion"):
                summary = state.workstream_summary or "Session ended"
                rule.write_completion(summary)  # type: ignore[attr-defined]
            if hasattr(rule, "retire_pending_children"):
                rule.retire_pending_children()  # type: ignore[attr-defined]
        try:
            state.save(state_path)
        except OSError:
            log.exception("Failed to save state during shutdown")
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
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)


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
        "session_id_kind": raw.get("session_id_kind", "conductor"),
        "native_session_id": raw.get("native_session_id"),
        "owner_pid": raw.get("owner_pid"),
        "owner_start_ticks": raw.get("owner_start_ticks"),
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
        help="Session identity (default: alpha; Codex uses cx-<color>)",
    )

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    start = sub.add_parser("start", help="Start the conductor daemon")
    start.add_argument("--session-id")
    start.add_argument("--session-id-kind", choices=("lane", "native"), default="native")
    start.add_argument("--native-session-id")
    start.add_argument("--owner-pid", type=int)
    start.add_argument("--owner-start-ticks", type=int)
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
