"""Heartbeat tick implementation.

See :mod:`agents.preset_bias_heartbeat` for design rationale + audit
provenance. This module owns the actual file IO + tick loop.

The tick has four observable side effects:

1. Reads ``recent-recruitment.json`` and inspects the ``preset.bias``
   entry's ``last_recruited_ts`` field.
2. If the entry is fresh (``time.time() - last_recruited_ts <
   DEFAULT_FRESHNESS_S``), no-op — LLM recruitment is alive, the
   heartbeat must not interfere.
3. If the entry is stale or missing, picks a random family from
   :func:`agents.studio_compositor.preset_family_selector.family_names`
   (uniform) and writes a new ``preset.bias`` entry under
   ``families.preset.bias`` with ``source="heartbeat-fallback"``.
4. Logs the fire to journal so observability can correlate heartbeat
   fires with downstream chain-mutation events.

The atomic write uses
:func:`agents.studio_compositor.atomic_io.atomic_write_json` —
``tempfile.mkstemp`` + ``fsync`` + ``os.replace`` — so concurrent
readers (the preset_recruitment_consumer in particular) never see a
partial-write window.

Test isolation: every public function takes its file paths + clock as
parameters with sensible defaults so test fixtures can substitute
:class:`pathlib.Path` instances under ``tmp_path`` and freeze ``now``.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agents.studio_compositor.atomic_io import atomic_write_json
from agents.studio_compositor.preset_family_selector import family_names

log = logging.getLogger(__name__)

# Canonical SHM path. Mirror of
# ``agents.studio_compositor.preset_recruitment_consumer.RECRUITMENT_FILE``
# — reading the same surface the consumer reads.
RECRUITMENT_FILE: Path = Path("/dev/shm/hapax-compositor/recent-recruitment.json")

# Marker stamped on every entry this agent writes. Distinguishes
# heartbeat-origin from LLM-origin recruitment in
# ``recent-recruitment.json`` so observability can compute the LLM
# recruitment rate and the operator can decide when the heartbeat is
# no longer needed (per audit §5 U1 + closing remark in module
# docstring).
HEARTBEAT_SOURCE: str = "heartbeat-fallback"

# Tick cadence — how often :func:`run_forever` calls
# :func:`tick_once`. The audit says "30s background tick"; this matches
# QW2's ETA + variance commitment. Half the freshness window so a single
# missed tick doesn't break the freshness invariant.
DEFAULT_TICK_S: float = 30.0

# Freshness window — how recent a ``preset.bias`` entry must be for the
# heartbeat to defer to LLM recruitment. The audit says ">=60s" stale
# triggers fallback; this is the reciprocal threshold.
DEFAULT_FRESHNESS_S: float = 60.0


def read_recruitment(path: Path = RECRUITMENT_FILE) -> dict[str, Any]:
    """Read ``recent-recruitment.json``; return ``{}`` on any failure.

    The contract intentionally swallows OSError + JSONDecodeError so a
    malformed/missing file degrades to "stale" — the heartbeat then
    fires + writes a fresh entry. This matches the
    :mod:`preset_recruitment_consumer`'s read contract (same shape).

    Logs an INFO when the file is missing (expected on first boot
    before any recruitment), WARNING when the file exists but is
    malformed (recoverable but indicates a writer bug elsewhere).
    """
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning(
            "preset.bias heartbeat: malformed recruitment file at %s — "
            "treating as stale and overwriting (%s)",
            path,
            exc,
        )
        return {}


def is_fresh(
    payload: dict[str, Any],
    *,
    freshness_s: float = DEFAULT_FRESHNESS_S,
    now: float | None = None,
) -> bool:
    """Return True iff ``payload`` has a ``preset.bias`` entry younger than
    ``freshness_s`` seconds.

    A missing / non-dict / no-timestamp / older-than-freshness entry is
    NOT fresh — heartbeat fires.
    """
    families = payload.get("families")
    if not isinstance(families, dict):
        return False
    entry = families.get("preset.bias")
    if not isinstance(entry, dict):
        return False
    ts = entry.get("last_recruited_ts")
    if not isinstance(ts, (int, float)):
        return False
    if now is None:
        now = time.time()
    return (now - float(ts)) < freshness_s


def pick_family(
    *,
    rng: random.Random | None = None,
    families: list[str] | None = None,
) -> str:
    """Uniform-sample a family name from
    :func:`preset_family_selector.family_names`.

    The caller can inject a seeded RNG (tests use this) or a custom
    family list (also tests). Production calls take both defaults; the
    family list comes off disk inventory at every call so any
    operator edit to ``FAMILY_PRESETS`` lands on the next tick without
    a restart — no hardcoded list drift.
    """
    chooser = rng if rng is not None else random
    family_pool = families if families is not None else family_names()
    if not family_pool:
        # Defensive: with an empty pool there's nothing to pick. The
        # caller's logging will surface the anomaly; we bubble up an
        # error rather than silently no-op so the operator notices.
        raise RuntimeError(
            "preset.bias heartbeat: empty family pool — "
            "preset_family_selector.FAMILY_PRESETS may be misconfigured"
        )
    return chooser.choice(sorted(family_pool))


def write_heartbeat_entry(
    family: str,
    *,
    path: Path = RECRUITMENT_FILE,
    now: float | None = None,
) -> None:
    """Atomically upsert a ``preset.bias`` entry into the recruitment file.

    Reads the current file (if any), preserves all sibling family
    entries (overlay.emphasis, structural.intent, etc.), then writes
    the merged payload back via
    :func:`agents.studio_compositor.atomic_io.atomic_write_json`. The
    atomic-write helper does the tmp + fsync + rename dance that
    guarantees no partial-read window.

    The new entry carries:

    - ``family`` — the chosen family name
    - ``last_recruited_ts`` — current wall-clock time
    - ``ttl_s`` — 8s, mirroring the director-loop preset.bias TTL
    - ``source`` — ``"heartbeat-fallback"`` — the observability marker
      that distinguishes heartbeat from LLM origin per audit §5 U1
    """
    if now is None:
        now = time.time()
    current = read_recruitment(path)
    families = current.get("families")
    if not isinstance(families, dict):
        families = {}
    families["preset.bias"] = {
        "family": family,
        "last_recruited_ts": now,
        "ttl_s": 8.0,
        "source": HEARTBEAT_SOURCE,
    }
    payload = {"families": families, "updated_at": now}
    atomic_write_json(payload, path)


def tick_once(
    *,
    path: Path = RECRUITMENT_FILE,
    freshness_s: float = DEFAULT_FRESHNESS_S,
    now: float | None = None,
    rng: random.Random | None = None,
) -> str | None:
    """Single tick — returns the chosen family name when fired, ``None`` when no-op.

    Test entry point. The production loop in :func:`run_forever`
    calls this every :data:`DEFAULT_TICK_S` seconds; tests call it
    directly with mocked clock + seeded RNG to assert behaviour
    deterministically.

    The function is intentionally NOT atomic across read+decide+write —
    if a real LLM recruitment lands in the millisecond between our
    read-fresh check and our write, the LLM entry is overwritten
    (regrettable but the heartbeat-fallback marker makes the
    overwrite visible to observability). The race window is small
    enough in practice that the 30s tick cadence + 60s freshness
    window mean overwrites are rare; the "no replacement of LLM"
    invariant holds in expectation, not strictly.
    """
    payload = read_recruitment(path)
    if is_fresh(payload, freshness_s=freshness_s, now=now):
        return None
    family = pick_family(rng=rng)
    last_ts = _last_preset_bias_ts(payload)
    age_s = _age_s(last_ts, now=now)
    write_heartbeat_entry(family, path=path, now=now)
    if age_s is None:
        log.info(
            "preset.bias heartbeat fallback fired: family=%s (no prior LLM recruitment on record)",
            family,
        )
    else:
        log.info(
            "preset.bias heartbeat fallback fired: family=%s (LLM recruitment stale %.1fs)",
            family,
            age_s,
        )
    return family


def _last_preset_bias_ts(payload: dict[str, Any]) -> float | None:
    """Extract the ``preset.bias.last_recruited_ts`` from a payload, or
    ``None`` when the entry is missing / malformed.

    Helper for the log-format split in :func:`tick_once`.
    """
    families = payload.get("families")
    if not isinstance(families, dict):
        return None
    entry = families.get("preset.bias")
    if not isinstance(entry, dict):
        return None
    ts = entry.get("last_recruited_ts")
    if not isinstance(ts, (int, float)):
        return None
    return float(ts)


def _age_s(ts: float | None, *, now: float | None = None) -> float | None:
    """Compute the age-in-seconds of a timestamp, or ``None`` when absent."""
    if ts is None:
        return None
    if now is None:
        now = time.time()
    return max(0.0, now - ts)


def run_forever(
    *,
    tick_s: float = DEFAULT_TICK_S,
    freshness_s: float = DEFAULT_FRESHNESS_S,
    path: Path = RECRUITMENT_FILE,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Production tick loop — fires :func:`tick_once` every ``tick_s`` seconds.

    Sleeps deterministically between ticks so journal logs show a
    consistent cadence the operator can correlate with downstream
    chain-mutation events. The ``sleep`` injection point lets tests
    bound the loop without monkey-patching :mod:`time`.

    Log line on entry includes the configured cadence + freshness
    window so the operator can confirm the unit is running with
    expected parameters.
    """
    log.info(
        "preset.bias heartbeat starting: tick=%.1fs freshness=%.1fs path=%s pid=%d",
        tick_s,
        freshness_s,
        path,
        os.getpid(),
    )
    while True:
        try:
            tick_once(path=path, freshness_s=freshness_s)
        except Exception:
            # Log + continue — the daemon must never die from a single
            # bad tick. A persistent failure surfaces via journal
            # repetition (operator alerts on the warning rate).
            log.warning("preset.bias heartbeat tick failed", exc_info=True)
        sleep(tick_s)
