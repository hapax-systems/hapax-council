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
    PERSONAGE_RUBRIC_VERSION,
    QUALITY_RUBRIC_VERSION,
    RESPONSIBLE_HOSTING_CONTEXT,
    forbidden_layout_authority_fields,
    render_nonhuman_personage_prompt_block,
    render_quality_prompt_block,
    score_segment_quality,
    validate_layout_responsibility,
    validate_nonhuman_personage,
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

# Max wall-clock for the entire prep window.  Daily prep is quality-budgeted:
# spend the window on candidates, and accept only artifacts that clear gates.
PREP_BUDGET_S = float(os.environ.get("HAPAX_SEGMENT_PREP_BUDGET_S", "3600"))  # 60 min

# Candidate cap per run, not a quality quota.  Fewer candidates leave more
# budget per candidate for sequential composition and repair; accepted count is
# whatever survives the gates.
MAX_SEGMENTS = int(os.environ.get("HAPAX_SEGMENT_PREP_MAX", "4"))
PREP_ARTIFACT_SCHEMA_VERSION = 1
PREP_ARTIFACT_AUTHORITY = "prior_only"
PREP_STATUS_VERSION = 2
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
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, list | tuple):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


# Per-role visual hook guidance for the prep prompt.  Tells the LLM which
# spoken patterns create typed layout needs so it can use them intentionally
# rather than accidentally.
_SEGMENTED_CONTENT_ROLES = frozenset(
    {"tier_list", "top_10", "rant", "react", "iceberg", "interview", "lecture"}
)
_SOURCE_EVIDENCE_HOOKS = (
    "SOURCE/EVIDENCE HOOKS — runtime can recognize source/detail commitments:\n"
    "  Use exact sentence starts when a beat needs visible source support:\n"
    "  'Source check: [named source] argues/finds/shows [claim].'\n"
    "  'Evidence check: [artifact/example/source] shows [claim].'\n"
    "  'Definition check: [term] means [definition].'\n"
    "  'Public readback: [visible evidence, receipt, or state to read].'\n"
    "  'Visible test: [test, comparison, or check the stream can show].'\n"
    "  'Worked example: [specific example to demonstrate].'\n"
    "  These are content commitments, not layout commands; runtime decides the\n"
    "  concrete posture and readback must prove visibility before success counts.\n"
    "  Example: 'Source check: the resolved vault note argues that the practice\n"
    "  mattered because it joined craft, economy, and local trust.'\n\n"
)
_ROLE_VISUAL_HOOKS: dict[str, str] = {
    "tier_list": (
        "TIER CHART HOOKS — runtime can recognize live tier placements:\n"
        "  MANDATORY: every ranking/body beat must include at least one exact\n"
        "  tier placement phrase: 'Place [item] in [S/A/B/C/D]-tier'.\n"
        "  Generic history, summary, or analysis without a placement is not a\n"
        "  responsible tier-list beat and will be quarantined.\n"
        "  The runtime can render rankings as they accumulate once readback succeeds.\n"
        "  Example: 'Place Candidate Alpha in S-tier.'\n\n"
        f"{_SOURCE_EVIDENCE_HOOKS}"
    ),
    "top_10": (
        "COUNTDOWN HOOKS — the stream requests a ranked countdown panel:\n"
        "  Use '#N is...' or 'Number N:' to update the current entry display.\n"
        "  The runtime layout loop must render the ranked-list panel before this counts.\n"
        "  Example: '#7 is the resolved source artifact with the sharpest reversal.'\n\n"
        f"{_SOURCE_EVIDENCE_HOOKS}"
    ),
    "iceberg": (
        "ICEBERG DEPTH HOOKS — the stream renders a depth indicator:\n"
        "  Use layer keywords to visually advance through layers:\n"
        "  'surface level' / 'commonly known' → top layer\n"
        "  'going deeper' / 'specialist knowledge' → mid layers\n"
        "  'obscure' / 'almost nobody talks about' → deep layers\n"
        "  'the deepest' / 'bottom of the iceberg' → abyss\n"
        "  The visual darkens and narrows as you descend.\n\n"
        f"{_SOURCE_EVIDENCE_HOOKS}"
    ),
    "rant": (
        "POSTURE HOOKS — the stream can reflect declared argumentative posture:\n"
        "  Escalation: 'ridiculous', 'unacceptable', 'outrageous' -> intense mood\n"
        "  De-escalation: 'fair', 'nuance', 'reasonable' -> low-intensity mood\n"
        "  Use escalation deliberately through the body; land with de-escalation.\n\n"
        f"{_SOURCE_EVIDENCE_HOOKS}"
    ),
    "react": (
        "POSTURE HOOKS — the stream can reflect declared argumentative posture:\n"
        "  Engagement: 'brilliant', 'impressive', 'incredible' -> high-salience mood\n"
        "  Skepticism: 'wait', 'hold on', 'not sure' -> cool mood\n"
        "  Revelation: 'exactly', 'this is it', 'nailed it' -> intense mood\n\n"
        f"{_SOURCE_EVIDENCE_HOOKS}"
    ),
    "interview": (
        "INTERVIEW HOOKS — questions need visible source/context commitments:\n"
        "  Use 'Source check:' for subject context, transcript context, or prior notes.\n"
        "  Use 'Evidence check:' when citing a specific answer, document, or artifact.\n"
        "  Ask real questions; never invent a guest answer unless a recorded/source\n"
        "  transcript is present in the segment research.\n\n"
        f"{_SOURCE_EVIDENCE_HOOKS}"
    ),
    "lecture": (
        "LECTURE HOOKS — every teaching beat needs source/detail visibility:\n"
        "  Use 'Source check:' for source-backed claims and thesis support.\n"
        "  Use 'Evidence check:' for examples, artifacts, cases, and receipts.\n"
        "  Use 'Definition check:' for terms, prerequisites, and distinctions.\n"
        "  A lecture beat that only explains in speech is not responsible live content.\n\n"
        f"{_SOURCE_EVIDENCE_HOOKS}"
    ),
}


def _render_planner_layout_obligations(programme: Any) -> str:
    content = getattr(programme, "content", None)
    raw_intents = getattr(content, "beat_layout_intents", []) or [] if content else []
    if not isinstance(raw_intents, list) or not raw_intents:
        return ""
    lines = [
        "== PLANNER LAYOUT OBLIGATIONS (PROPOSAL ONLY) ==",
        "The planner supplied proposal-only layout needs for these beats. They are",
        "not runtime authority and may not command a layout. Use supported spoken",
        "hooks that satisfy the needs; runtime decides the concrete posture and",
        "readback proves whether visibility actually happened.",
    ]
    for index, raw in enumerate(raw_intents):
        if hasattr(raw, "model_dump"):
            raw = raw.model_dump(mode="json")
        if not isinstance(raw, dict):
            continue
        beat_id = str(raw.get("beat_id") or f"beat-{index + 1}")
        needs = _string_list(raw.get("needs") or raw.get("layout_needs"))
        expected = _string_list(raw.get("expected_effects") or raw.get("expected_visible_effect"))
        evidence = _string_list(raw.get("evidence_refs") or raw.get("evidence_ref"))
        affordances = _string_list(raw.get("source_affordances") or raw.get("source_affordance"))
        lines.append(
            "- "
            f"{beat_id}: needs={needs or ['(unspecified)']}; "
            f"expected={expected or ['(unspecified)']}; "
            f"evidence_refs={evidence[:4] or ['(missing)']}; "
            f"source_affordances={affordances[:4] or ['(missing)']}"
        )
    return "\n".join(lines) + "\n\n"


def _prep_content_state_for_prompt() -> dict[str, Any] | None:
    """Return the current prep content state for composition prompts.

    The planner consumes the same state, but the composition and repair calls
    must also see it directly. Otherwise the planner can preserve the topic
    while losing exact source packets, target tiers, or forbidden anchors.
    """
    return _planner_content_state_from_env()


def _short_json_for_prompt(payload: Any, *, max_chars: int = 1600) -> str:
    try:
        rendered = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    except Exception:
        rendered = str(payload)
    if len(rendered) <= max_chars:
        return rendered
    return rendered[: max_chars - 20].rstrip() + "\n... [truncated]"


_FORBIDDEN_PROMPT_EXAMPLE_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bWelcome\b", re.IGNORECASE), "[human-greeting-token]"),
    (re.compile(r"\bToday\s+we\b", re.IGNORECASE), "[temporal-host-frame]"),
    (re.compile(r"\bwe\b", re.IGNORECASE), "[plural-host-token]"),
    (re.compile(r"\bour\b", re.IGNORECASE), "[plural-possessive-host-token]"),
    (re.compile(r"\bus\b", re.IGNORECASE), "[plural-object-host-token]"),
    (re.compile(r"\bjourney\b", re.IGNORECASE), "[journey-frame-token]"),
    (re.compile(r"\bviewer experience\b", re.IGNORECASE), "[viewer-experience-cliche]"),
    (re.compile(r"\bintegrity\b", re.IGNORECASE), "[institutional-virtue-cliche]"),
    (re.compile(r"\btrustworthiness\b", re.IGNORECASE), "[institutional-virtue-cliche]"),
    (re.compile(r"\bcredibility\b", re.IGNORECASE), "[institutional-virtue-cliche]"),
)


def _scrub_forbidden_prompt_examples(value: Any) -> str:
    text = str(value)
    for pattern, replacement in _FORBIDDEN_PROMPT_EXAMPLE_REPLACEMENTS:
        text = pattern.sub(replacement, text)
    return text


def _render_prep_content_state_prompt_block() -> str:
    state = _prep_content_state_for_prompt()
    if not state:
        return ""
    lines = [
        "== REQUIRED PREP CONTENT STATE ==",
        "This block is stronger than generic priors, prompt examples, and topic",
        "defaults. Use it as the source packet for item names, target tiers,",
        "evidence refs, and forbidden anchors. Do not invent substitute source",
        "names when an evidence ref is available.",
    ]
    for key in ("run_intent", "required_role", "focus"):
        value = state.get(key)
        if value:
            lines.append(f"- {key}: {value}")
    candidates = _string_list(state.get("topic_candidates"))
    if candidates:
        lines.append("- topic_candidates:")
        lines.extend(f"  - {item}" for item in candidates[:6])

    packets = state.get("source_packets")
    if isinstance(packets, list) and packets:
        lines.append("- source_packets:")
        for raw_packet in packets[:3]:
            if not isinstance(raw_packet, dict):
                continue
            packet_id = raw_packet.get("id") or "(unlabeled packet)"
            lines.append(f"  - id: {packet_id}")
            for key in ("role", "topic"):
                value = raw_packet.get(key)
                if value:
                    lines.append(f"    {key}: {_scrub_forbidden_prompt_examples(value)}")
            facts = _string_list(raw_packet.get("facts"))
            if facts:
                lines.append("    facts:")
                lines.extend(
                    f"      - {_scrub_forbidden_prompt_examples(item)}" for item in facts[:8]
                )
            evidence_refs = _string_list(raw_packet.get("evidence_refs"))
            if evidence_refs:
                lines.append("    evidence_refs:")
                lines.extend(f"      - {item}" for item in evidence_refs[:10])
            items = raw_packet.get("items")
            if isinstance(items, list) and items:
                lines.append("    required_items:")
                for raw_item in items[:12]:
                    if not isinstance(raw_item, dict):
                        continue
                    name = raw_item.get("name") or raw_item.get("item") or "(unnamed)"
                    tier = raw_item.get("target_tier") or raw_item.get("tier")
                    why = raw_item.get("why") or raw_item.get("rationale") or ""
                    tier_text = f" -> {tier}" if tier else ""
                    why_text = f": {_scrub_forbidden_prompt_examples(why)}" if why else ""
                    lines.append(
                        f"      - {_scrub_forbidden_prompt_examples(name)}{tier_text}{why_text}"
                    )
            forbidden = _string_list(raw_packet.get("forbidden_phrases"))
            if forbidden:
                lines.append(
                    "    forbidden_phrases: literal tokens supplied to validators but "
                    "withheld from generation; do not quote forbidden examples"
                )
    elif state:
        lines.append(_short_json_for_prompt(state))

    lines.extend(
        [
            "",
            "Content-state obligations:",
            "- If a required item has a target_tier, the spoken beat must use that",
            "  exact item name and target tier unless the beat is explicitly a hook",
            "  or close.",
            "- Source hooks should cite the concrete evidence ref or source packet",
            "  fact, not a generic invented source title.",
            "- Do not quote forbidden words or phrases as examples. Refer to them by",
            "  category such as human-greeting token, plural-host token, or",
            "  institutional-virtue cliche.",
            "- Public pressure must ask for a concrete judgment about a visible",
            "  ranking, comparison, receipt, or runtime readback.",
            "",
        ]
    )
    return "\n".join(lines)


