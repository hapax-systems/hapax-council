"""Periodic driver that calls ``apply_layout_switch`` from inside the
compositor process.

cc-task: ``u6-periodic-tick-driver``.

The U6 substrate (PR #2324) shipped the ``hapax_compositor_layout_active``
gauge + ``LayoutStore.set_active()``. PR #2376 shipped the
``apply_layout_switch`` adapter that combines selection + cooldown +
mutate. But until this driver, no caller invoked the adapter
periodically — so the live system sat on ``garage-door`` (the
``LayoutStore.__init__`` default) forever, with the gauge stuck at
``hapax_compositor_layout_active{layout="garage-door"} 1.0``.

This driver lives **inside the compositor process** because the
``LayoutStore`` is in-process state — running the driver as a separate
systemd unit would require IPC or cross-process file-watching. The
state_provider below reads the four input signals from the well-known
SHM/dotcache files used by ``director_loop``:

* ``stream_mode`` — ``~/.cache/hapax/stream-mode`` via ``shared.stream_mode``
* ``consent_safe_active`` — env-flag ``HAPAX_CONSENT_EGRESS_GATE`` (gate
  is retired by default per ``consent_live_egress.py``)
* ``vinyl_playing`` — ``/dev/shm/hapax-compositor/vinyl-operator-active.flag``
  (operator override) OR fresh+confident ``album-state.json``
* ``director_activity`` — last entry of
  ``~/hapax-state/stream-experiment/director-intent.jsonl``

Each tick, ``apply_layout_switch`` is called; we additionally increment
``hapax_layout_switch_dispatched_total{layout, reason}`` regardless of
whether the cooldown gate accepted the switch, so the operator can prove
the driver is alive even when the surface looks frozen.

Reversibility:

* ``HAPAX_LAYOUT_TICK_DISABLED=1`` skips driver startup entirely.
* The thread is daemon=True; compositor SIGTERM brings it down with
  the rest of the process.

Per ``feedback_no_expert_system_rules`` — the driver is a pure dispatcher;
all selection logic lives in ``layout_switcher.select_layout`` which is
already a typed declarative policy (priority order, no thresholds).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Env-flag gate. Operator can disable by setting this to any non-empty
# truthy value. Defaults to ENABLED — feature-forward per operator
# directive ``feedback_features_on_by_default``.
ENV_DISABLE: str = "HAPAX_LAYOUT_TICK_DISABLED"

# Tick cadence — 30s matches the LayoutSwitcher.DEFAULT_COOLDOWN_S so
# we tick once per cooldown window. Faster ticks would just hit the
# cooldown; slower ticks would miss vinyl-flap events.
DEFAULT_DRIVER_INTERVAL_S: float = 30.0

# Director intent staleness — anything older than this is treated as
# "no current director activity" so a long stall doesn't pin the
# layout into vinyl-focus on a stale react-tick.
DIRECTOR_INTENT_STALE_S: float = 180.0

# Vinyl evidence staleness — album-state confidence decays after this.
VINYL_STATE_STALE_S: float = 60.0
VINYL_CONFIDENCE_THRESHOLD: float = 0.5

# Well-known signal files. Duplicated from director_loop.py to avoid
# pulling that heavy module's transitive imports into the driver.
ALBUM_STATE_FILE: Path = Path("/dev/shm/hapax-compositor/album-state.json")
VINYL_OPERATOR_OVERRIDE_FLAG: Path = Path("/dev/shm/hapax-compositor/vinyl-operator-active.flag")
DIRECTOR_INTENT_JSONL: Path = Path(
    os.path.expanduser("~/hapax-state/stream-experiment/director-intent.jsonl")
)


def _is_disabled() -> bool:
    """Return True iff the operator has set ``HAPAX_LAYOUT_TICK_DISABLED``."""
    val = os.environ.get(ENV_DISABLE, "").strip().lower()
    return val in {"1", "true", "yes", "on", "enabled"}


def _read_stream_mode() -> str | None:
    """Read the current stream mode as the string the switcher expects.

    Returns ``"deep"`` if the live mode is research-focused; otherwise
    ``None`` so the switcher falls through to the default. We treat any
    error as "no signal" so the driver never accidentally trips
    consent-safe.
    """
    try:
        from shared.stream_mode import StreamMode, get_stream_mode

        mode = get_stream_mode()
        if mode == StreamMode.PUBLIC_RESEARCH:
            return "deep"
    except Exception:
        log.debug("read_stream_mode failed", exc_info=True)
    return None


def _read_consent_safe_active() -> bool:
    """The retired layout-swap gate is opt-in via env-flag (see
    ``consent_live_egress.py``). When set, the driver routes to
    consent-safe even though the face-obscure pipeline (#129) is the
    authoritative privacy enforcer — operator may want both belt-and-
    suspenders during an interview."""
    val = os.environ.get("HAPAX_CONSENT_EGRESS_GATE", "").strip().lower()
    return val in {"1", "true", "yes", "on", "enabled"}


def _read_vinyl_playing() -> bool:
    """Operator override flag OR fresh+confident album-state."""
    try:
        if VINYL_OPERATOR_OVERRIDE_FLAG.exists():
            return True
        if not ALBUM_STATE_FILE.exists():
            return False
        age = time.time() - ALBUM_STATE_FILE.stat().st_mtime
        if age > VINYL_STATE_STALE_S:
            return False
        data = json.loads(ALBUM_STATE_FILE.read_text())
        conf = float(data.get("confidence") or 0.0)
        return conf >= VINYL_CONFIDENCE_THRESHOLD
    except Exception:
        log.debug("read_vinyl_playing failed", exc_info=True)
        return False


def _read_director_activity() -> str | None:
    """Tail the last entry of director-intent.jsonl for ``activity``.

    We do not parse the entire file — only the last line. Files are
    rotated by ``director_loop._maybe_rotate_jsonl`` so the tail stays
    bounded. Returns ``None`` on missing/stale/unparseable.
    """
    try:
        if not DIRECTOR_INTENT_JSONL.exists():
            return None
        age = time.time() - DIRECTOR_INTENT_JSONL.stat().st_mtime
        if age > DIRECTOR_INTENT_STALE_S:
            return None
        # Read the last 4KB of the file — enough for the last entry,
        # and bounded so a runaway file doesn't blow memory.
        with DIRECTOR_INTENT_JSONL.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            offset = max(0, size - 4096)
            f.seek(offset)
            tail = f.read().decode("utf-8", errors="replace")
        last_line = ""
        for line in tail.splitlines():
            stripped = line.strip()
            if stripped:
                last_line = stripped
        if not last_line:
            return None
        rec = json.loads(last_line)
        activity = rec.get("activity")
        if isinstance(activity, str) and activity:
            return activity
    except Exception:
        log.debug("read_director_activity failed", exc_info=True)
    return None


def build_state_provider() -> Any:
    """Return a zero-arg callable that yields the dict the driver expects.

    Each call re-reads the underlying files so live state changes
    propagate at the next tick.
    """

    def _provider() -> dict[str, object]:
        return {
            "consent_safe_active": _read_consent_safe_active(),
            "vinyl_playing": _read_vinyl_playing(),
            "director_activity": _read_director_activity(),
            "stream_mode": _read_stream_mode(),
        }

    return _provider


class _LayoutStoreAdapter:
    """Adapt ``LayoutStore`` to the ``apply_layout_switch`` contract.

    The adapter expects ``layout_state`` with ``mutate(fn)`` and
    ``loader`` with ``load(name)``. ``LayoutStore`` exposes
    ``set_active(name)`` and ``get(name)`` instead. The adapter wraps
    a single store so both call shapes route to the same in-process
    state.

    ``mutate`` is called by the adapter as
    ``layout_state.mutate(lambda _previous: new_layout)`` — we ignore
    the lambda's return value and instead call ``store.set_active``
    using the layout's ``name`` attribute (every Layout pydantic model
    carries ``name``). ``load`` returns the cached Layout from the
    store; if the store hasn't loaded the named layout yet we trigger
    a directory rescan and try again.
    """

    def __init__(self, store: Any) -> None:
        self._store = store

    def load(self, name: str) -> Any:
        layout = self._store.get(name)
        if layout is None:
            # Fresh layout file may have appeared since last scan.
            self._store.reload_changed()
            layout = self._store.get(name)
        if layout is None:
            raise KeyError(f"layout {name!r} not loaded in LayoutStore")
        return layout

    def mutate(self, fn: Any) -> None:
        # The adapter calls fn(previous_layout) → new_layout. We use
        # the Layout's name to drive set_active so the gauge + the
        # downstream layout consumers all see the swap.
        previous = self._store.get_active()
        new_layout = fn(previous)
        name = getattr(new_layout, "name", None)
        if not isinstance(name, str) or not name:
            raise ValueError("layout returned from mutate() lacks a 'name' attribute")
        self._store.set_active(name)


def _emit_dispatch_counter(layout_name: str, reason: str) -> None:
    """Increment ``hapax_layout_switch_dispatched_total`` if available."""
    try:
        from agents.studio_compositor import metrics as _metrics

        counter = getattr(_metrics, "HAPAX_LAYOUT_SWITCH_DISPATCHED_TOTAL", None)
        if counter is not None:
            counter.labels(layout=layout_name, reason=reason).inc()
    except Exception:
        log.debug("layout-tick dispatch counter increment failed", exc_info=True)


def _driver_tick(
    *,
    state_provider: Any,
    layout_state: Any,
    loader: Any,
    switcher: Any,
) -> None:
    """One iteration: read state, select, dispatch counter, attempt apply."""
    from agents.studio_compositor.layout_switcher import (
        apply_layout_switch,
        select_layout,
    )

    state = state_provider()
    selection = select_layout(
        consent_safe_active=bool(state.get("consent_safe_active", False)),
        vinyl_playing=bool(state.get("vinyl_playing", False)),
        director_activity=state.get("director_activity"),
        stream_mode=state.get("stream_mode"),
    )
    _emit_dispatch_counter(selection.layout_name, selection.trigger)
    try:
        apply_layout_switch(
            layout_state,
            loader,
            switcher,
            consent_safe_active=bool(state.get("consent_safe_active", False)),
            vinyl_playing=bool(state.get("vinyl_playing", False)),
            director_activity=state.get("director_activity"),
            stream_mode=state.get("stream_mode"),
        )
    except KeyError:
        # Unknown layout name in the loader — log + skip; the
        # ``install-compositor-layouts.sh`` script must run to deploy
        # the layout JSONs the switcher knows about. We still emitted
        # the dispatch counter so the operator sees the reason.
        log.warning(
            "layout-tick: layout %r not loaded; running scripts/"
            "install-compositor-layouts.sh deploys the missing JSON",
            selection.layout_name,
        )


def run_layout_tick_loop(
    *,
    layout_state: Any,
    loader: Any,
    switcher: Any,
    state_provider: Any,
    interval_s: float = DEFAULT_DRIVER_INTERVAL_S,
    stop_event: Any | None = None,
    iterations: int | None = None,
    sleep_fn: Any = time.sleep,
) -> int:
    """Tick driver loop. Returns count of iterations executed.

    Parameters mirror ``layout_switcher.run_layout_switch_loop`` but
    add the dispatch counter side-effect via ``_driver_tick``. Tests
    inject ``iterations`` or set ``stop_event`` for bounded runs;
    production passes neither (runs until daemon thread exits).
    """
    iter_count = 0
    while True:
        if stop_event is not None:
            try:
                if stop_event.is_set():
                    break
            except Exception:
                log.debug("stop_event.is_set() failed; continuing", exc_info=True)
        if iterations is not None and iter_count >= iterations:
            break
        try:
            _driver_tick(
                state_provider=state_provider,
                layout_state=layout_state,
                loader=loader,
                switcher=switcher,
            )
        except Exception:
            log.warning("layout-tick driver tick raised; loop continues", exc_info=True)
        iter_count += 1
        sleep_fn(interval_s)
    return iter_count


def start_layout_tick_driver(compositor: Any) -> threading.Thread | None:
    """Start the layout-tick daemon thread alongside the compositor.

    Returns the thread object so callers can ``.join()`` in tests; in
    production the thread is daemon=True and dies with the process.
    Returns ``None`` if disabled by env-flag or if the LayoutStore has
    not been initialized on the compositor (defensive).
    """
    if _is_disabled():
        log.info("layout-tick driver disabled via %s", ENV_DISABLE)
        return None

    store = getattr(compositor, "_layout_store", None)
    if store is None:
        log.warning("compositor._layout_store missing — layout-tick driver not started")
        return None

    from agents.studio_compositor.layout_switcher import LayoutSwitcher

    initial = store.active_name() or "garage-door"
    switcher = LayoutSwitcher(initial_layout=initial)
    adapter = _LayoutStoreAdapter(store)

    state_provider = build_state_provider()

    def _target() -> None:
        log.info(
            "layout-tick driver started (interval=%.1fs initial=%s)",
            DEFAULT_DRIVER_INTERVAL_S,
            initial,
        )
        run_layout_tick_loop(
            layout_state=adapter,
            loader=adapter,
            switcher=switcher,
            state_provider=state_provider,
            interval_s=DEFAULT_DRIVER_INTERVAL_S,
        )

    thread = threading.Thread(target=_target, daemon=True, name="layout-tick-driver")
    thread.start()
    compositor._layout_tick_thread = thread  # type: ignore[attr-defined]
    return thread


__all__ = [
    "ALBUM_STATE_FILE",
    "DEFAULT_DRIVER_INTERVAL_S",
    "DIRECTOR_INTENT_JSONL",
    "DIRECTOR_INTENT_STALE_S",
    "ENV_DISABLE",
    "VINYL_CONFIDENCE_THRESHOLD",
    "VINYL_OPERATOR_OVERRIDE_FLAG",
    "VINYL_STATE_STALE_S",
    "build_state_provider",
    "run_layout_tick_loop",
    "start_layout_tick_driver",
]
