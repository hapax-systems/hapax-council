"""Preset recruitment consumer — closes the director→chain mutation loop.

The compositor's director loop emits ``compositional_impingement`` events with
``preset.bias`` payloads (e.g. ``preset.bias = audio-reactive``). The
``AffordancePipeline`` recruits a matching ``fx.family.<family>`` capability
and records the family in ``/dev/shm/hapax-compositor/recent-recruitment.json``
under the ``preset.bias`` key.

Without a consumer that reads that recruitment and mutates the chain, the
recruitment is observable but inert. ``random_mode.py`` was the historical
bridge but is dead code — never wired into a service or compositor invocation
site. The director-driven recruitment of fx-presets is the operator's stated
architecture (per 2026-04-20 directive: "no random_mode; all effects recruited
by Hapax via director loop and content programming").

This module is the bridge: read the recruited family, pick a preset within it
via ``preset_family_selector.pick_and_load_mutated``, and write the resulting
graph to ``random_mode.MUTATION_FILE`` (the same atomic-rename mutation bus
the chat reactor and chain builder write to).

Cooldown: 8s minimum between activations even when recruitment ticks every
second — preset.bias TTL is ~8s, the next director compositional impingement
will refresh + we re-check at the next state-reader tick. Without cooldown the
chain would thrash visibly to viewers.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from .preset_family_selector import family_names, pick_and_load_mutated
from .random_mode import MUTATION_FILE

log = logging.getLogger(__name__)

RECRUITMENT_FILE = Path("/dev/shm/hapax-compositor/recent-recruitment.json")
COOLDOWN_S = 8.0
"""Minimum seconds between consecutive consumer activations.

Matches the director's preset.bias TTL — recruitments that re-fire within
the cooldown window represent the same compositional moment, not a new
intent. Without cooldown the chain mutation thrashes visibly when the
director loop ticks at sub-cooldown intervals.
"""

_last_activation_t: float = 0.0
_last_family_activated: str | None = None
_last_recruitment_ts_seen: float = 0.0


def process_preset_recruitment() -> bool:
    """Read recent recruitment, mutate chain when a fresh fx.family was recruited.

    Returns True iff a chain mutation was written this tick. Idempotent —
    repeated calls within the cooldown window are no-ops.
    """
    global _last_activation_t, _last_family_activated, _last_recruitment_ts_seen
    if not RECRUITMENT_FILE.exists():
        return False
    try:
        payload = json.loads(RECRUITMENT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    bias = payload.get("families", {}).get("preset.bias")
    if not isinstance(bias, dict):
        return False
    family = bias.get("family")
    last_recruited_ts = bias.get("last_recruited_ts")
    if not isinstance(family, str) or not isinstance(last_recruited_ts, (int, float)):
        return False
    if family not in family_names():
        log.debug("preset recruitment family unknown: %r", family)
        return False
    # Two short-circuits before doing the picker work:
    # 1) Already saw and consumed this exact recruitment ts → no-op.
    if last_recruited_ts <= _last_recruitment_ts_seen:
        return False
    # 2) Cooldown gate. Fresh recruitments that arrive within the cooldown
    #    window after a previous activation are dropped. This protects the
    #    chain from thrashing when the director loop ticks faster than the
    #    cooldown allows.
    now = time.monotonic()
    if (now - _last_activation_t) < COOLDOWN_S:
        return False
    seed = int(last_recruited_ts) ^ os.getpid()
    hit = pick_and_load_mutated(family, last=_last_family_activated, seed=seed)
    if hit is None:
        log.debug("preset_family_selector returned no preset for family=%r", family)
        return False
    preset_name, graph = hit
    try:
        MUTATION_FILE.parent.mkdir(parents=True, exist_ok=True)
        MUTATION_FILE.write_text(json.dumps(graph))
    except OSError:
        log.warning("preset recruitment mutation write failed", exc_info=True)
        return False
    _last_activation_t = now
    _last_family_activated = preset_name
    _last_recruitment_ts_seen = float(last_recruited_ts)
    log.info(
        "preset recruitment: family=%r preset=%r (recruitment_ts=%.3f)",
        family,
        preset_name,
        last_recruited_ts,
    )
    return True
