"""``M8InstrumentReveal`` — Dirtywave M8 LCD reveal lifecycle.

Cc-task ``activity-reveal-ward-p2-m8-migration`` (WSJF 4.0). Sister to
``CodingActivityReveal`` (P1) but **NOT a CairoSource** — M8 is an
``external_rgba`` source: ``m8c-hapax`` writes RGBA frames to
``/dev/shm/hapax-sources/m8-display.rgba`` and the compositor's SHM
reader composites them directly. The M8 ward has no Cairo paint path,
so the activity-reveal lifecycle owner is a pure mixin subclass —
mixing in ``HomageTransitionalSource`` would inherit dead Cairo
machinery the M8 path will never use.

What this class owns:

* **Device-presence detection** — reads ``m8-display.rgba`` mtime and
  reports presence when the SHM file is fresh (< staleness window).
* **Claim score assembly** — 0.0 when absent, 0.30 base when present,
  0.30 + 0.55 = 0.85 when ``studio.m8_lcd_reveal`` was recently
  recruited via the AffordancePipeline.
* **Family contract** — declares ``WARD_ID="m8-display"``,
  ``SOURCE_KIND="external_rgba"``, ``SUPPRESS_WHEN_ACTIVE=frozenset()``.
  The router projects suppression FROM other wards onto the M8 surface
  (e.g., DURF gates the M8 visibility); M8 itself doesn't suppress
  others.

What this class does NOT own:

* The C carry-fork (``packages/m8c-hapax/``) and its SHM publish path.
* The ``54-hapax-m8-instrument.conf`` audio routing.
* ``ward-properties.json`` opacity flips — those happen at the router
  layer, driven by the claim this class produces.
* Cairo painting — ``render_content`` is a no-op (the M8 surface is
  RGBA, not Cairo-painted).

Spec: ``hapax-research/specs/2026-05-01-activity-reveal-ward-family-spec.md``
§3.2.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from agents.studio_compositor.activity_reveal_ward import (
    ActivityRevealMixin,
)

log = logging.getLogger(__name__)

# Default SHM path the m8c-hapax carry-fork writes to. Matches
# ``config/compositor-layouts/default.json`` ``m8-display.params.shm_path``.
DEFAULT_SHM_PATH: Path = Path("/dev/shm/hapax-sources/m8-display.rgba")

# Recent-recruitment surface read for the affordance-recruited boost.
# Cc-task acceptance criterion ¶4: ``0.30 base + 0.55 affordance boost
# when studio.m8_lcd_reveal recruited``. The ``recent-recruitment.json``
# file is the same surface ``compositional_consumer._mark_recruitment``
# writes to; once a future PR wires ``AffordancePipeline.select`` to
# write recruitment outcomes for non-compositional capabilities (or a
# separate path for ``studio.*``), this class picks up the boost
# automatically. Until then, the boost path is observably-untriggered;
# the base score still surfaces so the router has something to compare.
DEFAULT_RECRUITMENT_PATH: Path = Path("/dev/shm/hapax-compositor/recent-recruitment.json")

# Device presence freshness window. The compositor reads M8 frames at
# 60 Hz so a 5 s mtime drift means the producer is dead. Matches the
# operator-physical smoke target of "ward visible within 2 s of
# m8c-hapax startup" — 5 s gives a clean margin without trip-firing
# on a normal 60 Hz update cadence.
DEFAULT_DEVICE_PRESENT_WINDOW_S: float = 5.0

# Recruitment freshness window. The recruitment marker is stamped
# every time the AffordancePipeline picks the capability; we treat a
# pick within the last 60 s as "currently recruited" so the boost
# survives the recruitment cooldown without going stale during a
# sustained reveal session.
DEFAULT_RECRUITMENT_WINDOW_S: float = 60.0

# Score components — exact values per cc-task acceptance criterion.
_BASE_SCORE_PRESENT: float = 0.30
_AFFORDANCE_RECRUITED_BOOST: float = 0.55

# The capability name we listen for on the recruitment surface.
_M8_REVEAL_CAPABILITY: str = "studio.m8_lcd_reveal"

# Feature flag — keeps the ward dormant by default until the operator
# explicitly opts into the activity-reveal-ward router lifecycle.
# The default OFF state preserves the rollback property documented in
# the cc-task: even with the source registered in default.json, the
# ward stays at opacity 0.0 unless this flag flips and the router
# sees a positive claim.
_FEATURE_FLAG_ENV: str = "HAPAX_ACTIVITY_REVEAL_M8_ENABLED"


def _feature_flag_enabled() -> bool:
    raw = os.environ.get(_FEATURE_FLAG_ENV, "0")
    return raw.strip().lower() not in ("", "0", "false", "no", "off")


def _shm_mtime_age_s(path: Path, *, now: float | None = None) -> float | None:
    """Return seconds since ``path`` was last modified, or None if missing.

    Defensive on every OS error — the compositor's render path must
    not break when the SHM file vanishes mid-tick.
    """

    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    ts = time.time() if now is None else now
    return max(0.0, ts - mtime)


def _read_recruitment_age_s(
    path: Path, capability: str, *, now: float | None = None
) -> float | None:
    """Return seconds since ``capability`` was last marked recruited.

    The recent-recruitment.json schema is
    ``{"families": {<name>: {"last_recruited_ts": float, ...}}}``. We
    look up the named capability and compute the age. Returns None for
    missing file, malformed JSON, missing key, or non-numeric ts.
    """

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    families = data.get("families") or {}
    if not isinstance(families, dict):
        return None
    entry = families.get(capability) or {}
    if not isinstance(entry, dict):
        return None
    ts = entry.get("last_recruited_ts")
    if not isinstance(ts, (int, float)):
        return None
    now_ts = time.time() if now is None else now
    return max(0.0, now_ts - float(ts))


class M8InstrumentReveal(ActivityRevealMixin):
    """Pure-lifecycle activity-reveal ward for the Dirtywave M8 LCD.

    NOT a CairoSource. ``render_content`` is a no-op; the M8's
    external_rgba SHM bridge owns frame delivery. The router consumes
    the visibility claim this class produces and writes the opacity
    flip to ``ward-properties.json``.
    """

    # ── Family contract ─────────────────────────────────────────────
    WARD_ID = "m8-display"
    SOURCE_KIND = "external_rgba"
    DEFAULT_HYSTERESIS_S = 30.0
    VISIBILITY_CEILING_PCT = 0.15
    # M8 doesn't suppress siblings; siblings (e.g. DURF) suppress IT
    # via their own SUPPRESS_WHEN_ACTIVE projection.
    SUPPRESS_WHEN_ACTIVE = frozenset()

    def __init__(
        self,
        *,
        shm_path: Path | None = None,
        recruitment_path: Path | None = None,
        device_present_window_s: float = DEFAULT_DEVICE_PRESENT_WINDOW_S,
        recruitment_window_s: float = DEFAULT_RECRUITMENT_WINDOW_S,
        start_poll_thread: bool = False,
    ) -> None:
        # The mixin owns the claim-lock, ceiling counter, and poll
        # plumbing. We default the poll thread OFF — the router drives
        # ``poll_once`` from its own tick loop so a separate thread per
        # ward is unnecessary. Tests set ``start_poll_thread=True`` when
        # they want the mixin's standalone polling.
        super().__init__(start_poll_thread=start_poll_thread)
        self._shm_path = shm_path if shm_path is not None else DEFAULT_SHM_PATH
        self._recruitment_path = (
            recruitment_path if recruitment_path is not None else DEFAULT_RECRUITMENT_PATH
        )
        self._device_present_window_s = device_present_window_s
        self._recruitment_window_s = recruitment_window_s

    # ── Subclass contract (ActivityRevealMixin abstracts) ──────────

    def _device_present(self, *, now: float | None = None) -> bool:
        """True iff the m8-display SHM has been touched recently."""

        age = _shm_mtime_age_s(self._shm_path, now=now)
        if age is None:
            return False
        return age <= self._device_present_window_s

    def _affordance_recruited(self, *, now: float | None = None) -> bool:
        """True iff ``studio.m8_lcd_reveal`` was recently recruited."""

        age = _read_recruitment_age_s(self._recruitment_path, _M8_REVEAL_CAPABILITY, now=now)
        if age is None:
            return False
        return age <= self._recruitment_window_s

    def _compute_claim_score(self) -> float:
        """0.0 absent | 0.30 present | 0.85 present + recruited."""

        if not self._device_present():
            return 0.0
        score = _BASE_SCORE_PRESENT
        if self._affordance_recruited():
            score += _AFFORDANCE_RECRUITED_BOOST
        # Defensive clamp matches mixin's normalisation to [0, 1].
        return max(0.0, min(1.0, score))

    def _want_visible(self) -> bool:
        """Want visible when feature flag is on and device is present."""

        if not _feature_flag_enabled():
            return False
        return self._device_present()

    def _mandatory_invisible(self) -> bool:
        """No mandatory-invisible path for the M8 ward.

        Person-identifying data never flows through the M8 LCD (it's
        an instrument display showing tracker pattern data), so consent
        gates don't fire. Hardware absence is captured by
        ``_device_present`` returning False, which makes ``_want_visible``
        return False — that's the right way to suppress, not via
        mandatory_invisible.
        """

        return False

    def _claim_source_refs(self) -> tuple[str, ...]:
        """Provenance for the claim — the SHM path and capability name."""

        return (
            f"m8-display:shm:{self._shm_path}",
            f"affordance:{_M8_REVEAL_CAPABILITY}",
        )

    def _describe_source_registration(self) -> dict[str, Any]:
        return {
            "id": "m8-display",
            "class_name": "M8InstrumentReveal",
            "kind": "external_rgba",
            "shm_path": str(self._shm_path),
        }

    # ── Cairo no-op (cc-task acceptance criterion ¶2) ───────────────

    def render_content(self, *args: Any, **kwargs: Any) -> None:
        """No-op. M8 is external_rgba — pixels arrive via the SHM
        bridge, not via Cairo paint. Method exists so callers that
        broadcast ``render_content`` across all family wards (e.g.,
        future router-driven rendering harnesses) don't crash on the
        M8 entry."""

        del args, kwargs
        return None


__all__ = [
    "DEFAULT_DEVICE_PRESENT_WINDOW_S",
    "DEFAULT_RECRUITMENT_PATH",
    "DEFAULT_RECRUITMENT_WINDOW_S",
    "DEFAULT_SHM_PATH",
    "M8InstrumentReveal",
]
