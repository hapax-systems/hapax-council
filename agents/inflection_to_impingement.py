"""AUDIT-20 — relay inflection → impingement bridge.

Tails ``~/.cache/hapax/relay/inflections/*.md`` and emits one
``Impingement`` per new inflection file onto
``/dev/shm/hapax-dmn/impingements.jsonl``. Closes the QM2 (#1293)
instrumentation loop — the sampler had infrastructure but no events
were flowing because session inflections never reached the bus.

## Idempotency

Stable id ``inflection-{md5(filename)[:12]}``. The cursor file at
``~/.cache/hapax/relay/inflections/.bridge-cursor`` records every
filename that has already produced an impingement; reruns on the same
directory are no-ops.

## Type & strength

Inflection events are explicit peer-session broadcasts (mode-switch,
phase-shipped, scope-resolution). Mapped onto ``ImpingementType``:

* ``PATTERN_MATCH`` — the inflection filename suffix functions as an
  interrupt token (``mode-switch``, ``phase-shipped``, etc.).
* ``strength`` — from the inflection's own ``**Severity:**`` header
  (P0/P1/P2 → 0.95/0.75/0.5), falling back to 0.6 when none is
  declared. It was 0.6 for everything until 2026-08-10, so an
  active-data-loss P0 and a de-escalated note reached the affordance
  pipeline at identical salience. Severity is a declared,
  author-independent field; this is deliberately not author weighting.

## Run modes

Default: oneshot tick consumed by ``hapax-inflection-bridge.timer``.

    uv run python -m agents.inflection_to_impingement

``--dry-run`` lists what would be emitted without touching either the
cursor or the bus.

``--backfill`` ignores the existing cursor and rewrites it from the
current directory contents — useful after operator-staged files are
added or after a stale cursor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import time
import uuid
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_INFLECTIONS_DIR: Path = Path.home() / ".cache" / "hapax" / "relay" / "inflections"
DEFAULT_CURSOR_FILENAME: str = ".bridge-cursor"
DEFAULT_IMPINGEMENT_PATH: Path = Path("/dev/shm/hapax-dmn/impingements.jsonl")

_DEFAULT_STRENGTH: float = 0.6
_FILENAME_GLOB: str = "*.md"

#: Declared severity -> impingement strength. Every inflection used to enter the affordance
#: pipeline at _DEFAULT_STRENGTH, so a P0 reading "ACTIVE DATA LOSS, still running at time of
#: writing" and a P1 the operator himself de-escalated as "just a note" arrived at IDENTICAL
#: salience. Measured 2026-08-10: 16 P0 and 4 P1 in the directory, all stamped 0.6.
#:
#: This is SEVERITY — a declared, author-independent field. It is deliberately not author
#: weighting: no measured reliability exists for any author on this surface, and inventing one
#: would be the unmeasured weight the doctrine forbids. The parse is ported from
#: hooks/scripts/session-context.sh, which already reads this header correctly and is pinned by
#: tests/hooks/test_session_context_p0_broadcast.py. Port it; do not redesign it.
_SEVERITY_STRENGTH: dict[str, float] = {"P0": 0.95, "P1": 0.75, "P2": 0.5}

#: The header form every live inflection already uses: `**Severity:** P0`.
_SEVERITY_RE = re.compile(r"^\*\*Severity:\*\*\s*(P[0-2])\b", re.M)

#: Far enough to reach the header block (severity sits on line 3 of every live file), not so far
#: that ranking a long inflection means loading it.
_HEADER_SCAN_CHARS: int = 4096


def _stable_id(filename: str) -> str:
    digest = hashlib.md5(  # noqa: S324 — non-security identifier hash
        filename.encode("utf-8"), usedforsecurity=False
    ).hexdigest()
    return f"inflection-{digest[:12]}"


def _interrupt_token(filename: str) -> str:
    """Extract a coarse token from the filename suffix.

    Inflection filenames follow ``YYYYMMDD-HHMMSS-{role-or-topic}-{slug}.md``.
    The token is the segment after the second dash, lowercased,
    truncated to 64 chars. Falls back to ``"inflection"`` for short
    filenames.
    """
    stem = Path(filename).stem
    parts = stem.split("-")
    if len(parts) < 3:
        return "inflection"
    return "-".join(parts[2:])[:64].lower()


def _read_first_nonempty(path: Path, max_chars: int = 240) -> str:
    """Read the first non-empty line of an inflection file as narrative.

    Strips leading markdown decoration (``#``, ``-``, etc.) so the
    affordance pipeline embeds clean prose.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip().lstrip("#").lstrip("-").strip()
                if line:
                    return line[:max_chars]
    except OSError as exc:
        log.warning("inflection read failed for %s: %s", path, exc)
    return Path(path).stem


def read_severity(path: Path) -> str | None:
    """The inflection's declared severity, or None when it declares none.

    None is returned rather than a default so the caller can distinguish "declared P2" from
    "declared nothing" — the second is a defect in the inflection, not a low-severity signal.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(_HEADER_SCAN_CHARS)
    except OSError as exc:
        log.warning("inflection severity read failed for %s: %s", path, exc)
        return None
    match = _SEVERITY_RE.search(head)
    return match.group(1) if match else None


def strength_for(path: Path) -> float:
    """Impingement strength from declared severity, falling back to the historical constant.

    The fallback is the OLD behaviour for undeclared files, not a floor for declared ones: an
    inflection that forgets its header is no less urgent than it was yesterday, and silently
    demoting it would make the bridge punish the author instead of reporting the gap.
    """
    severity = read_severity(path)
    if severity is None:
        return _DEFAULT_STRENGTH
    return _SEVERITY_STRENGTH.get(severity, _DEFAULT_STRENGTH)


def load_seen(cursor_path: Path) -> set[str]:
    if not cursor_path.exists():
        return set()
    return {line.strip() for line in cursor_path.read_text().splitlines() if line.strip()}


def write_seen(cursor_path: Path, seen: set[str]) -> None:
    cursor_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cursor_path.with_suffix(cursor_path.suffix + ".tmp")
    tmp.write_text("\n".join(sorted(seen)) + "\n")
    tmp.replace(cursor_path)


def build_impingement_record(path: Path, *, now: float | None = None) -> dict:
    """Compose the impingement-bus record for a single inflection file.

    Schema matches the existing producers (`agents/content_id_watcher/
    emitter.py` + `agents/hapax_daimonion/run_loops_aux.py`): a flat
    dict with `ts`, `source`, `type`, `strength`, plus content fields.
    """
    filename = path.name
    return {
        "id": _stable_id(filename),
        "timestamp": now if now is not None else time.time(),
        "source": "relay.inflection",
        "type": "pattern_match",
        "strength": strength_for(path),
        "interrupt_token": _interrupt_token(filename),
        "trace_id": uuid.uuid4().hex,
        "content": {
            "narrative": _read_first_nonempty(path),
            "filename": filename,
            # Recorded, never ranked on. `source` stays the constant "relay.inflection":
            # shared/affordance_pipeline.py hashes it into feed_habituation (:1070) and dedupes
            # on source + content_hash (:1333), so varying it per author would partition the
            # habituation key for EVERY producer on the bus and re-fire every seen impingement
            # as novel. A measurable regression bought for nothing.
            "severity": read_severity(path),
        },
    }


def append_impingement(record: dict, *, impingement_path: Path) -> None:
    impingement_path.parent.mkdir(parents=True, exist_ok=True)
    with impingement_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


def tick(
    *,
    inflections_dir: Path = DEFAULT_INFLECTIONS_DIR,
    impingement_path: Path = DEFAULT_IMPINGEMENT_PATH,
    cursor_filename: str = DEFAULT_CURSOR_FILENAME,
    dry_run: bool = False,
    backfill: bool = False,
) -> list[str]:
    """Emit one impingement per new inflection. Returns emitted filenames."""
    if not inflections_dir.exists():
        log.info("inflections dir %s does not exist; nothing to do", inflections_dir)
        return []

    cursor_path = inflections_dir / cursor_filename
    seen = set() if backfill else load_seen(cursor_path)
    emitted: list[str] = []

    # Severity first, then filename for a stable tie-break. Emission used to be pure
    # lexicographic filename order, so a P1 note went out ahead of fourteen P0s purely because
    # `b` sorts before `c`. Filename is a provenance-adjacent proxy — the exact kind of ranking
    # signal this bus is not supposed to use — and it was the only one in play.
    for path in sorted(
        inflections_dir.glob(_FILENAME_GLOB),
        key=lambda p: (-strength_for(p), p.name),
    ):
        if path.name in seen:
            continue
        record = build_impingement_record(path)
        if dry_run:
            log.info("DRY-RUN would emit: %s -> %s", path.name, record["id"])
        else:
            append_impingement(record, impingement_path=impingement_path)
        emitted.append(path.name)
        seen.add(path.name)

    if emitted and not dry_run:
        write_seen(cursor_path, seen)

    return emitted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inflections-dir", type=Path, default=DEFAULT_INFLECTIONS_DIR)
    parser.add_argument("--impingement-path", type=Path, default=DEFAULT_IMPINGEMENT_PATH)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="rebuild the cursor from existing files (re-emits everything)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    emitted = tick(
        inflections_dir=args.inflections_dir,
        impingement_path=args.impingement_path,
        dry_run=args.dry_run,
        backfill=args.backfill,
    )

    log.info("emitted %d impingement(s) from %s", len(emitted), args.inflections_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