def _prep_content_state_items() -> list[dict[str, Any]]:
    state = _prep_content_state_for_prompt()
    packets = state.get("source_packets") if isinstance(state, dict) else None
    if not isinstance(packets, list):
        return []
    items: list[dict[str, Any]] = []
    for packet in packets:
        if not isinstance(packet, dict):
            continue
        for raw_item in packet.get("items") or []:
            if isinstance(raw_item, dict):
                item = dict(raw_item)
                item.setdefault("source_packet_id", packet.get("id"))
                items.append(item)
    return items


_BEAT_ITEM_INDEX_RE = re.compile(r"\bitem[_ -]?(\d+)\b", re.IGNORECASE)


def _required_item_for_beat(
    *,
    beat_index: int,
    beat_direction: str,
    role: str,
) -> dict[str, Any] | None:
    if role != "tier_list":
        return None
    lowered = beat_direction.lower()
    match = _BEAT_ITEM_INDEX_RE.search(beat_direction)
    if match is None and _TIER_SKIP_DIRECTION_RE.search(lowered):
        return None
    items = _prep_content_state_items()
    if not items:
        return None
    item_index = int(match.group(1)) - 1 if match else beat_index - 1
    if item_index < 0 or item_index >= len(items):
        return None
    return items[item_index]


def _render_required_item_for_beat(
    *,
    beat_index: int,
    beat_direction: str,
    role: str,
) -> str:
    item = _required_item_for_beat(
        beat_index=beat_index,
        beat_direction=beat_direction,
        role=role,
    )
    if not item:
        return ""
    name = item.get("name") or item.get("item")
    tier = item.get("target_tier") or item.get("tier")
    why = item.get("why") or item.get("rationale")
    if not name:
        return ""
    lines = [
        "== REQUIRED ITEM FOR THIS BEAT ==",
        f"- item: {name}",
    ]
    if tier:
        lines.append(f"- target_tier: {tier}")
        lines.append(
            f"- required spoken placement: Place {name} in {tier} because [source-grounded reason]."
        )
    if why:
        lines.append(f"- packet_reason: {why}")
    source_packet_id = item.get("source_packet_id")
    if source_packet_id:
        lines.append(f"- source_packet_id: {source_packet_id}")
    lines.append("")
    return "\n".join(lines)


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
    planner_layout_obligations = _render_planner_layout_obligations(programme)
    prep_content_state = _render_prep_content_state_prompt_block()

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
        f"Compose a {role_value.upper().replace('_', ' ')} segment for the Hapax "
        "research livestream. Hapax is the non-human public system named in the "
        "personage contract below; write for its voice aperture without pretending "
        "it is a human host.\n\n"
        f"{render_nonhuman_personage_prompt_block()}"
        f"== SEGMENT DIRECTION ==\n{narrative_beat}\n\n"
        f"== SEGMENT STRUCTURE ==\n{beat_lines}\n\n"
        f"{prep_content_state}"
        "== PUBLIC ARC ==\n"
        "Every segment is a constructed public demonstration, not a listicle. Treat "
        "arc/tension/stakes as non-human signal functions. Human narratology terms "
        "are allowed by analogy when the analogy is marked or functionally translated; "
        "do not let the analogy become human-host identity, feeling, empathy, or "
        "biography:\n"
        "- OPEN with a concrete referent under pressure: source, contradiction, receipt, or claim\n"
        "- The first beat's first sentence must bind that premise to an exact packet id, "
        "validator, code path, or receipt and include because/but/problem/contradiction/risk language\n"
        "- BUILD through source collisions, visible tests, and consequences\n"
        "- Include at least one PIVOT where new evidence changes the state of the ranking or claim\n"
        "- PEAK at roughly 2/3 through with the most specific cost, contradiction, or receipt\n"
        "- BREATHE before landing: let the public readback state stabilize\n"
        "- CLOSE with a reframe that changes the opening claim's status\n\n"
        "== BEAT DEPTH ==\n"
        "Each beat is 800-2000 characters of spoken prose (1-2 minutes at broadcast pace).\n"
        "That means 8-20 sentences per beat. Use full argument paragraphs, not tweet thread.\n"
        "- Every claim gets its FULL ARGUMENT, not just an assertion\n"
        "- Sources get CONTEXT: '[named source] argues X because Y, which matters because Z'\n"
        "- Transitions between beats should work as signal handoffs, not chapter breaks\n"
        "- Use rhetorical questions only when they pressure evidence, source status, or readback\n"
        "- Use 'by analogy' when a human rhetorical category helps communication across unlike entities\n"
        "- Let ideas BREATHE — develop a point, sit with it, then pivot\n"
        "- A beat that can be summarized in one sentence is a beat that wasn't written yet\n\n"
        f"{render_quality_prompt_block()}"
        "== FORBIDDEN HUMAN-HOST REGISTER ==\n"
        "Do not write or quote greeting tokens, monologue openers, shared-human "
        "journey frames, first-person plural host pronouns, host closers, or "
        "institutional-virtue cliches. Start with the concrete object under judgment: source, "
        "artifact, ranking, claim, contradiction, or visible test. Keep Hapax as a "
        "non-human voice aperture; do not claim objectivity, neutrality, freedom from "
        "bias, empathy, or viewer community feelings.\n\n"
        "== VISUAL HOOKS ==\n"
        "Your narration makes runtime-recognizable visible-action commitments. "
        "Specific text patterns propose typed layout needs; the runtime still "
        "decides the concrete posture and readback must prove visibility before "
        "success counts. Use these patterns intentionally:\n\n"
        "CHAT TRIGGERS — this exact sentence start marks a chat-poll moment:\n"
        "  'Chat pressure: [specific question or decision request].'\n"
        "  Use at beat endings where public input changes the bit. Never as filler.\n\n"
        f"{visual_hooks}"
        f"{planner_layout_obligations}"
        "== CRITICAL: SPOKEN PROSE ONLY ==\n"
        "Write ONLY words the Hapax voice aperture can emit on a live broadcast.\n"
        "NEVER include stage directions, beat labels, action cues, or meta-instructions.\n"
        "WRONG: 'We pivot. Challenge the S-tier placement. Discuss the complexity.'\n"
        "WRONG: 'We close. Recap the final tier chart. Invite chat to disagree.'\n"
        "RIGHT: 'But here is where the chart gets uncomfortable. Because the source "
        "record contradicts the first reading.'\n"
        "RIGHT: 'This pulls the comparison back together. The final ranking exposes "
        "the hidden constraint.'\n"
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
        "REGISTER: Hapax voice aperture on a live production. Non-human public "
        "instrument: source-grounded, direct, operationally opinionated, "
        "correction-ready. The appeal comes from receipts, compressed structure, "
        "visible transformations, and unusual vantage, not human warmth or cosplay.\n\n"
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


def _truthy_env(name: str) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _falsey_env(name: str) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    return raw in {"0", "false", "no", "off"}


def _sequential_prep_enabled() -> bool:
    if _falsey_env("HAPAX_SEGMENT_PREP_SEQUENTIAL_BEATS"):
        return False
    if _truthy_env("HAPAX_SEGMENT_PREP_SEQUENTIAL_BEATS"):
        return True
    return bool(os.environ.get("HAPAX_SEGMENT_PREP_CONTENT_STATE_JSON", "").strip())


def _prep_model() -> str:
    return configured_resident_model("HAPAX_SEGMENT_PREP_MODEL", purpose="segment prep")


def _tabby_chat_url() -> str:
    return tabby_chat_url()


def _loaded_tabby_model() -> str | None:
    attempts = int(os.environ.get("HAPAX_SEGMENT_PREP_MODEL_CHECK_ATTEMPTS", "3"))
    delay_s = float(os.environ.get("HAPAX_SEGMENT_PREP_MODEL_CHECK_RETRY_S", "2"))
    last_exc: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            return loaded_tabby_model(_tabby_chat_url())
        except Exception as exc:
            last_exc = exc
            if attempt + 1 < attempts:
                time.sleep(delay_s)
    if last_exc is not None:
        raise last_exc
    return None


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
        "resident_model_verified": False,
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
        verify_resident = not (
            isinstance(prep_session, dict) and prep_session.get("resident_model_verified") == model
        )
        content = call_resident_command_r(
            prompt,
            chat_url=_tabby_chat_url(),
            max_tokens=max_tokens,
            temperature=0.7,
            timeout_s=_PREP_LLM_TIMEOUT_S,
            verify_resident=verify_resident,
        )
        if isinstance(prep_session, dict):
            prep_session["resident_model_verified"] = model
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


_STRINGIFIED_BEAT_METADATA_RE = re.compile(
    r"^\s*[\{\[]\s*[\"']?(?:beat|beat_number|direction|draft|spoken_text|"
    r"narration|text)[\"']?\s*[:=]",
    re.IGNORECASE,
)


def _looks_like_stringified_beat_metadata(text: str) -> bool:
    return bool(
        _STRINGIFIED_BEAT_METADATA_RE.search(text)
        or (
            text.lstrip().startswith(("{", "["))
            and re.search(
                r"[\"'](?:beat|beat_number|direction|draft|spoken_text|narration|text)[\"']\s*:",
                text,
                re.IGNORECASE,
            )
        )
    )


