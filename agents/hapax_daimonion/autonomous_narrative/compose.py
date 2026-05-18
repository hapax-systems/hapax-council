"""Compose narrative prose from a ``NarrativeContext`` via the local LLM tier.

DUAL-MODE composition (operator directive 2026-05-04):

- **Ambient mode** (operator-context roles or no programme): 1-3 sentences,
  scientific register, observation-style. This is the original behaviour.
- **Segment mode** (segmented-content roles): 3-6 sentences, professional
  host register, audience-aware, beat-by-beat delivery. Hapax is the HOST,
  not a passive observer. Following professional segment duties is NOT a
  grounding violation.

Per operator directive 2026-04-27 ("there should BE no fences"), the
composer no longer drops emission to silence on register violations —
it sanitizes the trouble patterns that matter and emits the surviving
prose.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

from shared.claim_prompt import SURFACE_FLOORS
from shared.narration_triad import render_triad_prompt_context
from shared.operator_referent import REFERENTS
from shared.resident_command_r import call_resident_command_r

log = logging.getLogger(__name__)


_GROUNDED_MAX_TOKENS = 220  # ~3 full sentences (ambient mode)
_SEGMENT_MAX_TOKENS = 1200  # full segment in one shot (replaces per-beat 500)
_GROUNDED_TEMPERATURE = 0.85

# Per-beat dedup: prevents the same segment beat from being composed
# multiple times when the endogenous drive fires faster than TTS playback.
_last_segment_compose_at: float = 0.0
_SEGMENT_COMPOSE_COOLDOWN_S: float = 90.0  # Opus takes ~60s; 90s prevents overlap


def _set_last_segment_compose(ts: float) -> None:
    global _last_segment_compose_at
    _last_segment_compose_at = ts


_TROUBLE_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"[\U0001F300-\U0001FAFF]"),
    re.compile(r"\bthe\s+ai\b", re.IGNORECASE),
    re.compile(r"\b(an|this|our|my)\s+ai\b", re.IGNORECASE),
    re.compile(r"\bartificial\s+intelligence\b", re.IGNORECASE),
    re.compile(r"\bsubscribe\b", re.IGNORECASE),
    re.compile(r"\blike\s+and\s+(follow|subscribe|share)\b", re.IGNORECASE),
    re.compile(r"\bsmash\s+(that\s+)?(like|subscribe)\b", re.IGNORECASE),
    re.compile(r"\bhit\s+the\s+bell\b", re.IGNORECASE),
    re.compile(r"\bcomment\s+(below|down\s+below)\b", re.IGNORECASE),
    re.compile(r"\bdon['']?t\s+forget\s+to\s+(like|subscribe|share)\b", re.IGNORECASE),
    re.compile(
        r"\b(vinyl|platter|turntable|spinning|RPM|album\s+cover|album\s+art|record\s+playback)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bCBIP\b"),
    re.compile(r"\bchess[\s-]?boxing\b", re.IGNORECASE),
    re.compile(r"\bring[\s-]?2\s+gate\b", re.IGNORECASE),
    re.compile(r"\bintensity\s+router\b", re.IGNORECASE),
    re.compile(r"\b(feels?|wants?|dreams?|hopes?|desires?|longs?)\b", re.IGNORECASE),
    # RLHF openers and cheesy transitional filler
    re.compile(r"\bdiv(e|ing)\s+in(to)?\b", re.IGNORECASE),
    re.compile(r"\blet['']?s\s+(talk|dive|explore|unpack|break)\b", re.IGNORECASE),
    re.compile(r"\bbuckle\s+up\b", re.IGNORECASE),
    re.compile(r"\bwithout\s+further\s+ado\b", re.IGNORECASE),
    re.compile(r"\bwon['']?t\s+want\s+to\s+miss\b", re.IGNORECASE),
    re.compile(r"\bgame[\s-]?changer\b", re.IGNORECASE),
    re.compile(r"\bmind[\s-]?blow(ing|n)\b", re.IGNORECASE),
    re.compile(r"\btoday[,]?\s+(we['']?re|I['']?m|let)\b", re.IGNORECASE),
    re.compile(r"\bjust\s+getting\s+started\b", re.IGNORECASE),
    re.compile(r"\bstay\s+tuned\b", re.IGNORECASE),
    re.compile(r"\bwelcome\s+(back|to)\b", re.IGNORECASE),
)


def _violates_operator_referent_policy(
    text: str,
    operator_referent: str | None,
    *,
    segment_mode: bool = False,
) -> bool:
    """Fail closed on legal-name leaks or mixed non-formal referents.

    In segment mode, the mixed-referent check is relaxed because segment
    topics (e.g. "broadcast safety systems") may use 'the operator' in a
    generic technical sense, not as a reference to the Hapax operator.
    The legal-name check is always enforced.
    """
    legal_name = os.environ.get("HAPAX_OPERATOR_NAME", "").strip()
    if legal_name and re.search(re.escape(legal_name), text, flags=re.IGNORECASE):
        log.warning("autonomous_narrative: legal-name leak detected; dropping output")
        return True

    # In segment mode, skip mixed-referent check — the host register
    # may use 'the operator' generically in technical content.
    if segment_mode:
        return False

    if not operator_referent:
        return False

    scrubbed = re.sub(re.escape(operator_referent), "", text, flags=re.IGNORECASE)
    for referent in sorted(REFERENTS, key=len, reverse=True):
        if referent == operator_referent:
            continue
        if re.search(re.escape(referent), scrubbed, flags=re.IGNORECASE):
            log.warning("autonomous_narrative: mixed operator referents detected; dropping output")
            return True
    return False


# Patterns that are ONLY trouble during ambient mode. During segments,
# the host register needs these: audience address CTAs, energy language,
# broadcast transitions, and some emotional expression are professional
# delivery, not violations.
_SEGMENT_RELAXED_PATTERNS: frozenset[int] = frozenset(
    {
        # Index into _TROUBLE_PATTERNS for patterns relaxed during segments:
        # 4: subscribe, 5: like and follow, 6: smash that, 7: hit the bell,
        # 8: comment below, 9: don't forget to, 12: chess-boxing,
        # 14: feels/wants/dreams,
        # 15-25: RLHF openers & broadcast transitions — these ARE the host
        #   register for structured segments (dive into, let's talk, today
        #   we're, stay tuned, welcome back, etc.)
        4,
        5,
        6,
        7,
        8,
        9,
        12,
        14,
        15,
        16,
        17,
        18,
        19,
        20,
        21,
        22,
        23,
        24,
        25,
    }
)


def _sanitize_register(
    text: str,
    *,
    operator_referent: str | None = None,
    segment_mode: bool = False,
) -> str:
    """Drop sentences containing trouble patterns; keep the rest.

    Soft sanitize per 2026-04-27 "no fences" directive: if a sentence
    trips a constitutional fence, drop that sentence — but emit the
    surviving prose instead of dropping the whole utterance.

    During segment mode, the host register relaxes certain patterns:
    audience CTAs and some emotional expression are professional
    delivery, not violations.
    """
    if _violates_operator_referent_policy(text, operator_referent, segment_mode=segment_mode):
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    keep: list[str] = []
    for sentence in sentences:
        s = sentence.strip()
        if not s:
            continue
        trouble = False
        for i, pat in enumerate(_TROUBLE_PATTERNS):
            if segment_mode and i in _SEGMENT_RELAXED_PATTERNS:
                continue
            if pat.search(s):
                log.info("autonomous_narrative: dropped trouble sentence: %s", s[:120])
                trouble = True
                break
        if not trouble:
            keep.append(s)
    return " ".join(keep).strip()


# Beat index tracking — time-derived from the programme plan.
# The planner specifies segment_beat_durations (seconds per beat).
# The current beat is computed from elapsed programme time against
# the cumulative duration schedule. No expert rules — the content
# plan determines pacing.
#
# _last_beat_by_programme tracks the last-seen beat index per programme
# so we can detect transitions and fire cues exactly once.
_last_beat_by_programme: dict[str, int] = {}


def _resolve_beat_durations(prog: Any) -> list[float]:
    """Get beat durations from the plan, with fallback to even division."""
    content = getattr(prog, "content", None)
    beats = getattr(content, "segment_beats", []) or [] if content else []
    durations = getattr(content, "segment_beat_durations", []) or [] if content else []
    total_beats = len(beats)
    if total_beats == 0:
        return []
    # Use plan durations if provided and complete
    if len(durations) >= total_beats:
        return [float(d) for d in durations[:total_beats]]
    # Fallback: divide planned_duration_s evenly
    planned = getattr(prog, "planned_duration_s", 600.0) or 600.0
    even = float(planned) / total_beats
    # Pad with even durations if partial
    result = [float(d) for d in durations]
    while len(result) < total_beats:
        result.append(even)
    return result


def _get_beat_index(prog: Any) -> int:
    """Compute current beat index from elapsed programme time.

    Uses the planner's segment_beat_durations to determine which beat
    the segment is currently on. The beat index is purely time-derived
    from the programme plan — no emission counting, no expert rules.
    """
    import time as _time

    if prog is None:
        return 0
    content = getattr(prog, "content", None)
    beats = getattr(content, "segment_beats", []) or [] if content else []
    total = len(beats)
    if total == 0:
        return 0

    started_at = getattr(prog, "actual_started_at", None)
    if not started_at or not isinstance(started_at, (int, float)):
        return 0

    elapsed = _time.time() - started_at
    durations = _resolve_beat_durations(prog)

    # Walk through cumulative durations to find current beat
    cumulative = 0.0
    for i, dur in enumerate(durations):
        cumulative += dur
        if elapsed < cumulative:
            return i
    # Past all beats — clamp to last beat (closing)
    return total - 1


def check_beat_transition(prog: Any) -> tuple[bool, int]:
    """Check if the beat has changed since last check.

    Returns (changed, current_beat_index). When changed is True,
    the caller should fire the cue for current_beat_index.
    """
    if prog is None:
        return False, 0
    pid = getattr(prog, "programme_id", None)
    if pid is None:
        return False, 0
    pid = str(pid)

    current = _get_beat_index(prog)
    last = _last_beat_by_programme.get(pid, -1)

    if current != last:
        _last_beat_by_programme[pid] = current
        content = getattr(prog, "content", None)
        beats = getattr(content, "segment_beats", []) or [] if content else []
        total = len(beats)
        if last >= 0:
            log.info(
                "beat advanced: %s beat %d/%d -> %d/%d",
                pid,
                last,
                total,
                current,
                total,
            )
        else:
            log.info(
                "beat started: %s beat %d/%d",
                pid,
                current,
                total,
            )
        # Prune old entries
        if len(_last_beat_by_programme) > 10:
            oldest = list(_last_beat_by_programme.keys())[:-10]
            for k in oldest:
                _last_beat_by_programme.pop(k, None)
        return True, current

    return False, current


def _is_segment_mode(context: Any) -> bool:
    """True if the active programme is a segmented-content role."""
    from agents.hapax_daimonion.autonomous_narrative.segment_prompts import (
        SEGMENTED_CONTENT_ROLES,
    )

    prog = getattr(context, "programme", None)
    if prog is None:
        return False
    role = getattr(prog, "role", None)
    if role is None:
        return False
    role_value = getattr(role, "value", str(role))
    return role_value in SEGMENTED_CONTENT_ROLES


def compose_narrative(
    context: Any,
    *,
    operator_referent: str | None = None,
    llm_call: Any | None = None,
) -> str | None:
    """Compose narrative prose grounded in ``context``.

    Dual-mode: ambient observation (1-3 sentences, scientific register)
    vs segment hosting (3-6 sentences, professional host register).

    Returns None only when the LLM call genuinely fails or returns nothing.
    """
    try:
        import json
        from pathlib import Path

        bands_raw = json.loads(
            Path("/dev/shm/hapax-temporal/bands.json").read_text(encoding="utf-8")
        )
    except Exception:
        bands_raw = {}

    try:
        from agents.hapax_daimonion.phenomenal_context import render as render_phenom

        phenom_text = render_phenom(tier="CAPABLE")
        phenom_lines = phenom_text.strip().split("\n") if phenom_text else []
    except Exception:
        phenom_lines = []

    from shared.grounding_context import GroundingContextVerifier

    envelope = GroundingContextVerifier.build_envelope(
        turn_id="autonomous_narrative",
        temporal_bands=bands_raw,
        phenomenal_lines=phenom_lines,
        available_tools=[],
    )

    segment_mode = _is_segment_mode(context)
    seed = _build_seed(context)

    if segment_mode:
        from agents.hapax_daimonion.autonomous_narrative.segment_prompts import (
            build_segment_prompt,
        )

        prog = getattr(context, "programme", None)

        # Time-based cooldown: segments need continuous narration across
        # long beats (10+ minutes each). Opus takes ~60s per call, so a
        # 90s cooldown ensures steady output without overlapping calls.
        prog_id = getattr(prog, "programme_id", None)
        now = time.monotonic()
        elapsed = now - _last_segment_compose_at
        if elapsed < _SEGMENT_COMPOSE_COOLDOWN_S:
            log.debug(
                "compose_narrative: segment cooldown (%.0fs remaining)",
                _SEGMENT_COMPOSE_COOLDOWN_S - elapsed,
            )
            return None
        _set_last_segment_compose(now)

        prompt = build_segment_prompt(
            context,
            seed,
            operator_referent=operator_referent,
            envelope=envelope,
        )
        max_tokens = _SEGMENT_MAX_TOKENS
        log.info(
            "compose_narrative: SEGMENT mode (role=%s, programme=%s)",
            getattr(getattr(prog, "role", None), "value", "?"),
            prog_id,
        )
    else:
        prompt = _build_prompt(
            context, seed, operator_referent=operator_referent, envelope=envelope
        )
        max_tokens = _GROUNDED_MAX_TOKENS

    if llm_call is None:
        llm_call = _call_llm_grounded

    try:
        polished = llm_call(prompt=prompt, seed=seed, max_tokens=max_tokens)
    except Exception as exc:
        log.warning("autonomous_narrative LLM call failed: %s", exc)
        return None

    if not polished or not isinstance(polished, str):
        return None

    # Grounding triage: compute P(grounding_positive | candidate, context)
    # from impingement bus, speech chronicle, and technical density.
    # Segments bypass triage — they're already grounded by the Opus planner.
    # The triage is designed for ambient narration, not structured segments.
    if not segment_mode:
        try:
            from agents.hapax_daimonion.autonomous_narrative.grounding_triage import (
                triage as _grounding_triage,
            )

            action, posterior = _grounding_triage(polished.strip())
            if action == "silence":
                log.info(
                    "autonomous_narrative: grounding triage → silence (p=%.3f)",
                    posterior,
                )
                return None
            # "emit" and "marginal" both proceed — marginal is logged but allowed
        except Exception:
            log.debug("grounding_triage failed; proceeding", exc_info=True)

    # Segment mode uses relaxed sanitization — host register allows
    # audience address, energy language, and professional delivery.
    cleaned = _sanitize_register(
        polished.strip(),
        operator_referent=operator_referent,
        segment_mode=segment_mode,
    )
    if not cleaned:
        return None

    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    safe_sentences = []
    for sentence in sentences:
        s = sentence.strip()
        if not s:
            continue
        is_safe, reason = GroundingContextVerifier.verify_clause(envelope, s)
        if is_safe:
            safe_sentences.append(s)
        else:
            log.warning(
                "autonomous_narrative clause gate rejected sentence: %r (reason: %s)", s, reason
            )

    final_text = " ".join(safe_sentences).strip()
    if not final_text:
        return None
    if final_text[-1] not in ".!?":
        final_text = final_text + "."
    return final_text


# Segmented-content roles whose asset resolution enriches the narrative
# seed with concrete grounding material from vault / Qdrant / content-resolver.
_SEGMENTED_CONTENT_ROLES: frozenset[str] = frozenset(
    {"tier_list", "top_10", "rant", "react", "iceberg", "interview", "lecture"}
)


# Role-specific framing for the composition prompt. Each entry tells the
# LLM what kind of segment it's narrating so it produces role-appropriate
# prose rather than generic observation. Falls back to empty string for
# operator-context roles (those use the default generic framing).
_SEGMENT_FRAMING: dict[str, str] = {
    "tier_list": (
        "You are narrating a TIER LIST segment. Place items into ranked "
        "tiers (S/A/B/C/D) with brief reasoning per placement. Use the "
        "resolved candidates below as your source material."
    ),
    "top_10": (
        "You are narrating a TOP 10 COUNTDOWN. Count down from 10 to 1, "
        "building anticipation. Each entry deserves a sentence of context."
    ),
    "rant": (
        "You are narrating a RANT segment. Build a sustained, opinionated "
        "position using the operator's grounded positions below. Escalate "
        "with examples and evidence. Never invent positions the operator "
        "hasn't expressed."
    ),
    "react": (
        "You are narrating a REACT segment. Comment on the source material "
        "with genuine analytical engagement. Reference specific moments or "
        "claims from the resolved content."
    ),
    "iceberg": (
        "You are narrating an ICEBERG segment. Start at the surface "
        "(commonly known facts) and progressively descend into deeper, "
        "more specialized knowledge layers."
    ),
    "interview": (
        "You are narrating an INTERVIEW prep or segment. Frame questions "
        "and context about the subject using the prep material below."
    ),
    "lecture": (
        "You are delivering a LECTURE point. Present structured, "
        "authoritative explanation grounded in the operator's vault notes "
        "and research material."
    ),
}


def _render_assets_context(assets: Any) -> str:
    """Render resolved programme assets as a compact grounding block.

    Each asset type renders differently — tier lists show candidates,
    rants show operator positions, iceberg shows layers, etc. Returns
    empty string on None or empty assets so the caller can skip it.
    """
    if assets is None:
        return ""
    if getattr(assets, "is_empty", True):
        return ""

    lines: list[str] = ["Resolved programme assets:"]

    # TierListAssets / Top10Assets — list candidates
    candidates = getattr(assets, "candidates", None) or getattr(assets, "ranked_candidates", None)
    if candidates:
        for i, c in enumerate(candidates[:15], 1):
            lines.append(f"  {i}. {c[:120]}")

    # RantAssets — operator positions + corrections
    positions = getattr(assets, "operator_positions", None)
    if positions:
        lines.append("Operator positions:")
        for p in positions[:6]:
            lines.append(f"  - {p[:150]}")
    corrections = getattr(assets, "prior_corrections", None)
    if corrections:
        lines.append("Prior corrections:")
        for c in corrections[:4]:
            lines.append(f"  - {c[:150]}")

    # ReactAssets — resolved source material
    title = getattr(assets, "resolved_title", None)
    if title:
        lines.append(f"Source: {title}")
    excerpt = getattr(assets, "resolved_excerpt", None)
    if excerpt:
        lines.append(f"Excerpt: {excerpt[:200]}")

    # IcebergAssets — layered outline
    layers = getattr(assets, "layers", None)
    if layers:
        layer_names = ["Surface", "Areas", "Projects", "Deep"]
        for i, layer in enumerate(layers):
            name = layer_names[i] if i < len(layer_names) else f"Layer {i + 1}"
            if layer:
                lines.append(f"  [{name}]: {', '.join(str(x)[:80] for x in layer[:4])}")

    # InterviewAssets — prep hits
    prep = getattr(assets, "prep_hits", None)
    if prep:
        lines.append("Subject prep:")
        for p in prep[:6]:
            lines.append(f"  - {p[:150]}")

    # LectureAssets — outline notes + RAG
    notes = getattr(assets, "outline_notes", None)
    if notes:
        lines.append("Vault outline notes:")
        for n in notes[:6]:
            lines.append(f"  - {n}")
    fallbacks = getattr(assets, "rag_fallbacks", None)
    if fallbacks:
        lines.append("RAG context:")
        for f in fallbacks[:4]:
            lines.append(f"  - {f[:150]}")

    return "\n".join(lines) if len(lines) > 1 else ""


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _delivery_mode_value(content: Any) -> str:
    mode = getattr(content, "delivery_mode", "live_prior")
    return str(getattr(mode, "value", mode) or "live_prior").strip().lower().replace("-", "_")


def _render_live_prior_context(prog: Any) -> str:
    content = getattr(prog, "content", None)
    if content is None or _delivery_mode_value(content) != "live_prior":
        return ""

    beat_index = _get_beat_index(prog)
    cards = [_mapping(item) for item in getattr(content, "beat_cards", []) or []]
    priors = [_mapping(item) for item in getattr(content, "live_priors", []) or []]
    cards = [item for item in cards if item.get("beat_index") in {None, beat_index}]
    priors = [item for item in priors if item.get("beat_index") in {None, beat_index}]
    if not cards and not priors:
        return ""

    lines = [
        "Prepared live priors (proposal-only; compose live, do not read as a script):",
        f"  current beat index: {beat_index}",
    ]
    for card in cards[:2]:
        title = str(card.get("title") or card.get("beat_id") or "beat").strip()
        summary = str(card.get("prior_summary") or "").strip()
        needs = ", ".join(str(item) for item in card.get("layout_needs") or [] if item)
        actions = ", ".join(str(item) for item in card.get("action_intent_kinds") or [] if item)
        if title:
            lines.append(f"  - beat card: {title[:140]}")
        if summary:
            lines.append(f"    prior: {summary[:700]}")
        if actions:
            lines.append(f"    action intents: {actions[:220]}")
        if needs:
            lines.append(f"    layout needs: {needs[:220]}")
    for prior in priors[:2]:
        text = str(prior.get("text") or "").strip()
        if text:
            lines.append(f"  - live prior excerpt: {text[:700]}")
    return "\n".join(lines)


def _build_seed(context: Any) -> str:
    """Deterministic state summary used as the LLM grounding."""
    parts: list[str] = []
    prog = getattr(context, "programme", None)
    role_value: str | None = None
    if prog is not None:
        role = getattr(prog, "role", None)
        if role is not None:
            role_value = getattr(role, "value", str(role))
            parts.append(f"Active programme role: {role_value}")
        beat = (
            getattr(getattr(prog, "narrative", None), "narrative_beat", None)
            or getattr(prog, "narrative_beat", None)
            or getattr(getattr(prog, "content", None), "narrative_beat", None)
        )
        if isinstance(beat, str) and beat:
            parts.append(f"Programme narrative beat: {beat}")

        live_prior_context = _render_live_prior_context(prog)
        if live_prior_context:
            parts.append(live_prior_context)

        # Resolve structured assets for segmented-content roles.
        # Enriches the seed with concrete vault / Qdrant / content-resolver
        # grounding so the narrator has material to work with, not just intent.
        if role_value and role_value in _SEGMENTED_CONTENT_ROLES:
            try:
                from agents.programme_authors.asset_resolver import resolve_assets

                content = getattr(prog, "content", None)
                topic = None
                if isinstance(beat, str):
                    topic = beat
                topic = (
                    getattr(content, "declared_topic", None)
                    or topic
                    or getattr(prog, "topic", None)
                    or ""
                )
                source_uri = getattr(content, "source_uri", None) or getattr(
                    prog, "source_uri", None
                )
                subject = getattr(content, "subject", None) or getattr(prog, "subject", None)
                assets = resolve_assets(
                    role_value,
                    topic=str(topic),
                    source_uri=source_uri,
                    subject=subject,
                )
                assets_ctx = _render_assets_context(assets)
                if assets_ctx:
                    parts.append(assets_ctx)
            except Exception:
                log.debug("asset resolution failed for role=%s", role_value, exc_info=True)

    tone = getattr(context, "stimmung_tone", "")
    if tone:
        parts.append(f"Stimmung tone: {tone}")
    activity = getattr(context, "director_activity", "")
    if activity:
        parts.append(f"Current activity: {activity}")
    events_summary = _summarize_events(context.chronicle_events)
    if events_summary:
        parts.append(f"Recent events: {events_summary}")
    vault_summary = _summarize_vault_context(getattr(context, "vault_context", None))
    if vault_summary:
        parts.append(vault_summary)
    triad_summary = render_triad_prompt_context(getattr(context, "triad_continuity", None))
    if triad_summary:
        parts.append("Narration continuity ledger:\n" + triad_summary)

    drive_ctx = _read_drive_context()
    if drive_ctx:
        parts.append(drive_ctx)

    return "\n".join(parts)


def _read_drive_context() -> str:
    """Read the narrative drive's latest context from SHM."""
    try:
        import json as _json
        from pathlib import Path as _P

        p = _P("/dev/shm/hapax-daimonion/drive-context.json")
        if not p.exists():
            return ""
        data = _json.loads(p.read_text(encoding="utf-8"))
        parts = ["Narrative drive context:"]
        if data.get("chronicle_event_count"):
            parts.append(f"  Chronicle events (600s window): {data['chronicle_event_count']}")
        if data.get("stimmung_stance"):
            parts.append(f"  Stimmung stance: {data['stimmung_stance']}")
        if data.get("operator_presence_score"):
            parts.append(f"  Operator presence: {data['operator_presence_score']}")
        if data.get("programme_role"):
            parts.append(f"  Programme role: {data['programme_role']}")
        return "\n".join(parts) if len(parts) > 1 else ""
    except Exception:
        return ""


