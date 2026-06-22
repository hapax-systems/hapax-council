"""Worker-lane failure-classification receipt + GUARDED family-availability witness.

When a worker dispatch lane TERMINALLY fails, the launcher (``scripts/hapax-methodology-dispatch``)
classifies the failure via the platform :class:`CapabilityAdapter` and calls into here to (1) append a
lossless sibling receipt to the failure-classification ledger, and (2) write a GUARDED worker
family-availability witness.

The witness is deliberately SEPARATE from the review plane's witness
(``review_team.FAMILY_OUTAGE_STATE`` = ``~/.cache/hapax/review-team/family-outage.json``): a worker
quota wall must never flip a review SEAT family to outaged, nor vice-versa. It is gated to an explicit
high-confidence allowlist (:data:`WORKER_AVAILABILITY_DEGRADE_CODES` = QUOTA_EXHAUSTION /
PROVIDER_OUTAGE) — it NEVER writes on UNKNOWN/TRANSIENT/AUTH_FAILURE/etc., so an ambiguous failure or a
single bad credential cannot mark a whole family unavailable. It writes exactly ONE key — the failing
lane's own family — so it is structurally incapable of flipping a sibling family or sibling route to
blocked. The classification HOLDS only the failing lane (coord_dispatch already defers that lane's MQ
message); it issues no degrade signal for any sibling.

LEAF module: imports only :mod:`shared.failure_classification` + :mod:`shared.jsonl_append` + stdlib,
never ``coord_dispatch`` — so the launcher can use it alongside coord_dispatch with no import cycle.
TTL is applied by the (future) reader, mirroring ``review_team.FAMILY_OUTAGE_TTL_S`` semantics; this
slice ships the WRITE side (a guarded witness), as the review plane shipped its witness before the
worker path existed.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from pathlib import Path

from shared.failure_classification import FailureCode, FailureReceipt
from shared.jsonl_append import append_jsonl

#: Worker failure-classification ledger (HOME-based, outside every git worktree — matches the other
#: ``~/.cache/hapax/*.jsonl`` ledgers, so it carries no merge-conflict surface).
FAILURE_CLASSIFICATION_LEDGER = Path.home() / ".cache" / "hapax" / "failure-classification.jsonl"

#: Worker family-availability witness — SEPARATE file + directory from
#: ``review_team.FAMILY_OUTAGE_STATE`` by design (the two planes never share a witness).
WORKER_FAMILY_AVAILABILITY_STATE = (
    Path.home() / ".cache" / "hapax" / "capability" / "worker-family-availability.json"
)

#: The ONLY codes that may degrade a worker family's availability — explicit high-confidence vendor
#: walls. NEVER UNKNOWN/TRANSIENT (ambiguous/retryable), and deliberately NOT AUTH_FAILURE (a single
#: bad credential must not mark a whole family unavailable). PROVIDER_OUTAGE is forward-compat: the
#: Claude/Codex CLI table emits only QUOTA_EXHAUSTION today, but a structured provider-outage signal
#: (e.g. via the glmcp/zai path) should witness too.
WORKER_AVAILABILITY_DEGRADE_CODES: frozenset[FailureCode] = frozenset(
    {FailureCode.QUOTA_EXHAUSTION, FailureCode.PROVIDER_OUTAGE}
)


def append_failure_receipt_record(
    *,
    task_id: str,
    lane: str,
    returncode: int,
    receipt: FailureReceipt,
    now_iso: str,
    ledger_path: Path | None = None,
) -> bool:
    """Append one lossless failure-classification line. Fail-open (never blocks the dispatch path).

    The line is ``FailureReceipt.model_dump()`` plus an envelope (``ts``/``task_id``/``lane``/
    ``returncode``); it is NOT a bare ``FailureReceipt`` (that model has no ts/lane/returncode and is
    ``extra="forbid"``), so a reader must treat the line as envelope + dumped receipt, not
    ``FailureReceipt.model_validate``.
    """

    record = {
        "ts": now_iso,
        "task_id": task_id,
        "lane": lane,
        "returncode": returncode,
        **receipt.model_dump(),
    }
    return append_jsonl(ledger_path or FAILURE_CLASSIFICATION_LEDGER, record, raising=False)


def update_worker_family_availability(
    *,
    family: str,
    code: FailureCode,
    now_iso: str,
    state_path: Path | None = None,
) -> bool:
    """GUARDED witness write. Returns ``True`` iff a degrade key was written for ``family``.

    Writes ``{family: now_iso}`` ONLY when ``code`` is in :data:`WORKER_AVAILABILITY_DEGRADE_CODES`.
    Any other code (incl. UNKNOWN/TRANSIENT) CLEARS the family key if present (recovery, mirroring
    ``review_team.update_family_outage``) and is otherwise a complete no-op (the state file is not
    created). Writes exactly one key — the failing lane's own ``family`` — so it cannot flip a
    sibling. Atomic: tempfile + ``os.replace`` under an exclusive ``flock`` on the ``.lock`` sidecar.
    """

    state_path = state_path or WORKER_FAMILY_AVAILABILITY_STATE
    state_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = state_path.with_name(f"{state_path.name}.lock")
    wrote = False
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                if not isinstance(state, dict):
                    state = {}
            except (OSError, json.JSONDecodeError):
                state = {}
            if code in WORKER_AVAILABILITY_DEGRADE_CODES:
                state[family] = now_iso
                wrote = True
                changed = True
            elif family in state:
                state.pop(family, None)  # recovery: clear a prior degrade
                changed = True
            else:
                changed = False  # no-degrade default + nothing to clear -> do not create the file
            if changed:
                with tempfile.NamedTemporaryFile(
                    "w",
                    encoding="utf-8",
                    dir=state_path.parent,
                    prefix=f"{state_path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as tmp:
                    tmp.write(json.dumps(state, indent=1))
                    tmp_path = Path(tmp.name)
                os.replace(tmp_path, state_path)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return wrote
