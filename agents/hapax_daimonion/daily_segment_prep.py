"""Daily segment prep — compose all segments offline before going live.

Every day Hapax spends a prep window (default 30 min) composing full
narration scripts for all planned segments.  The resulting scripts are
stored to disk and loaded by the programme loop during the livestream.
During delivery, TTS reads the pre-composed text — zero LLM calls.

This is the "radio show prep" pattern: write the script before you go
on air, then DELIVER it live.

Usage:
    uv run python -m agents.hapax_daimonion.daily_segment_prep
    uv run python -m agents.hapax_daimonion.daily_segment_prep --prep-dir ~/.cache/hapax/segment-prep

The runner can also be triggered by a systemd timer (see
systemd/units/hapax-segment-prep.timer).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shared.resident_command_r import (
    RESIDENT_COMMAND_R_MODEL,
    call_resident_command_r,
    clean_local_model_text,
    configured_resident_model,
    loaded_tabby_model,
    tabby_chat_url,
)
from shared.segment_quality_actionability import (
    ACTIONABILITY_RUBRIC_VERSION,
    EXPLICIT_LAYOUT_FALLBACK_CONTEXT,
    LAYOUT_RESPONSIBILITY_VERSION,
    NON_RESPONSIBLE_STATIC_CONTEXT,
    QUALITY_RUBRIC_VERSION,
    RESPONSIBLE_HOSTING_CONTEXT,
    forbidden_layout_authority_fields,
    render_quality_prompt_block,
    score_segment_quality,
    validate_layout_responsibility,
    validate_segment_actionability,
)

log = logging.getLogger(__name__)

# Where prepped segments live.  One subdirectory per date.
DEFAULT_PREP_DIR = Path(
    os.environ.get(
        "HAPAX_SEGMENT_PREP_DIR",
        os.path.expanduser("~/.cache/hapax/segment-prep"),
    )
)

# Max wall-clock for the entire prep window.
PREP_BUDGET_S = float(os.environ.get("HAPAX_SEGMENT_PREP_BUDGET_S", "1800"))  # 30 min

# How many segments to prep per run.  Fewer segments = more time per
# segment for iterative refinement.  Each segment gets an initial
# composition pass PLUS a critic/rewrite pass.
MAX_SEGMENTS = int(os.environ.get("HAPAX_SEGMENT_PREP_MAX", "4"))
PREP_ARTIFACT_SCHEMA_VERSION = 1
PREP_ARTIFACT_AUTHORITY = "prior_only"
PREP_STATUS_VERSION = 1
PREP_STATUS_FILENAME = "prep-status.json"


def _today_dir(base: Path) -> Path:
    today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    d = base / today
    d.mkdir(parents=True, exist_ok=True)
    return d


def _today_path(base: Path) -> Path:
    today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    return base / today


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_json(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return _sha256_text(text)


def _is_sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value.lower())
    )


def _artifact_hash(payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k != "artifact_sha256"}
    return _sha256_json(body)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _update_prep_status(
    prep_session: dict[str, Any] | None,
    *,
    status: str | None = None,
    phase: str | None = None,
    **updates: Any,
) -> None:
    if not isinstance(prep_session, dict):
        return
    raw_path = prep_session.get("prep_status_path")
    if not raw_path:
        return
    path = Path(str(raw_path))
    payload = dict(prep_session.get("prep_status") or {})
    if status is not None:
        payload["status"] = status
    if phase is not None:
        payload["phase"] = phase
    payload.update({key: value for key, value in updates.items() if value is not None})
    payload["prep_status_version"] = PREP_STATUS_VERSION
    payload["updated_at"] = datetime.now(tz=UTC).isoformat()
    start_monotonic = prep_session.get("_prep_started_monotonic")
    if isinstance(start_monotonic, int | float):
        payload["elapsed_s"] = round(time.monotonic() - float(start_monotonic), 1)
    payload["llm_calls"] = list(prep_session.get("llm_calls") or [])
    prep_session["prep_status"] = payload
    try:
        _write_json_atomic(path, payload)
    except Exception:
        log.warning("daily_segment_prep: failed to write prep status %s", path, exc_info=True)


def _json_equal(left: Any, right: Any) -> bool:
    return _sha256_json(left) == _sha256_json(right)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


# Per-role visual hook guidance for the prep prompt.  Tells the LLM which
# text patterns trigger role-specific on-screen visuals so it can use them
# intentionally rather than accidentally.
_ROLE_VISUAL_HOOKS: dict[str, str] = {
    "tier_list": (
        "TIER CHART HOOKS — the stream renders a live tier chart:\n"
        "  MANDATORY: every ranking/body beat must include at least one exact\n"
        "  tier placement phrase: 'Place [item] in [S/A/B/C/D]-tier'.\n"
        "  Generic history, summary, or analysis without a placement is not a\n"
        "  responsible tier-list beat and will be quarantined.\n"
        "  Items appear on the tier chart as you place them. The audience sees\n"
        "  your rankings build in real time.\n"
        "  Example: 'Place Popcorn Sutton's still craft in S-tier.'\n\n"
    ),
    "top_10": (
        "COUNTDOWN HOOKS — the stream requests a ranked countdown panel:\n"
        "  Use '#N is...' or 'Number N:' to update the current entry display.\n"
        "  The runtime layout loop must render the ranked-list panel before this counts.\n"
        "  Example: '#7 is the Bourdain episode on Appalachian food ways.'\n\n"
    ),
    "iceberg": (
        "ICEBERG DEPTH HOOKS — the stream renders a depth indicator:\n"
        "  Use layer keywords to visually advance through layers:\n"
        "  'surface level' / 'commonly known' → top layer\n"
        "  'going deeper' / 'specialist knowledge' → mid layers\n"
        "  'obscure' / 'almost nobody talks about' → deep layers\n"
        "  'the deepest' / 'bottom of the iceberg' → abyss\n"
        "  The visual darkens and narrows as you descend.\n\n"
    ),
    "rant": (
        "MOOD HOOKS — the stream mood shifts with your affect:\n"
        "  Escalation: 'ridiculous', 'unacceptable', 'outrageous' → intense mood\n"
        "  De-escalation: 'fair', 'nuance', 'reasonable' → warm mood\n"
        "  Use escalation deliberately through the body; land with de-escalation.\n\n"
    ),
    "react": (
        "MOOD HOOKS — the stream mood shifts with your affect:\n"
        "  Engagement: 'brilliant', 'impressive', 'incredible' → warm mood\n"
        "  Skepticism: 'wait', 'hold on', 'not sure' → cool mood\n"
        "  Revelation: 'exactly', 'this is it', 'nailed it' → intense mood\n\n"
    ),
}


def _build_full_segment_prompt(
    programme: Any,
    seed: str,
    operator_referent: str | None = None,
) -> str:
    """Build a prompt that asks the LLM to compose ALL beats at once.

    Unlike the live `build_segment_prompt` which asks for the current
    beat only, this prompt gives the full structure and asks for a
    JSON array of narration blocks — one per beat.  Each beat is a
    substantial paragraph (800-2000 chars, ~1-2 minutes spoken).
    """
    from shared.claim_prompt import SURFACE_FLOORS, render_envelope
    from shared.operator_referent import REFERENTS

    envelope = render_envelope([], floor=SURFACE_FLOORS["autonomous_narrative"])

    role = getattr(programme, "role", None)
    role_value = getattr(role, "value", str(role)) if role else "rant"
    content = getattr(programme, "content", None)
    narrative_beat = getattr(content, "narrative_beat", "") or "" if content else ""
    beats = getattr(content, "segment_beats", []) or [] if content else []

    beat_lines = "\n".join(f"  {i + 1}. {b}" for i, b in enumerate(beats))

    referent_clause = ""
    if operator_referent:
        referents = ", ".join(f"'{r}'" for r in REFERENTS)
        referent_clause = (
            f"- If you refer to the operator, use exactly '{operator_referent}'. "
            f"Other referents: {referents}.\n"
        )

    # Build role-specific visual hook guidance
    visual_hooks = _ROLE_VISUAL_HOOKS.get(role_value, "")

    return (
        f"{envelope}\n\n"
        f"You are Hapax, preparing a {role_value.upper().replace('_', ' ')} segment "
        f"for your research livestream.\n\n"
        f"== SEGMENT DIRECTION ==\n{narrative_beat}\n\n"
        f"== SEGMENT STRUCTURE ==\n{beat_lines}\n\n"
        "== DRAMATIC ARC ==\n"
        "Every segment is a PERFORMANCE, not a listicle. Shape energy across beats:\n"
        "- OPEN with a hook that creates *tension* — a question, a paradox, a provocation\n"
        "- BUILD through the body — each beat must EARN the next, not just follow it\n"
        "- Include at least one PIVOT — a moment where the frame shifts unexpectedly\n"
        "- PEAK at roughly 2/3 through — the deepest, most surprising, most specific beat\n"
        "- BREATHE before landing — a beat that lets the audience absorb what just happened\n"
        "- CLOSE with a reframe that changes how the opening sounds in retrospect\n\n"
        "== BEAT DEPTH ==\n"
        "Each beat is 800-2000 characters of spoken prose (1-2 minutes at broadcast pace).\n"
        "That means 8-20 sentences per beat. Think ESSAY PARAGRAPH, not tweet thread.\n"
        "- Every claim gets its FULL ARGUMENT, not just an assertion\n"
        "- Sources get CONTEXT: 'Zuboff argues X because Y, which matters because Z'\n"
        "- Transitions between beats should feel like a DJ crossfade, not a chapter break\n"
        "- Use rhetorical questions, callbacks to earlier beats, direct address to chat\n"
        "- Let ideas BREATHE — develop a point, sit with it, then pivot\n"
        "- A beat that can be summarized in one sentence is a beat that wasn't written yet\n\n"
        f"{render_quality_prompt_block()}"
        "== VISUAL HOOKS ==\n"
        "Your narration DRIVES the stream visuals. Specific text patterns trigger "
        "on-screen effects automatically. Use them intentionally:\n\n"
        "CHAT TRIGGERS — these phrases poll chat immediately:\n"
        "  'What do you think?', 'Drop it in the chat', 'Let me know in the chat',\n"
        "  'What would you change?', 'What's your pick?'\n"
        "  Use at beat endings where audience engagement adds value. Never as filler.\n\n"
        f"{visual_hooks}"
        "== CRITICAL: SPOKEN PROSE ONLY ==\n"
        "Write ONLY words you would SAY OUT LOUD on a live broadcast.\n"
        "NEVER include stage directions, beat labels, action cues, or meta-instructions.\n"
        "WRONG: 'We pivot. Challenge the S-tier placement. Discuss the complexity.'\n"
        "WRONG: 'We close. Recap the final tier chart. Invite chat to disagree.'\n"
        "RIGHT: 'But here is where the chart gets uncomfortable. Because Sutton — '\n"
        "RIGHT: 'So let me pull this back together. The final chart tells a story...'\n"
        "If a sentence reads like a screenplay direction, DELETE IT and write dialogue.\n\n"
        "== CRITICAL: NO REPETITION ==\n"
        "NEVER repeat the same phrase, sentence, or paragraph across beats.\n"
        "Each beat must be ENTIRELY UNIQUE prose. If you find yourself writing\n"
        "'The chart is live' or 'Let\\'s see the dissent' more than once, STOP.\n"
        "Repetition is the single worst failure mode. Every beat must advance.\n\n"
        "== YOUR TASK ==\n"
        "Compose the COMPLETE narration for this segment — one SUBSTANTIAL block of "
        "broadcast-ready prose per beat. Return a JSON array where each element is "
        "the spoken text for that beat (800-2000 characters each, 8-20 sentences).\n\n"
        "Example format:\n"
        '[\n  "Opening beat — a full paragraph that hooks, contextualizes, and builds '
        'anticipation. Multiple sentences developing the frame...",\n'
        '  "Second beat — continues with depth. Names sources with context. Develops '
        'the argument across many sentences...",\n'
        "  ...\n]\n\n"
        "REGISTER: specialist host on a live production. Mid-Atlantic "
        "broadcast — informed, direct, opinionated. Conference keynote "
        "meets late-night monologue. Charlie Rose depth meets Anthony Bourdain energy.\n\n"
        "RHETORIC — every beat must satisfy ALL of these:\n"
        "1. CLAIM → EVIDENCE → SO-WHAT → IMPLICATION chain per beat.\n"
        "2. Every sentence has at least one TECHNICAL NOUN or PROPER NAME.\n"
        "3. Every claim NAMES ITS SOURCE with context, not just a name-drop.\n"
        "4. ACTIVE VOICE throughout.\n"
        "5. Code for INSIDERS, land for OUTSIDERS.\n"
        "6. Hapax is the system's name. Never 'the AI'.\n"
        "7. VARY SENTENCE LENGTH — short punches between longer developments.\n"
        "8. Each beat must be AT LEAST 800 characters. Shorter beats are FAILURES.\n"
        f"{referent_clause}\n"
        "Segment research & assets:\n"
        "---\n"
        f"{seed}\n"
        "---\n\n"
        "Output ONLY the JSON array. No preamble, no markdown fences, "
        "no explanation. Start with [ and end with ]."
    )


# Resident Command-R calls can be slow when producing long, grounded programme
# plans and 800-2000 char beat scripts. Keep the client timeout above observed
# local inference latency so prep preserves call continuity instead of killing a
# still-productive resident generation.
_PREP_LLM_TIMEOUT_S = float(os.environ.get("HAPAX_SEGMENT_PREP_LLM_TIMEOUT_S", "1200"))

# Content prep is a single-resident-model path.  Evidence acquisition can
# happen elsewhere, but plan/draft/refine must run on the same grounded local
# generator so prep artifacts have a coherent model provenance.
RESIDENT_PREP_MODEL = RESIDENT_COMMAND_R_MODEL
_ALLOWED_PREP_MODELS = {RESIDENT_PREP_MODEL}


def _prep_model() -> str:
    return configured_resident_model("HAPAX_SEGMENT_PREP_MODEL", purpose="segment prep")


def _tabby_chat_url() -> str:
    return tabby_chat_url()


def _loaded_tabby_model() -> str | None:
    return loaded_tabby_model(_tabby_chat_url())


def _assert_resident_prep_model(expected: str | None = None) -> str:
    expected = expected or _prep_model()
    loaded = _loaded_tabby_model()
    if loaded != expected:
        raise RuntimeError(
            "segment prep refuses to run unless TabbyAPI is already serving "
            f"{expected!r}; current model is {loaded!r}"
        )
    return loaded


def _new_prep_session() -> dict[str, Any]:
    return {
        "prep_session_id": f"segment-prep-{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%SZ')}",
        "model_id": _prep_model(),
        "llm_calls": [],
    }


def _record_llm_call(
    prep_session: dict[str, Any] | None,
    *,
    phase: str,
    programme_id: str,
    prompt: str,
) -> dict[str, Any] | None:
    if prep_session is None:
        return None
    calls = prep_session.setdefault("llm_calls", [])
    record = {
        "call_index": len(calls) + 1,
        "phase": phase,
        "programme_id": programme_id,
        "model_id": prep_session.get("model_id", _prep_model()),
        "prompt_sha256": _sha256_text(prompt),
        "prompt_chars": len(prompt),
        "called_at": datetime.now(tz=UTC).isoformat(),
    }
    calls.append(record)
    return record


def _call_llm(
    prompt: str,
    *,
    prep_session: dict[str, Any] | None = None,
    phase: str = "compose",
    programme_id: str = "",
    max_tokens: int = 16384,
) -> str:
    """Call the resident Command-R TabbyAPI endpoint.

    This path intentionally has no model-load, unload, or LiteLLM fallback.
    A residency mismatch is a hard failure because a wrong-model prep artifact
    is worse than no prep artifact.
    """
    model = _prep_model()
    record = _record_llm_call(
        prep_session,
        phase=phase,
        programme_id=programme_id,
        prompt=prompt,
    )
    current_call = (record or {}) | {
        "status": "in_progress",
        "max_tokens": max_tokens,
        "timeout_s": _PREP_LLM_TIMEOUT_S,
    }
    _update_prep_status(
        prep_session,
        status="in_progress",
        phase=f"{phase}_llm_call_in_progress",
        current_llm_call=current_call,
        current_model_id=model,
    )

    try:
        content = call_resident_command_r(
            prompt,
            chat_url=_tabby_chat_url(),
            max_tokens=max_tokens,
            temperature=0.7,
            timeout_s=_PREP_LLM_TIMEOUT_S,
        )
        log.info("segment prep LLM: served by resident Command-R")
        _update_prep_status(
            prep_session,
            status="in_progress",
            phase=f"{phase}_llm_call_returned",
            current_llm_call=current_call | {"status": "returned"},
        )
        return content
    except Exception as exc:
        _update_prep_status(
            prep_session,
            status="in_progress",
            phase=f"{phase}_llm_call_failed",
            current_llm_call=current_call | {"status": "failed"},
            last_error=f"{type(exc).__name__}: {exc}",
        )
        log.warning("segment prep LLM: resident Command-R call failed", exc_info=True)
        raise


def _clean_llm_text(text: str) -> str:
    """Clean leaked hidden-reasoning tags from compatible local backends."""
    return clean_local_model_text(text)


def _parse_script(raw: str) -> list[str]:
    """Parse the LLM response into a list of beat narration blocks."""
    text = _clean_llm_text(raw.strip())
    # Strip markdown fences
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # drop opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        log.warning("segment prep: LLM response is not valid JSON")
        return []

    if not isinstance(parsed, list):
        log.warning("segment prep: LLM response is not a JSON array")
        return []

    beats: list[str] = []
    for item in parsed:
        text: str
        if isinstance(item, dict):
            text = str(
                item.get("draft")
                or item.get("spoken_text")
                or item.get("narration")
                or item.get("text")
                or ""
            ).strip()
        else:
            text = str(item).strip()
        if text:
            beats.append(text)
    return beats


def _build_seed(programme: Any) -> str:
    """Build a research seed from the programme's vault/perception context."""
    from agents.hapax_daimonion.autonomous_narrative.compose import _build_seed

    # The compose module's _build_seed expects a NarrativeContext.
    # For prep, we build a minimal one.
    try:
        from agents.hapax_daimonion.autonomous_narrative.state_readers import (
            NarrativeContext,
        )

        ctx = NarrativeContext(programme=programme)
        return _build_seed(ctx)
    except Exception:
        # Fallback: use narrative_beat as seed
        content = getattr(programme, "content", None)
        return getattr(content, "narrative_beat", "") or ""


