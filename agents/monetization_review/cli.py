"""Operator review CLI — present blocks, accept/reject/whitelist.

Tier-3 deterministic. No LLM calls. Reads the flagged-payload store,
shows each record via ``rich`` (or plain text fallback), captures the
operator decision, optionally appends to the whitelist YAML and signals
SIGHUP to running consumers (``logos-api``, ``hapax-daimonion``) so the
gate reloads without restart.

Usage::

    uv run python -m agents.monetization_review              # interactive
    uv run python -m agents.monetization_review --list       # tabular non-interactive
    uv run python -m agents.monetization_review --prune      # 7-day cleanup
    uv run python -m agents.monetization_review --signal-reload  # SIGHUP daemons + exit
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import signal
import subprocess
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final

from agents.monetization_review.flagged_store import (
    DEFAULT_FLAGGED_DIR,
    DEFAULT_RETENTION_DAYS,
    FlaggedRecord,
    FlaggedStore,
)
from agents.monetization_review.whitelist import (
    DEFAULT_WHITELIST_PATH,
    EMPTY_WHITELIST_TEMPLATE,
    Whitelist,
)

log = logging.getLogger(__name__)

# Daemons that load the whitelist; SIGHUP triggers their re-read.
RELOAD_DAEMONS: Final[tuple[str, ...]] = (
    "hapax-logos-api.service",
    "hapax-daimonion.service",
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="monetization_review",
        description="Operator review of de-monetization-blocked payloads.",
    )
    p.add_argument(
        "--flagged-dir",
        type=Path,
        default=DEFAULT_FLAGGED_DIR,
        help=f"Flagged-payload root (default: {DEFAULT_FLAGGED_DIR})",
    )
    p.add_argument(
        "--whitelist",
        type=Path,
        default=DEFAULT_WHITELIST_PATH,
        help=f"Whitelist YAML path (default: {DEFAULT_WHITELIST_PATH})",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="Print tabular summary of flagged payloads, no prompts.",
    )
    p.add_argument(
        "--prune",
        action="store_true",
        help=f"Delete flagged-payload directories older than {DEFAULT_RETENTION_DAYS} days.",
    )
    p.add_argument(
        "--retention-days",
        type=int,
        default=DEFAULT_RETENTION_DAYS,
        help=f"Days to retain flagged payloads (default: {DEFAULT_RETENTION_DAYS}).",
    )
    p.add_argument(
        "--signal-reload",
        action="store_true",
        help="SIGHUP whitelist-loading daemons and exit (no review prompts).",
    )
    p.add_argument(
        "--no-reload",
        action="store_true",
        help="Skip the SIGHUP step after whitelist edits (CLI exits faster in tests).",
    )
    p.add_argument(
        "--no-color",
        action="store_true",
        help="Disable rich colors / use plain print fallback.",
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.signal_reload:
        _signal_reload()
        return 0

    store = FlaggedStore(root=args.flagged_dir)

    if args.prune:
        removed = store.prune(retention_days=args.retention_days)
        print(f"Pruned {len(removed)} expired date directories.")
        for path in removed:
            print(f"  removed: {path}")
        return 0

    records = store.iter_records()
    _ensure_whitelist_template(args.whitelist)

    if args.list:
        _print_table(records, no_color=args.no_color)
        return 0

    return _interactive_review(records, args.whitelist, args.no_color, args.no_reload)


def _ensure_whitelist_template(path: Path) -> None:
    """Drop a commented empty template if the whitelist file does not exist.

    Operator-friendly: first run shows them what the schema looks like
    even if no whitelist edits happen. Idempotent — never overwrites.
    """
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(EMPTY_WHITELIST_TEMPLATE, encoding="utf-8")


def _interactive_review(
    records: list[FlaggedRecord],
    whitelist_path: Path,
    no_color: bool,
    no_reload: bool,
) -> int:
    if not records:
        print("No flagged payloads found.")
        return 0

    whitelist = Whitelist.load(whitelist_path)
    print(
        f"Loaded whitelist: exact={len(whitelist.exact)}, "
        f"regex={len(whitelist.regex)}, capabilities={len(whitelist.capabilities)}"
    )
    print(
        f"{len(records)} flagged record(s). [a]ccept / [r]eject / [w]hitelist-exact / "
        "[c]apability-whitelist / [g]regex-whitelist / [n]ext / [q]uit"
    )

    edited = False
    for idx, record in enumerate(records, start=1):
        _print_record(idx, len(records), record, no_color=no_color)
        choice = _prompt("Decision", default="n").strip().lower()
        if choice in ("q", "quit", "exit"):
            break
        if choice in ("a", "accept"):
            print("  → accepted (acknowledged; still blocked).")
            continue
        if choice in ("r", "reject"):
            print("  → rejected (block was correct).")
            continue
        if choice in ("w", "whitelist", "whitelist-exact"):
            whitelist.append_exact(record.rendered_payload, path=whitelist_path)
            edited = True
            print(f"  → exact-whitelist appended: {record.rendered_payload[:60]!r}")
            continue
        if choice in ("c", "capability"):
            whitelist.append_capability(record.capability_name, path=whitelist_path)
            edited = True
            print(f"  → capability-whitelist appended: {record.capability_name}")
            continue
        if choice in ("g", "regex"):
            pattern = _prompt("  regex pattern (matching the payload)").strip()
            note = _prompt("  note (optional)").strip()
            try:
                re.compile(pattern)
            except re.error as e:
                print(f"  → invalid regex ({e}); skipping.")
                continue
            whitelist.append_regex(pattern, note, path=whitelist_path)
            edited = True
            print(f"  → regex-whitelist appended: {pattern!r}")
            continue
        # default: next
        continue

    if edited and not no_reload:
        _signal_reload()
    return 0


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        return input(f"{label}{suffix}: ") or default
    except EOFError:
        return default


def _print_record(idx: int, total: int, record: FlaggedRecord, *, no_color: bool) -> None:
    rule = "─" * 72
    print()
    print(rule)
    print(f"[{idx}/{total}] {record.capability_name} — surface={record.surface or '(unknown)'}")
    print(f"  ts        : {record.ts:.2f} ({record.date_str})")
    print(f"  risk      : {record.risk}")
    print(f"  reason    : {record.reason}")
    if record.programme_id:
        print(f"  programme : {record.programme_id}")
    print(f"  source    : {record.source_path}")
    payload_preview = record.rendered_payload
    if len(payload_preview) > 400:
        payload_preview = payload_preview[:400] + "…"
    print(f"  payload   : {payload_preview}")
    print(rule)


def _print_table(records: Iterable[FlaggedRecord], *, no_color: bool) -> None:
    rows = list(records)
    if not rows:
        print("No flagged payloads.")
        return
    print(f"{'ts':>10}  {'risk':<6}  {'capability':<32}  {'surface':<10}  reason")
    for record in rows:
        ts_short = f"{record.ts:.0f}"
        capability = record.capability_name[:32]
        surface = (record.surface or "")[:10]
        reason = record.reason[:60]
        print(f"{ts_short:>10}  {record.risk:<6}  {capability:<32}  {surface:<10}  {reason}")


def _signal_reload() -> None:
    """Send SIGHUP to whitelist-loading daemons.

    Uses ``systemctl --user kill --signal=SIGHUP`` rather than direct
    pid lookup because the daemons run as systemd user units; systemctl
    handles the unit→pid resolution and is no-ops if the unit is dead.

    Operator-friendly: prints which daemons were signalled. Skips
    silently when ``systemctl`` is not on PATH (test environments).
    """
    if not _has_systemctl():
        log.info("systemctl not available; skipping SIGHUP step")
        return
    for unit in RELOAD_DAEMONS:
        try:
            subprocess.run(
                ["systemctl", "--user", "kill", "--signal=SIGHUP", unit],
                check=False,
                capture_output=True,
                timeout=5.0,
            )
            print(f"  SIGHUP → {unit}")
        except (subprocess.TimeoutExpired, OSError) as e:
            log.warning("SIGHUP %s failed: %s", unit, e)


def _has_systemctl() -> bool:
    return any(
        os.access(os.path.join(p, "systemctl"), os.X_OK)
        for p in os.environ.get("PATH", "").split(os.pathsep)
        if p
    )


def install_inprocess_sighup_handler(
    on_reload: callable,  # type: ignore[valid-type]
) -> None:
    """Install a SIGHUP handler that calls ``on_reload`` once per signal.

    Used by long-running consumers (``logos-api``, ``hapax-daimonion``)
    so they can refresh their whitelist reference when the operator
    edits the YAML and signals.

    Idempotent: replaces any prior handler installed by this function.
    """

    def _handler(signum: int, frame) -> None:  # type: ignore[no-untyped-def]
        log.info("SIGHUP received; reloading whitelist")
        try:
            on_reload()
        except Exception:  # noqa: BLE001 — handler must not crash the daemon
            log.warning("whitelist reload failed", exc_info=True)

    signal.signal(signal.SIGHUP, _handler)


__all__ = [
    "RELOAD_DAEMONS",
    "install_inprocess_sighup_handler",
    "main",
]
