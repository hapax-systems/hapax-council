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
* ``strength=0.6`` — peer-relay broadcasts deserve mid-range salience;
  enough to register on the affordance pipeline but not crowd out
  sensory impingements.

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
        "strength": _DEFAULT_STRENGTH,
        "interrupt_token": _interrupt_token(filename),
        "trace_id": uuid.uuid4().hex,
        "content": {
            "narrative": _read_first_nonempty(path),
            "filename": filename,
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

    for path in sorted(inflections_dir.glob(_FILENAME_GLOB)):
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
