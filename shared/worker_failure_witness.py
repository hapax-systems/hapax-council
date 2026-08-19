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
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
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


#: Content-addressed store for externalised ``raw_signal`` payloads. Sibling of the
#: ledger, so a reader that has one has the other.
FAILURE_SIGNAL_BLOB_DIR = Path.home() / ".cache" / "hapax" / "failure-signals"

#: Signals at or below this stay INLINE. Small payloads are worth more readable in
#: the ledger than deduplicated, and the bloat is entirely in the large ones.
RAW_SIGNAL_INLINE_MAX_BYTES = 4096


def _externalise_raw_signal(dumped: dict) -> dict:
    """Replace a large ``raw_signal`` with a content-addressed reference.

    MEASURED 2026-08-19 on appendix: the ledger was **732.7 MB across 3,614
    records**, and ``raw_signal`` accounted for **731.1 MB of it (99.8%)**. Of those
    3,614 payloads only **11 were distinct** — a single 186,359-character string
    repeated **3,589 times**, a 328x dedupe ratio. The ledger was re-embedding the
    same error blob on every failure.

    Content addressing collapses that to one file on disk plus a hash per record:
    ~732 MB becomes well under 1 MB, with the payload still byte-for-byte
    retrievable. **This is losslessness preserved by indirection, not truncation** —
    the docstring contract of the caller is "one lossless line", and dropping bytes
    would break it.

    FORWARD-ONLY. Existing ledger lines are left exactly as they are; no history
    rewrite. A reader must therefore handle BOTH shapes: an inline ``raw_signal``
    string, or ``raw_signal_ref`` naming the blob.

    FAIL-OPEN, and narrowing rather than widening: if the blob cannot be written,
    the payload stays INLINE — the previous behaviour — and ``raw_signal_ref_error``
    records why. That degrades to the status quo instead of silently dropping
    evidence, and it is never silent.
    """
    raw = dumped.get("raw_signal")
    if not isinstance(raw, str):
        return dumped
    # surrogatepass, NOT replace. Python str admits lone surrogates (a subprocess
    # decoding bytes with errors="surrogateescape" produces them routinely, which is
    # exactly how a raw failure signal is captured). Under errors="replace" each one
    # becomes "?" — and since the inline copy is then dropped, that silently destroys
    # the only remaining copy. The contract here is LOSSLESS; "replace" quietly broke
    # it for precisely the payloads most likely to appear in a failure ledger.
    # Readers must decode with the same error mode: see read_raw_signal().
    encoded = raw.encode("utf-8", "surrogatepass")
    if len(encoded) <= RAW_SIGNAL_INLINE_MAX_BYTES:
        return dumped

    digest = hashlib.sha256(encoded).hexdigest()
    out = dict(dumped)
    tmp_path: Path | None = None
    try:
        FAILURE_SIGNAL_BLOB_DIR.mkdir(parents=True, exist_ok=True)
        blob = FAILURE_SIGNAL_BLOB_DIR / f"{digest}.txt"
        if not blob.exists():
            # Atomic, and safe against concurrent writers of identical content:
            # same digest means same bytes, so a racing rename is a no-op.
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=FAILURE_SIGNAL_BLOB_DIR, delete=False
            ) as tmp:
                tmp.write(encoded)
                tmp_path = Path(tmp.name)
            # Last statement in the try: if it succeeds there is no exception, so the
            # cleanup below never runs against a renamed file. (An earlier revision also
            # cleared tmp_path here; that assignment was unreachable-dead — nothing
            # followed it — and guarded only a hypothetical future edit.)
            os.replace(tmp_path, blob)
    except OSError as exc:
        # Keep the payload inline (status quo) and say so. Never blocks dispatch.
        # Clean up the temp file: if the write succeeded and the rename did not, an
        # orphan of full payload size would otherwise accumulate in the blob dir on
        # every retry — a storage failure that grows storage is the wrong shape.
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                # Best-effort by design. The temp may already be gone (a concurrent
                # writer of identical content renamed it), and a cleanup failure must
                # never mask the original OSError being reported below.
                pass
        out["raw_signal_ref_error"] = f"{type(exc).__name__}: {exc}"
        return out

    out.pop("raw_signal", None)
    out["raw_signal_ref"] = {
        "sha256": digest,
        "bytes": len(encoded),
        "path": str(blob),
    }
    return out


def read_raw_signal(record: Mapping[str, object]) -> str | None:
    """Recover a ledger record's raw signal, whichever shape it is stored in.

    Emitting ``raw_signal_ref`` without shipping a reader would have made the ledger
    write-only: `shared/jsonl_tail.py` returns lines, nothing resolves the blob, and
    every existing consumer expects an inline ``raw_signal``. A format change with no
    consumer is not forward-compatible, it is just broken later.

    Handles BOTH shapes, because the change is forward-only and old lines keep the
    inline string:
      * inline   -> ``record["raw_signal"]`` returned as-is
      * external -> ``record["raw_signal_ref"]`` resolved from disk

    VERIFIES rather than trusts. The blob is content-addressed, so both the byte
    length and the SHA-256 are checkable, and a mismatch means corruption or a
    truncated write — exactly what the reader exists to catch. Returns ``None`` on
    any failure rather than raising: this sits on a diagnostic path and must not
    become a second outage. Decodes with ``surrogatepass`` to match the writer.
    """
    inline = record.get("raw_signal")
    if isinstance(inline, str):
        return inline

    ref = record.get("raw_signal_ref")
    if not isinstance(ref, Mapping):
        return None

    # The digest and length are REQUIRED, not optional. An earlier revision checked each
    # only `if isinstance(...)`, so a ref carrying neither skipped verification entirely
    # while the docstring claimed the reader verifies rather than trusts.
    expected_sha = ref.get("sha256")
    expected_bytes = ref.get("bytes")
    if not isinstance(expected_sha, str) or not isinstance(expected_bytes, int):
        return None

    # CONFINE the read to the blob directory, and require the filename to be the digest it
    # declares. Without this the reader resolves whatever `path` the record carries and
    # returns its contents — an arbitrary-file-read reachable from a ledger line. The ledger
    # is written by this module today, but it is a plain JSONL file on disk that anything can
    # append to, and its whole purpose is to carry hostile provider output. Content-addressing
    # makes the check free: the only legitimate path is <blob dir>/<sha256>.txt.
    path = ref.get("path")
    if not isinstance(path, str):
        return None
    try:
        resolved = Path(path).resolve()
        blob_dir = FAILURE_SIGNAL_BLOB_DIR.resolve()
    except OSError:
        return None
    if resolved.parent != blob_dir or resolved.name != f"{expected_sha}.txt":
        return None

    try:
        data = resolved.read_bytes()
    except OSError:
        return None

    if len(data) != expected_bytes:
        return None
    if hashlib.sha256(data).hexdigest() != expected_sha:
        return None

    return data.decode("utf-8", "surrogatepass")


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
        **_externalise_raw_signal(receipt.model_dump()),
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