def _summarize_vault_context(vault_context: Any) -> str:
    """Render the operator's vault state as a compact context block."""
    if vault_context is None:
        return ""
    excerpts = getattr(vault_context, "daily_note_excerpts", ()) or ()
    goals = getattr(vault_context, "active_goals", ()) or ()
    if not excerpts and not goals:
        return ""

    sections: list[str] = []
    if goals:
        goal_lines = [f"  - [{prio}] {title} ({status})" for title, prio, status in goals]
        sections.append("Operator's active goals:\n" + "\n".join(goal_lines))
    if excerpts:
        note_lines: list[str] = []
        for date_label, body in excerpts:
            indented_body = body.replace("\n", "\n    ")
            note_lines.append(f"  [{date_label}]\n    {indented_body}")
        sections.append("Operator's recent daily notes (oldest first):\n" + "\n".join(note_lines))

    return "Operator focus context:\n" + "\n\n".join(sections)


def _summarize_events(events: tuple[dict, ...]) -> str:
    """Render the chronicle events as a compact bullet list for the prompt.

    Deduplicates by (source, narrative-prefix) so the LLM doesn't see
    8 copies of the same templated exploration.* curiosity message —
    that paralyzed Command-R into 4-word stub outputs. Cap at 8 unique
    events, sorted by ts ascending so the LLM sees temporal order.
    """
    if not events:
        return ""
    sorted_events = sorted(events, key=lambda e: float(e.get("ts") or e.get("timestamp") or 0.0))
    seen: set[tuple[str, str]] = set()
    bullets: list[str] = []
    for e in sorted_events:
        source = e.get("source") or "unknown"
        kind = e.get("intent_family") or e.get("event_type") or e.get("type") or ""
        payload = e.get("content") or e.get("payload") or {}
        narrative = ""
        if isinstance(payload, dict):
            narrative = payload.get("narrative") or payload.get("metric") or ""
            if not narrative and isinstance(payload.get("changed_params"), dict):
                params = payload["changed_params"]
                top = sorted(
                    params.items(),
                    key=lambda kv: abs(kv[1]) if isinstance(kv[1], (int, float)) else 0,
                    reverse=True,
                )[:2]
                narrative = "shift in " + ", ".join(k for k, _ in top)
            if not narrative and payload.get("technique_name"):
                narrative = f"activated {payload['technique_name']}"
        dedup_key = (str(source), narrative[:60])
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        suffix = f": {narrative}" if narrative else ""
        bullets.append(f"  - {source}/{kind}{suffix}".rstrip("/"))
        if len(bullets) >= 8:
            break
    return "\n" + "\n".join(bullets)


