"""Per-call receipt ledger for the Perplexity research desk MCP server.

Every tool call on the desk writes exactly one JSONL row here. The ledger is the
capability's **receipt surface**: the desk spends a subscription entitlement we do
not meter directly (Perplexity Computer credits), so the only thing the estate can
count is the calls it served and the bytes it returned.

Two properties are load-bearing and pinned by tests:

1. **The bearer key never reaches a row.** The row schema is closed — a writer
   builds rows only through :func:`build_record`, which accepts a fixed field set
   and drops nothing into it that was not named. There is no ``**extra`` path and
   no request-header capture, so there is no route by which the credential could
   arrive here.
2. **A delivery receipt is durable or the call fails.** ``append`` raises on IO
   failure rather than swallowing it (the opposite of
   :mod:`shared.jsonl_append`'s default advisory posture), because the caller
   returns a receipt id to an external agent and a receipt with no row behind it
   is a lie. Delivery is idempotent on request id, so a client retry after a
   ledger failure is safe.

Delete-the-estate statement: an append-only record of each authenticated call an
external agent made against a local tool surface, carrying enough to count calls,
bytes and outcomes and nothing that could authenticate anyone.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from shared.jsonl_append import append_jsonl

LEDGER_SCHEMA = 1

#: Default ledger location. HOME-local on purpose: :mod:`shared.jsonl_append`
#: serialises appends with ``flock``, which is only reliable on a local
#: filesystem, and the vault is NFS.
DEFAULT_LEDGER_PATH = Path.home() / ".cache" / "hapax" / "research-desk" / "ledger.jsonl"

ToolName = Literal["list_open_research_requests", "fetch_request", "deliver_result"]
Outcome = Literal["ok", "duplicate", "refused", "error"]

_TOOL_NAMES: frozenset[str] = frozenset(
    ("list_open_research_requests", "fetch_request", "deliver_result")
)
_OUTCOMES: frozenset[str] = frozenset(("ok", "duplicate", "refused", "error"))


def ledger_path_from_env(env: dict[str, str] | os._Environ[str] | None = None) -> Path:
    """Resolve the ledger path, honouring ``HAPAX_RESEARCH_DESK_LEDGER``."""
    source = os.environ if env is None else env
    override = source.get("HAPAX_RESEARCH_DESK_LEDGER", "").strip()
    return Path(override).expanduser() if override else DEFAULT_LEDGER_PATH


def utc_now_iso() -> str:
    """Timestamp in the estate's canonical second-resolution UTC form."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_record(
    *,
    tool: str,
    outcome: str,
    caller_ip: str | None,
    request_id: str | None = None,
    bytes_out: int = 0,
    bytes_in: int = 0,
    reason_code: str | None = None,
    receipt_id: str | None = None,
    result_count: int | None = None,
    at: str | None = None,
) -> dict[str, Any]:
    """Build one closed-schema ledger row.

    Raises ``ValueError`` for an unknown ``tool`` or ``outcome`` so a typo becomes a
    test failure rather than an unqueryable ledger.
    """
    if tool not in _TOOL_NAMES:
        raise ValueError(
            f"unknown research-desk tool {tool!r}; expected one of {sorted(_TOOL_NAMES)}"
        )
    if outcome not in _OUTCOMES:
        raise ValueError(f"unknown outcome {outcome!r}; expected one of {sorted(_OUTCOMES)}")
    return {
        "ledger_schema": LEDGER_SCHEMA,
        "at": at or utc_now_iso(),
        "tool": tool,
        "outcome": outcome,
        "request_id": request_id,
        "receipt_id": receipt_id,
        "result_count": result_count,
        "bytes_in": int(bytes_in),
        "bytes_out": int(bytes_out),
        "reason_code": reason_code,
        "caller_ip": caller_ip,
    }


def append(record: dict[str, Any], *, path: Path | None = None) -> None:
    """Append one row, raising on failure.

    ``shared.jsonl_append`` fails open by default; the desk does not want that
    posture, so ``raising=True`` is passed and the exception propagates to the tool
    boundary.
    """
    target = path or ledger_path_from_env()
    append_jsonl(target, record, sort_keys=True, raising=True)


def read_records(path: Path | None = None) -> list[dict[str, Any]]:
    """Read every well-formed row. Used by tests and by the measurement pass."""
    import json

    target = path or ledger_path_from_env()
    if not target.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        rows.append(json.loads(stripped))
    return rows
