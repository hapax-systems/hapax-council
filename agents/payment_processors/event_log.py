"""Append-only payment-event log shared by all receive rails.

Each rail (Lightning, Nostr Zap, Liberapay, x402 USDC-on-Base) calls
``append_event`` with a ``PaymentEvent`` once per confirmed receipt. The log lives at
``/dev/shm/hapax-monetization/events.jsonl`` (operator-overridable
via ``HAPAX_MONETIZATION_LOG_PATH``).

The aggregator tails the log and pushes the most recent event into
the awareness ``MonetizationBlock``. Storage in /dev/shm is
intentional — the log is ephemeral by spec; persistent monetization
records belong in the chronicle (see ``shared.chronicle.record``)
which receivers also call. Reboot/power-loss on /dev/shm is an explicit
ceiling: rows here are *protocol-confirmed and fsynced*, never "durable".

Writer and reader coordinate on one stable per-target sidecar ``flock`` plus a
pre-append WAL/HOLD marker so a torn or unconfirmed tail is never projected as
money: ``append_event`` refuses/HOLDs rather than concatenate, and ``tail_events``
admits only newline-framed rows and, when a valid marker is retained, only the
confirmed prefix ending at the marker's ``start_offset``.

Idempotency: rails MUST set ``external_id`` (Alby invoice id, Nostr
zap event id, Liberapay sponsorship id, or x402 USDC ``tx_hash:log_index``)
so the aggregator can skip duplicates. The log itself is append-only and never
deduplicates; deduplication happens at read time keyed by ``(rail, external_id)``.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import re
import stat
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from prometheus_client import Counter

from agents.operator_awareness.state import PaymentEvent

# Reuse the proven low-level append mechanics from the Stage-0 sink rather than
# reinventing them: the encoded-line short-write loop is shared verbatim, and the
# sidecar flock / ftruncate rollback / pre-append WAL-marker discipline mirror it.
# Only the *contract* differs — this append is best-effort (returns a bool, never
# raises), so the rollback/marker helpers below carry that boolean status.
from shared.durable_jsonl_sink import DurableSinkAppendError, _write_all

log = logging.getLogger(__name__)

DEFAULT_PAYMENT_LOG_PATH = Path(
    os.environ.get(
        "HAPAX_MONETIZATION_LOG_PATH",
        "/dev/shm/hapax-monetization/events.jsonl",
    )
)

# Bounded tail length when reading the log. Aggregator displays the
# latest event; counter math walks the full file but stops early once
# the bounded tail is satisfied — see ``tail_events``.
DEFAULT_TAIL_LIMIT = 200

_lock = threading.Lock()

# Symlink-following defense for the low-level opens (0 where unsupported).
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
# Machine-readable WAL/HOLD marker header schema.
_MARKER_VERSION = 1
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
# Sentinel: a marker is present but unverifiable/held → readers fail closed.
_READ_FAIL_CLOSED = object()

payment_events_appended_total = Counter(
    "hapax_payment_events_appended_total",
    "Receive-rail payment events appended to the canonical log.",
    ["rail"],
)


@dataclass(frozen=True)
class PaymentEventRead:
    """A typed payment-event snapshot distinguishing OK from HELD/UNREADABLE.

    ``status`` is ``"ok"`` (no in-flight append; ``events`` is the confirmed
    content, possibly empty — a legitimate zero), ``"held"`` (a valid WAL marker is
    present; ``events`` is only the confirmed prefix and the *current* total is
    UNKNOWN), or ``"unreadable"`` (marker unverifiable or target/lock unreadable;
    ``events`` is empty). Money-awareness write consumers must refuse to
    receipt+write on any non-``ok`` status so a HOLD/unreadable ledger never erases
    last-known monetary truth.
    """

    status: Literal["ok", "held", "unreadable"]
    events: tuple[PaymentEvent, ...]


def append_event(event: PaymentEvent, *, log_path: Path | None = None) -> bool:
    """Append one event to the JSONL log under a fail-closed WAL protocol.

    When ``log_path`` is omitted, re-resolves the module-level
    ``DEFAULT_PAYMENT_LOG_PATH`` at call time so monkeypatching that attribute in
    tests takes effect.

    Serialisation: an in-process lock plus a stable per-target sidecar ``flock``
    coordinate cooperating same-host writers (Lightning + Liberapay + Nostr + USDC)
    so their bytes never interleave mid-line, and coordinate with ``tail_events``.

    Return contract (best-effort; this never raises so a rail's polling loop is
    never broken — even a payload-serialisation failure returns False before any
    mutation):

    * **True** means exactly one full, newline-terminated line completed the
      protocol: it was written by the short-write loop, its post-write size was
      verified, and the target fd was ``fsync``-ed (the commit point) under the
      lock; the metric is incremented only afterward. It is a protocol-confirmed,
      fsynced write — NOT a reboot-durability or exactly-once claim (see ceilings).
    * **False** means the append was NOT confirmed. It may follow a payload
      serialisation failure, a partial/failed write, a complete-but-unsynced write,
      an unexplained post-write size mismatch, or a refusal because the target
      carries a torn (non-newline-terminated) tail or a prior append left a HOLD/WAL
      marker. On False the caller MUST NOT advance its seen/cursor state; it must
      inspect/reconcile/repair before retry. A retry into a cleanly rolled-back
      target is safe; a retry into a HOLD/torn target is refused (fail-closed) until
      an operator reconciles. ``append_event`` never auto-truncates an unknown
      pre-existing torn tail nor a size-mismatched (foreign-mutation) tail — the
      bytes may be the only copy of an unredelivered (e.g. Nostr) event.

    Fail-closed structure: a fsynced HOLD/WAL marker (machine-readable header
    carrying version, exact target, validated ``start_offset``, and line digest) is
    written under the sidecar lock with ``O_EXCL`` *before* the first target byte.
    It is removed only on a clean commit whose fd also closed cleanly, or on a
    byte-identical rollback; it is retained on any ambiguous outcome so every future
    append and read HOLDs. The distinct post-commit outcomes are:

    * clean commit + clean close → marker removed → True;
    * commit + target-fd close failure → marker RETAINED (writeback ambiguous),
      True, next append/read HOLDs;
    * commit + marker-cleanup failure → True, next append/read HOLDs;
    * lock ``LOCK_UN``/lock-fd close failure → warn only, the confirmed True stands
      and no marker/HOLD is implied (lock cleanup is orthogonal to the data).

    Ceilings (NOT proven here):

    * Power-loss/reboot on the ephemeral ``/dev/shm`` log — rows here are
      protocol-confirmed and fsynced, never reboot-durable.
    * Process death at ANY protocol/caller boundary, not merely between write and
      fsync. The critical unsolved window is *commit-to-caller-state*: after the
      target fsync and marker removal but before ``append_event`` returns, or before
      the rail persists/advances its seen/cursor state. Because this function
      intentionally never deduplicates, a restart or source redelivery can append
      the same logical event again — there is NO exactly-once guarantee.
    * Non-cooperating writers that ignore the lock, cross-host outbox delivery, and
      source redelivery / exactly-once external effects.
    * Financial-evidence: a protocol-confirmed PaymentEvent JSONL row is an
      ephemeral awareness projection — NOT settlement, revenue, cost, return,
      profit, or outcome evidence. Its private resource receipt is
      admission/provenance evidence, not proof of any of those facts.

    Receive-rail callers commit or attach a private resource receipt before calling
    ``append_event``; ``append_event`` itself neither performs nor authenticates
    that receipt-admission precondition and never deduplicates (deduplication
    happens at read time keyed by ``(rail, external_id)``).
    """
    target = log_path if log_path is not None else DEFAULT_PAYMENT_LOG_PATH
    try:
        line = (event.model_dump_json() + "\n").encode("utf-8")
    except Exception:  # noqa: BLE001 — serialisation happens before any mutation
        log.warning(
            "payment-event log append could not serialise the event for %s; no bytes "
            "were written. next action: inspect the PaymentEvent payload",
            target,
            exc_info=True,
        )
        return False
    with _lock:
        confirmed = _append_event_under_lock(target, line)
    if confirmed:
        # The metric is observational and strictly after the commit point. A metric
        # failure must never surface a confirmed row as an exception/False — that
        # would stall seen-state advance and induce duplicate redelivery.
        try:
            payment_events_appended_total.labels(rail=event.rail).inc()
        except Exception:  # noqa: BLE001
            log.warning(
                "payment-event log append CONFIRMED but the Prometheus metric "
                "increment for rail %s failed; returning confirmed. The event is "
                "protocol-confirmed and must not be re-appended. next action: check "
                "the metrics registry",
                event.rail,
                exc_info=True,
            )
    return confirmed


def _event_log_lock_path(target: Path) -> Path:
    return target.with_name(f"{target.name}.lock")


def _event_log_hold_path(target: Path) -> Path:
    return target.with_name(f"{target.name}.hold")


def _is_regular_fd(fd: int) -> bool:
    try:
        return stat.S_ISREG(os.fstat(fd).st_mode)
    except OSError:
        return False


def _append_event_under_lock(target: Path, line: bytes) -> bool:
    """Append ``line`` to ``target`` under the sidecar flock; return confirmed.

    Explicit lock-fd lifecycle so no ordinary filesystem/lock error escapes the
    never-raises contract and so post-commit lock-cleanup errors preserve a
    confirmed True (they are never remapped to a no-write False).
    """

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        log.warning(
            "payment-event log append could not create parent directory %s; next "
            "action: verify the log root path and permissions, then retry",
            target.parent,
            exc_info=True,
        )
        return False

    lock_path = _event_log_lock_path(target)
    hold_path = _event_log_hold_path(target)
    try:
        # O_RDWR so a substituted FIFO cannot block a write-only open; O_NOFOLLOW so
        # a symlinked lock path is rejected rather than followed.
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | _NOFOLLOW, 0o600)
    except OSError:
        log.warning(
            "payment-event log append could not open sidecar lock %s; next action: "
            "verify the log directory exists and is writable, then retry",
            lock_path,
            exc_info=True,
        )
        return False

    try:
        if not _is_regular_fd(lock_fd):
            log.error(
                "payment-event log append: sidecar lock %s is not a regular file; "
                "refusing without mutation. next action: quarantine the path",
                lock_path,
            )
            return False
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
        except OSError:
            log.warning(
                "payment-event log append could not acquire sidecar lock %s; next "
                "action: retry after verifying no stale writer holds it",
                lock_path,
                exc_info=True,
            )
            return False
        # No target byte is mutated before the lock is held. The result and its
        # commit state are decided inside the locked body; lock release/close
        # failures below only warn — they never flip a confirmed True to False.
        result = _append_event_line_locked(target, line, hold_path)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except OSError:
            log.warning(
                "payment-event log %s lock release failed (append confirmed=%s); the "
                "lock fd close will drop it and the data is unaffected. next action: "
                "check lock fd state",
                lock_path,
                result,
                exc_info=True,
            )
        return result
    finally:
        try:
            os.close(lock_fd)
        except OSError:
            log.warning(
                "payment-event log %s lock fd close failed; the lock is released on "
                "process exit and any confirmed append stands. next action: check for "
                "fd exhaustion",
                lock_path,
                exc_info=True,
            )


def _append_event_line_locked(target: Path, line: bytes, hold_path: Path) -> bool:
    """Run the WAL append protocol assuming the sidecar lock is already held.

    Never raises. Setup/inspection failures before the target is mutated return
    False with truthful marker/target state. After the commit point (full write +
    verified size + target fsync) the event is protocol-confirmed: a target-fd close
    failure retains the WAL marker and stays fail-visible/ambiguous (next append/read
    HOLDs), a marker-cleanup failure likewise returns True and HOLDs the next
    append, and neither is remapped to a no-write False.
    """

    present = _marker_present(hold_path)
    if present is None:
        log.warning(
            "payment-event log %s: could not confirm WAL marker %s state at the HOLD "
            "gate; refusing without mutation. next action: verify the log directory is "
            "readable, then retry",
            target,
            hold_path,
        )
        return False
    if present:
        log.error(
            "payment-event log %s is HELD by pre-append WAL marker %s from a prior "
            "unconfirmed append; refusing to append without mutation. next action: "
            "stop rail writers, reconcile the tail against source redelivery, then "
            "remove the marker",
            target,
            hold_path,
        )
        return False

    try:
        fd = os.open(target, os.O_RDWR | os.O_CREAT | os.O_APPEND | _NOFOLLOW, 0o600)
    except OSError:
        log.warning(
            "payment-event log append could not open %s; next action: verify the log "
            "directory exists and is writable (and the path is not a symlink), then "
            "retry",
            target,
            exc_info=True,
        )
        return False

    committed = False
    close_ok = True
    try:
        if not _is_regular_fd(fd):
            log.error(
                "payment-event log %s is not a regular file; refusing without "
                "mutation. next action: quarantine the path",
                target,
            )
            return False
        try:
            start_offset = os.lseek(fd, 0, os.SEEK_END)
            tail_byte = os.pread(fd, 1, start_offset - 1) if start_offset > 0 else b"\n"
        except OSError:
            log.warning(
                "payment-event log %s: could not inspect the tail before append; "
                "refusing without mutation. next action: verify the log file is a "
                "readable regular file, then retry",
                target,
                exc_info=True,
            )
            return False
        if tail_byte != b"\n":
            log.error(
                "payment-event log %s has a non-newline-terminated tail (a torn "
                "partial line from an earlier append); refusing to append without "
                "mutation. next action: stop rail writers, inspect and "
                "repair/quarantine the torn final line (do NOT blindly truncate — it "
                "may be the only fragment of an unredelivered event), then retry",
                target,
            )
            return False

        digest = hashlib.sha256(line).hexdigest()
        marker = _write_pre_append_marker(hold_path, target, start_offset, digest)
        if marker is None:
            log.error(
                "payment-event log %s: a WAL marker %s appeared under the lock "
                "(O_EXCL); treating it as a HOLD and refusing without mutation. next "
                "action: reconcile the tail, then remove the marker",
                target,
                hold_path,
            )
            return False
        if marker is False:
            return False  # logged inside; marker left fail-closed

        size_mismatch = False
        try:
            _write_all(fd, line)
            actual = os.fstat(fd).st_size
            if actual == start_offset + len(line):
                os.fsync(fd)
                committed = True  # commit point: full write + verified size + fsync
            else:
                size_mismatch = True
        except (OSError, DurableSinkAppendError):
            # Write/fsync failure with the exception active: exc_info is valid here.
            if _rollback_event_append(fd, start_offset):
                if _remove_event_log_marker(hold_path):
                    log.warning(
                        "payment-event log append to %s failed; rolled back to a "
                        "byte-identical preimage at byte %d. next action: inspect "
                        "storage write/fsync errors, then retry",
                        target,
                        start_offset,
                        exc_info=True,
                    )
                else:
                    log.error(
                        "payment-event log %s append rolled back byte-identically but "
                        "the WAL marker %s could not be removed; it will HOLD the next "
                        "append until reconciled (the tail is actually clean). next "
                        "action: verify no row exists at byte %d, then remove the "
                        "marker",
                        target,
                        hold_path,
                        start_offset,
                        exc_info=True,
                    )
            else:
                log.error(
                    "payment-event log append to %s failed AND rollback failed at byte "
                    "%d; the pre-append WAL marker %s is retained so every future "
                    "append and read HOLDs until reconciled (any already-written bytes "
                    "are ambiguous — a torn prefix or a complete unsynced line). next "
                    "action: stop rail writers and reconcile the tail before removing "
                    "the marker",
                    target,
                    start_offset,
                    hold_path,
                    exc_info=True,
                )
            return False
        if size_mismatch:
            # An unexplained post-write size is evidence of foreign/unexpected
            # mutation under the lock. Do NOT ftruncate (that could erase another
            # writer's bytes); retain the marker and HOLD. No active exception here,
            # so no exc_info.
            log.error(
                "payment-event log %s: post-write size %d != expected start_offset(%d)"
                "+len(%d) — unexplained/foreign mutation under the lock. NOT truncating "
                "(that could erase another writer); retaining WAL marker %s so every "
                "future append and read HOLDs until reconciled. next action: stop rail "
                "writers and reconcile the tail",
                target,
                actual,  # saved before this point — never re-stat after bytes+marker
                start_offset,
                len(line),
                hold_path,
            )
            return False
    finally:
        try:
            os.close(fd)
        except OSError:
            close_ok = False
            log.warning(
                "payment-event log %s target fd close failed (committed=%s). next "
                "action: check for fd exhaustion",
                target,
                committed,
                exc_info=True,
            )

    # committed is True here (the only fall-through from the try body).
    if not close_ok:
        # Distinct from a clean commit: write+fsync reached the commit point, but the
        # close failed, so writeback state is ambiguous. Do NOT remove the marker
        # (that would claim a clean protocol); retain it so the next append/read
        # HOLDs, and return True so this confirmed event is never re-appended. No
        # active exception here (it was logged in the finally), so no exc_info.
        log.error(
            "payment-event log %s: event CONFIRMED (write+fsync) but the target fd "
            "close failed; retaining WAL marker %s so the next append/read HOLDs until "
            "an operator confirms the tail. next action: verify the tail row, then "
            "remove the marker",
            target,
            hold_path,
        )
        return True
    if not _remove_event_log_marker(hold_path):
        # Clean commit, but marker cleanup is unconfirmed: the event is confirmed, so
        # do NOT re-append (return True); leave the marker so the next append/read
        # HOLDs. The unlink error was logged inside the helper — no exc_info here.
        log.error(
            "payment-event log %s: event CONFIRMED but WAL marker %s cleanup is "
            "unconfirmed; the event is protocol-confirmed and must NOT be re-appended, "
            "so the next append/read will HOLD until an operator confirms the tail row "
            "and removes the marker. next action: verify the tail, then remove the "
            "marker",
            target,
            hold_path,
        )
    return True


def _marker_present(hold_path: Path) -> bool | None:
    """Return whether the WAL marker exists, or ``None`` if the check itself failed.

    Uses ``os.stat`` (not ``Path.exists``) so a stat error other than absence is
    surfaced as ``None`` (treat as unsafe → refuse) rather than silently mapped to
    "absent". The real exception is logged here, where it is caught.
    """

    try:
        os.stat(hold_path)
    except FileNotFoundError:
        return False
    except OSError:
        log.warning("payment-event log: could not stat WAL marker %s", hold_path, exc_info=True)
        return None
    return True


def _write_pre_append_marker(
    hold_path: Path, target: Path, start_offset: int, digest: str
) -> bool | None:
    """Write the fsynced pre-append HOLD/WAL marker.

    Returns ``True`` when the marker was created and its content fsynced, ``None``
    when a marker already exists (``O_EXCL`` — never clobber a marker that appears),
    and ``False`` when creation or the content write failed. The header is a
    machine-readable JSON object (``marker_version``, exact ``target``,
    ``start_offset``, ``line_sha256``) that ``tail_events`` validates before trusting
    the marker's prefix. Created under the sidecar lock *before* the first target
    byte so the HOLD survives even when an ``fsync`` fails after a complete
    newline-terminated write and the rollback also fails (the tail would still end in
    a newline, so a newline-only guard could not detect it). Refusing to append
    without this WAL protection is fail-closed.
    """

    header = json.dumps(
        {
            "marker_version": _MARKER_VERSION,
            "target": str(target),
            "start_offset": start_offset,
            "line_sha256": digest,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    content = (
        header + "\n"
        "This pre-append WAL marker was written under the sidecar lock before any "
        "target bytes. Its presence means an append is in-flight or did not confirm; "
        "every future append and read refuses/HOLDs until an operator reconciles the "
        "tail against source redelivery and removes this marker.\n"
    ).encode("utf-8")
    try:
        fd = os.open(hold_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW, 0o600)
    except FileExistsError:
        return None
    except OSError:
        log.error(
            "payment-event log %s: could not create the pre-append HOLD marker %s; "
            "refusing to append without WAL protection. next action: verify the log "
            "directory is writable, then retry",
            target,
            hold_path,
            exc_info=True,
        )
        return False
    try:
        try:
            _write_all(fd, content)
            os.fsync(fd)
        finally:
            os.close(fd)
    except (OSError, DurableSinkAppendError):
        # The marker exists (O_EXCL created it) but its content/fsync did not
        # complete. Leave it in place fail-closed: no target byte was written, and
        # its presence HOLDs the next append/read until an operator reconciles.
        log.error(
            "payment-event log %s: created HOLD marker %s but its content write/fsync "
            "failed; leaving it in place so the next append/read HOLDs (no target byte "
            "was written). next action: confirm the tail is clean, then remove the "
            "marker",
            target,
            hold_path,
            exc_info=True,
        )
        return False
    return True


def _rollback_event_append(fd: int, start_offset: int) -> bool:
    """Truncate a partial/unsynced append back to ``start_offset``, byte-identically.

    Mirrors ``shared.durable_jsonl_sink._rollback_partial_append`` but returns a
    status so the caller can retain the pre-append WAL marker when rollback fails.
    Only called for a write/fsync failure — never for a size mismatch, which may be
    foreign bytes that must not be truncated.
    """

    try:
        os.ftruncate(fd, start_offset)
        os.fsync(fd)
        return True
    except OSError:
        return False


def _remove_event_log_marker(hold_path: Path) -> bool:
    """Remove the WAL marker idempotently; return whether it is now absent."""

    try:
        hold_path.unlink()
    except FileNotFoundError:
        return True
    except OSError:
        log.warning("payment-event log: could not remove WAL marker %s", hold_path, exc_info=True)
        return False
    return True


def read_payment_events(
    *,
    limit: int = DEFAULT_TAIL_LIMIT,
    log_path: Path | None = None,
) -> PaymentEventRead:
    """Read the log as a typed snapshot distinguishing OK vs HELD vs UNREADABLE.

    When ``log_path`` is omitted, re-resolves the module-level
    ``DEFAULT_PAYMENT_LOG_PATH`` at call time (monkeypatch-friendly). Coordinates
    with ``append_event`` on the same stable per-target sidecar ``flock``.

    Status meanings (see :class:`PaymentEventRead`):

    * ``ok`` — no WAL marker and the file read cleanly; a missing or verified-empty
      log is ``ok`` with no events (a *legitimate* zero);
    * ``held`` — a valid WAL marker is present (an append is in-flight/unconfirmed).
      ``events`` carries only the newline-complete prefix ending exactly at
      ``marker.start_offset`` (every ambiguous suffix byte excluded), but the
      *current* total is UNKNOWN — money-awareness write consumers must preserve
      prior state, not project this;
    * ``unreadable`` — the marker is unverifiable (unreadable, malformed header,
      wrong version, target mismatch, out-of-range/mid-record ``start_offset``) or
      the target/lock could not be read; ``events`` is empty.

    In every case a final row is admitted only if it is newline-framed. Money
    -awareness write consumers MUST refuse to receipt+write on any non-``ok`` status
    so a HOLD/unreadable ledger never erases last-known monetary truth; only ``ok``
    (including verified-empty/missing) may produce a zero block.
    """
    target = log_path if log_path is not None else DEFAULT_PAYMENT_LOG_PATH
    if not target.exists():
        return PaymentEventRead("ok", ())  # verified-missing is a legitimate zero
    lock_path = _event_log_lock_path(target)
    hold_path = _event_log_hold_path(target)
    try:
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | _NOFOLLOW, 0o600)
    except OSError:
        log.warning(
            "payment-event log read could not open sidecar lock %s; next action: "
            "verify the log directory, then retry",
            lock_path,
            exc_info=True,
        )
        return PaymentEventRead("unreadable", ())
    try:
        if not _is_regular_fd(lock_fd):
            log.error(
                "payment-event log read: sidecar lock %s is not a regular file; "
                "refusing to read. next action: quarantine the path",
                lock_path,
            )
            return PaymentEventRead("unreadable", ())
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
        except OSError:
            log.warning(
                "payment-event log read could not acquire sidecar lock %s; next action: retry",
                lock_path,
                exc_info=True,
            )
            return PaymentEventRead("unreadable", ())
        return _tail_events_locked(target, hold_path, limit)
    finally:
        try:
            os.close(lock_fd)
        except OSError:
            log.warning(
                "payment-event log read: lock fd close failed for %s",
                lock_path,
                exc_info=True,
            )


def tail_events(
    *,
    limit: int = DEFAULT_TAIL_LIMIT,
    log_path: Path | None = None,
) -> list[PaymentEvent]:
    """Best-effort event list (the confirmed prefix under HOLD, empty if unreadable).

    Convenience over :func:`read_payment_events` that returns only the events, so a
    HOLD or unreadable snapshot is indistinguishable from empty. Do NOT use it to
    decide whether to receipt+write a monetization block — a money-awareness write
    consumer must call :func:`read_payment_events` and refuse on any non-``ok``
    status. Suitable for display/count reads that tolerate a best-effort tail.
    """
    return list(read_payment_events(limit=limit, log_path=log_path).events)


def _tail_events_locked(target: Path, hold_path: Path, limit: int) -> PaymentEventRead:
    try:
        fd = os.open(target, os.O_RDONLY | _NOFOLLOW)
    except OSError:
        log.warning(
            "payment-event log read could not open %s; next action: verify the log "
            "file (and that the path is not a symlink), then retry",
            target,
            exc_info=True,
        )
        return PaymentEventRead("unreadable", ())
    try:
        if not _is_regular_fd(fd):
            log.error(
                "payment-event log read: %s is not a regular file; refusing. next "
                "action: quarantine the path",
                target,
            )
            return PaymentEventRead("unreadable", ())
        try:
            target_size = os.fstat(fd).st_size
        except OSError:
            log.warning("payment-event log read could not stat %s", target, exc_info=True)
            return PaymentEventRead("unreadable", ())
        prefix_limit = _read_marker_prefix_limit(hold_path, target, target_size, fd)
        if prefix_limit is _READ_FAIL_CLOSED:
            return PaymentEventRead("unreadable", ())
        # A valid marker (prefix_limit is an int) means an append is in-flight →
        # HELD; no marker (None) → OK. Either way admit only the newline-framed rows
        # of the confirmed region.
        held = prefix_limit is not None
        read_size = target_size if prefix_limit is None else prefix_limit
        events = _read_newline_framed_events(fd, target, read_size, limit)
        if events is _READ_FAIL_CLOSED:
            return PaymentEventRead("unreadable", ())
        return PaymentEventRead("held" if held else "ok", tuple(events))
    finally:
        try:
            os.close(fd)
        except OSError:
            log.warning("payment-event log read: fd close failed for %s", target, exc_info=True)


# Bounded read chunk. Memory ceiling is truthful: at most one in-flight line buffer
# (bounded by the longest single record) plus ``limit`` retained events — the whole
# file is never held in memory.
_READ_CHUNK = 1 << 16


def _read_newline_framed_events(fd: int, target: Path, read_size: int, limit: int) -> object:
    """Stream exactly ``read_size`` bytes from offset 0 and admit newline-framed rows.

    Returns a ``list[PaymentEvent]`` on success, or ``_READ_FAIL_CLOSED`` when the
    read fails (an unreadable snapshot, distinct from a verified-empty one).

    ``os.pread`` may short-read, so the loop consumes chunks until exactly
    ``read_size`` bytes are read or fails closed on an unexpected early EOF (the file
    is stable under the sidecar lock). Only newline-terminated records are admitted:
    a trailing fragment after the last newline within ``read_size`` (torn/unconfirmed)
    is excluded. Bounded memory: one line buffer plus a ``deque(maxlen=limit)``.
    """

    tail: deque[PaymentEvent] = deque(maxlen=limit)
    buf = bytearray()
    consumed = 0
    while consumed < read_size:
        try:
            chunk = os.pread(fd, min(_READ_CHUNK, read_size - consumed), consumed)
        except OSError:
            log.warning("payment-event log read failed at %s", target, exc_info=True)
            return _READ_FAIL_CLOSED
        if not chunk:
            log.warning(
                "payment-event log read: %s ended after %d of %d expected bytes under "
                "the lock; fail-closed. next action: re-read after verifying the file",
                target,
                consumed,
                read_size,
            )
            return _READ_FAIL_CLOSED
        consumed += len(chunk)
        buf.extend(chunk)
        newline = buf.find(b"\n")
        while newline != -1:
            record = bytes(buf[:newline])
            del buf[: newline + 1]
            if record:
                try:
                    tail.append(PaymentEvent.model_validate_json(record))
                except (ValueError, TypeError):
                    log.debug("malformed payment-event line skipped")
            newline = buf.find(b"\n")
    # Any bytes left in ``buf`` are a final fragment with no terminating newline
    # inside the confirmed prefix — excluded by the newline-framing contract.
    return list(tail)


def _read_marker_prefix_limit(
    hold_path: Path, target: Path, target_size: int, target_fd: int
) -> object:
    """Resolve the read prefix from the WAL marker.

    Returns ``None`` (no marker → read the whole file), an ``int`` prefix limit
    (valid marker → read only ``[0, start_offset)``), or ``_READ_FAIL_CLOSED`` when a
    marker is present but unverifiable (readers must project no events).
    """

    try:
        mfd = os.open(hold_path, os.O_RDONLY | _NOFOLLOW)
    except FileNotFoundError:
        return None
    except OSError:
        log.error(
            "payment-event log read: could not open WAL marker %s; fail-closed. next "
            "action: reconcile the tail, then remove the marker",
            hold_path,
            exc_info=True,
        )
        return _READ_FAIL_CLOSED
    try:
        if not _is_regular_fd(mfd):
            log.error(
                "payment-event log read: WAL marker %s is not a regular file; "
                "fail-closed. next action: quarantine the path",
                hold_path,
            )
            return _READ_FAIL_CLOSED
        try:
            raw = os.pread(mfd, 65536, 0)
        except OSError:
            log.error(
                "payment-event log read: could not read WAL marker %s; fail-closed. "
                "next action: reconcile the tail, then remove the marker",
                hold_path,
                exc_info=True,
            )
            return _READ_FAIL_CLOSED
    finally:
        try:
            os.close(mfd)
        except OSError:
            log.warning(
                "payment-event log read: marker fd close failed for %s",
                hold_path,
                exc_info=True,
            )

    header = raw.split(b"\n", 1)[0]
    try:
        payload = json.loads(header)
    except (ValueError, TypeError, RecursionError):
        log.error(
            "payment-event log %s: WAL marker %s header is not valid JSON; fail-closed "
            "(refusing to project a possibly-torn tail). next action: reconcile the "
            "tail, then remove the marker",
            target,
            hold_path,
        )
        return _READ_FAIL_CLOSED
    reason = _marker_verification_failure(payload, target, target_size)
    if reason is not None:
        log.error(
            "payment-event log %s: WAL marker %s is unverifiable (%s); fail-closed. "
            "next action: reconcile the tail, then remove the marker",
            target,
            hold_path,
            reason,
        )
        return _READ_FAIL_CLOSED
    start_offset = int(payload["start_offset"])
    # Boundary: range alone permits a syntactically valid but corrupt marker to name
    # a mid-record offset. Require start_offset == 0 or the byte before it to be a
    # newline, so the confirmed prefix truly ends at a record boundary.
    if start_offset > 0:
        try:
            boundary = os.pread(target_fd, 1, start_offset - 1)
        except OSError:
            log.error(
                "payment-event log %s: could not verify WAL marker %s boundary byte; "
                "fail-closed. next action: reconcile the tail, then remove the marker",
                target,
                hold_path,
                exc_info=True,
            )
            return _READ_FAIL_CLOSED
        if boundary != b"\n":
            log.error(
                "payment-event log %s: WAL marker %s start_offset %d does not end at a "
                "record boundary (byte before it is not a newline); fail-closed. next "
                "action: reconcile the tail, then remove the marker",
                target,
                hold_path,
                start_offset,
            )
            return _READ_FAIL_CLOSED
    return start_offset


def _marker_verification_failure(payload: object, target: Path, target_size: int) -> str | None:
    """Return why ``payload`` is not a trustworthy marker header, or ``None``."""

    if not isinstance(payload, dict):
        return "header is not a JSON object"
    if payload.get("marker_version") != _MARKER_VERSION:
        return f"unexpected marker_version {payload.get('marker_version')!r}"
    if payload.get("target") != str(target):
        return f"target mismatch {payload.get('target')!r}"
    start_offset = payload.get("start_offset")
    if not isinstance(start_offset, int) or isinstance(start_offset, bool):
        return "start_offset is not an integer"
    if start_offset < 0 or start_offset > target_size:
        return f"start_offset {start_offset} out of range for size {target_size}"
    digest = payload.get("line_sha256")
    if not isinstance(digest, str) or _SHA256_HEX_RE.fullmatch(digest) is None:
        return "line_sha256 is not 64 lowercase hex chars"
    return None


def event_window_sha256(events: list[PaymentEvent]) -> str:
    """Hash the exact payment-event window that backs an awareness write."""

    digest = hashlib.sha256()
    for event in events:
        digest.update(event.model_dump_json().encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


__all__ = [
    "DEFAULT_PAYMENT_LOG_PATH",
    "DEFAULT_TAIL_LIMIT",
    "PaymentEventRead",
    "append_event",
    "event_window_sha256",
    "payment_events_appended_total",
    "read_payment_events",
    "tail_events",
]