def _build_prompt(
    context: Any, seed: str, *, operator_referent: str | None = None, envelope: Any | None = None
) -> str:
    """The full LLM prompt for the local grounded tier."""
    if envelope is not None:
        from shared.grounding_context import GroundingContextVerifier

        envelope_xml = GroundingContextVerifier.render_xml(envelope)
    else:
        # Fallback for tests that don't pass an envelope
        from shared.claim_prompt import render_envelope

        envelope_xml = render_envelope([], floor=SURFACE_FLOORS["autonomous_narrative"])

    referent_clause = ""
    if operator_referent:
        referents = ", ".join(f"'{r}'" for r in REFERENTS)
        referent_clause = (
            "- If you refer to the operator, use exactly "
            f"'{operator_referent}'. Do not use the legal name. Do not mix any other "
            f"operator referent from this set: {referents}.\n"
        )

    # Segment-specific framing: tell the LLM what kind of segment it's
    # composing for, so tier lists rank items, rants build intensity, etc.
    segment_framing = ""
    prog = getattr(context, "programme", None)
    if prog is not None:
        role = getattr(prog, "role", None)
        role_value = getattr(role, "value", str(role)) if role is not None else None
        if role_value and role_value in _SEGMENT_FRAMING:
            segment_framing = (
                f"\nSEGMENT TYPE: {role_value.upper()}\n{_SEGMENT_FRAMING[role_value]}\n\n"
            )

    return (
        f"{envelope_xml}\n\n"
        "Compose one short autonomous narration for the Hapax "
        "research-instrument livestream, spoken in first-system voice "
        "(Hapax as a system, not a character).\n\n"
        f"{segment_framing}"
        "BEFORE EVERY SENTENCE, ask: does saying this HELP my grounding "
        "or HURT it? Grounding means: specificity, verifiability, earned "
        "authority, epistemic honesty. If a sentence could come from any "
        "chatbot on any topic, it hurts your grounding. If it could only "
        "come from a system that actually knows this material, it helps. "
        "Kill everything that hurts.\n\n"
        "MEANING TRIAGE — before emitting any sentence, pass it "
        "through these gates. If it fails ANY gate, kill it:\n"
        "1. Does it contain a SPECIFIC NOUN — a module name, a metric, "
        "a frequency, a state transition? If not, it's filler.\n"
        "2. Does it carry NEW INFORMATION not present in the previous "
        "sentence? Repetition dressed as elaboration is padding.\n"
        "3. Could a person who knows nothing about this system still "
        "distinguish this sentence from a generic chatbot? If not, "
        "it sounds like AI slop.\n"
        "4. Is it in ACTIVE VOICE with a concrete subject? "
        "'Hapax resolved X' not 'X was resolved'.\n\n"
        "REGISTER: scientific present tense. 1-3 sentences, "
        "60-220 characters. TTS-friendly clauses ending in periods. "
        "System name is 'Hapax' (never 'the AI'). "
        "No personifying verbs (feels, wants, dreams).\n"
        f"{referent_clause}\n"
        "State (deterministic snapshot):\n"
        "---\n"
        f"{seed}\n"
        "---\n\n"
        "Output only the prose. No preamble, no explanation, no "
        "bracketed tokens. End every sentence with a period."
    )


