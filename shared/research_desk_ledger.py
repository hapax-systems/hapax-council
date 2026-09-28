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

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from shared.jsonl_append import append_jsonl

LOG = logging.getLogger("hapax-research-desk.ledger")

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


@dataclass(frozen=True)
class LedgerRead:
    """Every well-formed row, plus the line numbers of the ones that were not.

    Malformed lines are **counted and named**, never silently dropped and never
    raised past the caller. The reason is the call site: ``--check`` runs as the
    server unit's ``ExecStartPre``, so a bare ``JSONDecodeError`` on one torn line
    — an append interrupted by a kill, a hand edit — would wedge service start
    permanently with a stack trace carrying no next action. A receipt ledger that
    cannot be read is a reason to say so, not a reason to refuse to serve.
    """

    records: list[dict[str, Any]]
    malformed_lines: tuple[int, ...]

    def __len__(self) -> int:
        return len(self.records)

    @property
    def ok(self) -> bool:
        return not self.malformed_lines

    def repair_action(self, path: Path) -> str:
        return (
            f"inspect line(s) {', '.join(str(n) for n in self.malformed_lines)} of {path}; "
            "a torn line is usually an append interrupted mid-write — delete or repair it"
        )


def read_records(path: Path | None = None) -> LedgerRead:
    """Read the ledger, separating well-formed rows from unparseable lines."""
    target = path or ledger_path_from_env()
    if not target.exists():
        return LedgerRead(records=[], malformed_lines=())
    rows: list[dict[str, Any]] = []
    malformed: list[int] = []
    for number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            malformed.append(number)
            LOG.warning(
                "research desk ledger: line %d of %s is not JSON; skipping it. "
                "Next action: delete or repair that line",
                number,
                target,
            )
            continue
        if not isinstance(parsed, dict):
            malformed.append(number)
            LOG.warning(
                "research desk ledger: line %d of %s is not a JSON object; skipping it. "
                "Next action: delete or repair that line",
                number,
                target,
            )
            continue
        rows.append(parsed)
    return LedgerRead(records=rows, malformed_lines=tuple(malformed))
