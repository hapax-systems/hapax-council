"""M8 stem-recorder day-roll chronicle emitter.

Watches the stem-archive directory and emits an `m8.stem.day_rolled`
ChronicleEvent each time a per-day FLAC file finishes (the recorder
script closes a file at UTC midnight). The event payload carries the
filename, duration, size, sample rate, channels, and bit depth so
downstream analysis (auto-clip-shorts-livestream-pipeline, post-hoc
stem queries) can pick the right window to operate on.

Designed as a side-process to the parec/sox recorder — keeps the bash
script narrow (just records audio) and the chronicle integration in
Python where the typed event API lives.

cc-task: m8-stem-archive-recorder
"""

from __future__ import annotations

import logging
import os
import secrets
import subprocess
import time
from pathlib import Path

from shared.chronicle import ChronicleEvent, record

log = logging.getLogger(__name__)

_DEFAULT_STEM_DIR = Path(os.environ.get("HAPAX_M8_STEM_DIR", "/var/lib/hapax/m8-stems"))
_DEFAULT_CURSOR = Path(
    os.environ.get(
        "HAPAX_M8_STEM_CURSOR", str(Path.home() / ".cache/hapax/m8-stem-emitter-cursor.txt")
    )
)


def _flac_metadata(path: Path) -> dict | None:
    """Return {duration_s, sample_rate, channels, bit_depth} via `sox --i`.

    Returns None if sox is unavailable or the file isn't readable.
    """
    try:
        result = subprocess.run(
            ["sox", "--i", str(path)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None

    out: dict = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("Sample Rate"):
            out["sample_rate"] = int(line.split(":")[1].strip())
        elif line.startswith("Channels"):
            out["channels"] = int(line.split(":")[1].strip())
        elif line.startswith("Sample Encoding"):
            # e.g. "24-bit Signed Integer PCM"
            tokens = line.split(":", 1)[1].strip().split()
            if tokens and tokens[0].endswith("-bit"):
                out["bit_depth"] = int(tokens[0].split("-")[0])
        elif line.startswith("Duration"):
            # e.g. "00:30:00.00 = 79380000 samples = 135000 CDDA sectors"
            time_str = line.split(":", 1)[1].strip().split()[0]
            try:
                h, m, s = time_str.split(":")
                out["duration_s"] = round(int(h) * 3600 + int(m) * 60 + float(s), 3)
            except ValueError:
                pass
    return out or None


def _read_cursor(cursor_path: Path) -> set[str]:
    if not cursor_path.exists():
        return set()
    try:
        return {line.strip() for line in cursor_path.read_text().splitlines() if line.strip()}
    except OSError:
        return set()


def _write_cursor(cursor_path: Path, seen: set[str]) -> None:
    cursor_path.parent.mkdir(parents=True, exist_ok=True)
    cursor_path.write_text("\n".join(sorted(seen)) + "\n")


def _new_trace_id() -> tuple[str, str]:
    """Generate a fresh trace_id + span_id for an emitted event."""
    return (secrets.token_hex(16), secrets.token_hex(8))


def emit_for_completed_files(
    *,
    stem_dir: Path = _DEFAULT_STEM_DIR,
    cursor_path: Path = _DEFAULT_CURSOR,
    now: float | None = None,
) -> int:
    """Scan stem_dir and emit chronicle events for files newly completed.

    A FLAC file is "complete" when it hasn't been modified for 60s
    (longer than the worst-case sox flush). The cursor tracks which
    completed files have already been emitted.

    Returns the number of events emitted on this scan.
    """
    if not stem_dir.is_dir():
        return 0

    now_ts = now if now is not None else time.time()
    seen = _read_cursor(cursor_path)
    emitted = 0

    for path in sorted(stem_dir.glob("*.flac")):
        if path.name in seen:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if (now_ts - stat.st_mtime) < 60.0:
            # Likely still being written — skip until next scan.
            continue

        meta = _flac_metadata(path)
        # ``salience`` lifts day-roll events above the chronicle-ticker
        # ward's ``_SALIENCE_THRESHOLD`` (0.7) so the operator can see
        # daily archive completion without ``m8_stem_recorder`` joining
        # the source allow-list. Day-rolls are once-per-day, structurally
        # high-salience — 0.95 keeps them just under the synthetic
        # ceiling so genuinely critical events can still rank above.
        payload = {
            "filename": path.name,
            "size_bytes": stat.st_size,
            "duration_s": meta.get("duration_s") if meta else None,
            "sample_rate": meta.get("sample_rate") if meta else None,
            "channels": meta.get("channels") if meta else None,
            "bit_depth": meta.get("bit_depth") if meta else None,
            "salience": 0.95,
        }
        trace_id, span_id = _new_trace_id()
        event = ChronicleEvent(
            ts=stat.st_mtime,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=None,
            source="m8_stem_recorder",
            event_type="m8.stem.day_rolled",
            payload=payload,
        )
        try:
            record(event)
        except OSError as exc:
            log.warning("m8_stem_emitter: chronicle record failed for %s: %s", path.name, exc)
            continue
        seen.add(path.name)
        emitted += 1

    if emitted:
        _write_cursor(cursor_path, seen)
    return emitted


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    count = emit_for_completed_files()
    log.info("m8_stem_emitter: emitted %d day-roll events", count)


if __name__ == "__main__":
    main()