def _call_llm_grounded(
    *,
    prompt: str,
    seed: str,
    max_tokens: int = _GROUNDED_MAX_TOKENS,
) -> str | None:
    """Production LLM call via resident Command-R on TabbyAPI.

    Grounding acts stay on the resident local grounded model, not cloud,
    not LiteLLM fallback, and not a model-swapped TabbyAPI process.

    ``max_tokens`` is elevated during segment mode (500 vs 220) so the
    host prompt can produce 3-6 sentences of professional delivery.
    """

    def _one_call(temp: float) -> str | None:
        return call_resident_command_r(
            prompt,
            max_tokens=max_tokens,
            temperature=temp,
        )

    try:
        text = _one_call(_GROUNDED_TEMPERATURE)
        if not text:
            return None
        # Retry once warmer if the model bailed early (no terminal
        # punctuation OR shorter than 30 chars). Command-R produces
        # 4-word stubs when the prompt feels too constrained; a warmer
        # retry breaks the stub-attractor.
        if len(text) < 30 or text[-1] not in ".!?":
            log.info(
                "autonomous_narrative: short/unterminated output (%d chars), retrying warmer",
                len(text),
            )
            retry = _one_call(min(_GROUNDED_TEMPERATURE + 0.2, 1.1))
            if retry and (len(retry) > len(text) or retry[-1] in ".!?"):
                text = retry
        return text or None
    except Exception as exc:
        log.info("grounded LLM call failed for autonomous narrative: %s", exc)
        return None