def _build_refinement_prompt(script: list[str], programme: Any) -> str:
    """Build a critic/rewrite prompt for iterative refinement.

    Takes the initial draft and asks the LLM to evaluate each beat
    and rewrite any that are thin, rushed, or don't earn their
    conclusions.
    """
    role = getattr(getattr(programme, "role", None), "value", "rant")
    content = getattr(programme, "content", None)
    narrative_beat = getattr(content, "narrative_beat", "") or "" if content else ""
    beats = getattr(content, "segment_beats", []) or [] if content else []

    beat_review = ""
    for i, (direction, text) in enumerate(zip(beats, script, strict=False)):
        chars = len(text)
        beat_review += f"\n--- Beat {i + 1} ({chars} chars) ---\n"
        beat_review += f"Direction: {direction}\n"
        beat_review += f"Draft: {text}\n"

    return (
        f"You are a broadcast editor reviewing a {role.upper().replace('_', ' ')} "
        f"segment script for a research livestream.\n\n"
        f"Topic: {narrative_beat}\n\n"
        "== REVIEW CRITERIA ==\n"
        "For each beat, evaluate:\n"
        "1. LENGTH: Is it at least 800 characters? Beats under 600 chars are THIN.\n"
        "2. SPECIFICITY: Does it name sources WITH context, or just name-drop?\n"
        "3. ARC: Does it earn the next beat, or just stop and start a new topic?\n"
        "4. RHETORIC: Does it vary sentence length? Use direct address? Callbacks?\n"
        "5. ENERGY: Does the beat breathe, or does it rush through its material?\n"
        "6. DEPTH: Could a Wikipedia article make this same point? If yes, it's too shallow.\n"
        "7. STAGE DIRECTIONS: Does the beat contain meta-instructions like 'We pivot',\n"
        "   'We close', 'Recap the chart', 'Invite chat'? These are FATAL — rewrite as\n"
        "   actual spoken prose that a host would say out loud.\n"
        "8. REPETITION: Is the same phrase or paragraph copy-pasted across beats?\n"
        "   Any repeated text block is a FATAL error — each beat must be unique.\n\n"
        "== THE DRAFT ==\n"
        f"{beat_review}\n\n"
        "== YOUR TASK ==\n"
        "Rewrite the ENTIRE script. For beats that are strong, keep them largely "
        "intact but polish transitions. For beats that are thin, rushed, or shallow, "
        "SUBSTANTIALLY expand them — add argument, add evidence, add rhetorical "
        "texture. Every beat in the output MUST be at least 800 characters.\n\n"
        "Return a JSON array of the rewritten beats (same count as the input). "
        "Output ONLY the JSON array. No preamble, no markdown fences. "
        "Start with [ and end with ]."
    )


