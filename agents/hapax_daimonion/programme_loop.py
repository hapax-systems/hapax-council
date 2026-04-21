"""ProgrammeManager tick loop + Hapax-authored programme planner trigger.

Closes B3 critical #4 + #5 wire-up gap from the 2026-04-20 audit, plus
the auto-author trigger from the post-2026-04-21-loop follow-on.

The ProgrammeManager (``agents/programme_manager/manager.py``) is fully
implemented but had no production runner — its lifecycle metrics
(``hapax_programme_start_total`` / ``_end_total`` / ``_active``), the
JSONL outcome log under ``~/hapax-state/programmes/<show>/<id>.jsonl``,
and the 5 named abort predicates (``operator_left_room_for_10min``,
``impingement_pressure_above_0.8_for_3min``, ``consent_contract_expired``,
``vinyl_side_a_finished``, ``operator_voice_contradicts_programme_intent``)
all stayed dormant because nothing ticked the manager.

This loop wires it. Spawned from ``run_inner._make_task`` like every
other daimonion background task; supervised under RECREATE policy so
crashes are restarted with backoff. Cadence is 1 Hz — programmes are
minutes-long; faster ticks are wasted work.

When the store has no scheduled programmes AND ``HAPAX_PROGRAMME_AUTO_PLAN=1``
is set, the loop calls ``ProgrammePlanner.plan()`` to author a fresh
plan via the grounded ``balanced`` LLM tier, writes it to the store,
and activates the first programme. Authorship is fully Hapax-generated
per memory ``feedback_hapax_authors_programmes``; the operator does NOT
write programme outlines.

Planning is throttled by ``PROGRAMME_PLAN_COOLDOWN_S`` (default 5 min)
so a string of LLM failures does not retry constantly. Default flag is
OFF — the manager loop ticks but won't auto-author until the operator
opts in (matches the GEM LLM-authoring opt-in pattern).
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import os
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.hapax_daimonion.daemon import VoiceDaemon
    from agents.programme_manager.manager import ProgrammeManager
    from agents.programme_manager.planner import ProgrammePlanner
    from shared.programme_store import ProgrammePlanStore

log = logging.getLogger(__name__)

PROGRAMME_TICK_INTERVAL_S = 1.0

# Auto-author cooldown: don't re-attempt planning for 5min after a
# failure (LLM gateway down, validation failure, etc.). Adjustable via
# env for ablation studies.
PROGRAMME_PLAN_COOLDOWN_S = float(os.environ.get("HAPAX_PROGRAMME_PLAN_COOLDOWN_S", "300"))

PROGRAMME_AUTO_PLAN_ENV = "HAPAX_PROGRAMME_AUTO_PLAN"


def _build_manager() -> ProgrammeManager:
    """Construct the production ProgrammeManager.

    Late imports keep daimonion startup fast when programmes aren't
    in use — the heavy programme_manager + shared.programme_store
    modules only load when this loop fires.
    """
    from agents.programme_manager.abort_predicates import (
        DEFAULT_ABORT_PREDICATES,
    )
    from agents.programme_manager.manager import ProgrammeManager
    from agents.programme_manager.transition import TransitionChoreographer
    from shared.programme_store import default_store

    return ProgrammeManager(
        store=default_store(),
        choreographer=TransitionChoreographer(),
        abort_predicates=dict(DEFAULT_ABORT_PREDICATES),
    )


def is_auto_plan_enabled() -> bool:
    """Read HAPAX_PROGRAMME_AUTO_PLAN env flag fresh each call."""
    raw = os.environ.get(PROGRAMME_AUTO_PLAN_ENV, "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _current_show_id() -> str:
    """Per-day show id keyed on working_mode.

    The planner accepts any string; we use ``show-YYYY-MM-DD-<mode>`` so
    the JSONL outcome log under ~/hapax-state/programmes/<show>/ groups
    each calendar day's programmes together by mode.
    """
    today = _dt.date.today().isoformat()
    try:
        from shared.working_mode import get_working_mode

        mode = str(get_working_mode())
    except Exception:
        mode = "unknown"
    return f"show-{today}-{mode}"


def _current_working_mode() -> str | None:
    try:
        from shared.working_mode import get_working_mode

        return str(get_working_mode())
    except Exception:
        return None


def _has_pending_or_active(store: ProgrammePlanStore) -> bool:
    """True when the store has at least one programme worth ticking."""
    from shared.programme import ProgrammeStatus

    return any(p.status in (ProgrammeStatus.ACTIVE, ProgrammeStatus.PENDING) for p in store.all())


def _maybe_author_plan(
    manager: ProgrammeManager,
    planner: ProgrammePlanner | None,
    last_attempt_ts: float,
) -> tuple[ProgrammePlanner | None, float]:
    """Attempt one author-plan-then-activate cycle when conditions allow.

    Returns ``(planner, last_attempt_ts)`` so the caller persists the
    cooldown timestamp + lazy planner instance across ticks.
    """
    if not is_auto_plan_enabled():
        return planner, last_attempt_ts

    now = time.monotonic()
    if last_attempt_ts != 0.0 and (now - last_attempt_ts) < PROGRAMME_PLAN_COOLDOWN_S:
        return planner, last_attempt_ts

    if _has_pending_or_active(manager.store):
        return planner, last_attempt_ts

    if planner is None:
        try:
            from agents.programme_manager.planner import ProgrammePlanner as _Planner

            planner = _Planner()
        except Exception:
            log.warning("ProgrammePlanner construction failed", exc_info=True)
            return planner, now

    show_id = _current_show_id()
    log.info("auto-authoring programmes for show=%s", show_id)
    try:
        plan = planner.plan(
            show_id=show_id,
            working_mode=_current_working_mode(),
        )
    except Exception:
        log.warning("ProgrammePlanner.plan raised", exc_info=True)
        return planner, now

    if plan is None or not plan.programmes:
        log.warning(
            "ProgrammePlanner returned empty plan for show=%s; cooldown until next attempt",
            show_id,
        )
        return planner, now

    for programme in plan.programmes:
        try:
            manager.store.add(programme)
        except Exception:
            log.warning(
                "store.add failed for programme %s — continuing",
                programme.programme_id,
                exc_info=True,
            )

    first = plan.programmes[0]
    try:
        manager.store.activate(first.programme_id)
        log.info(
            "auto-author: activated %s (plan has %d programmes)",
            first.programme_id,
            len(plan.programmes),
        )
    except Exception:
        log.warning("store.activate failed for %s", first.programme_id, exc_info=True)

    return planner, now


async def programme_manager_loop(daemon: VoiceDaemon) -> None:
    """Tick the ProgrammeManager at 1 Hz while the daemon runs.

    Errors are logged but never propagate — a bad programme plan must
    never take the daemon down. The loop also tolerates a lazy
    construction failure (missing dependency, broken import) and
    re-attempts on the next tick rather than spinning at full CPU.

    When ``HAPAX_PROGRAMME_AUTO_PLAN=1`` is set, the loop calls
    ``_maybe_author_plan`` once per tick to author + activate fresh
    programmes when the store is empty (subject to PROGRAMME_PLAN_COOLDOWN_S
    throttling between attempts).
    """
    manager: ProgrammeManager | None = None
    planner: ProgrammePlanner | None = None
    last_plan_attempt_ts = 0.0
    construction_warned_at: float | None = None
    log.info("programme_manager_loop starting (tick interval %.1fs)", PROGRAMME_TICK_INTERVAL_S)

    while daemon._running:
        if manager is None:
            try:
                manager = _build_manager()
                log.info("programme_manager_loop: ProgrammeManager constructed")
            except Exception:
                # Throttle the warning so a persistent construction
                # failure doesn't flood the log; once per minute is
                # enough for the operator to notice.
                now = time.monotonic()
                if construction_warned_at is None or now - construction_warned_at > 60.0:
                    log.warning("programme_manager construction failed", exc_info=True)
                    construction_warned_at = now
                await asyncio.sleep(PROGRAMME_TICK_INTERVAL_S)
                continue

        try:
            decision = manager.tick()
            if decision.trigger.value != "none":
                log.info(
                    "programme transition: %s (%s → %s)",
                    decision.trigger.value,
                    getattr(decision.from_programme, "programme_id", None),
                    getattr(decision.to_programme, "programme_id", None),
                )
        except Exception:
            log.warning("programme_manager.tick raised", exc_info=True)

        try:
            planner, last_plan_attempt_ts = _maybe_author_plan(
                manager, planner, last_plan_attempt_ts
            )
        except Exception:
            log.warning("_maybe_author_plan raised", exc_info=True)

        await asyncio.sleep(PROGRAMME_TICK_INTERVAL_S)


__all__ = [
    "PROGRAMME_AUTO_PLAN_ENV",
    "PROGRAMME_PLAN_COOLDOWN_S",
    "PROGRAMME_TICK_INTERVAL_S",
    "is_auto_plan_enabled",
    "programme_manager_loop",
]
