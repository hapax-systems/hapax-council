"""Bounded tail reads for append-only JSONL ledgers.

An append-only ledger is read far more often than it is written, and the readers
almost always want only the newest rows. Reading one with
``path.read_text().splitlines()`` costs the whole file in RAM every call — for
``route-decisions.jsonl`` that measured 2.5 GB on disk and ~4.9 GB peak RSS, paid
in front of every side-effecting MCP call.

``read_tail_lines`` seeks backward from EOF and stops as soon as it has enough
lines, so cost is proportional to what the caller asked for rather than to the
file. Both bounds matter: ``max_lines`` covers the normal case, ``max_bytes``
covers a ledger whose rows are enormous or whose newlines are missing entirely.

**Truncation is not observable to the caller.** The return value of a scan that
stopped at a bound is indistinguishable from one that reached the start of the
file, so a caller that scans for malformed rows learns "no malformed rows *in the
window we read*" and cannot tell it apart from "no malformed rows". Consumers
that treat absence as an all-clear — ``shared/mcp_connector_policy`` reads this
ledger to answer route-decision questions — are narrowing their evidence without
being told. That is a deliberate trade for bounded cost, but it belongs where the
result is consumed and not only where the bound was introduced. Anything that
needs to distinguish the two cases must compare against the file size itself, or
this function needs to grow a returned truncation flag.
"""

from __future__ import annotations

import io
from pathlib import Path

DEFAULT_CHUNK_BYTES = 64 * 1024


def read_tail_lines(
    path: Path,
    *,
    max_lines: int,
    max_bytes: int | None = None,
    encoding: str = "utf-8",
    chunk_bytes: int = DEFAULT_CHUNK_BYTES,
) -> list[str]:
    """Return at most ``max_lines`` final lines of ``path``, oldest-first.

    A partial line at the front of the scanned window is dropped: it is the tail
    of a row whose beginning was never read, so parsing it would surface a
    spurious malformed-row error. When the scan reaches the start of the file no
    line is partial and nothing is dropped.

    Raises ``OSError`` like any other read; callers that already treat an
    unreadable ledger as empty should keep doing so.
    """
    if max_lines <= 0:
        return []

    # Collect chunks newest-first and join once. Prepending to a bytes buffer per
    # chunk would recopy the whole window each time — quadratic in chunk count,
    # which for an 8 MiB window is hundreds of MB of pointless copying on a path
    # that runs before every side-effecting MCP call.
    chunks: list[bytes] = []
    newlines = 0
    with path.open("rb") as handle:
        handle.seek(0, io.SEEK_END)
        end = handle.tell()
        pos = end
        while pos > 0:
            step = min(chunk_bytes, pos)
            if max_bytes is not None:
                # Clamp to the remaining budget rather than only checking before
                # the read: an unclamped step overshoots max_bytes by up to one
                # chunk, so the documented defence against a ledger of enormous
                # or newline-free rows was one chunk_bytes weaker than it reads.
                remaining = max_bytes - (end - pos)
                if remaining <= 0:
                    break
                step = min(step, remaining)
            pos -= step
            handle.seek(pos)
            block = handle.read(step)
            chunks.append(block)
            newlines += block.count(b"\n")
            # Strictly more newlines than requested lines guarantees that
            # max_lines complete lines survive dropping the leading partial.
            if newlines > max_lines:
                break

    lines = b"".join(reversed(chunks)).decode(encoding, errors="replace").splitlines()
    if pos > 0 and lines:
        lines = lines[1:]
    return lines[-max_lines:]