def _layout_repair_required(layout_responsibility: dict[str, Any]) -> bool:
    """Return True when the draft failed only by leaving repairable layout gaps."""
    violations = layout_responsibility.get("violations")
    if not isinstance(violations, list) or not violations:
        return False
    repairable_reasons = {"unsupported_layout_need", "missing_tier_placement_phrase"}
    return all(
        isinstance(item, dict) and item.get("reason") in repairable_reasons for item in violations
    )


_TIER_BODY_DIRECTION_RE = re.compile(
    r"\b(?:body|item[_ -]?\d+|entry[_ -]?\d+|rank|ranking|place|placing|tier placement)\b",
    re.IGNORECASE,
)
_TIER_SKIP_DIRECTION_RE = re.compile(
    r"\b(?:hook|intro|open|opener|criteria|rubric|close|closing|recap|wrap|chat)\b",
    re.IGNORECASE,
)


def _tier_list_placement_violations(
    *,
    role: str,
    segment_beats: list[str],
    beat_action_intents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Require tier-chart placements for every non-skip tier-list beat."""
    if role != "tier_list":
        return []
    violations: list[dict[str, Any]] = []
    for index, declaration in enumerate(beat_action_intents):
        if not isinstance(declaration, dict):
            continue
        direction = (
            str(segment_beats[index])
            if index < len(segment_beats)
            else str(declaration.get("beat_direction") or "")
        )
        body_or_rank_direction = bool(_TIER_BODY_DIRECTION_RE.search(direction))
        skip_direction = bool(_TIER_SKIP_DIRECTION_RE.search(direction))
        if not body_or_rank_direction and skip_direction:
            continue
        intents = declaration.get("intents") or []
        has_placement = any(
            isinstance(intent, dict) and intent.get("kind") == "tier_chart" for intent in intents
        )
        if not has_placement:
            violations.append(
                {
                    "reason": "missing_tier_placement_phrase",
                    "beat_index": declaration.get("beat_index", index),
                    "beat_direction": direction,
                    "required_trigger": "Place [item] in [S/A/B/C/D]-tier",
                    "required_action_kind": "tier_chart",
                }
            )
    return violations


def _with_tier_list_placement_gate(
    layout_responsibility: dict[str, Any],
    *,
    role: str,
    segment_beats: list[str],
    beat_action_intents: list[dict[str, Any]],
) -> dict[str, Any]:
    violations = _tier_list_placement_violations(
        role=role,
        segment_beats=segment_beats,
        beat_action_intents=beat_action_intents,
    )
    if not violations:
        return layout_responsibility
    gated = json.loads(json.dumps(layout_responsibility))
    gated["ok"] = False
    gated["violations"] = list(gated.get("violations") or []) + violations
    runtime_validation = gated.get("runtime_layout_validation")
    if isinstance(runtime_validation, dict):
        runtime_validation["ok"] = False
    return gated


def _build_layout_repair_prompt(
    script: list[str],
    programme: Any,
    layout_responsibility: dict[str, Any],
) -> str:
    role = getattr(getattr(programme, "role", None), "value", "rant")
    content = getattr(programme, "content", None)
    narrative_beat = getattr(content, "narrative_beat", "") or "" if content else ""
    beats = getattr(content, "segment_beats", []) or [] if content else []
    visual_hooks = _ROLE_VISUAL_HOOKS.get(role, "")
    failed = {
        int(item["beat_index"])
        for item in layout_responsibility.get("violations", [])
        if isinstance(item, dict)
        and isinstance(item.get("beat_index"), int)
        and item.get("reason") in {"unsupported_layout_need", "missing_tier_placement_phrase"}
    }

    mandatory_lines: list[str] = []
    beat_review = ""
    for i, (direction, text) in enumerate(zip(beats, script, strict=False)):
        status = "FAILED: missing supported visible/doable placement" if i in failed else "ok"
        beat_review += f"\n--- Beat {i + 1} ({status}) ---\n"
        beat_review += f"Direction: {direction}\n"
        if role == "tier_list" and i in failed:
            mandatory_lines.append(
                f"- Beat {i + 1}: include a literal sentence that starts with "
                "'Place ' and matches `Place [item] in [S/A/B/C/D]-tier`."
            )
            beat_review += (
                "Mandatory visible trigger: write an exact placement sentence like "
                "'Place Sutton's moonshine craft in S-tier.'\n"
            )
        beat_review += f"Draft: {text}\n"

    mandatory_block = ""
    if mandatory_lines:
        mandatory_block = (
            "== MANDATORY FAILED-BEAT REPAIRS ==\n" + "\n".join(mandatory_lines) + "\n\n"
        )

    return (
        f"You are repairing a {role.upper().replace('_', ' ')} segment for Hapax's "
        "responsible livestream layout contract.\n\n"
        f"Topic: {narrative_beat}\n\n"
        "The previous draft failed because some beats only made spoken arguments. "
        "For Hapax-hosted responsible segments, spoken-only beats do not satisfy "
        "layout responsibility. Rewrite the full script with the same beat count "
        "so every failed beat includes a supported visible/doable trigger in the "
        "spoken words.\n\n"
        f"{render_quality_prompt_block()}"
        "== ROLE-SPECIFIC VISIBLE ACTIONS ==\n"
        f"{visual_hooks}"
        f"{mandatory_block}"
        "If this is a tier-list segment, every failed item/ranking/body beat must "
        "say an exact placement phrase that matches the runtime trigger regex:\n"
        "  Place [item] in [S/A/B/C/D]-tier\n"
        "The sentence must begin with the word 'Place', include the word 'in' "
        "before the tier, and use S-tier, A-tier, B-tier, C-tier, or D-tier. "
        "VALID: 'Place Popcorn Sutton's moonshine craft in S-tier.' "
        "INVALID: 'Let's kick things off by placing Popcorn Sutton in S-tier.' "
        "INVALID: 'Sutton belongs in A-tier.' "
        "Do not merely discuss history; make a ranking the audience can see.\n\n"
        "Do not invent camera shots, screenshots, clips, direct layout commands, "
        "coordinates, cue strings, or stage directions. Keep the prose live-host "
        "spoken text only.\n\n"
        "== DRAFT TO REPAIR ==\n"
        f"{beat_review}\n\n"
        "Return ONLY a JSON array of rewritten spoken beats, same count as the "
        "input. No preamble, no markdown fences. Start with [ and end with ]."
    )


def _repair_layout_actionability(
    script: list[str],
    programme: Any,
    layout_responsibility: dict[str, Any],
    *,
    prep_session: dict[str, Any] | None = None,
    programme_id: str = "",
) -> list[str]:
    """Give resident Command-R one chance to turn spoken-only beats into visible actions."""
    if not _layout_repair_required(layout_responsibility):
        return script
    prompt = _build_layout_repair_prompt(script, programme, layout_responsibility)
    try:
        raw = _call_llm(
            prompt,
            prep_session=prep_session,
            phase="layout_repair",
            programme_id=programme_id,
        )
        repaired = _parse_script(raw)
        if repaired and len(repaired) >= len(script):
            log.info(
                "layout repair: rewrote %d beats for %s after spoken-only layout failure",
                len(script),
                programme_id or "unknown",
            )
            return repaired[: len(script)]
        log.warning(
            "layout repair: got %d beats (expected %d), keeping refined draft",
            len(repaired) if repaired else 0,
            len(script),
        )
    except Exception:
        log.warning("layout repair: LLM call failed, keeping refined draft", exc_info=True)
    return script


def _refine_script(
    script: list[str],
    programme: Any,
    *,
    prep_session: dict[str, Any] | None = None,
    programme_id: str = "",
) -> list[str]:
    """Iterative refinement pass — critic + rewrite.

    Sends the initial draft to the LLM with a broadcast-editor persona
    that evaluates each beat on specificity, arc, length, and rhetoric,
    then rewrites weak beats.  Returns the improved script.
    """
    prompt = _build_refinement_prompt(script, programme)
    try:
        raw = _call_llm(
            prompt,
            prep_session=prep_session,
            phase="refine",
            programme_id=programme_id,
        )
        refined = _parse_script(raw)
        if refined and len(refined) >= len(script):
            # Log improvement stats
            old_avg = sum(len(b) for b in script) / max(len(script), 1)
            new_avg = sum(len(b) for b in refined) / max(len(refined), 1)
            log.info(
                "refinement: avg chars/beat %.0f → %.0f (%.0f%% change)",
                old_avg,
                new_avg,
                ((new_avg - old_avg) / max(old_avg, 1)) * 100,
            )
            return refined[: len(script)]  # Trim to original beat count
        log.warning(
            "refinement: got %d beats (expected %d), keeping original",
            len(refined) if refined else 0,
            len(script),
        )
    except Exception:
        log.warning("refinement: LLM call failed, keeping original", exc_info=True)
    return script


def _source_hashes_from_fields(
    *,
    programme_id: str,
    role: str,
    topic: str,
    segment_beats: list[str],
    seed_sha256: str,
    prompt_sha256: str,
) -> dict[str, str]:
    source_payload = {
        "programme_id": programme_id,
        "role": role,
        "topic": topic,
        "segment_beats": segment_beats,
    }
    return {
        "programme_sha256": _sha256_json(source_payload),
        "topic_sha256": _sha256_text(str(topic)),
        "segment_beats_sha256": _sha256_json(segment_beats),
        "seed_sha256": seed_sha256,
        "prompt_sha256": prompt_sha256,
    }


def _source_hashes(programme: Any, *, seed: str, prompt: str) -> dict[str, str]:
    content = getattr(programme, "content", None)
    beat_values = getattr(content, "segment_beats", []) or [] if content else []
    return _source_hashes_from_fields(
        programme_id=str(getattr(programme, "programme_id", "unknown")),
        role=str(getattr(getattr(programme, "role", None), "value", "unknown")),
        topic=str(getattr(content, "narrative_beat", "") or "" if content else ""),
        segment_beats=[str(item) for item in beat_values],
        seed_sha256=_sha256_text(seed),
        prompt_sha256=_sha256_text(prompt),
    )


def prep_segment(
    programme: Any,
    prep_dir: Path,
    *,
    prep_session: dict[str, Any] | None = None,
) -> Path | None:
    """Compose the full narration script for one programme and save it.

    Two-pass process:
      1. Initial composition — full script from the segment prompt
      2. Refinement — broadcast-editor review + rewrite of weak beats

    Returns the path to the saved JSON file, or None on failure.
    """
    prog_id = str(getattr(programme, "programme_id", "unknown"))
    try:
        artifact_name = _programme_artifact_name(prog_id)
        diagnostic_name = _programme_artifact_name(
            prog_id,
            suffix=".actionability-invalid.json",
        )
        layout_diagnostic_name = _programme_artifact_name(
            prog_id,
            suffix=".layout-invalid.json",
        )
    except ValueError as exc:
        log.warning("prep_segment: skipping unsafe programme_id %r: %s", prog_id, exc)
        return None
    if prep_session is None:
        prep_session = _new_prep_session()
    role = getattr(getattr(programme, "role", None), "value", "unknown")
    content = getattr(programme, "content", None)
    beats = getattr(content, "segment_beats", []) or [] if content else []

    if not beats:
        log.info("prep_segment: %s has no beats, skipping", prog_id)
        return None

    log.info("prep_segment: composing %s (%s, %d beats)", prog_id, role, len(beats))

    # Pass 1: Initial composition
    seed = _build_seed(programme)
    prompt = _build_full_segment_prompt(programme, seed)
    source_hashes = _source_hashes(programme, seed=seed, prompt=prompt)
    raw = _call_llm(
        prompt,
        prep_session=prep_session,
        phase="compose",
        programme_id=prog_id,
    )
    script = _parse_script(raw)

    if not script:
        log.warning("prep_segment: empty script for %s", prog_id)
        return None

    # Pad or truncate to match beat count
    if len(script) < len(beats):
        log.warning(
            "prep_segment: script has %d blocks but %d beats; padding",
            len(script),
            len(beats),
        )
        script.extend([""] * (len(beats) - len(script)))
    elif len(script) > len(beats):
        script = script[: len(beats)]

    avg_chars = sum(len(b) for b in script) / max(len(script), 1)
    log.info(
        "prep_segment: pass 1 done for %s — %d beats, avg %.0f chars/beat",
        prog_id,
        len(script),
        avg_chars,
    )

    # Pass 2: Iterative refinement
    script = _refine_script(
        script,
        programme,
        prep_session=prep_session,
        programme_id=prog_id,
    )
    actionability = validate_segment_actionability(
        script,
        [str(item) for item in beats],
    )
    if actionability["ok"] is not True:
        log.warning(
            "prep_segment: quarantining %s with %d unsupported action claims",
            prog_id,
            len(actionability["removed_unsupported_action_lines"]),
        )
        diagnostic_path = prep_dir / diagnostic_name
        diagnostic = {
            "schema_version": PREP_ARTIFACT_SCHEMA_VERSION,
            "authority": PREP_ARTIFACT_AUTHORITY,
            "programme_id": prog_id,
            "role": role,
            "topic": getattr(content, "narrative_beat", "") or "",
            "segment_beats": list(beats),
            "prepared_script_candidate": script,
            "sanitized_script_candidate": actionability["prepared_script"],
            "actionability_rubric_version": ACTIONABILITY_RUBRIC_VERSION,
            "actionability_alignment": {
                "ok": False,
                "removed_unsupported_action_lines": actionability[
                    "removed_unsupported_action_lines"
                ],
            },
            "prepped_at": datetime.now(tz=UTC).isoformat(),
            "prep_session_id": prep_session["prep_session_id"],
            "model_id": prep_session["model_id"],
            "prompt_sha256": source_hashes["prompt_sha256"],
            "seed_sha256": source_hashes["seed_sha256"],
            "not_loadable_reason": "actionability alignment failed",
        }
        diagnostic["artifact_sha256"] = _artifact_hash(diagnostic)
        tmp = diagnostic_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(diagnostic, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(diagnostic_path)
        return None
    script = list(actionability["prepared_script"])
    layout_responsibility = validate_layout_responsibility(
        actionability["beat_action_intents"],
    )
    segment_beat_strings = [str(item) for item in beats]
    layout_responsibility = _with_tier_list_placement_gate(
        layout_responsibility,
        role=role,
        segment_beats=segment_beat_strings,
        beat_action_intents=actionability["beat_action_intents"],
    )
    if layout_responsibility["ok"] is not True and _layout_repair_required(layout_responsibility):
        repaired_script = _repair_layout_actionability(
            script,
            programme,
            layout_responsibility,
            prep_session=prep_session,
            programme_id=prog_id,
        )
        if repaired_script != script:
            repaired_actionability = validate_segment_actionability(
                repaired_script,
                [str(item) for item in beats],
            )
            if repaired_actionability["ok"] is True:
                repaired_layout = validate_layout_responsibility(
                    repaired_actionability["beat_action_intents"],
                )
                repaired_layout = _with_tier_list_placement_gate(
                    repaired_layout,
                    role=role,
                    segment_beats=segment_beat_strings,
                    beat_action_intents=repaired_actionability["beat_action_intents"],
                )
                if repaired_layout["ok"] is True:
                    log.info(
                        "prep_segment: layout repair made %s responsible-layout loadable",
                        prog_id,
                    )
                    script = list(repaired_actionability["prepared_script"])
                    actionability = repaired_actionability
                    layout_responsibility = repaired_layout
                else:
                    log.warning(
                        "prep_segment: layout repair for %s still violates layout "
                        "responsibility: %s",
                        prog_id,
                        [item.get("reason") for item in repaired_layout["violations"]],
                    )
            else:
                log.warning(
                    "prep_segment: layout repair for %s introduced unsupported action "
                    "claims; keeping refined draft",
                    prog_id,
                )
    quality_report = score_segment_quality(script, [str(item) for item in beats])
    if layout_responsibility["ok"] is not True:
        log.warning(
            "prep_segment: quarantining %s with layout responsibility violations: %s",
            prog_id,
            [item.get("reason") for item in layout_responsibility["violations"]],
        )
        diagnostic_path = prep_dir / layout_diagnostic_name
        diagnostic = {
            "schema_version": PREP_ARTIFACT_SCHEMA_VERSION,
            "authority": PREP_ARTIFACT_AUTHORITY,
            "programme_id": prog_id,
            "role": role,
            "topic": getattr(content, "narrative_beat", "") or "",
            "segment_beats": list(beats),
            "prepared_script_candidate": script,
            "segment_quality_rubric_version": QUALITY_RUBRIC_VERSION,
            "segment_quality_report": quality_report,
            "actionability_rubric_version": ACTIONABILITY_RUBRIC_VERSION,
            "actionability_alignment": {
                "ok": actionability["ok"],
                "removed_unsupported_action_lines": actionability[
                    "removed_unsupported_action_lines"
                ],
            },
            "layout_responsibility_version": LAYOUT_RESPONSIBILITY_VERSION,
            "layout_responsibility": layout_responsibility,
            "prepped_at": datetime.now(tz=UTC).isoformat(),
            "prep_session_id": prep_session["prep_session_id"],
            "model_id": prep_session["model_id"],
            "prompt_sha256": source_hashes["prompt_sha256"],
            "seed_sha256": source_hashes["seed_sha256"],
            "not_loadable_reason": "layout responsibility failed",
        }
        diagnostic["artifact_sha256"] = _artifact_hash(diagnostic)
        tmp = diagnostic_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(diagnostic, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(diagnostic_path)
        return None

    # Save to disk
    out_path = prep_dir / artifact_name
    final_avg = sum(len(b) for b in script) / max(len(script), 1)
    payload = {
        "schema_version": PREP_ARTIFACT_SCHEMA_VERSION,
        "authority": PREP_ARTIFACT_AUTHORITY,
        "programme_id": prog_id,
        "role": role,
        "topic": getattr(content, "narrative_beat", "") or "",
        "segment_beats": list(beats),
        "prepared_script": script,
        "segment_quality_rubric_version": QUALITY_RUBRIC_VERSION,
        "actionability_rubric_version": ACTIONABILITY_RUBRIC_VERSION,
        "layout_responsibility_version": LAYOUT_RESPONSIBILITY_VERSION,
        "hosting_context": layout_responsibility["hosting_context"],
        "segment_quality_report": quality_report,
        "beat_action_intents": actionability["beat_action_intents"],
        "actionability_alignment": {
            "ok": actionability["ok"],
            "removed_unsupported_action_lines": actionability["removed_unsupported_action_lines"],
        },
        "beat_layout_intents": layout_responsibility["beat_layout_intents"],
        "layout_decision_contract": layout_responsibility["layout_decision_contract"],
        "runtime_layout_validation": layout_responsibility["runtime_layout_validation"],
        "layout_decision_receipts": layout_responsibility["layout_decision_receipts"],
        "prepped_at": datetime.now(tz=UTC).isoformat(),
        "prep_session_id": prep_session["prep_session_id"],
        "model_id": prep_session["model_id"],
        "prompt_sha256": source_hashes["prompt_sha256"],
        "seed_sha256": source_hashes["seed_sha256"],
        "source_hashes": source_hashes,
        "source_provenance_sha256": _sha256_json(source_hashes),
        "llm_calls": [
            call
            for call in prep_session.get("llm_calls", [])
            if call.get("programme_id") == prog_id
        ],
        "beat_count": len(beats),
        "avg_chars_per_beat": round(final_avg),
        "refinement_applied": True,
    }
    payload["artifact_sha256"] = _artifact_hash(payload)
    tmp = out_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(out_path)
    log.info(
        "prep_segment: saved %s (%d blocks, avg %.0f chars/beat)",
        out_path,
        len(script),
        final_avg,
    )

    # Pass 3: Self-evaluation → emit impingement
    # This is how taste develops. Hapax evaluates its own output and
    # the evaluation flows through the impingement bus into the
    # narrative drive's Bayesian prior, shaping future generation.
    _emit_self_evaluation(prog_id, role, script, beats)

    return out_path


def _emit_self_evaluation(
    prog_id: str,
    role: str,
    script: list[str],
    beat_directions: list[str],
) -> None:
    """Emit a self-evaluation impingement after segment prep.

    Scores the segment on depth, specificity, and arc — then writes
    the evaluation to the impingement bus.  The narrative drive
    consumes these impingements and accumulates them as evidence
    about what Hapax does well and where it falls short.

    This is NOT a personality simulation.  It is a selection pressure:
    segments that score well on a topic bias future planning toward
    that topic.  Segments that score poorly bias against the pattern
    that produced them.
    """
    try:
        thin_beats = sum(1 for b in script if len(b) < 600)
        avg_chars = sum(len(b) for b in script) / max(len(script), 1)
        # Rough source density: count capitalized proper nouns as proxy
        total_text = " ".join(script)
        # Words that look like source citations (capitalized, 2+ chars)
        source_like = [
            w
            for w in total_text.split()
            if len(w) > 2
            and w[0].isupper()
            and w not in ("The", "This", "That", "And", "But", "For", "Not")
        ]
        source_density = len(source_like) / max(len(total_text.split()), 1)

        quality = (
            "strong"
            if thin_beats == 0 and avg_chars > 800
            else "developing"
            if thin_beats <= 2
            else "thin"
        )

        impingement = {
            "source": "self_evaluation.segment_prep",
            "programme_id": prog_id,
            "role": role,
            "evaluation": {
                "quality": quality,
                "avg_chars_per_beat": round(avg_chars),
                "thin_beats": thin_beats,
                "total_beats": len(script),
                "source_density": round(source_density, 3),
            },
            "ts": datetime.now(tz=UTC).isoformat(),
        }

        bus_path = Path("/dev/shm/hapax-dmn/impingements.jsonl")
        if bus_path.parent.exists():
            with bus_path.open("a") as f:
                f.write(json.dumps(impingement) + "\n")
            log.info(
                "self-eval: %s quality=%s avg_chars=%.0f thin=%d sources=%.3f",
                prog_id,
                quality,
                avg_chars,
                thin_beats,
                source_density,
            )
    except Exception:
        log.debug("self-eval: impingement emission failed (non-fatal)", exc_info=True)


def run_prep(prep_dir: Path | None = None) -> list[Path]:
    """Run the daily prep window.

    1. Call the planner to generate programme plans
    2. For each segmented-content programme, compose the full script
    3. Save results to the prep directory
    4. Write a manifest summarizing what was prepped

    Returns list of saved file paths.
    """
    from agents.hapax_daimonion.autonomous_narrative.segment_prompts import (
        SEGMENTED_CONTENT_ROLES,
    )

    if prep_dir is None:
        prep_dir = DEFAULT_PREP_DIR
    today = _today_dir(prep_dir)
    existing_manifest_names = _accepted_manifest_programme_names(
        today,
        _manifest_programme_names(today) or [],
    )
    existing_programme_ids = _accepted_manifest_programme_ids(today, existing_manifest_names)

    start = time.monotonic()
    saved: list[Path] = []
    prep_session = _new_prep_session()
    started_at = datetime.now(tz=UTC).isoformat()
    prep_session["_prep_started_monotonic"] = start
    prep_session["prep_status_path"] = str(today / PREP_STATUS_FILENAME)
    prep_session["prep_status"] = {
        "prep_status_version": PREP_STATUS_VERSION,
        "status": "in_progress",
        "phase": "run_start",
        "pid": os.getpid(),
        "started_at": started_at,
        "updated_at": started_at,
        "prep_session_id": prep_session["prep_session_id"],
        "model_id": prep_session["model_id"],
        "target_segments": MAX_SEGMENTS,
        "existing_manifest_programmes": existing_manifest_names,
        "llm_calls": [],
    }
    _update_prep_status(prep_session, status="in_progress", phase="resident_model_check")
    try:
        _assert_resident_prep_model(prep_session["model_id"])
    except Exception as exc:
        _update_prep_status(
            prep_session,
            status="failed",
            phase="resident_model_check_failed",
            last_error=f"{type(exc).__name__}: {exc}",
        )
        raise

    # Step 1: Plan — call the planner in rounds until we have enough
    # segmented programmes. Each round yields ~3 programmes; for 10
    # segments we typically need 4 rounds.
    log.info("daily_segment_prep: planning programmes (target=%d)...", MAX_SEGMENTS)
    segmented: list[Any] = []
    seen_ids: set[str] = set(existing_programme_ids)
    plan_round = 0
    max_rounds = 1 if MAX_SEGMENTS == 1 else (MAX_SEGMENTS // 2) + 2
    planner_target_programmes = 1 if MAX_SEGMENTS == 1 else None
    _update_prep_status(
        prep_session,
        status="in_progress",
        phase="planning_start",
        max_rounds=max_rounds,
        planner_target_programmes=planner_target_programmes,
    )

    try:
        from agents.programme_manager.planner import ProgrammePlanner

        planner = ProgrammePlanner(
            llm_fn=lambda prompt: _call_llm(
                prompt,
                prep_session=prep_session,
                phase="plan",
                programme_id="planner",
                max_tokens=8192,
            )
        )
    except Exception as exc:
        _update_prep_status(
            prep_session,
            status="failed",
            phase="planner_construction_failed",
            last_error=f"{type(exc).__name__}: {exc}",
        )
        log.error("daily_segment_prep: planner construction failed", exc_info=True)
        return saved

    while len(segmented) < MAX_SEGMENTS and plan_round < max_rounds:
        elapsed = time.monotonic() - start
        if elapsed >= PREP_BUDGET_S:
            _update_prep_status(
                prep_session,
                status="in_progress",
                phase="planning_budget_exhausted",
                plan_round=plan_round,
                segmented_count=len(segmented),
            )
            log.warning(
                "daily_segment_prep: prep budget exhausted during planning (%.0fs)", elapsed
            )
            break

        plan_round += 1
        show_id = f"show-{datetime.now(tz=UTC).strftime('%Y%m%d')}-{plan_round:02d}"
        _update_prep_status(
            prep_session,
            status="in_progress",
            phase="planner_round_in_progress",
            plan_round=plan_round,
            show_id=show_id,
            segmented_count=len(segmented),
        )
        try:
            plan = planner.plan(
                show_id=show_id,
                target_programmes=planner_target_programmes,
            )
        except Exception as exc:
            _update_prep_status(
                prep_session,
                status="in_progress",
                phase="planner_round_failed",
                plan_round=plan_round,
                show_id=show_id,
                last_error=f"{type(exc).__name__}: {exc}",
            )
            log.warning("daily_segment_prep: planner round %d failed", plan_round, exc_info=True)
            continue

        if plan is None or not plan.programmes:
            _update_prep_status(
                prep_session,
                status="in_progress",
                phase="planner_round_no_programmes",
                plan_round=plan_round,
                show_id=show_id,
                segmented_count=len(segmented),
            )
            log.warning("daily_segment_prep: planner round %d returned no programmes", plan_round)
            continue

        for p in plan.programmes:
            pid = getattr(p, "programme_id", "")
            role_val = getattr(getattr(p, "role", None), "value", "")
            if role_val in SEGMENTED_CONTENT_ROLES and pid not in seen_ids:
                segmented.append(p)
                seen_ids.add(pid)

        log.info(
            "daily_segment_prep: round %d → %d total segmented (%d new this round)",
            plan_round,
            len(segmented),
            len(
                [
                    p
                    for p in plan.programmes
                    if getattr(getattr(p, "role", None), "value", "") in SEGMENTED_CONTENT_ROLES
                ]
            ),
        )
        _update_prep_status(
            prep_session,
            status="in_progress",
            phase="planner_round_returned",
            plan_round=plan_round,
            show_id=show_id,
            planned_programmes=len(plan.programmes),
            segmented_count=len(segmented),
        )

    log.info(
        "daily_segment_prep: %d segmented programmes collected in %d rounds",
        len(segmented),
        plan_round,
    )

    # Step 2: Compose each segmented-content programme on the same resident model.
    for prog in segmented[:MAX_SEGMENTS]:
        elapsed = time.monotonic() - start
        if elapsed >= PREP_BUDGET_S:
            _update_prep_status(
                prep_session,
                status="in_progress",
                phase="compose_budget_exhausted",
                saved_count=len(saved),
                segmented_count=len(segmented),
            )
            log.warning("daily_segment_prep: prep budget exhausted (%.0fs)", elapsed)
            break

        prog_id = getattr(prog, "programme_id", "?")
        _update_prep_status(
            prep_session,
            status="in_progress",
            phase="compose_segment_in_progress",
            programme_id=str(prog_id),
            saved_count=len(saved),
            segmented_count=len(segmented),
        )
        try:
            path = prep_segment(prog, today, prep_session=prep_session)
        except Exception as exc:
            _update_prep_status(
                prep_session,
                status="in_progress",
                phase="compose_segment_failed",
                programme_id=str(prog_id),
                last_error=f"{type(exc).__name__}: {exc}",
                saved_count=len(saved),
            )
            log.warning("daily_segment_prep: segment %s failed, continuing", prog_id, exc_info=True)
            path = None
        if path:
            saved.append(path)
            _update_prep_status(
                prep_session,
                status="in_progress",
                phase="compose_segment_saved",
                programme_id=str(prog_id),
                saved_count=len(saved),
                last_saved_path=str(path),
            )

    _update_prep_status(prep_session, status="in_progress", phase="final_resident_model_check")
    try:
        _assert_resident_prep_model(prep_session["model_id"])
    except Exception as exc:
        _update_prep_status(
            prep_session,
            status="failed",
            phase="final_resident_model_check_failed",
            last_error=f"{type(exc).__name__}: {exc}",
            saved_count=len(saved),
            segmented_count=len(segmented),
        )
        raise

    # Step 3: Write manifest.  The manifest is the loader allow-list, so
    # repeated prep runs must append newly accepted artifacts without
    # re-admitting stale files that no longer pass the current load gates.
    manifest = today / "manifest.json"
    manifest_programmes = _accepted_manifest_programme_names(
        today,
        [*existing_manifest_names, *(p.name for p in saved)],
    )
    manifest_payload = {
        "date": datetime.now(tz=UTC).strftime("%Y-%m-%d"),
        "prepped_at": datetime.now(tz=UTC).isoformat(),
        "prep_session_id": prep_session["prep_session_id"],
        "model_id": prep_session["model_id"],
        "llm_calls": prep_session.get("llm_calls", []),
        "programmes": manifest_programmes,
        "run_saved_programmes": [p.name for p in saved],
        "total_elapsed_s": round(time.monotonic() - start, 1),
    }
    manifest_tmp = manifest.with_suffix(".json.tmp")
    manifest_tmp.write_text(
        json.dumps(
            manifest_payload,
            indent=2,
        ),
        encoding="utf-8",
    )
    manifest_tmp.replace(manifest)
    final_status = "completed" if saved else "completed_no_programmes"
    if segmented and not saved:
        final_status = "completed_no_segments_saved"
    _update_prep_status(
        prep_session,
        status=final_status,
        phase=final_status,
        saved_count=len(saved),
        segmented_count=len(segmented),
        manifest_path=str(manifest),
        manifest_programmes=manifest_programmes,
        run_saved_programmes=[p.name for p in saved],
    )

    # Step 4: Upsert programme summaries into Qdrant so the affordance
    # pipeline can semantically match impingements against available
    # pre-composed content.
    _upsert_programmes_to_qdrant(segmented[:MAX_SEGMENTS], saved)

    log.info(
        "daily_segment_prep: done. %d segments prepped in %.0fs",
        len(saved),
        time.monotonic() - start,
    )
    return saved


def _upsert_programmes_to_qdrant(
    programmes: list[Any],
    saved_paths: list[Path],
) -> None:
    """Embed and upsert prepped programmes into Qdrant.

    Each programme gets a semantic summary embedded and stored in the
    affordances collection with a ``programme.prepped.*`` capability name.
    This lets the affordance pipeline's cosine-similarity retrieval
    surface relevant pre-composed programmes when impingements fire.

    Best-effort: Qdrant or Ollama unavailability does NOT block the prep.
    """
    if not programmes or not saved_paths:
        return

    try:
        import uuid

        from shared.affordance_pipeline import (
            COLLECTION_NAME,
            embed_batch_safe,
        )
        from shared.config import get_qdrant

        saved_by_id: dict[str, tuple[Path, dict[str, Any]]] = {}
        for path in saved_paths:
            try:
                artifact = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                log.debug("prep qdrant: failed to read saved artifact %s", path, exc_info=True)
                continue
            if not isinstance(artifact, dict):
                continue
            reason = _artifact_rejection_reason(
                artifact,
                path=path,
                manifest_programmes=_manifest_programmes(path.parent),
            )
            if reason:
                log.warning("prep qdrant: refusing %s: %s", path.name, reason)
                continue
            pid = str(artifact.get("programme_id") or "")
            if pid:
                saved_by_id[pid] = (path, artifact)

        # Build semantic summaries for successfully saved programmes only.
        texts: list[str] = []
        prog_ids: list[str] = []
        prog_meta: list[dict] = []
        for prog in programmes:
            pid = getattr(prog, "programme_id", None) or ""
            if not pid or pid not in saved_by_id:
                continue
            artifact_path, artifact = saved_by_id[pid]
            content = getattr(prog, "content", None)
            role_value = getattr(getattr(prog, "role", None), "value", "rant")
            topic = getattr(content, "narrative_beat", "") or "" if content else ""
            beats = getattr(content, "segment_beats", []) or [] if content else []

            # Build a rich text summary for embedding
            beat_summary = " → ".join(str(b)[:60] for b in beats[:8])
            text = (
                f"Programme {pid}: {role_value} segment about {topic[:200]}. "
                f"Beats: {beat_summary}. "
                "Accepted prepared artifact candidate available."
            )
            texts.append(text)
            prog_ids.append(pid)
            prog_meta.append(
                {
                    "programme_id": pid,
                    "role": role_value,
                    "topic": str(topic)[:500],
                    "beat_count": len(beats),
                    "has_script": True,
                    "artifact_type": "prepared_script",
                    "accepted": True,
                    "acceptance_gate": "daily_segment_prep._upsert_programmes_to_qdrant",
                    "authority": artifact.get("authority"),
                    "artifact_path": str(artifact_path),
                    "artifact_sha256": artifact.get("artifact_sha256"),
                    "model_id": artifact.get("model_id"),
                    "prep_session_id": artifact.get("prep_session_id"),
                    "llm_call_count": len(artifact.get("llm_calls") or []),
                    "prompt_sha256": artifact.get("prompt_sha256"),
                    "seed_sha256": artifact.get("seed_sha256"),
                    "source_hashes": artifact.get("source_hashes"),
                    "source_provenance_sha256": artifact.get("source_provenance_sha256"),
                    "segment_quality_label": (artifact.get("segment_quality_report") or {}).get(
                        "label"
                    ),
                    "actionability_ok": (artifact.get("actionability_alignment") or {}).get("ok"),
                    "beat_action_intents": artifact.get("beat_action_intents"),
                    "hosting_context": artifact.get("hosting_context"),
                    "runtime_layout_validation": artifact.get("runtime_layout_validation"),
                    "beat_layout_intents": artifact.get("beat_layout_intents"),
                    "prepped_at": artifact.get("prepped_at"),
                }
            )

        if not texts:
            return

        # Batch embed
        embeddings = embed_batch_safe(texts, prefix="search_document")
        if embeddings is None:
            log.warning("prep qdrant: embed_batch failed, skipping Qdrant upsert")
            return

        # Build Qdrant points
        from qdrant_client.models import PointStruct

        points = []
        for i, (pid, meta) in enumerate(zip(prog_ids, prog_meta, strict=True)):
            if i >= len(embeddings) or embeddings[i] is None:
                continue
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"programme.prepped.{pid}"))
            points.append(
                PointStruct(
                    id=point_id,
                    vector=embeddings[i],
                    payload={
                        "capability_name": f"programme.prepped.{pid}",
                        "description": texts[i],
                        "daemon": "hapax_daimonion",
                        **meta,
                    },
                )
            )

        if not points:
            return

        client = get_qdrant()
        client.upsert(collection_name=COLLECTION_NAME, points=points)
        log.info("prep qdrant: upserted %d programme points", len(points))

    except Exception:
        log.warning("prep qdrant: upsert failed (non-fatal)", exc_info=True)


_PROGRAMME_ID_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _programme_artifact_name(value: Any, *, suffix: str = ".json") -> str:
    programme_id = str(value)
    if not _PROGRAMME_ID_FILENAME_RE.fullmatch(programme_id):
        raise ValueError("programme_id is not safe for a prep artifact filename")
    name = f"{programme_id}{suffix}"
    if _safe_manifest_name(name) != name:
        raise ValueError("programme_id does not produce a manifest-safe artifact name")
    return name


def _safe_manifest_name(value: Any) -> str | None:
    name = str(value)
    if not name or name == "manifest.json":
        return None
    if Path(name).name != name:
        return None
    if not name.endswith(".json"):
        return None
    return name


def _manifest_programme_names(today: Path) -> list[str] | None:
    manifest_path = today / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        log.debug("load_prepped: failed to read manifest %s", manifest_path, exc_info=True)
        return []
    programmes = manifest.get("programmes")
    if not isinstance(programmes, list):
        return []
    names: list[str] = []
    seen: set[str] = set()
    for item in programmes:
        name = _safe_manifest_name(item)
        if name is None or name in seen:
            continue
        names.append(name)
        seen.add(name)
    return names


def _manifest_programmes(today: Path) -> set[str] | None:
    names = _manifest_programme_names(today)
    if names is None:
        return None
    return set(names)


def _llm_calls_rejection_reason(calls: Any) -> str | None:
    if not isinstance(calls, list) or not calls:
        return "missing llm_calls"
    last_index = 0
    for call in calls:
        if not isinstance(call, dict):
            return "invalid llm_calls"
        call_index = call.get("call_index")
        if not isinstance(call_index, int) or call_index <= last_index:
            return "non-monotonic llm_calls"
        last_index = call_index
        if call.get("model_id") != RESIDENT_PREP_MODEL:
            return "llm call model mismatch"
        if not call.get("phase") or not call.get("programme_id") or not call.get("called_at"):
            return "incomplete llm call provenance"
        if not _is_sha256_hex(call.get("prompt_sha256")):
            return "missing llm call prompt hash"
    return None


def _actionability_rejection_reason(data: dict[str, Any]) -> str | None:
    if data.get("segment_quality_rubric_version") != QUALITY_RUBRIC_VERSION:
        return "unsupported segment quality rubric"
    if data.get("actionability_rubric_version") != ACTIONABILITY_RUBRIC_VERSION:
        return "unsupported actionability rubric"
    if not isinstance(data.get("segment_quality_report"), dict):
        return "missing segment quality report"

    intents = data.get("beat_action_intents")
    script = data.get("prepared_script")
    if not isinstance(intents, list) or not isinstance(script, list):
        return "missing beat action intents"
    if len(intents) != len(script):
        return "beat action intent count mismatch"
    for expected_index, declaration in enumerate(intents):
        if not isinstance(declaration, dict):
            return "invalid beat action intent"
        if declaration.get("beat_index") != expected_index:
            return "beat action index mismatch"
        declared_intents = declaration.get("intents")
        if not isinstance(declared_intents, list) or not declared_intents:
            return "missing declared beat intent"
        for intent in declared_intents:
            if not isinstance(intent, dict):
                return "invalid declared beat intent"
            if not intent.get("kind") or not intent.get("expected_effect"):
                return "incomplete declared beat intent"

    alignment = data.get("actionability_alignment")
    if not isinstance(alignment, dict):
        return "missing actionability alignment"
    if not isinstance(alignment.get("removed_unsupported_action_lines", []), list):
        return "invalid actionability alignment"
    if alignment.get("ok") is not True:
        return "actionability alignment failed"
    return None


def _layout_rejection_reason(data: dict[str, Any]) -> str | None:
    if data.get("layout_responsibility_version") != LAYOUT_RESPONSIBILITY_VERSION:
        return "unsupported layout responsibility version"
    hosting_context = data.get("hosting_context")
    if hosting_context not in {
        RESPONSIBLE_HOSTING_CONTEXT,
        EXPLICIT_LAYOUT_FALLBACK_CONTEXT,
        NON_RESPONSIBLE_STATIC_CONTEXT,
    }:
        return "unsupported hosting context"
    if forbidden_layout_authority_fields(data):
        return "layout metadata contains direct authority fields"

    runtime_validation = data.get("runtime_layout_validation")
    if not isinstance(runtime_validation, dict):
        return "missing runtime layout validation"
    if runtime_validation.get("status") != "pending_runtime_readback":
        return "runtime layout validation is not pending readback"
    if runtime_validation.get("ok") is not True:
        return "layout responsibility failed"
    if runtime_validation.get("layout_success") is not False:
        return "prep artifact claims layout success"
    receipts = data.get("layout_decision_receipts")
    if not isinstance(receipts, list):
        return "invalid layout decision receipts"
    if hosting_context == RESPONSIBLE_HOSTING_CONTEXT and receipts:
        return "responsible prep artifact contains layout decision receipts"

    if hosting_context in {EXPLICIT_LAYOUT_FALLBACK_CONTEXT, NON_RESPONSIBLE_STATIC_CONTEXT}:
        return None

    script = data.get("prepared_script")
    beat_layout_intents = data.get("beat_layout_intents")
    if not isinstance(script, list) or not isinstance(beat_layout_intents, list):
        return "missing beat layout intents"
    if len(beat_layout_intents) != len(script):
        return "beat layout intent count mismatch"
    for expected_index, declaration in enumerate(beat_layout_intents):
        if not isinstance(declaration, dict):
            return "invalid beat layout intent"
        if declaration.get("beat_index") != expected_index:
            return "beat layout intent index mismatch"
        needs = declaration.get("needs")
        if not isinstance(needs, list) or not needs:
            return "missing declared layout needs"
        if declaration.get("default_static_success_allowed") is True:
            return "responsible beat allows static default success"
        if not _string_list(declaration.get("evidence_refs")):
            return "missing layout evidence refs"
        if not _string_list(declaration.get("source_affordances")):
            return "missing layout source affordances"
        for need in needs:
            if not isinstance(need, str) or not need:
                return "invalid declared layout need"

    tier_placement_violations = _tier_list_placement_violations(
        role=str(data.get("role") or ""),
        segment_beats=_string_list(data.get("segment_beats")),
        beat_action_intents=data.get("beat_action_intents")
        if isinstance(data.get("beat_action_intents"), list)
        else [],
    )
    if tier_placement_violations:
        return "tier list missing exact placement phrases"

    contract = data.get("layout_decision_contract")
    if not isinstance(contract, dict):
        return "missing layout decision contract"
    if contract.get("may_command_layout") is not False:
        return "layout decision contract may command layout"
    if contract.get("authority_boundary") != "canonical_broadcast_runtime_decides":
        return "invalid layout authority boundary"

    try:
        from agents.hapax_daimonion.segment_layout_contract import (
            validate_prepared_segment_artifact,
        )

        validate_prepared_segment_artifact(
            data,
            artifact_path=str(data.get("artifact_path") or ""),
            artifact_sha256=str(data.get("artifact_sha256") or ""),
        )
    except Exception as exc:
        return f"invalid projected layout contract: {exc}"
    return None


def _artifact_rejection_reason(
    data: dict[str, Any],
    *,
    path: Path,
    manifest_programmes: set[str] | None,
) -> str | None:
    if manifest_programmes is None:
        return "missing manifest"
    if path.name not in manifest_programmes:
        return "not listed in manifest"
    if data.get("schema_version") != PREP_ARTIFACT_SCHEMA_VERSION:
        return "unsupported schema_version"
    if data.get("authority") != PREP_ARTIFACT_AUTHORITY:
        return "invalid authority"
    if data.get("model_id") != RESIDENT_PREP_MODEL:
        return "wrong model_id"
    if not data.get("prep_session_id"):
        return "missing prep_session_id"
    call_reason = _llm_calls_rejection_reason(data.get("llm_calls"))
    if call_reason:
        return call_reason
    script = data.get("prepared_script")
    if (
        not isinstance(script, list)
        or not script
        or not all(isinstance(item, str) for item in script)
    ):
        return "invalid prepared_script"
    beats = data.get("segment_beats")
    if not isinstance(beats, list) or not all(isinstance(item, str) for item in beats):
        return "invalid segment_beats"
    if beats and len(script) != len(beats):
        return "script beat count mismatch"
    actionability_reason = _actionability_rejection_reason(data)
    if actionability_reason:
        return actionability_reason
    layout_reason = _layout_rejection_reason(data)
    if layout_reason:
        return layout_reason
    expected_hash = data.get("artifact_sha256")
    if not isinstance(expected_hash, str) or expected_hash != _artifact_hash(data):
        return "artifact hash mismatch"
    if not _is_sha256_hex(data.get("prompt_sha256")) or not _is_sha256_hex(data.get("seed_sha256")):
        return "missing prompt or seed hash"
    source_hashes = data.get("source_hashes")
    if not isinstance(source_hashes, dict):
        return "missing source hashes"
    for key in (
        "programme_sha256",
        "topic_sha256",
        "segment_beats_sha256",
        "seed_sha256",
        "prompt_sha256",
    ):
        if not _is_sha256_hex(source_hashes.get(key)):
            return f"missing source hash {key}"
    if source_hashes.get("seed_sha256") != data.get("seed_sha256") or source_hashes.get(
        "prompt_sha256"
    ) != data.get("prompt_sha256"):
        return "source hash mismatch"
    programme_id = data.get("programme_id")
    role = data.get("role")
    topic = data.get("topic")
    if not isinstance(programme_id, str) or not isinstance(role, str) or not isinstance(topic, str):
        return "missing programme source identity"
    try:
        expected_name = _programme_artifact_name(programme_id)
    except ValueError:
        return "unsafe programme_id"
    if expected_name != path.name:
        return "programme_id filename mismatch"
    if source_hashes != _source_hashes_from_fields(
        programme_id=programme_id,
        role=role,
        topic=topic,
        segment_beats=beats,
        seed_sha256=data["seed_sha256"],
        prompt_sha256=data["prompt_sha256"],
    ):
        return "source hash mismatch"
    source_provenance_sha256 = data.get("source_provenance_sha256")
    if not _is_sha256_hex(source_provenance_sha256) or source_provenance_sha256 != _sha256_json(
        source_hashes
    ):
        return "source provenance hash mismatch"
    return None


def _accepted_artifact_or_reason(
    path: Path,
    *,
    manifest_programmes: set[str] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "listed file missing"
    except Exception:
        log.debug("load_prepped: failed to read %s", path, exc_info=True)
        return None, "failed to read artifact"
    if not isinstance(data, dict):
        return None, "top-level is not object"

    reason = _artifact_rejection_reason(
        data,
        path=path,
        manifest_programmes=manifest_programmes,
    )
    if reason:
        return None, reason

    runtime_actionability = validate_segment_actionability(
        list(data["prepared_script"]),
        list(data["segment_beats"]),
    )
    if runtime_actionability["ok"] is not True:
        return None, "runtime actionability alignment failed"
    if not _json_equal(
        data.get("beat_action_intents"),
        runtime_actionability["beat_action_intents"],
    ):
        return None, "beat action intents do not match script"

    runtime_layout = validate_layout_responsibility(
        runtime_actionability["beat_action_intents"],
        responsibility_mode=str(data.get("hosting_context") or RESPONSIBLE_HOSTING_CONTEXT),
    )
    if not _json_equal(data.get("beat_layout_intents"), runtime_layout["beat_layout_intents"]):
        return None, "beat layout intents do not match script"

    try:
        from agents.hapax_daimonion.segment_layout_contract import (
            validate_prepared_segment_artifact,
        )

        contract = validate_prepared_segment_artifact(
            data,
            artifact_path=str(path),
            artifact_sha256=str(data.get("artifact_sha256") or ""),
        )
    except Exception as exc:
        return None, f"projected layout contract failed: {exc}"
    projected_layout_contract = contract.model_dump(mode="json", by_alias=True)

    data["runtime_actionability_validation"] = {
        "rubric_version": ACTIONABILITY_RUBRIC_VERSION,
        "ok": runtime_actionability["ok"],
        "beat_action_intents": runtime_actionability["beat_action_intents"],
    }
    data["runtime_layout_validation"] = runtime_layout["runtime_layout_validation"] | {
        "layout_responsibility_version": LAYOUT_RESPONSIBILITY_VERSION,
        "hosting_context": runtime_layout["hosting_context"],
        "beat_layout_intents": runtime_layout["beat_layout_intents"],
        "violations": runtime_layout["violations"],
    }
    data["prepared_artifact_ref"] = {
        "ref": f"prepared_artifact:{data.get('artifact_sha256')}",
        "artifact_sha256": data.get("artifact_sha256"),
        "prep_session_id": data.get("prep_session_id"),
        "model_id": data.get("model_id"),
        "authority": data.get("authority"),
        "projected_authority": contract.artifact_authority,
    }
    data["projected_layout_contract"] = projected_layout_contract
    data["beat_layout_intents"] = projected_layout_contract["beat_layout_intents"]
    data["layout_decision_contract"] = projected_layout_contract["layout_decision_contract"]
    data["layout_decision_receipts"] = runtime_layout["layout_decision_receipts"]
    data["artifact_path_diagnostic"] = str(path)
    data["artifact_path"] = str(path)
    data["accepted"] = True
    data["acceptance_gate"] = "daily_segment_prep.load_prepped_programmes"
    return data, None


def _accepted_manifest_programme_names(today: Path, candidate_names: list[str]) -> list[str]:
    accepted: list[str] = []
    seen: set[str] = set()
    ordered_candidates: list[str] = []
    for item in candidate_names:
        name = _safe_manifest_name(item)
        if name is None or name in seen:
            continue
        ordered_candidates.append(name)
        seen.add(name)

    manifest_programmes = set(ordered_candidates)
    for name in ordered_candidates:
        path = today / name
        _, reason = _accepted_artifact_or_reason(
            path,
            manifest_programmes=manifest_programmes,
        )
        if reason:
            log.warning("daily_segment_prep: dropping %s from manifest: %s", name, reason)
            continue
        accepted.append(name)
    return accepted


def _accepted_manifest_programme_ids(today: Path, accepted_names: list[str]) -> set[str]:
    manifest_programmes = set(accepted_names)
    programme_ids: set[str] = set()
    for name in accepted_names:
        data, reason = _accepted_artifact_or_reason(
            today / name,
            manifest_programmes=manifest_programmes,
        )
        if reason or data is None:
            continue
        programme_id = data.get("programme_id")
        if isinstance(programme_id, str) and programme_id:
            programme_ids.add(programme_id)
    return programme_ids


def load_prepped_programmes(prep_dir: Path | None = None) -> list[dict]:
    """Load today's prepped segments from disk.

    Returns a list of dicts, each with programme_id, prepared_script, etc.
    Used by the programme loop to populate prepared_script on programmes.
    """
    if prep_dir is None:
        prep_dir = DEFAULT_PREP_DIR
    today = _today_path(prep_dir)
    if not today.exists():
        return []
    manifest_names = _manifest_programme_names(today)
    manifest_programmes = set(manifest_names) if manifest_names is not None else None

    results = []
    for name in manifest_names or []:
        f = today / name
        if f.name == "manifest.json":
            continue
        data, reason = _accepted_artifact_or_reason(
            f,
            manifest_programmes=manifest_programmes,
        )
        if reason:
            log.warning("load_prepped: rejecting %s: %s", f.name, reason)
            continue
        if data is not None:
            results.append(data)
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Daily segment prep runner")
    parser.add_argument("--prep-dir", type=Path, default=None)
    args = parser.parse_args()
    saved = run_prep(prep_dir=args.prep_dir)
    for p in saved:
        print(f"  ✓ {p}")
