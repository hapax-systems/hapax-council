"""Operator-toggleable source-mode state for the dual-processor audio arbiter.

Per `docs/superpowers/specs/2026-04-21-evilpet-s4-dynamic-dual-processor-design.md`
§3.1, three audio sources (vinyl, mpc, sfx) default to dry but are
operator-toggleable into modulated mode. This module owns the state-file
contract: the CLI (`scripts/hapax-source-mode`) writes, the Phase B arbiter
reads. No runtime dependency on pydantic-ai or PipeWire — pure stdlib so
the CLI stays fast and the module is usable before the arbiter ships.

Semantics
---------

State file: ``/dev/shm/hapax-audio-router/source-mode.json``
JSON shape: ``{"vinyl": "dry"|"modulated", "mpc": ..., "sfx": ...}``

Absent file, missing key, unrecognised value, or any parse error **fails
safe to dry**. That is: if the operator has not explicitly asked for
modulation, the source stays dry. This matches the operator directive
that vinyl / MPC / SFX remain dry-default, with modulation always an
explicit opt-in.

Voice and music sources are NOT represented here — they are
unconditionally modulated per the "no naked signal" directive, and any
entry for them in the file is ignored.
"""

from __future__ import annotations

import json
import os
import tempfile
from enum import StrEnum
from pathlib import Path
from typing import Final

TOGGLEABLE_SOURCES: Final[tuple[str, ...]] = ("vinyl", "mpc", "sfx")
"""Sources that honour the state file. Voice + music are always modulated."""

DEFAULT_STATE_PATH: Final[Path] = Path("/dev/shm/hapax-audio-router/source-mode.json")


class SourceMode(StrEnum):
    """Per-source routing mode.

    ``DRY`` — arbiter bypasses both engines for this source; raw passthrough.
    ``MODULATED`` — arbiter may route through primary/secondary per §3.3.
    """

    DRY = "dry"
    MODULATED = "modulated"


def read_modes(path: Path = DEFAULT_STATE_PATH) -> dict[str, SourceMode]:
    """Return the current mode for every toggleable source.

    Missing file / malformed JSON / unknown values all fall back to
    ``SourceMode.DRY`` for the affected key. Unknown keys in the file
    are silently ignored. Voice/music keys are never returned.

    The result always contains exactly ``TOGGLEABLE_SOURCES`` as keys.
    """
    raw: dict[str, object]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}

    result: dict[str, SourceMode] = {}
    for source in TOGGLEABLE_SOURCES:
        value = raw.get(source)
        if isinstance(value, str):
            try:
                result[source] = SourceMode(value.lower())
                continue
            except ValueError:
                pass
        result[source] = SourceMode.DRY
    return result


def write_mode(
    source: str,
    mode: SourceMode,
    path: Path = DEFAULT_STATE_PATH,
) -> dict[str, SourceMode]:
    """Set ``source`` to ``mode`` and return the merged state.

    Atomic write via tmp + rename so a reader can never observe a
    half-written file. Parent directory created on demand. Source name
    must be in ``TOGGLEABLE_SOURCES`` — attempting to toggle voice or
    music raises ``ValueError`` (enforced contract; the arbiter ignores
    those keys but callers should not fake it).
    """
    if source not in TOGGLEABLE_SOURCES:
        raise ValueError(
            f"source {source!r} is not toggleable; must be one of {TOGGLEABLE_SOURCES}"
        )

    current = read_modes(path)
    current[source] = mode

    payload = {key: value.value for key, value in current.items()}
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(payload, fp, sort_keys=True)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return current


__all__ = [
    "DEFAULT_STATE_PATH",
    "TOGGLEABLE_SOURCES",
    "SourceMode",
    "read_modes",
    "write_mode",
]