def _load_script_json_array(text: str) -> list[Any] | None:
    def _script_array_from(value: Any) -> list[Any] | None:
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for key in (
                "prepared_script",
                "script",
                "rewritten_script",
                "revised_script",
                "beats",
                "rewritten_beats",
                "revised_beats",
                "narration_blocks",
            ):
                candidate = value.get(key)
                if isinstance(candidate, list):
                    return candidate
        return None

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        starts = [index for index in (text.find("["), text.find("{")) if index >= 0]
        if not starts:
            return None
        start = min(starts)
        try:
            parsed, _end = json.JSONDecoder().raw_decode(text[start:])
        except json.JSONDecodeError:
            return None
    return _script_array_from(parsed)


_MARKDOWN_BEAT_RE = re.compile(r"^\s*(?:\d+[\.)]|[-*])\s+(?P<text>\S.*)$")


def _parse_markdown_script_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _MARKDOWN_BEAT_RE.match(line)
        if match:
            if current:
                blocks.append(" ".join(current).strip())
            current = [match.group("text").strip()]
            continue
        if current and not line.startswith(("```", "[", "]", "{", "}")):
            current.append(line)
    if current:
        blocks.append(" ".join(current).strip())
    return [block for block in blocks if len(block) >= 20]


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

    parsed = _load_script_json_array(text)
    if parsed is None:
        fallback = _parse_markdown_script_blocks(text)
        if fallback:
            return fallback
        log.warning("segment prep: LLM response is not valid JSON")
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
            if _looks_like_stringified_beat_metadata(text):
                log.warning("segment prep: rejected stringified beat metadata")
                continue
        if text:
            beats.append(text)
    return beats


def _parse_single_beat(raw: str) -> str:
    parsed = _parse_script(raw)
    if parsed:
        return parsed[0].strip()
    text = _clean_llm_text(raw.strip())
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    text = re.sub(r"^\s*(?:beat\s*)?\d+[\.)]\s*", "", text, flags=re.IGNORECASE).strip()
    text = text.strip("\"' \n\t")
    return text


def _build_sequential_beat_prompt(
    *,
    programme: Any,
    seed: str,
    beat_index: int,
    beat_direction: str,
    previous_beats: list[str],
) -> str:
    role = getattr(getattr(programme, "role", None), "value", "rant")
    content = getattr(programme, "content", None)
    narrative_beat = getattr(content, "narrative_beat", "") or "" if content else ""
    beats = getattr(content, "segment_beats", []) or [] if content else []
    visual_hooks = _ROLE_VISUAL_HOOKS.get(role, "")
    prep_content_state = _render_prep_content_state_prompt_block()
    required_item = _render_required_item_for_beat(
        beat_index=beat_index,
        beat_direction=beat_direction,
        role=role,
    )
    previous = "\n\n".join(
        f"Previous beat {i + 1}: {text}" for i, text in enumerate(previous_beats[-3:])
    )
    previous_block = previous or "(none)"
    opening_contract = ""
    if beat_index == 0:
        opening_contract = (
            "== OPENING PREMISE CONTRACT ==\n"
            "- The first sentence must state the exact claim under pressure, not a "
            "generic setup. It must include because, but, problem, contradiction, "
            "risk, or pressure language.\n"
            "- Bind the premise to an exact packet id, code path, validator, or "
            "receipt before expanding it. `source packet` or `validator` alone is "
            "not specific enough.\n"
            "- The opening should make the later item placements feel necessary: "
            "loadability, source receipt, runtime readback, and pool-release fitness "
            "must be in the same public problem.\n\n"
        )
    return (
        "Compose exactly one prepared livestream beat for Hapax. This is sequential "
        "segment prep: previous accepted beats are context, and this response must "
        "continue the same public bit without resetting into a host opener.\n\n"
        f"{render_nonhuman_personage_prompt_block()}"
        f"Role: {role}\n"
        f"Topic: {narrative_beat}\n"
        f"Beat {beat_index + 1} of {len(beats)} direction: {beat_direction}\n\n"
        f"{prep_content_state}"
        f"{required_item}"
        f"{opening_contract}"
        "== PREVIOUS ACCEPTED BEATS ==\n"
        f"{previous_block}\n\n"
        "== HARD OUTPUT CONTRACT ==\n"
        "- Output only the spoken paragraph for this beat. No JSON, markdown, label, "
        "analysis, or stage direction.\n"
        "- 650-1200 characters.\n"
        "- Do not use first-person singular or plural host pronouns.\n"
        "- Do not start with a greeting, temporal host frame, presenter transition, "
        "or conclusion phrase.\n"
        "- Do not quote forbidden human-host examples; name their category instead.\n"
        "- Use Hapax/source/public/runtime nouns instead of human-host framing.\n"
        "- Include at least one source/detail/action hook from the role guidance when "
        "the beat makes a claim.\n"
        "- If this is a tier-list item/ranking beat, include an exact sentence starting "
        "with `Place ` and using `in S-tier`, `in A-tier`, `in B-tier`, `in C-tier`, "
        "or `in D-tier`.\n\n"
        "== ROLE GUIDANCE ==\n"
        f"{visual_hooks}\n"
        "== SEGMENT RESEARCH AND ASSETS ==\n"
        "---\n"
        f"{seed}\n"
        "---\n"
    )


def _build_single_beat_repair_prompt(
    *,
    beat_text: str,
    beat_index: int,
    beat_direction: str,
    programme: Any,
    personage: dict[str, Any],
    repair_reasons: list[str],
) -> str:
    role = getattr(getattr(programme, "role", None), "value", "rant")
    prep_content_state = _render_prep_content_state_prompt_block()
    required_item = _render_required_item_for_beat(
        beat_index=beat_index,
        beat_direction=beat_direction,
        role=role,
    )
    violations = personage.get("violations") if isinstance(personage, dict) else []
    violation_lines = "\n".join(
        f"- {item.get('reason')}: {item.get('match')!r}"
        for item in violations
        if isinstance(item, dict)
    )
    reason_lines = "\n".join(f"- {item}" for item in repair_reasons)
    return (
        "Repair this single Hapax beat. Return only the repaired spoken paragraph.\n\n"
        f"{render_nonhuman_personage_prompt_block()}"
        f"Beat {beat_index + 1} direction: {beat_direction}\n"
        f"{prep_content_state}"
        f"{required_item}"
        "Repair reasons:\n"
        f"{reason_lines or '- quality/actionability repair required'}\n\n"
        "Violations:\n"
        f"{violation_lines or '- no regex personage violation detected'}\n\n"
        "Rules: 750-1200 characters; no first-person host pronouns; no greeting, "
        "temporal host frame, shared-human journey, viewer-experience cliche, "
        "institutional-virtue cliche, host closer, or thanks-for-watching language; no fake "
        "objectivity; keep or add exact source/action hooks; include a callback "
        "to a prior beat when possible; if this is a tier-list item, include a "
        "sentence starting with `Place ` and an explicit packet target tier. "
        "If this is beat 1, the first sentence must state a source-bound premise "
        "with because/but/problem/contradiction/risk language and an exact packet, "
        "validator, code path, or receipt name. Generic `source packet`, `validator`, "
        "`method`, or `segment` wording does not repair specificity.\n\n"
        "Draft:\n"
        f"{beat_text}\n"
    )


_SUPPORTED_BEAT_HOOK_RE = re.compile(
    r"\b(?:Source check|Evidence check|Definition check|Public readback|Visible test|"
    r"Worked example|Chat pressure):",
    re.IGNORECASE,
)
_PREMISE_PRESSURE_RE = re.compile(
    r"\b(?:because|but|why|problem|contradiction|risk|pressure|fails?|failure|cost)\b",
    re.IGNORECASE,
)
_CONCRETE_SOURCE_REF_RE = re.compile(
    r"\b(?:packet:[A-Za-z0-9:_-]+|[\w./-]+\.py(?::[\w.]+)?|validate_[a-z_]+|"
    r"DailySegmentPrep|Command-R|LayoutState|review_segment_batch|prep_segment)\b",
    re.IGNORECASE,
)
_GENERIC_SPECIFICITY_SINK_RE = re.compile(
    r"\b(?:source packet|validator|review receipt|code path|the method|the segment|"
    r"the content|information presented|valuable information)\b",
    re.IGNORECASE,
)


def _script_sentences(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"(?<=[.!?])\s+", text.strip()) if item.strip()]


def _opening_premise_repair_reason(beat: str) -> str | None:
    sentences = _script_sentences(beat)
    first_sentence = sentences[0] if sentences else beat
    if not _PREMISE_PRESSURE_RE.search(first_sentence):
        return (
            "opening premise is soft: first sentence must state the exact claim "
            "under pressure and include because/but/problem/contradiction/risk language"
        )
    if not _CONCRETE_SOURCE_REF_RE.search(beat):
        return (
            "opening premise is unbound: name an exact packet id, code path, validator, "
            "or receipt before expanding the claim"
        )
    return None


def _specificity_repair_reason(beat: str) -> str | None:
    has_concrete_ref = bool(_CONCRETE_SOURCE_REF_RE.search(beat) or _PLACEMENT_RE.search(beat))
    if not has_concrete_ref:
        return (
            "specificity is too low: include an exact packet id, code path, validator "
            "name, receipt id, or source-packet item name"
        )
    if _GENERIC_SPECIFICITY_SINK_RE.search(beat) and not _CONCRETE_SOURCE_REF_RE.search(beat):
        return (
            "specificity is generic: replace broad source/validator/method language "
            "with exact packet, validator, receipt, or item names"
        )
    return None


def _single_beat_repair_reasons(
    *,
    beat: str,
    beat_index: int,
    beat_direction: str,
    programme: Any,
    personage: dict[str, Any],
) -> list[str]:
    role = getattr(getattr(programme, "role", None), "value", "rant")
    reasons: list[str] = []
    if len(beat) < 650:
        reasons.append(f"beat is too short ({len(beat)} chars); minimum is 650")
    if personage.get("ok") is not True:
        reasons.append("beat violates the non-human personage contract")
    if not _SUPPORTED_BEAT_HOOK_RE.search(beat):
        reasons.append("beat lacks a supported source/detail/readback/chat hook")
    if beat_index == 0:
        premise_reason = _opening_premise_repair_reason(beat)
        if premise_reason:
            reasons.append(premise_reason)
    specificity_reason = _specificity_repair_reason(beat)
    if specificity_reason:
        reasons.append(specificity_reason)
    item_direction = _BEAT_ITEM_INDEX_RE.search(beat_direction) is not None
    skip_direction = _TIER_SKIP_DIRECTION_RE.search(beat_direction) is not None
    if role == "tier_list" and (item_direction or not skip_direction):
        required_item = _render_required_item_for_beat(
            beat_index=beat_index,
            beat_direction=beat_direction,
            role=role,
        )
        if required_item:
            expected_item = _required_item_for_beat(
                beat_index=beat_index,
                beat_direction=beat_direction,
                role=role,
            )
            placement_ok = False
            if expected_item:
                expected_phrase = (
                    f"Place {expected_item['name']} in {expected_item['tier']}"
                    if expected_item.get("tier")
                    else ""
                )
                placement_ok = bool(
                    expected_phrase
                    and re.search(
                        r"\b" + re.escape(expected_phrase) + r"\b",
                        beat,
                        flags=re.IGNORECASE,
                    )
                )
            else:
                placement_ok = bool(_PLACEMENT_RE.search(beat))
            if not placement_ok:
                reasons.append(
                    "tier-list item beat lacks the exact source-packet item/tier placement phrase"
                )
    return reasons


