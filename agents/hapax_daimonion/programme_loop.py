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
import json as _json
import logging
import os
import time
from pathlib import Path as _Path
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
PROGRAMME_PLAN_COOLDOWN_S = float(os.environ.get("HAPAX_PROGRAMME_PLAN_COOLDOWN_S", "30"))

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
    from agents.programme_manager.completion_predicates import (
        DEFAULT_COMPLETION_PREDICATES,
    )
    from agents.programme_manager.manager import ProgrammeManager
    from agents.programme_manager.transition import TransitionChoreographer
    from shared.programme_store import default_store

    return ProgrammeManager(
        store=default_store(),
        choreographer=TransitionChoreographer(),
        completion_predicates=dict(DEFAULT_COMPLETION_PREDICATES),
        abort_predicates=dict(DEFAULT_ABORT_PREDICATES),
        # Unregistered predicates default to True so programmes don't
        # get stuck when the planner emits predicate names that the
        # runtime doesn't implement yet (e.g. operator_speaks_3_times).
        unknown_predicate_satisfies=True,
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


def _gather_perception() -> dict | None:
    """Read the director's narrative-state snapshot for planner context."""
    try:
        import json as _json
        from pathlib import Path as _Path

        state_path = _Path("/dev/shm/hapax-director/narrative-state.json")
        if state_path.exists():
            data = _json.loads(state_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
    except Exception:
        log.debug("perception read for planner failed", exc_info=True)
    return None


def _gather_vault_state() -> dict | None:
    """Read vault context (daily notes + goals) for planner grounding."""
    try:
        from agents.hapax_daimonion.autonomous_narrative.state_readers import (
            read_recent_vault_context,
        )

        ctx = read_recent_vault_context()
        if ctx.is_empty():
            return None
        result: dict = {}
        if ctx.active_goals:
            result["active_goals"] = [
                {"title": t, "priority": p, "status": s} for t, p, s in ctx.active_goals
            ]
        if ctx.daily_note_excerpts:
            result["recent_daily_notes"] = [
                {"date": d, "excerpt": b[:300]} for d, b in ctx.daily_note_excerpts
            ]
        return result
    except Exception:
        log.debug("vault_state read for planner failed", exc_info=True)
    return None


def _gather_profile() -> dict | None:
    """Read operator profile digest for planner grounding.

    The profile store has 74k+ facts; we only send the digest (summary
    per dimension) to keep the planner prompt budget manageable.
    """
    try:
        from shared.profile_store import ProfileStore

        store = ProfileStore()
        digest = store.get_digest()
        if not digest:
            return None
        # Compact the digest: overall summary + dimension names + fact counts
        result: dict = {}
        if digest.get("overall_summary"):
            result["summary"] = digest["overall_summary"][:500]
        dims = {}
        for dim_name, dim_data in digest.get("dimensions", {}).items():
            dim_summary = dim_data.get("summary", "")
            dims[dim_name] = {
                "fact_count": dim_data.get("fact_count", 0),
                "summary": dim_summary[:200] if dim_summary else "",
            }
        if dims:
            result["dimensions"] = dims
        return result if result else None
    except Exception:
        log.debug("profile read for planner failed", exc_info=True)
    return None


def _gather_content_state(store: ProgrammePlanStore) -> dict | None:
    """Read chat state + recent programme history for planner context."""
    import json as _json
    from pathlib import Path as _Path

    result: dict = {}
    # Chat state from the YouTube chat reader ring buffer
    try:
        chat_path = _Path("/dev/shm/hapax-chat/recent.jsonl")
        if chat_path.exists():
            lines = chat_path.read_text(encoding="utf-8").strip().splitlines()
            recent = lines[-10:] if len(lines) > 10 else lines
            messages = []
            for line in recent:
                try:
                    msg = _json.loads(line)
                    messages.append(msg.get("text", "")[:80])
                except Exception:
                    pass
            if messages:
                result["recent_chat"] = messages
                result["chat_message_count"] = len(lines)
    except Exception:
        log.debug("chat state read for planner failed", exc_info=True)

    # Recent completed programme history (last 5) — tells the planner
    # what has already run so it doesn't repeat the same shape.
    try:
        from shared.programme import ProgrammeStatus

        completed = [p for p in store.all() if p.status == ProgrammeStatus.COMPLETED]
        if completed:
            recent_completed = completed[-5:]
            result["recent_programmes"] = [
                {
                    "role": str(getattr(p.role, "value", p.role)),
                    "beat": (getattr(getattr(p, "content", None), "narrative_beat", "") or "")[:80],
                }
                for p in recent_completed
            ]
    except Exception:
        log.debug("programme history read for planner failed", exc_info=True)

    return result if result else None


# ── Recycled segment picker ──────────────────────────────────────────────────
#
# When all pre-authored segments have been played, pick the most
# contextually relevant completed segment from the archive and reset it
# to PENDING so the playback loop re-delivers it. Scoring is a weighted
# sum of: content affinity (keyword overlap between the segment's
# narrative_beat + script text and current perception signals),
# role affinity (working_mode × stance → preferred roles), and a
# recency penalty (don't replay the segment that just finished).

# Track recently played recycled segments to avoid tight loops.
_recycled_recent: list[str] = []
_RECYCLED_RECENT_MAX = 5

# Working mode × stance → preferred roles (soft bias, not exclusive)
_ROLE_AFFINITY: dict[str, dict[str, list[str]]] = {
    "rnd": {
        "nominal": ["iceberg", "lecture", "tier_list"],
        "seeking": ["iceberg", "rant", "lecture"],
        "cautious": ["lecture", "tier_list"],
        "degraded": ["tier_list"],
    },
    "deep_work": {
        "nominal": ["lecture", "iceberg"],
        "seeking": ["rant", "iceberg"],
        "cautious": ["lecture"],
        "degraded": ["tier_list"],
    },
    "broadcast": {
        "nominal": ["rant", "iceberg", "tier_list"],
        "seeking": ["rant", "tier_list"],
        "cautious": ["lecture", "tier_list"],
        "degraded": ["tier_list"],
    },
}


def _gather_context_keywords() -> list[str]:
    """Gather keywords from live perception signals for content matching.

    Reads narrative-state, stimmung, and working-mode to build a bag of
    words the segment scorer can match against segment content.
    """
    keywords: list[str] = []
    try:
        state_path = _Path("/dev/shm/hapax-director/narrative-state.json")
        if state_path.exists():
            data = _json.loads(state_path.read_text(encoding="utf-8"))
            # Extract topic/theme signals from the narrative state
            for key in ("current_topic", "theme", "mood", "focus_area", "exploration_target"):
                val = data.get(key)
                if isinstance(val, str) and val:
                    keywords.extend(val.lower().split())
            # Recent impingement summaries
            for imp in data.get("recent_impingements", [])[:5]:
                if isinstance(imp, dict):
                    summary = imp.get("summary", "") or imp.get("title", "")
                    if summary:
                        keywords.extend(summary.lower().split()[:8])
    except Exception:
        pass

    try:
        stimmung_path = _Path("/dev/shm/hapax-stimmung/state.json")
        if stimmung_path.exists():
            stim = _json.loads(stimmung_path.read_text(encoding="utf-8"))
            stance = stim.get("overall_stance", "")
            if stance:
                keywords.append(stance.lower())
    except Exception:
        pass

    # Deduplicate and filter noise words
    noise = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "of",
        "to",
        "in",
        "for",
        "and",
        "on",
        "it",
        "at",
        "by",
        "or",
        "as",
        "be",
        "that",
        "this",
        "with",
        "from",
        "not",
        "but",
        "its",
        "has",
        "had",
        "have",
    }
    return list(dict.fromkeys(w for w in keywords if len(w) > 2 and w not in noise))


def _score_segment_content(programme: object, context_keywords: list[str]) -> float:
    """Score a segment's content relevance to the current context.

    Returns 0.0–1.0. Higher = more contextually relevant.
    Uses keyword overlap between context signals and the segment's
    narrative_beat + prepared_script text.
    """
    content = getattr(programme, "content", None)
    if not content:
        return 0.0

    # Build segment text bag from narrative_beat + script blocks
    seg_text = ""
    beat = getattr(content, "narrative_beat", "") or ""
    seg_text += beat.lower() + " "
    for block in getattr(content, "prepared_script", None) or []:
        if isinstance(block, str):
            seg_text += block.lower()[:200] + " "
        elif isinstance(block, dict):
            seg_text += (block.get("text", "") or "").lower()[:200] + " "

    if not context_keywords or not seg_text:
        return 0.0

    # Count keyword hits
    hits = sum(1 for kw in context_keywords if kw in seg_text)
    # Normalize: full score at 5+ hits
    return min(1.0, hits / 5.0)


def _pick_recycled_segment(
    store: object,
    active: object | None,
) -> object | None:
    """Pick a completed segment from the archive for recycling.

    Scoring: content_affinity × 0.5 + role_affinity × 0.3 + recency × 0.2.
    Resets the chosen segment to PENDING so the playback loop picks it up.
    Falls back to random when no contextual signals are available.
    """
    import random as _rng

    from shared.programme import ProgrammeStatus

    all_progs = store.all()
    pool = [
        p
        for p in all_progs
        if p.status == ProgrammeStatus.COMPLETED
        and getattr(getattr(p, "content", None), "prepared_script", None)
    ]
    if not pool:
        return None

    # Gather context
    context_keywords = _gather_context_keywords()
    stance = "nominal"
    working_mode = "rnd"
    try:
        stim = _json.loads(_Path("/dev/shm/hapax-stimmung/state.json").read_text(encoding="utf-8"))
        stance = stim.get("overall_stance", "nominal")
    except Exception:
        pass
    try:
        from shared.working_mode import get_working_mode

        working_mode = str(get_working_mode())
    except Exception:
        pass

    # Preferred roles for this mode × stance
    mode_affinities = _ROLE_AFFINITY.get(working_mode, _ROLE_AFFINITY.get("rnd", {}))
    preferred_roles = mode_affinities.get(stance, [])

    # Active programme id + recent recycled ids for recency penalty
    active_pid = getattr(active, "programme_id", None) if active else None

    scored: list[tuple[float, object]] = []
    for p in pool:
        # Content affinity (0.0–1.0)
        content_score = _score_segment_content(p, context_keywords)

        # Role affinity (0.0 or 1.0)
        role_val = getattr(p.role, "value", str(p.role))
        role_score = 1.0 if role_val in preferred_roles else 0.0

        # Recency penalty: penalize the just-finished segment and recent replays
        recency_score = 1.0
        if p.programme_id == active_pid:
            recency_score = 0.0
        elif p.programme_id in _recycled_recent:
            # Graduated penalty: more recent = heavier penalty
            idx = _recycled_recent.index(p.programme_id)
            recency_score = (idx + 1) / (_RECYCLED_RECENT_MAX + 1)

        # Weighted composite + small random jitter for variety
        total = (
            content_score * 0.50 + role_score * 0.25 + recency_score * 0.20 + _rng.random() * 0.05
        )
        scored.append((total, p))

    if not scored:
        return None

    scored.sort(key=lambda x: x[0], reverse=True)
    winner = scored[0][1]

    # Track recency
    _recycled_recent.insert(0, winner.programme_id)
    while len(_recycled_recent) > _RECYCLED_RECENT_MAX:
        _recycled_recent.pop()

    # Reset to PENDING so the playback loop re-activates it
    try:
        updated = winner.model_copy(
            update={
                "status": ProgrammeStatus.PENDING,
                "actual_started_at": None,
                "actual_ended_at": None,
            }
        )
        store.add(updated)
        log.info(
            "recycled-picker: selected %s (content=%.2f role=%s recency=%.2f)",
            winner.programme_id,
            scored[0][0],
            getattr(winner.role, "value", "?"),
            recency_score,
        )
        return updated
    except Exception:
        log.debug("recycled-picker: reset to PENDING failed", exc_info=True)
        return None


def _has_pending_queued(store: ProgrammePlanStore) -> bool:
    """True when the store already has pending programmes queued.

    We only block planning when there are PENDING programmes waiting
    to activate. An ACTIVE programme does NOT block planning — segments
    should always be pre-assembling the next batch while the current
    one runs. This ensures continuous flow: when the active segment
    completes, the next one is already waiting.
    """
    from shared.programme import ProgrammeStatus

    return any(p.status == ProgrammeStatus.PENDING for p in store.all())


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

    if _has_pending_queued(manager.store):
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

    # Gather rich context for the planner — each gather is fail-safe.
    perception = _gather_perception()
    vault_state = _gather_vault_state()
    profile = _gather_profile()
    content_state = _gather_content_state(manager.store)

    try:
        plan = planner.plan(
            show_id=show_id,
            working_mode=_current_working_mode(),
            perception=perception,
            vault_state=vault_state,
            profile=profile,
            content_state=content_state,
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
                # Attach to daemon so read_active_programme() in the
                # narrative composer can see the active programme.
                daemon.programme_manager = manager  # type: ignore[attr-defined]
                log.info("programme_manager_loop: ProgrammeManager constructed")

                # Prep-to-store bridge: load today's prepped segments from
                # disk, create Programme objects, and add+activate them.
                # When prepped segments exist, they replace the auto-planner
                # — the content was composed offline, ready for delivery.
                try:
                    from agents.hapax_daimonion.daily_segment_prep import (
                        load_prepped_programmes,
                    )
                    from shared.programme import (
                        Programme,
                        ProgrammeContent,
                        ProgrammeRole,
                    )

                    prepped = load_prepped_programmes()
                    loaded_any = False
                    for p in prepped:
                        pid = p.get("programme_id")
                        script = p.get("prepared_script", [])
                        if not pid or not script:
                            continue
                        try:
                            # Build a Programme from the prep file
                            role_str = p.get("role", "rant")
                            try:
                                role = ProgrammeRole(role_str)
                            except ValueError:
                                role = ProgrammeRole.RANT

                            content = ProgrammeContent(
                                narrative_beat=p.get("topic", "")[:500],
                                segment_beats=p.get("segment_beats", []),
                                prepared_script=list(script),
                            )
                            prog = Programme(
                                programme_id=pid,
                                role=role,
                                planned_duration_s=3600.0,
                                content=content,
                                parent_show_id=f"show-{_dt.datetime.now(tz=_dt.UTC).strftime('%Y%m%d')}",
                            )
                            manager.store.add(prog)
                            log.info(
                                "prep-to-store: added %s (%s, %d beats, script ready)",
                                pid,
                                role_str,
                                len(script),
                            )
                            loaded_any = True
                        except Exception:
                            log.warning("prep-to-store: failed to add %s", pid, exc_info=True)

                    # Activate the first prepped segment
                    if loaded_any and prepped:
                        first_pid = prepped[0].get("programme_id")
                        if first_pid:
                            try:
                                manager.store.activate(first_pid)
                                log.info("prep-to-store: activated %s", first_pid)
                            except Exception:
                                log.debug("prep-to-store: activate failed", exc_info=True)
                except Exception:
                    log.debug("prep-to-store bridge failed", exc_info=True)
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

        # Beat transition check — runs every tick (1 Hz) so beat cues
        # fire on time regardless of narration recruitment cadence.
        # Also maintains the segment-cue-hold.json that suppresses
        # director overrides during segments.
        try:
            from agents.hapax_daimonion.autonomous_narrative.compose import (
                check_beat_transition,
            )
            from agents.hapax_daimonion.autonomous_narrative.cue_executor import (
                execute_cue,
            )
            from agents.hapax_daimonion.autonomous_narrative.segment_prompts import (
                SEGMENTED_CONTENT_ROLES,
            )

            active = manager.store.active_programme()
            _hold_path = _Path("/dev/shm/hapax-compositor/segment-cue-hold.json")
            _segment_path = _Path("/dev/shm/hapax-compositor/active-segment.json")
            if active is not None:
                rv = getattr(active.role, "value", str(active.role))
                if rv in SEGMENTED_CONTENT_ROLES:
                    # Refresh hold file every tick so director stays suppressed
                    try:
                        _hold_path.parent.mkdir(parents=True, exist_ok=True)
                        _tmp = _hold_path.with_suffix(".json.tmp")
                        _tmp.write_text(
                            _json.dumps(
                                {
                                    "set_at": time.time(),
                                    "ttl_s": 5.0,
                                    "programme": str(active.programme_id),
                                }
                            ),
                            encoding="utf-8",
                        )
                        _tmp.replace(_hold_path)
                    except Exception:
                        pass

                    # Write segment state for the Segment Content Ward.
                    # The ward reads this at 1 Hz and renders the visual overlay.
                    try:
                        content = getattr(active, "content", None)
                        beats = getattr(content, "segment_beats", []) or [] if content else []
                        narrative_beat = (
                            getattr(content, "narrative_beat", "") or "" if content else ""
                        )
                        topic = getattr(active, "topic", None) or narrative_beat
                        started_at = getattr(active, "actual_started_at", None) or time.time()
                        planned_duration_s = getattr(active, "planned_duration_s", 3600.0)
                        _, beat_idx = check_beat_transition(active)
                        _seg_tmp = _segment_path.with_suffix(".json.tmp")
                        _seg_tmp.write_text(
                            _json.dumps(
                                {
                                    "programme_id": str(active.programme_id),
                                    "role": rv,
                                    "topic": str(topic)[:200],
                                    "narrative_beat": str(narrative_beat)[:300],
                                    "segment_beats": [str(b)[:100] for b in beats[:12]],
                                    "current_beat_index": beat_idx,
                                    "started_at": started_at,
                                    "planned_duration_s": planned_duration_s,
                                }
                            ),
                            encoding="utf-8",
                        )
                        _seg_tmp.replace(_segment_path)
                    except Exception:
                        log.debug("active-segment.json write failed", exc_info=True)

                    changed, beat_idx = check_beat_transition(active)
                    if changed:
                        cues = (
                            getattr(
                                getattr(active, "content", None),
                                "segment_cues",
                                [],
                            )
                            or []
                        )
                        if cues and 0 <= beat_idx < len(cues):
                            execute_cue(cues[beat_idx])
                else:
                    # Not a segmented role — clear hold and segment state
                    _hold_path.unlink(missing_ok=True)
                    _segment_path.unlink(missing_ok=True)
            else:
                _hold_path.unlink(missing_ok=True)
                _segment_path.unlink(missing_ok=True)

            # Continuous cycling: activate the next pending prepped
            # programme when either (a) no programme is active, or
            # (b) the active programme has no prepared script (i.e.
            # came from the auto-planner, not the prep bridge).
            # This is the "radio station" model — never dead air.
            #
            # When the pending pool is empty, recycle completed
            # segments from the archive using contextual matching
            # (working_mode × stance → role affinity) or pseudo-RNG
            # as fallback. Never dead air.
            try:
                from shared.programme import ProgrammeStatus as _PS

                _active = manager.store.active_programme()
                _needs_cycle = _active is None or not getattr(
                    getattr(_active, "content", None), "prepared_script", None
                )
                if _needs_cycle:
                    pending = [
                        p
                        for p in manager.store.all()
                        if p.status == _PS.PENDING and getattr(p.content, "prepared_script", None)
                    ]
                    nxt = None
                    if pending:
                        nxt = pending[0]
                    else:
                        # Pool exhausted — recycle from completed archive
                        nxt = _pick_recycled_segment(manager.store, _active)

                    if nxt is not None:
                        # Deactivate the current non-prepped programme if any
                        if _active is not None:
                            try:
                                manager.store.deactivate(_active.programme_id)
                                log.info(
                                    "auto-cycle: deactivated non-prepped %s",
                                    _active.programme_id,
                                )
                            except Exception:
                                log.debug("auto-cycle: deactivate failed", exc_info=True)
                        manager.store.activate(nxt.programme_id)
                        log.info(
                            "auto-cycle: activated %s %s (%s)",
                            "recycled" if nxt.status == _PS.COMPLETED else "next prepped",
                            nxt.programme_id,
                            getattr(nxt.role, "value", "?"),
                        )
            except Exception:
                log.debug("auto-cycle failed", exc_info=True)
        except Exception:
            log.debug("beat transition check failed", exc_info=True)

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
