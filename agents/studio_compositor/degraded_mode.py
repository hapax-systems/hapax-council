"""Task #122 — DEGRADED-STREAM mode controller.

During a live-change operation (service restart, deployment, rebuild),
the livestream should degrade gracefully rather than expose raw failure
states (broken wards, shader-compile artifacts, frozen frames, LLM
timeouts). DEGRADED mode freezes expressive surfaces to their last-good
state and holds them there until the operation completes.

Invariants while degraded:

- FX chain pins every slot to ``passthrough`` (no shader rotation,
  no preset-family bias).
- Cairo sources skip :meth:`CairoSource.render` and re-blit the cached
  last-good surface (fallback: a Gruvbox-dark solid fill).
- Director skips its LLM call and emits a silence-hold fallback
  intent so the no-vacuum invariant (2026-04-18) still holds.
- Audio stays live — we do not mute.

This module owns only the **state** — individual surfaces gate on
:meth:`DegradedModeController.is_active` to choose their degraded
behavior. Publishing to ``/dev/shm/hapax-compositor/degraded-mode.json``
lets out-of-process consumers (rebuild scripts, operator HUD, future
observer dashboards) poll the same truth.

See ``docs/superpowers/plans/2026-04-18-active-work-index.md`` task
#122 for the operator directive that motivated this module.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from enum import StrEnum
from pathlib import Path
from typing import Any

__all__ = [
    "DEGRADED_MODE_PATH",
    "DEFAULT_TTL_S",
    "DegradedMode",
    "DegradedModeController",
    "get_controller",
]

log = logging.getLogger(__name__)

# Canonical publication path. Kept beside the other compositor signals
# (``budget-signal.json``, ``ward-properties.json``) so a single
# directory bind captures all operator-facing state.
DEGRADED_MODE_PATH: Path = Path("/dev/shm/hapax-compositor/degraded-mode.json")

# Default TTL for a degraded activation. A typical Python service
# restart under ``rebuild-service.sh`` completes in 5-15 s; 60 s leaves
# comfortable headroom for slow imports, Qdrant reconnects, and ExllamaV2
# GPU warmup. Operators can extend with ``activate(ttl_s=…)``.
DEFAULT_TTL_S: float = 60.0

# Minimum TTL. Shorter activations would race the 200 ms-ish cache
# coherence window used by consumers (cairo ward props, fx tick).
_MIN_TTL_S: float = 1.0


class DegradedMode(StrEnum):
    """Tri-state operating mode for the stream."""

    NORMAL = "normal"
    DEGRADED = "degraded"
    RECOVERING = "recovering"


class DegradedModeController:
    """Owns the degraded-mode state and publishes it to ``/dev/shm``.

    Single instance per process — callers should go through
    :func:`get_controller` so the Stream Deck adapter, sidechat bridge,
    fx tick, cairo runner, and director loop all read the same truth.
    The class is nonetheless safe to instantiate directly in tests.

    The in-process cached state has priority over the filesystem marker
    for ``is_active()`` queries, so tests that never publish to
    ``/dev/shm`` still behave correctly. The filesystem publication is
    for cross-process consumers.
    """

    def __init__(
        self,
        *,
        path: Path | None = None,
        clock: Any = None,
    ) -> None:
        self._path = Path(path) if path is not None else DEGRADED_MODE_PATH
        self._clock = clock or time.time
        self._lock = threading.Lock()
        # Cached publication payload. ``None`` = NORMAL.
        self._state: dict[str, Any] | None = None
        # Prometheus gauge + counter created lazily to avoid a hard
        # dependency on the compositor metrics registry in test envs.
        self._gauge: Any = None
        self._holds_counter: Any = None
        self._init_metrics()

    # ------------------------------------------------------------------ public
    def activate(self, reason: str, *, ttl_s: float = DEFAULT_TTL_S) -> None:
        """Enter DEGRADED mode with a human-readable ``reason``.

        Idempotent: calling ``activate`` while already degraded refreshes
        ``activated_at`` and ``ttl_s`` — the operator can "extend the
        hold" by re-pressing the Stream Deck SAFE MODE key.
        """
        if ttl_s < _MIN_TTL_S:
            raise ValueError(f"ttl_s must be >= {_MIN_TTL_S}s, got {ttl_s}")
        now = float(self._clock())
        payload = {
            "state": DegradedMode.DEGRADED.value,
            "reason": str(reason or "unspecified"),
            "activated_at": now,
            "ttl_s": float(ttl_s),
        }
        with self._lock:
            self._state = payload
        self._publish(payload)
        if self._gauge is not None:
            try:
                self._gauge.set(1)
            except Exception:
                log.debug("degraded-mode gauge set failed", exc_info=True)
        log.info("DEGRADED mode activated: reason=%r ttl=%.1fs", reason, ttl_s)

    def deactivate(self) -> None:
        """Explicit exit. Idempotent — no-op when already NORMAL."""
        with self._lock:
            was_active = self._state is not None
            self._state = None
        if was_active:
            self._unpublish()
            if self._gauge is not None:
                try:
                    self._gauge.set(0)
                except Exception:
                    log.debug("degraded-mode gauge clear failed", exc_info=True)
            log.info("DEGRADED mode deactivated")

    def is_active(self) -> bool:
        """True iff degraded AND TTL has not elapsed.

        Hot path — called from the fx tick, every cairo source render
        tick, and every director iteration. Stays lock-free on the
        fast path (snapshot read + two float compares).
        """
        snapshot = self._state
        if snapshot is None:
            return False
        ttl = snapshot.get("ttl_s", 0.0)
        activated = snapshot.get("activated_at", 0.0)
        if ttl <= 0:
            return True  # sentinel: no expiry
        if float(self._clock()) - float(activated) > float(ttl):
            # TTL elapsed. Clear lazily under lock so repeated callers
            # do not all race to unpublish.
            self.deactivate()
            return False
        return True

    def current_reason(self) -> str | None:
        """Return the activation reason if degraded, else ``None``."""
        if not self.is_active():
            return None
        snapshot = self._state
        return snapshot.get("reason") if snapshot is not None else None

    def record_hold(self, surface: str) -> None:
        """Record a single degraded-induced hold from a caller surface.

        ``surface`` is a free-form short tag — ``"director"``,
        ``"fx_chain"``, ``"cairo"`` etc. Best-effort: metric
        failures never raise.
        """
        if self._holds_counter is None:
            return
        try:
            self._holds_counter.labels(surface=str(surface)).inc()
        except Exception:
            log.debug("degraded-holds counter inc failed", exc_info=True)

    # ------------------------------------------------------------------ internals
    def _publish(self, payload: dict[str, Any]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            log.debug("could not create degraded-mode parent", exc_info=True)
            return
        # Atomic publish: tmp + rename. Consumers never see a torn file.
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                dir=str(self._path.parent),
                prefix=".degraded-mode.",
                suffix=".tmp",
                delete=False,
            ) as fh:
                json.dump(payload, fh)
                tmp_path = fh.name
            os.replace(tmp_path, self._path)
        except OSError:
            log.warning("degraded-mode publish failed", exc_info=True)

    def _unpublish(self) -> None:
        try:
            self._path.unlink(missing_ok=True)
        except OSError:
            log.debug("degraded-mode unpublish failed", exc_info=True)

    def _init_metrics(self) -> None:
        try:
            from prometheus_client import Counter, Gauge

            from agents.studio_compositor.metrics import REGISTRY
        except Exception:
            log.debug("prometheus/metrics unavailable", exc_info=True)
            return
        if REGISTRY is None:
            return
        try:
            self._gauge = Gauge(
                "hapax_degraded_mode_active",
                "1 while DEGRADED mode is active, 0 when NORMAL. The "
                "``_seconds_total`` view is obtained in Grafana by "
                "integrating this gauge via ``sum_over_time(... [$range])``.",
                registry=REGISTRY,
            )
        except ValueError:
            # Already registered on a prior controller (hot reload).
            log.debug("degraded-mode gauge already registered")
        try:
            self._holds_counter = Counter(
                "hapax_degraded_holds_total",
                "Count of per-surface holds triggered while degraded. "
                'Labelled by surface so ``{surface="director"}`` yields '
                'the director-skip count and ``{surface="fx_chain"}`` '
                "the slot-pin count.",
                ["surface"],
                registry=REGISTRY,
            )
        except ValueError:
            log.debug("degraded-holds counter already registered")


# ------------------------------------------------------------------ singleton
_singleton_lock = threading.Lock()
_singleton: DegradedModeController | None = None


def get_controller() -> DegradedModeController:
    """Return the process-wide :class:`DegradedModeController` instance.

    Lazy — constructs on first call. Tests that want an isolated
    controller should instantiate :class:`DegradedModeController`
    directly with an explicit ``path=`` kwarg instead of going through
    this accessor.
    """
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = DegradedModeController()
        return _singleton