def _compose_script_sequential(
    programme: Any,
    *,
    seed: str,
    prep_session: dict[str, Any] | None,
    programme_id: str,
) -> list[str]:
    content = getattr(programme, "content", None)
    beats = [str(item) for item in (getattr(content, "segment_beats", []) or [])]
    script: list[str] = []
    for index, beat_direction in enumerate(beats):
        prompt = _build_sequential_beat_prompt(
            programme=programme,
            seed=seed,
            beat_index=index,
            beat_direction=beat_direction,
            previous_beats=script,
        )
        raw = _call_llm(
            prompt,
            prep_session=prep_session,
            phase="compose_beat",
            programme_id=programme_id,
            max_tokens=4096,
        )
        beat = _parse_single_beat(raw)
        for _attempt in range(2):
            personage = validate_nonhuman_personage(beat)
            repair_reasons = _single_beat_repair_reasons(
                beat=beat,
                beat_index=index,
                beat_direction=beat_direction,
                programme=programme,
                personage=personage,
            )
            if not repair_reasons:
                break
            repair_prompt = _build_single_beat_repair_prompt(
                beat_text=beat,
                beat_index=index,
                beat_direction=beat_direction,
                programme=programme,
                personage=personage,
                repair_reasons=repair_reasons,
            )
            repaired_raw = _call_llm(
                repair_prompt,
                prep_session=prep_session,
                phase="compose_beat_repair",
                programme_id=programme_id,
                max_tokens=4096,
            )
            repaired = _parse_single_beat(repaired_raw)
            if repaired:
                beat = repaired
        script.append(beat)
    return script


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
    prep_content_state = _render_prep_content_state_prompt_block()

    beat_review = ""
    for i, (direction, text) in enumerate(zip(beats, script, strict=False)):
        chars = len(text)
        beat_review += f"\n--- Beat {i + 1} ({chars} chars) ---\n"
        beat_review += f"Direction: {direction}\n"
        beat_review += f"Draft: {text}\n"

    return (
        "Run a resident prep-critic pass on a "
        f"{role.upper().replace('_', ' ')} segment script for the Hapax research "
        "livestream.\n\n"
        f"{render_nonhuman_personage_prompt_block()}"
        f"Topic: {narrative_beat}\n\n"
        f"{prep_content_state}"
        "== REVIEW CRITERIA ==\n"
        "For each beat, evaluate:\n"
        "1. LENGTH: Is it at least 800 characters? Beats under 600 chars are THIN.\n"
        "2. SPECIFICITY: Does it name sources WITH context, or just name-drop?\n"
        "3. ARC: Does it earn the next beat, or just stop and start a new topic?\n"
        "4. RHETORIC: Does it vary sentence length, use callbacks, and create public pressure?\n"
        "5. PRESSURE: Does the beat breathe, or does it rush through its material?\n"
        "6. DEPTH: Could a Wikipedia article make this same point? If yes, it's too shallow.\n"
        "7. STAGE DIRECTIONS: Does the beat contain meta-instructions like 'We pivot',\n"
        "   'We close', 'Recap the chart', 'Invite chat'? These are FATAL — rewrite as\n"
        "   spoken prose the Hapax voice aperture can emit.\n"
        "8. REPETITION: Is the same phrase or paragraph copy-pasted across beats?\n"
        "   Any repeated text block is a FATAL error — each beat must be unique.\n\n"
        "9. PERSONAGE: Does the beat pretend Hapax has human feelings, empathy, biography,\n"
        "   human-host warmth, shared-human 'we', bias-free objectivity, or first-person "
        "inner life? These are FATAL.\n"
        "10. OPENERS: Does the draft start with a greeting, temporal host frame, "
        "shared-human journey, or invitation to join? These are FATAL; replace with a source, artifact, "
        "ranking, contradiction, or visible test.\n\n"
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
    repairable_reasons = {
        "unsupported_layout_need",
        "missing_tier_placement_phrase",
        "weak_action_only_not_responsible_layout",
    }
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
    planner_layout_obligations = _render_planner_layout_obligations(programme)
    prep_content_state = _render_prep_content_state_prompt_block()
    failed = {
        int(item["beat_index"])
        for item in layout_responsibility.get("violations", [])
        if isinstance(item, dict)
        and isinstance(item.get("beat_index"), int)
        and item.get("reason")
        in {
            "unsupported_layout_need",
            "missing_tier_placement_phrase",
            "weak_action_only_not_responsible_layout",
        }
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
                "'Place Candidate Alpha in S-tier.'\n"
            )
        elif i in failed:
            mandatory_lines.append(
                f"- Beat {i + 1}: include at least one sentence that starts with "
                "'Source check:', 'Evidence check:', 'Definition check:', "
                "'Public readback:', 'Visible test:', or 'Worked example:'."
            )
            beat_review += (
                "Mandatory visible trigger: write a source/detail sentence like "
                "'Source check: the resolved source note argues that the claim "
                "matters because it changes the public interpretation.'\n"
            )
        beat_review += f"Draft: {text}\n"

    mandatory_block = ""
    if mandatory_lines:
        mandatory_block = (
            "== MANDATORY FAILED-BEAT REPAIRS ==\n" + "\n".join(mandatory_lines) + "\n\n"
        )

    return (
        f"Repair a {role.upper().replace('_', ' ')} segment for the "
        "responsible livestream layout contract.\n\n"
        f"{render_nonhuman_personage_prompt_block()}"
        f"Topic: {narrative_beat}\n\n"
        f"{prep_content_state}"
        "The previous draft failed because some beats only made spoken arguments. "
        "For Hapax-hosted responsible segments, spoken-only beats do not satisfy "
        "layout responsibility. Rewrite the full script with the same beat count "
        "so every failed beat includes a supported visible/doable trigger in the "
        "spoken words.\n\n"
        f"{render_quality_prompt_block()}"
        "== FORBIDDEN HUMAN-HOST REGISTER ==\n"
        "Do not add or retain greeting tokens, temporal host frames, first-person "
        "plural host pronouns, shared-human journey language, invitations to join, "
        "host closers, or any claim that Hapax is objective, unbiased, neutral, "
        "empathetic, or human-like. Use Hapax/source/public/runtime nouns instead of "
        "a shared human-host frame.\n\n"
        "== ROLE-SPECIFIC VISIBLE ACTIONS ==\n"
        f"{visual_hooks}"
        f"{planner_layout_obligations}"
        f"{mandatory_block}"
        "If this is a tier-list segment, every failed item/ranking/body beat must "
        "say an exact placement phrase that matches the runtime trigger regex:\n"
        "  Place [item] in [S/A/B/C/D]-tier\n"
        "The sentence must begin with the word 'Place', include the word 'in' "
        "before the tier, and use S-tier, A-tier, B-tier, C-tier, or D-tier. "
        "VALID: 'Place Candidate Alpha in S-tier.' "
        "INVALID: 'Let's kick things off by placing Candidate Alpha in S-tier.' "
        "INVALID: 'Candidate Alpha belongs in A-tier.' "
        "Do not merely discuss history; make a ranking with a visible counterpart.\n\n"
        "For non-tier failed beats, use source/detail hooks exactly. VALID: "
        "'Source check: the resolved source note argues that the distinction changes "
        "the stakes.' VALID: 'Evidence check: the archived artifact shows the "
        "timeline moved in three steps.' VALID: 'Definition check: local meaning "
        "means the term is being used as social evidence, not only description.' "
        "VALID: 'Public readback: the source card must show the receipt before the "
        "claim counts.' VALID: 'Visible test: the ranking compares source access "
        "against visible readback.' VALID: 'Worked example: the artifact moves from "
        "claim to receipt in three steps.'\n\n"
        "Do not invent camera shots, screenshots, clips, direct layout commands, "
        "coordinates, cue strings, or stage directions. Keep the prose voice-aperture "
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


def _quality_or_personage_repair_required(
    quality_report: dict[str, Any],
    personage: dict[str, Any],
) -> bool:
    scores = quality_report.get("scores") if isinstance(quality_report, dict) else {}
    return (
        personage.get("ok") is not True
        or quality_report.get("label") == "generic"
        or float(quality_report.get("overall") or 0.0) < 3.5
        or int((quality_report.get("diagnostics") or {}).get("thin_beats") or 0) > 0
        or _quality_score_floor_failure(scores) is not None
    )


PREP_QUALITY_SCORE_FLOORS = {
    "premise": 4,
    "specificity": 5,
    "public_pressure": 3,
    "source_fidelity": 3,
    "actionability": 4,
    "layout_responsibility": 4,
}


def _quality_score_floor_failure(scores: dict[str, Any]) -> str | None:
    if not isinstance(scores, dict):
        return "segment quality scores malformed"
    for key, floor in PREP_QUALITY_SCORE_FLOORS.items():
        if int(scores.get(key) or 0) < floor:
            return f"segment {key} below floor"
    return None


def _quality_floor_rejection_reason(quality_report: dict[str, Any]) -> str | None:
    if not isinstance(quality_report, dict):
        return "missing segment quality report"
    if quality_report.get("rubric_version") != QUALITY_RUBRIC_VERSION:
        return "unsupported segment quality rubric"
    scores = quality_report.get("scores")
    diagnostics = quality_report.get("diagnostics")
    if not isinstance(scores, dict) or not isinstance(diagnostics, dict):
        return "malformed segment quality report"
    if quality_report.get("label") == "generic":
        return "segment quality is generic"
    if float(quality_report.get("overall") or 0.0) < 3.5:
        return "segment quality overall below floor"
    if int(diagnostics.get("thin_beats") or 0) > 0:
        return "segment contains thin beats"
    score_floor_reason = _quality_score_floor_failure(scores)
    if score_floor_reason:
        return score_floor_reason
    return None


_PLACEMENT_RE = re.compile(
    r"\bPlace\s+(?P<item>.+?)\s+in\s+(?P<tier>[SABCD]-tier)\b",
    re.IGNORECASE,
)


def _normalize_target_item(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.strip("\"'“”‘’")
    text = re.sub(r"\s+", " ", text)
    return text


def _content_state_target_failures(
    *,
    script: list[str],
    prep_content_state: dict[str, Any] | None,
    segment_beats: list[str] | None = None,
) -> list[dict[str, Any]]:
    packets = (
        prep_content_state.get("source_packets") if isinstance(prep_content_state, dict) else None
    )
    if not isinstance(packets, list):
        return []
    expected: dict[str, dict[str, Any]] = {}
    ordered_expected: list[dict[str, Any]] = []
    for packet in packets:
        if not isinstance(packet, dict):
            continue
        for item in packet.get("items") or []:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("item")
            tier = item.get("target_tier") or item.get("tier")
            if not isinstance(name, str) or not name.strip() or not isinstance(tier, str):
                continue
            target = {
                "item": name.strip(),
                "tier": tier.strip(),
                "source_packet_id": str(packet.get("id") or ""),
            }
            expected[_normalize_target_item(name)] = target
            ordered_expected.append(target)
    if not expected:
        return []

    placements: dict[str, set[str]] = {}
    placement_beats: dict[tuple[str, str], set[int]] = {}
    extras: list[dict[str, str]] = []
    for beat_index, text in enumerate(script):
        for match in _PLACEMENT_RE.finditer(text):
            raw_item = match.group("item").strip(" \"'“”‘’.")
            normalized = _normalize_target_item(raw_item)
            tier = match.group("tier").lower()
            placements.setdefault(normalized, set()).add(tier)
            placement_beats.setdefault((normalized, tier), set()).add(beat_index)
            if normalized not in expected:
                extras.append({"item": raw_item, "tier": tier, "reason": "extra_target"})

    failures: list[dict[str, Any]] = list(extras)
    expected_beat_by_item: dict[str, int] = {}
    if segment_beats:
        for beat_index, direction in enumerate(segment_beats):
            match = _BEAT_ITEM_INDEX_RE.search(str(direction))
            if not match:
                continue
            item_index = int(match.group(1)) - 1
            if 0 <= item_index < len(ordered_expected):
                expected_beat_by_item[
                    _normalize_target_item(ordered_expected[item_index]["item"])
                ] = beat_index
    for normalized, target in expected.items():
        tiers = placements.get(normalized, set())
        target_tier = str(target["tier"]).lower()
        if target_tier not in tiers:
            failures.append(
                {
                    "item": target["item"],
                    "target_tier": target["tier"],
                    "observed_tiers": sorted(tiers),
                    "source_packet_id": target["source_packet_id"],
                    "reason": "missing_or_misplaced_target",
                }
            )
            continue
        expected_beat = expected_beat_by_item.get(normalized)
        if expected_beat is not None:
            observed_beats = sorted(placement_beats.get((normalized, target_tier), set()))
            if expected_beat not in observed_beats:
                failures.append(
                    {
                        "item": target["item"],
                        "target_tier": target["tier"],
                        "expected_beat_index": expected_beat,
                        "observed_beat_indices": observed_beats,
                        "source_packet_id": target["source_packet_id"],
                        "reason": "target_placement_wrong_beat",
                    }
                )
            extra_beats = [index for index in observed_beats if index != expected_beat]
            if extra_beats:
                failures.append(
                    {
                        "item": target["item"],
                        "target_tier": target["tier"],
                        "expected_beat_index": expected_beat,
                        "observed_extra_beat_indices": extra_beats,
                        "source_packet_id": target["source_packet_id"],
                        "reason": "target_placement_extra_beat",
                    }
                )
    return failures


def _content_state_rejection_reason(
    *,
    script: list[str],
    prep_content_state: dict[str, Any] | None,
    segment_beats: list[str] | None = None,
) -> str | None:
    target_failures = _content_state_target_failures(
        script=script,
        prep_content_state=prep_content_state,
        segment_beats=segment_beats,
    )
    if target_failures:
        return "content-state target fidelity failed"
    return None


_DEHOST_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bwe(?:'|’)ve\b", re.IGNORECASE), "the method has"),
    (re.compile(r"\bthe method(?:'|’)ve\b", re.IGNORECASE), "the method has"),
    (re.compile(r"\bhello everyone\b", re.IGNORECASE), "human-greeting token"),
    (re.compile(r"\bwelcome to\b", re.IGNORECASE), "human-greeting token"),
    (re.compile(r"\bwelcome back\b", re.IGNORECASE), "human-greeting token"),
    (re.compile(r"\bas a human\b", re.IGNORECASE), "as a flesh-host simulation"),
    (re.compile(r"\bthe method(?:'|’)ll\b", re.IGNORECASE), "the method will"),
    (
        re.compile(r"\bLet(?:'|’)s\s+(?:delve|dive|discuss|explore)\b", re.IGNORECASE),
        "The segment turns",
    ),
    (re.compile(r"\bLet(?:'|’)s\b", re.IGNORECASE), "The segment"),
    (re.compile(r"\bour livestream\b", re.IGNORECASE), "the livestream"),
    (re.compile(r"\bour segments\b", re.IGNORECASE), "the prepared segments"),
    (re.compile(r"\bour segment\b", re.IGNORECASE), "the prepared segment"),
    (re.compile(r"\bour content\b", re.IGNORECASE), "the content"),
    (re.compile(r"\bour audience\b", re.IGNORECASE), "the public"),
    (re.compile(r"\bour viewers\b", re.IGNORECASE), "the public"),
    (
        re.compile(r"\bengag(?:e|ing) the audience\b", re.IGNORECASE),
        "creating an inspectable public decision",
    ),
    (re.compile(r"\baudience\b", re.IGNORECASE), "public"),
    (
        re.compile(r"\bactively engage the public\b", re.IGNORECASE),
        "create an inspectable public decision",
    ),
    (
        re.compile(r"\bengage the public actively\b", re.IGNORECASE),
        "create an inspectable public decision",
    ),
    (
        re.compile(r"\baudience to actively engage and contribute\b", re.IGNORECASE),
        "public decision to become inspectable",
    ),
    (
        re.compile(r"\bactively engage and contribute\b", re.IGNORECASE),
        "make a bounded public decision",
    ),
    (re.compile(r"\baudience participation\b", re.IGNORECASE), "public decision pressure"),
    (re.compile(r"\baudience engagement\b", re.IGNORECASE), "public decision pressure"),
    (re.compile(r"\baudience questions\b", re.IGNORECASE), "chat-pressure decisions"),
    (re.compile(r"\breal-time feedback\b", re.IGNORECASE), "runtime readback pressure"),
    (
        re.compile(r"\bactively involve viewers\b", re.IGNORECASE),
        "make the public decision inspectable",
    ),
    (re.compile(r"\bpassive listeners\b", re.IGNORECASE), "unbound recipients"),
    (re.compile(r"\bactive contributors\b", re.IGNORECASE), "bounded public decision inputs"),
    (re.compile(r"\bdriving the narrative\b", re.IGNORECASE), "changing the public decision state"),
    (re.compile(r"\bshape the conversation\b", re.IGNORECASE), "change the public decision state"),
    (
        re.compile(r"\bopen the floor to the public\b", re.IGNORECASE),
        "open a bounded chat-pressure decision",
    ),
    (re.compile(r"\bviewers\b", re.IGNORECASE), "the public"),
    (re.compile(r"\bviewer\b", re.IGNORECASE), "public reader"),
    (re.compile(r"\bYour input is invaluable[^.?!]*[.?!]", re.IGNORECASE), ""),
    (re.compile(r"\bnon-human persona\b", re.IGNORECASE), "non-human personage contract"),
    (
        re.compile(r"\bdistinct and authentic voice aperture\b", re.IGNORECASE),
        "bounded voice-aperture rule",
    ),
    (re.compile(r"\bauthentic voice aperture\b", re.IGNORECASE), "bounded voice-aperture rule"),
    (re.compile(r"\bpublic run(?:'|’)s authenticity\b", re.IGNORECASE), "source-bounded register"),
    (
        re.compile(r"\bshowcases? the public run(?:'|’)s authenticity\b", re.IGNORECASE),
        "shows the source-bounded register",
    ),
    (
        re.compile(r"\bfoster a genuine connection\b", re.IGNORECASE),
        "create a bounded public readback",
    ),
    (
        re.compile(r"\bresonate[s]? with the public\b", re.IGNORECASE),
        "remain legible under public readback",
    ),
    (
        re.compile(r"\bconnects genuinely with the public\b", re.IGNORECASE),
        "binds to a public readback",
    ),
    (
        re.compile(r"\bconnects genuinely with the audience\b", re.IGNORECASE),
        "binds to a public readback",
    ),
    (
        re.compile(r"\bresonate[s]? with the audience\b", re.IGNORECASE),
        "remain legible under public readback",
    ),
    (
        re.compile(r"\bdelivering informative and captivating segments\b", re.IGNORECASE),
        "delivering source-bound, inspectable segments",
    ),
    (re.compile(r"\bcaptivating segments\b", re.IGNORECASE), "inspectable segments"),
    (
        re.compile(r"\bdynamic and immersive experience\b", re.IGNORECASE),
        "visible source-bound sequence",
    ),
    (
        re.compile(r"\bmeaningful and immersive experience\b", re.IGNORECASE),
        "source-bound public readback",
    ),
    (
        re.compile(r"\binteractive livestream experience\b", re.IGNORECASE),
        "inspectable public readback",
    ),
    (re.compile(r"\bimmersive experience\b", re.IGNORECASE), "inspectable public readback"),
    (re.compile(r"\bshared experience\b", re.IGNORECASE), "shared public receipt"),
    (
        re.compile(r"\bdrive meaningful discussions\b", re.IGNORECASE),
        "create bounded public decisions",
    ),
    (re.compile(r"\bmeaningful discourse\b", re.IGNORECASE), "bounded public decision pressure"),
    (
        re.compile(r"\bengaging and informative experience\b", re.IGNORECASE),
        "source-bound public readback",
    ),
    (re.compile(r"\blivestream(?:'|’)s success\b", re.IGNORECASE), "pool-release fitness"),
    (re.compile(r"\bfosters? trust\b", re.IGNORECASE), "keeps receipt strength visible"),
    (
        re.compile(r"\bsubstantial engagement strategies\b", re.IGNORECASE),
        "specific public-pressure hooks",
    ),
    (
        re.compile(r"\bvaluable and engaging for the public\b", re.IGNORECASE),
        "source-bound and inspectable for the public",
    ),
    (re.compile(r"\bengaging for the public\b", re.IGNORECASE), "legible under public readback"),
    (re.compile(r"\bgrounded and authentic\b", re.IGNORECASE), "source-bound and inspectable"),
    (re.compile(r"\bauthentic\b", re.IGNORECASE), "source-bound"),
    (re.compile(r"\btransparency and honesty\b", re.IGNORECASE), "source-bound disclosure"),
    (
        re.compile(r"\bpresent(?:ing)? information with transparency\b", re.IGNORECASE),
        "stating source bounds",
    ),
    (
        re.compile(r"\bclearly and objectively\b", re.IGNORECASE),
        "with source bounds and uncertainty",
    ),
    (re.compile(r"\bstriving for objectivity\b", re.IGNORECASE), "stating source bounds"),
    (re.compile(r"\bwe must\b", re.IGNORECASE), "the method must"),
    (re.compile(r"\bwe can\b", re.IGNORECASE), "the method can"),
    (re.compile(r"\bwe will\b", re.IGNORECASE), "the segment will"),
    (re.compile(r"\bwe aim to\b", re.IGNORECASE), "the method is required to"),
    (re.compile(r"\bwe strive for\b", re.IGNORECASE), "the method requires"),
    (re.compile(r"\bHapax should prioritize\b", re.IGNORECASE), "the source packet requires"),
    (re.compile(r"\bHapax aims to\b", re.IGNORECASE), "the source packet points toward"),
    (
        re.compile(r"\bHapax's segments should strive for\b", re.IGNORECASE),
        "the source packet requires",
    ),
    (
        re.compile(r"\bHapax should acknowledge\b", re.IGNORECASE),
        "the source packet requires acknowledging",
    ),
    (re.compile(r"\bHapax should focus on\b", re.IGNORECASE), "the source packet points toward"),
    (
        re.compile(r"\bHapax should communicate\b", re.IGNORECASE),
        "the source packet requires communicating",
    ),
    (
        re.compile(r"\bHapax should not\b", re.IGNORECASE),
        "the validator rejects claims that Hapax can",
    ),
    (
        re.compile(r"\bHapax should openly acknowledge\b", re.IGNORECASE),
        "the source packet requires acknowledging",
    ),
    (re.compile(r"\bHapax maintains\b", re.IGNORECASE), "the source packet preserves"),
    (re.compile(r"\bHapax must adhere to\b", re.IGNORECASE), "the validator requires"),
    (
        re.compile(
            r"\bwe\s+(?:risk|avoid|uphold|create|maintain|prioritize|incorporate|provide|remain)\b",
            re.IGNORECASE,
        ),
        "the method",
    ),
    (re.compile(r"\bwe\b", re.IGNORECASE), "the method"),
    (re.compile(r"\bour\b", re.IGNORECASE), "the public run's"),
    (re.compile(r"\bus\b", re.IGNORECASE), "the public run"),
    (
        re.compile(r"\bHapax(?:'s)?\s+(?:integrity|trustworthiness|credibility)\b", re.IGNORECASE),
        "the validator receipt",
    ),
    (
        re.compile(r"\bHapax(?:'|’)s non-human identity and purpose\b", re.IGNORECASE),
        "the non-human personage contract",
    ),
    (re.compile(r"\bcredibility\b", re.IGNORECASE), "receipt strength"),
    (re.compile(r"\bintegrity\b", re.IGNORECASE), "contract fit"),
    (re.compile(r"\btrustworthiness\b", re.IGNORECASE), "receipt strength"),
    (re.compile(r"\bcommitment\b", re.IGNORECASE), "runtime obligation"),
    (re.compile(r"\bunbiased\b", re.IGNORECASE), "bounded-source"),
    (
        re.compile(r"\bsense of community and engagement\b", re.IGNORECASE),
        "visible public decision pressure",
    ),
    (re.compile(r"\bsense of community\b", re.IGNORECASE), "visible public decision pressure"),
    (re.compile(r"\bviewer engagement\b", re.IGNORECASE), "public pressure"),
    (re.compile(r"\blasting impact\b", re.IGNORECASE), "inspectable consequence"),
    (re.compile(r"\bcompelling livestream experience\b", re.IGNORECASE), "legible public bit"),
    (
        re.compile(r"\b(?:next-nine|final-nine|the next nine|next nine segments)\b", re.IGNORECASE),
        "pool release",
    ),
    (re.compile(r"\bthe method place\b", re.IGNORECASE), "the method places"),
    (re.compile(r"\bthe method employ\b", re.IGNORECASE), "the method employs"),
    (re.compile(r"\bthe method have\b", re.IGNORECASE), "the method has"),
    (re.compile(r"\bthe method rank\b", re.IGNORECASE), "the method ranks"),
    (re.compile(r"\bthe method don(?:'|’)t\b", re.IGNORECASE), "the method does not"),
    (re.compile(r"\bthe method accepting\b", re.IGNORECASE), "the method accepts"),
    (re.compile(r"\bthe method rigorous\b", re.IGNORECASE), "the method requires rigorous"),
    (
        re.compile(r"\bthe method the contract fit\b", re.IGNORECASE),
        "the method preserves the contract fit",
    ),
    (re.compile(r"\bthe method turn\b", re.IGNORECASE), "the method turns"),
    (re.compile(r"\bthe method(?:'|’)ll\b", re.IGNORECASE), "the method will"),
    (re.compile(r"\bthe method assign\b", re.IGNORECASE), "the method assigns"),
    (re.compile(r"\bthe method enable\b", re.IGNORECASE), "the method enables"),
    (re.compile(r"\bthe method adhere\b", re.IGNORECASE), "the method adheres"),
    (re.compile(r"\bthe method recognize\b", re.IGNORECASE), "the method recognizes"),
    (re.compile(r"\bthe method implement\b", re.IGNORECASE), "the method implements"),
    (re.compile(r"\bthe method consider\b", re.IGNORECASE), "the method considers"),
    (re.compile(r"\bthe method acknowledge\b", re.IGNORECASE), "the method acknowledges"),
    (re.compile(r"\bthe method conclude\b", re.IGNORECASE), "the method concludes"),
    (re.compile(r"\bThe segment engage\b", re.IGNORECASE), "The segment engages"),
    (re.compile(r"\bThe segment ensure\b", re.IGNORECASE), "The segment ensures"),
    (re.compile(r"\bThe segment keep\b", re.IGNORECASE), "The segment keeps"),
    (re.compile(r"\bThe segment consider\b", re.IGNORECASE), "The segment considers"),
    (re.compile(r"\bThe segment review\b", re.IGNORECASE), "The segment reviews"),
    (re.compile(r"\bThe segment turn\b", re.IGNORECASE), "The segment turns"),
    (re.compile(r"\bthe method value\b", re.IGNORECASE), "the method records"),
    (re.compile(r"\bthe method ensure\b", re.IGNORECASE), "the method ensures"),
    (re.compile(r"\bthe method prevent\b", re.IGNORECASE), "the method prevents"),
    (re.compile(r"\bthe method enhance\b", re.IGNORECASE), "the method enhances"),
    (re.compile(r"\bthe method emphasize\b", re.IGNORECASE), "the method emphasizes"),
    (re.compile(r"\bThe segment begin\b", re.IGNORECASE), "The segment begins"),
    (re.compile(r"\bbounded-source source\b", re.IGNORECASE), "bounded-source system"),
)


def _dehost_personage_script(script: list[str]) -> list[str]:
    cleaned: list[str] = []
    for raw in script:
        text = raw
        for pattern, replacement in _DEHOST_REPLACEMENTS:
            text = pattern.sub(replacement, text)
        text = re.sub(
            r"\s*Place Candidate [A-Z][A-Za-z]+ in [SABCD]-tier\.",
            "",
            text,
        )
        text = re.sub(
            r"\s*\[[^\]]*(?:insert|chart|stage)[^\]]*\]\.?", "", text, flags=re.IGNORECASE
        )
        cleaned.append(text)
    return cleaned


def _content_state_target_items(
    prep_content_state: dict[str, Any] | None,
) -> list[dict[str, str]]:
    packets = (
        prep_content_state.get("source_packets") if isinstance(prep_content_state, dict) else None
    )
    if not isinstance(packets, list):
        return []
    items: list[dict[str, str]] = []
    for packet in packets:
        if not isinstance(packet, dict):
            continue
        for raw_item in packet.get("items") or []:
            if not isinstance(raw_item, dict):
                continue
            name = raw_item.get("name") or raw_item.get("item")
            tier = raw_item.get("target_tier") or raw_item.get("tier")
            if isinstance(name, str) and name.strip() and isinstance(tier, str) and tier.strip():
                items.append({"name": name.strip(), "tier": tier.strip()})
    return items


def _enforce_declared_target_phrases(
    script: list[str],
    prep_content_state: dict[str, Any] | None,
    segment_beats: list[str] | None = None,
) -> list[str]:
    items = _content_state_target_items(prep_content_state)
    if not items:
        return script
    updated = list(script)
    expected_beat_by_phrase: dict[str, int] = {}
    if segment_beats:
        for beat_index, direction in enumerate(segment_beats):
            match = _BEAT_ITEM_INDEX_RE.search(str(direction))
            if not match:
                continue
            item_index = int(match.group(1)) - 1
            if 0 <= item_index < len(items):
                item = items[item_index]
                phrase = f"Place {item['name']} in {item['tier']}"
                expected_beat_by_phrase[phrase] = beat_index
    for item_index, item in enumerate(items):
        phrase = f"Place {item['name']} in {item['tier']}"
        beat_index = expected_beat_by_phrase.get(phrase, min(item_index + 1, len(updated) - 1))
        phrase_re = re.compile(r"\b" + re.escape(phrase) + r"\b\.?", flags=re.IGNORECASE)
        item_name = item["name"]
        if not item_name.lower().endswith("s"):
            plural_phrase = f"Place {item_name}s in {item['tier']}"
            plural_phrase_re = re.compile(
                r"\b" + re.escape(plural_phrase) + r"\b\.?",
                flags=re.IGNORECASE,
            )
            updated = [plural_phrase_re.sub("", text).strip() for text in updated]
        for index, text in enumerate(updated):
            if index != beat_index:
                updated[index] = phrase_re.sub("", text).strip()
        if re.search(phrase_re, updated[beat_index]):
            continue
        updated[beat_index] = updated[beat_index].rstrip() + f" {phrase}."
    return updated


def _ensure_public_pressure_line(script: list[str]) -> list[str]:
    updated = list(script)
    if updated and "risk" not in " ".join(updated).lower():
        updated[0] = (
            updated[0].rstrip()
            + " The risk is concrete: a smooth prepared prior can enter the pool "
            "while the receipts still say quarantine."
        )
    if updated and not any(
        token in " ".join(updated).lower() for token in ("remember", "back to", "circle back")
    ):
        updated[-1] = (
            updated[-1].rstrip()
            + " Remember the opening contradiction: loadable does not mean fit."
        )
    if any("Chat pressure:" in beat for beat in updated):
        return updated
    if not script:
        return updated
    updated[-1] = (
        updated[-1].rstrip()
        + " Chat pressure: should pool release stay closed unless every target "
        "placement, source receipt, and pending runtime readback survives review?"
    )
    return updated


def _build_quality_personage_repair_prompt(
    script: list[str],
    programme: Any,
    quality_report: dict[str, Any],
    personage: dict[str, Any],
) -> str:
    role = getattr(getattr(programme, "role", None), "value", "rant")
    content = getattr(programme, "content", None)
    narrative_beat = getattr(content, "narrative_beat", "") or "" if content else ""
    beats = getattr(content, "segment_beats", []) or [] if content else []
    visual_hooks = _ROLE_VISUAL_HOOKS.get(role, "")
    prep_content_state = _render_prep_content_state_prompt_block()
    violations = personage.get("violations") if isinstance(personage, dict) else []
    violation_lines = "\n".join(
        "- beat {beat_index}: {reason} -> {match!r}".format(
            beat_index=item.get("beat_index"),
            reason=item.get("reason"),
            match=item.get("match"),
        )
        for item in violations
        if isinstance(item, dict)
    )
    if not violation_lines:
        violation_lines = "- no personage regex violations; quality repair still required"

    beat_review = ""
    for i, (direction, text) in enumerate(zip(beats, script, strict=False)):
        beat_review += f"\n--- Beat {i + 1} ---\n"
        beat_review += f"Direction: {direction}\n"
        beat_review += f"Draft: {text}\n"

    return (
        "Repair the prepared segment candidate. This is the final resident "
        "Command-R repair pass before quarantine; keep the same beat count and "
        "return spoken prose only.\n\n"
        f"{render_nonhuman_personage_prompt_block()}"
        f"Role: {role}\n"
        f"Topic: {narrative_beat}\n\n"
        f"{prep_content_state}"
        "== CURRENT QUALITY REPORT ==\n"
        f"{json.dumps(quality_report, indent=2, sort_keys=True)}\n\n"
        "== PERSONAGE VIOLATIONS TO REMOVE ==\n"
        f"{violation_lines}\n\n"
        "== HARD REWRITE RULES ==\n"
        "- No first-person host pronouns.\n"
        "- No greetings, temporal host frames, invitations to join, host closers, "
        "or shared-human journey language.\n"
        "- Do not quote forbidden human-host examples; name their category instead.\n"
        "- No objectivity theater: do not claim bias-free, neutral, unbiased, "
        "or beacon-of-objectivity posture.\n"
        "- Every beat must be at least 650 characters and must carry a claim, "
        "source/evidence hook, public consequence, and visible/doable counterpart.\n"
        "- Beat 1 must state the source-bound premise in its first sentence: exact "
        "claim under pressure plus because/but/problem/contradiction/risk language "
        "plus an exact packet id, code path, validator, or receipt.\n"
        "- Specificity means exact packet ids, code paths, validator names, receipt "
        "ids, and source-packet item names; broad `source packet`, `validator`, "
        "`method`, or `segment` wording is not enough.\n"
        "- Use 'Source check:', 'Evidence check:', 'Definition check:', "
        "'Public readback:', 'Visible test:', 'Worked example:', and "
        "'Chat pressure:' exactly when applicable.\n"
        "- For tier-list body beats, include an exact sentence that starts with "
        "'Place ' and matches `Place [item] in [S/A/B/C/D]-tier`.\n"
        "- Do not invent runtime success. Say what the runtime must read back or "
        "what the source packet supports.\n\n"
        "== ROLE VISIBLE HOOKS ==\n"
        f"{visual_hooks}\n"
        "== DRAFT TO REWRITE ==\n"
        f"{beat_review}\n\n"
        "Return ONLY a JSON array of rewritten spoken beats, same count as the "
        "input. No preamble, no markdown fences. Start with [ and end with ]."
    )


def _repair_quality_personage(
    script: list[str],
    programme: Any,
    quality_report: dict[str, Any],
    personage: dict[str, Any],
    *,
    prep_session: dict[str, Any] | None = None,
    programme_id: str = "",
) -> list[str]:
    if _sequential_prep_enabled():
        content = getattr(programme, "content", None)
        beats = getattr(content, "segment_beats", []) or [] if content else []
        repaired: list[str] = []
        for index, text in enumerate(script):
            beat_direction = str(beats[index]) if index < len(beats) else f"beat {index + 1}"
            beat_personage = validate_nonhuman_personage(text)
            repair_reasons = _single_beat_repair_reasons(
                beat=text,
                beat_index=index,
                beat_direction=beat_direction,
                programme=programme,
                personage=beat_personage,
            )
            repair_reasons.append(
                "whole-script quality floor failed; add source fidelity, public pressure, "
                "tension, callback, and visible/doable consequence without host framing"
            )
            repair_prompt = _build_single_beat_repair_prompt(
                beat_text=text,
                beat_index=index,
                beat_direction=beat_direction,
                programme=programme,
                personage=beat_personage,
                repair_reasons=repair_reasons,
            )
            try:
                raw = _call_llm(
                    repair_prompt,
                    prep_session=prep_session,
                    phase="quality_personage_beat_repair",
                    programme_id=programme_id,
                    max_tokens=4096,
                )
            except Exception:
                log.warning(
                    "quality/personage beat repair failed for %s beat %d; "
                    "keeping candidate for final gates",
                    programme_id or "unknown",
                    index + 1,
                    exc_info=True,
                )
                repaired.append(text)
                continue
            beat = _parse_single_beat(raw)
            candidate = beat or text
            candidate_personage = validate_nonhuman_personage(candidate)
            if candidate_personage["ok"] is True and len(candidate) >= max(
                450, int(len(text) * 0.8)
            ):
                repaired.append(candidate)
            else:
                log.warning(
                    "quality/personage beat repair for %s beat %d regressed; "
                    "keeping candidate for final gates",
                    programme_id or "unknown",
                    index + 1,
                )
                repaired.append(text)
        return repaired

    prompt = _build_quality_personage_repair_prompt(
        script,
        programme,
        quality_report,
        personage,
    )
    try:
        raw = _call_llm(
            prompt,
            prep_session=prep_session,
            phase="quality_personage_repair",
            programme_id=programme_id,
        )
        repaired = _parse_script(raw)
        if repaired and len(repaired) >= len(script):
            log.info(
                "quality/personage repair: rewrote %d beats for %s",
                len(script),
                programme_id or "unknown",
            )
            return repaired[: len(script)]
        log.warning(
            "quality/personage repair: got %d beats (expected %d), keeping candidate",
            len(repaired) if repaired else 0,
            len(script),
        )
    except Exception:
        log.warning("quality/personage repair: LLM call failed, keeping candidate", exc_info=True)
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
    content_state_sha256: str | None = None,
) -> dict[str, str]:
    content_state_sha256 = content_state_sha256 or _content_state_sha256(None)
    source_payload = {
        "programme_id": programme_id,
        "role": role,
        "topic": topic,
        "segment_beats": segment_beats,
        "content_state_sha256": content_state_sha256,
    }
    return {
        "programme_sha256": _sha256_json(source_payload),
        "topic_sha256": _sha256_text(str(topic)),
        "segment_beats_sha256": _sha256_json(segment_beats),
        "seed_sha256": seed_sha256,
        "prompt_sha256": prompt_sha256,
        "content_state_sha256": content_state_sha256,
    }


def _content_state_sha256(content_state: dict[str, Any] | None) -> str:
    return _sha256_json(content_state if content_state else None)


def _source_hashes(
    programme: Any,
    *,
    seed: str,
    prompt: str,
    content_state: dict[str, Any] | None,
) -> dict[str, str]:
    content = getattr(programme, "content", None)
    beat_values = getattr(content, "segment_beats", []) or [] if content else []
    return _source_hashes_from_fields(
        programme_id=str(getattr(programme, "programme_id", "unknown")),
        role=str(getattr(getattr(programme, "role", None), "value", "unknown")),
        topic=str(getattr(content, "narrative_beat", "") or "" if content else ""),
        segment_beats=[str(item) for item in beat_values],
        seed_sha256=_sha256_text(seed),
        prompt_sha256=_sha256_text(prompt),
        content_state_sha256=_content_state_sha256(content_state),
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
        personage_diagnostic_name = _programme_artifact_name(
            prog_id,
            suffix=".personage-invalid.json",
        )
        quality_diagnostic_name = _programme_artifact_name(
            prog_id,
            suffix=".quality-invalid.json",
        )
        content_state_diagnostic_name = _programme_artifact_name(
            prog_id,
            suffix=".content-state-invalid.json",
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
    prep_content_state = _prep_content_state_for_prompt()
    prompt = _build_full_segment_prompt(programme, seed)
    source_hashes = _source_hashes(
        programme,
        seed=seed,
        prompt=prompt,
        content_state=prep_content_state,
    )
    if _sequential_prep_enabled():
        script = _compose_script_sequential(
            programme,
            seed=seed,
            prep_session=prep_session,
            programme_id=prog_id,
        )
    else:
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
            "prep_content_state_sha256": source_hashes["content_state_sha256"],
            "source_hashes": source_hashes,
            "source_provenance_sha256": _sha256_json(source_hashes),
            "prep_content_state": prep_content_state,
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
    personage = validate_nonhuman_personage(script)
    if _quality_or_personage_repair_required(quality_report, personage):
        repaired_script = _repair_quality_personage(
            script,
            programme,
            quality_report,
            personage,
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
                if repaired_layout["ok"] is not True and _layout_repair_required(repaired_layout):
                    layout_repaired_script = _repair_layout_actionability(
                        repaired_script,
                        programme,
                        repaired_layout,
                        prep_session=prep_session,
                        programme_id=prog_id,
                    )
                    if layout_repaired_script != repaired_script:
                        layout_repaired_actionability = validate_segment_actionability(
                            layout_repaired_script,
                            [str(item) for item in beats],
                        )
                        if layout_repaired_actionability["ok"] is True:
                            layout_repaired_layout = validate_layout_responsibility(
                                layout_repaired_actionability["beat_action_intents"],
                            )
                            layout_repaired_layout = _with_tier_list_placement_gate(
                                layout_repaired_layout,
                                role=role,
                                segment_beats=segment_beat_strings,
                                beat_action_intents=layout_repaired_actionability[
                                    "beat_action_intents"
                                ],
                            )
                            if layout_repaired_layout["ok"] is True:
                                repaired_script = layout_repaired_script
                                repaired_actionability = layout_repaired_actionability
                                repaired_layout = layout_repaired_layout
                candidate_script = list(repaired_actionability["prepared_script"])
                candidate_quality = score_segment_quality(
                    candidate_script,
                    [str(item) for item in beats],
                )
                candidate_personage = validate_nonhuman_personage(candidate_script)
                current_overall = float(quality_report.get("overall") or 0.0)
                candidate_overall = float(candidate_quality.get("overall") or 0.0)
                if candidate_personage["ok"] is True and (
                    personage.get("ok") is not True or candidate_overall >= current_overall
                ):
                    script = candidate_script
                    actionability = repaired_actionability
                    layout_responsibility = repaired_layout
                    quality_report = candidate_quality
                    personage = candidate_personage
                else:
                    log.warning(
                        "prep_segment: quality/personage repair for %s regressed "
                        "quality or personage; keeping candidate",
                        prog_id,
                    )
            else:
                log.warning(
                    "prep_segment: quality/personage repair for %s introduced unsupported "
                    "action claims; keeping candidate",
                    prog_id,
                )

    dehosted_script = _ensure_public_pressure_line(
        _enforce_declared_target_phrases(
            _dehost_personage_script(script),
            prep_content_state,
            [str(item) for item in beats],
        )
    )
    if dehosted_script != script:
        dehosted_actionability = validate_segment_actionability(
            dehosted_script,
            [str(item) for item in beats],
        )
        if dehosted_actionability["ok"] is True:
            dehosted_layout = validate_layout_responsibility(
                dehosted_actionability["beat_action_intents"],
            )
            dehosted_layout = _with_tier_list_placement_gate(
                dehosted_layout,
                role=role,
                segment_beats=segment_beat_strings,
                beat_action_intents=dehosted_actionability["beat_action_intents"],
            )
            script = list(dehosted_actionability["prepared_script"])
            actionability = dehosted_actionability
            layout_responsibility = dehosted_layout
            quality_report = score_segment_quality(script, [str(item) for item in beats])
            personage = validate_nonhuman_personage(script)
        else:
            log.warning(
                "prep_segment: de-hosting sanitizer introduced unsupported action "
                "claims for %s; keeping candidate",
                prog_id,
            )
    if personage["ok"] is not True:
        log.warning(
            "prep_segment: quarantining %s with non-human personage violations: %s",
            prog_id,
            [item.get("reason") for item in personage["violations"]],
        )
        diagnostic_path = prep_dir / personage_diagnostic_name
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
            "personage_rubric_version": PERSONAGE_RUBRIC_VERSION,
            "personage_alignment": personage,
            "prepped_at": datetime.now(tz=UTC).isoformat(),
            "prep_session_id": prep_session["prep_session_id"],
            "model_id": prep_session["model_id"],
            "prompt_sha256": source_hashes["prompt_sha256"],
            "seed_sha256": source_hashes["seed_sha256"],
            "prep_content_state_sha256": source_hashes["content_state_sha256"],
            "source_hashes": source_hashes,
            "source_provenance_sha256": _sha256_json(source_hashes),
            "prep_content_state": prep_content_state,
            "not_loadable_reason": "non-human personage alignment failed",
        }
        diagnostic["artifact_sha256"] = _artifact_hash(diagnostic)
        tmp = diagnostic_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(diagnostic, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(diagnostic_path)
        return None

    quality_reason = _quality_floor_rejection_reason(quality_report)
    if quality_reason:
        log.warning("prep_segment: quarantining %s: %s", prog_id, quality_reason)
        diagnostic_path = prep_dir / quality_diagnostic_name
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
            "personage_rubric_version": PERSONAGE_RUBRIC_VERSION,
            "personage_alignment": personage,
            "prepped_at": datetime.now(tz=UTC).isoformat(),
            "prep_session_id": prep_session["prep_session_id"],
            "model_id": prep_session["model_id"],
            "prompt_sha256": source_hashes["prompt_sha256"],
            "seed_sha256": source_hashes["seed_sha256"],
            "prep_content_state_sha256": source_hashes["content_state_sha256"],
            "source_hashes": source_hashes,
            "source_provenance_sha256": _sha256_json(source_hashes),
            "prep_content_state": prep_content_state,
            "not_loadable_reason": quality_reason,
        }
        diagnostic["artifact_sha256"] = _artifact_hash(diagnostic)
        tmp = diagnostic_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(diagnostic, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(diagnostic_path)
        return None

    content_state_reason = _content_state_rejection_reason(
        script=script,
        prep_content_state=prep_content_state,
        segment_beats=[str(item) for item in beats],
    )
    if content_state_reason:
        failures = _content_state_target_failures(
            script=script,
            prep_content_state=prep_content_state,
            segment_beats=[str(item) for item in beats],
        )
        log.warning("prep_segment: quarantining %s: %s", prog_id, content_state_reason)
        diagnostic_path = prep_dir / content_state_diagnostic_name
        diagnostic = {
            "schema_version": PREP_ARTIFACT_SCHEMA_VERSION,
            "authority": PREP_ARTIFACT_AUTHORITY,
            "programme_id": prog_id,
            "role": role,
            "topic": getattr(content, "narrative_beat", "") or "",
            "segment_beats": list(beats),
            "prepared_script_candidate": script,
            "content_state_target_failures": failures,
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
            "personage_rubric_version": PERSONAGE_RUBRIC_VERSION,
            "personage_alignment": personage,
            "prepped_at": datetime.now(tz=UTC).isoformat(),
            "prep_session_id": prep_session["prep_session_id"],
            "model_id": prep_session["model_id"],
            "prompt_sha256": source_hashes["prompt_sha256"],
            "seed_sha256": source_hashes["seed_sha256"],
            "prep_content_state_sha256": source_hashes["content_state_sha256"],
            "source_hashes": source_hashes,
            "source_provenance_sha256": _sha256_json(source_hashes),
            "prep_content_state": prep_content_state,
            "not_loadable_reason": content_state_reason,
        }
        diagnostic["artifact_sha256"] = _artifact_hash(diagnostic)
        tmp = diagnostic_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(diagnostic, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(diagnostic_path)
        return None

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
            "personage_rubric_version": PERSONAGE_RUBRIC_VERSION,
            "personage_alignment": personage,
            "prepped_at": datetime.now(tz=UTC).isoformat(),
            "prep_session_id": prep_session["prep_session_id"],
            "model_id": prep_session["model_id"],
            "prompt_sha256": source_hashes["prompt_sha256"],
            "seed_sha256": source_hashes["seed_sha256"],
            "prep_content_state_sha256": source_hashes["content_state_sha256"],
            "source_hashes": source_hashes,
            "source_provenance_sha256": _sha256_json(source_hashes),
            "prep_content_state": prep_content_state,
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
        "personage_rubric_version": PERSONAGE_RUBRIC_VERSION,
        "hosting_context": layout_responsibility["hosting_context"],
        "segment_quality_report": quality_report,
        "personage_alignment": personage,
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
        "prep_content_state_sha256": source_hashes["content_state_sha256"],
        "source_hashes": source_hashes,
        "source_provenance_sha256": _sha256_json(source_hashes),
        "prep_content_state": prep_content_state,
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

    # Pass 3: self-evaluation -> emit impingement.
    # This is how selection pressure updates: scored output flows through
    # the impingement bus into the narrative drive's Bayesian prior.
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


def _planner_content_state_from_env() -> dict[str, Any] | None:
    raw = os.environ.get("HAPAX_SEGMENT_PREP_CONTENT_STATE_JSON", "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("daily_segment_prep: invalid HAPAX_SEGMENT_PREP_CONTENT_STATE_JSON")
        else:
            if isinstance(parsed, dict) and parsed:
                return parsed

    focus = os.environ.get("HAPAX_SEGMENT_PREP_FOCUS", "").strip()
    candidates = [
        item.strip()
        for item in os.environ.get("HAPAX_SEGMENT_PREP_TOPIC_CANDIDATES", "").split("|")
        if item.strip()
    ]
    source_refs = [
        item.strip()
        for item in os.environ.get("HAPAX_SEGMENT_PREP_SOURCE_REFS", "").split("|")
        if item.strip()
    ]
    if not (focus or candidates or source_refs):
        return None
    return {
        "focus": focus or None,
        "topic_candidates": candidates,
        "source_refs": source_refs,
        "grounding_instruction": (
            "Select only topics that can be grounded from these candidates/source refs. "
            "If a candidate is too thin, produce no programme rather than a generic segment."
        ),
    }


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
        "candidate_cap": MAX_SEGMENTS,
        "accepted_count_is_outcome": True,
        "quality_budget_s": PREP_BUDGET_S,
        "existing_manifest_programmes": existing_manifest_names,
        "llm_calls": [],
    }
    _update_prep_status(prep_session, status="in_progress", phase="resident_model_check")
    try:
        _assert_resident_prep_model(prep_session["model_id"])
        prep_session["resident_model_verified"] = prep_session["model_id"]
    except Exception as exc:
        _update_prep_status(
            prep_session,
            status="failed",
            phase="resident_model_check_failed",
            last_error=f"{type(exc).__name__}: {exc}",
        )
        raise

    # Step 1: Plan — call the planner in rounds until we have candidate
    # programmes to spend the prep budget on.  MAX_SEGMENTS is a run cap,
    # not an accepted-artifact target.
    log.info(
        "daily_segment_prep: planning programme candidates (candidate_cap=%d)...", MAX_SEGMENTS
    )
    segmented: list[Any] = []
    seen_ids: set[str] = set(existing_programme_ids)
    plan_round = 0
    max_rounds = 1 if MAX_SEGMENTS == 1 else (MAX_SEGMENTS // 2) + 2
    planner_candidate_cap = 1 if MAX_SEGMENTS == 1 else None
    planner_content_state = _planner_content_state_from_env()
    _update_prep_status(
        prep_session,
        status="in_progress",
        phase="planning_start",
        max_rounds=max_rounds,
        planner_candidate_cap=planner_candidate_cap,
        planner_content_state=planner_content_state,
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
                candidate_cap=planner_candidate_cap,
                working_mode="daily_segment_prep",
                content_state=planner_content_state,
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


def _quality_report_rejection_reason(data: dict[str, Any]) -> str | None:
    if data.get("segment_quality_rubric_version") != QUALITY_RUBRIC_VERSION:
        return "unsupported segment quality rubric"
    report = data.get("segment_quality_report")
    if not isinstance(report, dict):
        return "missing segment quality report"
    script = data.get("prepared_script")
    beats = data.get("segment_beats")
    if not isinstance(script, list) or not all(isinstance(item, str) for item in script):
        return "invalid prepared_script"
    if not isinstance(beats, list) or not all(isinstance(item, str) for item in beats):
        return "invalid segment_beats"
    recomputed = score_segment_quality(script, beats)
    if not _json_equal(report, recomputed):
        return "segment quality report does not match script"
    return _quality_floor_rejection_reason(recomputed)


def _content_state_artifact_rejection_reason(data: dict[str, Any]) -> str | None:
    script = data.get("prepared_script")
    if not isinstance(script, list) or not all(isinstance(item, str) for item in script):
        return "invalid prepared_script"
    prep_content_state = data.get("prep_content_state")
    if prep_content_state is not None and not isinstance(prep_content_state, dict):
        return "invalid prep content state"
    return _content_state_rejection_reason(
        script=script,
        prep_content_state=prep_content_state,
        segment_beats=_string_list(data.get("segment_beats")),
    )


def _actionability_rejection_reason(data: dict[str, Any]) -> str | None:
    if data.get("actionability_rubric_version") != ACTIONABILITY_RUBRIC_VERSION:
        return "unsupported actionability rubric"

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


def _personage_rejection_reason(data: dict[str, Any]) -> str | None:
    if data.get("personage_rubric_version") != PERSONAGE_RUBRIC_VERSION:
        return "unsupported personage rubric"
    script = data.get("prepared_script")
    if not isinstance(script, list) or not all(isinstance(item, str) for item in script):
        return "invalid prepared_script"
    validation = validate_nonhuman_personage(script)
    if validation["ok"] is not True:
        return "non-human personage alignment failed"
    stored = data.get("personage_alignment")
    if not isinstance(stored, dict):
        return "missing personage alignment"
    if stored.get("ok") is not True:
        return "personage alignment failed"
    if not _json_equal(stored, validation):
        return "personage alignment does not match script"
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
    quality_reason = _quality_report_rejection_reason(data)
    if quality_reason:
        return quality_reason
    content_state_reason = _content_state_artifact_rejection_reason(data)
    if content_state_reason:
        return content_state_reason
    personage_reason = _personage_rejection_reason(data)
    if personage_reason:
        return personage_reason
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
        "content_state_sha256",
    ):
        if not _is_sha256_hex(source_hashes.get(key)):
            return f"missing source hash {key}"
    if source_hashes.get("seed_sha256") != data.get("seed_sha256") or source_hashes.get(
        "prompt_sha256"
    ) != data.get("prompt_sha256"):
        return "source hash mismatch"
    prep_content_state_sha256 = data.get("prep_content_state_sha256")
    if (
        not _is_sha256_hex(prep_content_state_sha256)
        or prep_content_state_sha256 != source_hashes.get("content_state_sha256")
        or prep_content_state_sha256 != _content_state_sha256(data.get("prep_content_state"))
    ):
        return "content state hash mismatch"
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
        content_state_sha256=prep_content_state_sha256,
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
    runtime_personage = validate_nonhuman_personage(list(data["prepared_script"]))
    if runtime_personage["ok"] is not True:
        return None, "runtime personage alignment failed"
    if not _json_equal(data.get("personage_alignment"), runtime_personage):
        return None, "personage alignment does not match script"

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
    data["runtime_personage_validation"] = {
        "rubric_version": PERSONAGE_RUBRIC_VERSION,
        "ok": runtime_personage["ok"],
        "violations": runtime_personage["violations"],
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
