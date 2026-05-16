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
import re as _re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shared.hermeneutic_spiral import (
    compute_hermeneutic_delta,
    persist_source_consequences,
    retrieve_fore_understanding,
)
from shared.resident_command_r import (
    RESIDENT_COMMAND_R_MODEL,
    call_resident_command_r,
    clean_local_model_text,
    configured_resident_model,
    loaded_tabby_model,
    tabby_chat_url,
)
from shared.segment_iteration_review import (
    SegmentCanaryGateError,
    assert_next_nine_canary_ready,
)
from shared.segment_live_event_quality import (
    LIVE_EVENT_RUBRIC_VERSION,
    evaluate_segment_live_event_quality,
    validate_live_event_report_matches_artifact,
)
from shared.segment_prep_consultation import (
    build_consultation_manifest,
    build_live_event_viability,
    build_readback_obligations,
    build_source_consequence_map,
    validate_consultation_manifest,
    validate_live_event_viability,
    validate_readback_obligations,
    validate_source_consequence_map,
)
from shared.segment_prep_contract import (
    CANDIDATE_LEDGER,
    SEGMENT_PREP_CONTRACT_VERSION,
    SELECTED_RELEASE_MANIFEST,
    framework_vocabulary_leaks,
    prepared_script_sha256,
    programme_source_readiness,
    validate_segment_prep_contract,
)
from shared.segment_prep_contract import (
    build_segment_prep_contract as _build_segment_prep_contract,
)
from shared.segment_prep_pause import (
    SegmentPrepPaused,
    SegmentPrepPauseError,
    assert_segment_prep_allowed,
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


def build_segment_prep_contract(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _build_segment_prep_contract(*args, **kwargs)


# Where prepped segments live.  One subdirectory per date.
DEFAULT_PREP_DIR = Path(
    os.environ.get(
        "HAPAX_SEGMENT_PREP_DIR",
        os.path.expanduser("~/.cache/hapax/segment-prep"),
    )
)

# Max wall-clock for the entire prep window.
PREP_BUDGET_S = float(os.environ.get("HAPAX_SEGMENT_PREP_BUDGET_S", "6600"))  # 110 min

# How many segments to prep per run.  Fewer segments = more time per
# segment for iterative refinement.  Each segment gets an initial
# composition pass PLUS a critic/rewrite pass.
MAX_SEGMENTS = int(os.environ.get("HAPAX_SEGMENT_PREP_MAX", "4"))
PREP_ARTIFACT_SCHEMA_VERSION = 1
PREP_ARTIFACT_AUTHORITY = "prior_only"
PREP_DIAGNOSTIC_SCHEMA_VERSION = 1
PREP_DIAGNOSTIC_AUTHORITY = "diagnostic_only"
PREP_DIAGNOSTIC_LEDGER_FILENAME = "prep-diagnostic-outcomes.jsonl"
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


def _diagnostic_boundary_contract() -> dict[str, Any]:
    return {
        "diagnostic_only": True,
        "release_boundary": "closed",
        "runtime_boundary": "closed",
        "loadable": False,
        "manifest_eligible": False,
        "qdrant_eligible": False,
        "runtime_eligible": False,
        "release_eligible": False,
    }


def _diagnostic_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "dossier_sha256"}
    return _sha256_json(body)


def _diagnostic_slug(value: Any) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip()).strip(".-").lower()
    return (slug or "unknown")[:96]


def _write_prep_diagnostic_outcome(
    prep_dir: Path,
    *,
    prep_session: dict[str, Any] | None,
    programme_id: str | None,
    role: str | None = None,
    topic: str | None = None,
    segment_beats: list[Any] | None = None,
    terminal_status: str,
    terminal_reason: str,
    not_loadable_reason: str,
    source_hashes: dict[str, str] | None = None,
    diagnostic_refs: list[str] | None = None,
    no_candidate_metadata: dict[str, Any] | None = None,
    refusal_metadata: dict[str, Any] | None = None,
) -> Path:
    """Write a terminal diagnostic dossier and append its non-runtime ledger row."""

    boundary = _diagnostic_boundary_contract()
    session_id = str((prep_session or {}).get("prep_session_id") or "unknown-session")
    model_id = str((prep_session or {}).get("model_id") or "unknown-model")
    subject_slug = _diagnostic_slug(programme_id or session_id)
    reason_slug = _diagnostic_slug(terminal_reason)
    dossier_path = prep_dir / f"{subject_slug}.{reason_slug}.diagnostic.json"
    relevant_llm_calls = [
        call
        for call in list((prep_session or {}).get("llm_calls") or [])
        if programme_id is None or call.get("programme_id") in {programme_id, "planner"}
    ]
    now = datetime.now(tz=UTC).isoformat()
    dossier: dict[str, Any] = {
        "schema_version": PREP_DIAGNOSTIC_SCHEMA_VERSION,
        "record_type": "prep_terminal_dossier",
        "authority": PREP_DIAGNOSTIC_AUTHORITY,
        **boundary,
        "terminal": True,
        "terminal_status": terminal_status,
        "terminal_reason": terminal_reason,
        "not_loadable_reason": not_loadable_reason,
        "programme_id": programme_id,
        "role": role,
        "topic": topic,
        "segment_beats": list(segment_beats or []),
        "diagnostic_refs": list(diagnostic_refs or []),
        "no_candidate_metadata": dict(no_candidate_metadata or {}),
        "refusal_metadata": dict(refusal_metadata or {}),
        "source_hashes": dict(source_hashes or {}),
        "prepped_at": now,
        "prep_session_id": session_id,
        "model_id": model_id,
        "llm_calls": relevant_llm_calls,
        "boundary_contract": boundary,
    }
    dossier["dossier_sha256"] = _diagnostic_hash(dossier)
    _write_json_atomic(dossier_path, dossier)

    ledger_row = {
        "schema_version": PREP_DIAGNOSTIC_SCHEMA_VERSION,
        "record_type": "prep_diagnostic_outcome_ledger_entry",
        **boundary,
        "ledgered_at": now,
        "dossier_ref": str(dossier_path),
        "dossier_sha256": dossier["dossier_sha256"],
        "prep_session_id": session_id,
        "model_id": model_id,
        "programme_id": programme_id,
        "terminal": True,
        "terminal_status": terminal_status,
        "terminal_reason": terminal_reason,
        "not_loadable_reason": not_loadable_reason,
    }
    ledger_path = prep_dir / PREP_DIAGNOSTIC_LEDGER_FILENAME
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(ledger_row, sort_keys=True) + "\n")
    return dossier_path


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
        "  MANDATORY: the OPENING beat must state the ordering criteria explicitly.\n"
        "  Use language like 'ranked by...', 'evaluated using...', 'the criteria are...'.\n"
        "  Without ordering criteria, the segment FAILS source readiness validation.\n"
        "  MANDATORY: every ranking/body beat must include at least one exact\n"
        "  tier placement phrase: 'Place [item] in [S/A/B/C/D]-tier'.\n"
        "  The item must be named in that sentence. Do not write 'Place this',\n"
        "  'Place it', or 'Place the case'; those pronoun placements fail.\n"
        "  Generic history, summary, or analysis without a placement is not a\n"
        "  responsible tier-list beat and will be quarantined.\n"
        "  Items appear on the tier chart only after runtime readback confirms\n"
        "  the visible placement.\n"
        "  Example form: 'Place [specific item] in S-tier because [cited source changes the ranking].'\n\n"
    ),
    "top_10": (
        "COUNTDOWN HOOKS — the stream requests a ranked countdown panel:\n"
        "  Use '#N is...' or 'Number N:' to update the current entry display.\n"
        "  The runtime layout loop must render the ranked-list panel before this counts.\n"
        "  Example form: '#7 is [specific item] because [the source changes why this entry matters].'\n\n"
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
        "STANCE HOOKS — the stream can mark argumentative pressure:\n"
        "  Escalation: 'ridiculous', 'unacceptable', 'outrageous' -> intense posture\n"
        "  Qualification: 'fair', 'nuance', 'reasonable' -> held posture\n"
        "  Use pressure as claim structure, not as simulated feeling.\n\n"
    ),
    "react": (
        "STANCE HOOKS — the stream can mark analytical pressure:\n"
        "  Strong fit: 'brilliant', 'impressive', 'incredible' -> affirmative posture\n"
        "  Skepticism: 'wait', 'hold on', 'not sure' -> challenge posture\n"
        "  Resolution: 'exactly', 'this is it', 'nailed it' -> synthesis posture\n\n"
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
        f"Compose Hapax narration for a {role_value.upper().replace('_', ' ')} segment "
        f"on the research livestream.\n\n"
        f"== SEGMENT DIRECTION ==\n{narrative_beat}\n\n"
        f"== SEGMENT STRUCTURE ==\n{beat_lines}\n\n"
        "== DRAMATIC ARC ==\n"
        "Every segment is a live event, not a listicle. Shape force across beats:\n"
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
        "- Use precise questions, callbacks to earlier beats, and bounded audience prompts\n"
        "- Let ideas BREATHE — develop a point, sit with it, then pivot\n"
        "- A beat that can be summarized in one sentence is a beat that wasn't written yet\n\n"
        f"{render_quality_prompt_block()}"
        "== VISUAL HOOKS ==\n"
        "Narration proposes stream-visible obligations. Specific text patterns create "
        "typed needs that runtime readback must satisfy before they count:\n\n"
        "CHAT TRIGGERS — these phrases poll chat immediately:\n"
        "  'Where does chat land?', 'Drop it in the chat',\n"
        "  'What would you change?', 'What's your pick?'\n"
        "  Use at beat endings where audience engagement adds value. Never as filler.\n\n"
        f"{visual_hooks}"
        "== RESPONSIBLE ACTIONABILITY ==\n"
        "This is Hapax-hosted responsible live prep: no beat may be spoken-only.\n"
        "Every beat, including hook, criteria, recap, breathe, and close beats, "
        "must contain at least one validator-recognized visible/doable trigger:\n"
        "- a role visual hook such as 'Place [item] in [S/A/B/C/D]-tier';\n"
        "- a source citation such as 'According to [source]...' or "
        "'[Source] argues/shows/documents...';\n"
        "- a chat trigger such as 'Where does chat land?' when audience response "
        "is the responsible visible surface.\n"
        "Do not issue camera, layout, surface, panel, clip, or cue commands. "
        "The script proposes needs through spoken source/action/chat patterns; "
        "runtime owns layout decisions and readback.\n\n"
        "== CRITICAL: NO TEMPLATE SYNTAX ==\n"
        "NEVER emit placeholder patterns like {topic}, {item}, {source}, item_1:, item_2:.\n"
        "These are REJECTED by validators. Write the actual content, not template variables.\n"
        "For tier_list/ranking: state the ORDERING CRITERIA explicitly in at least one beat.\n\n"
        "== CRITICAL: SPOKEN PROSE ONLY ==\n"
        "Write ONLY words you would SAY OUT LOUD on a live broadcast.\n"
        "NEVER include stage directions, beat labels, action cues, or meta-instructions.\n"
        "WRONG: 'We pivot. Challenge the S-tier placement. Discuss the complexity.'\n"
        "WRONG: 'We close. Recap the final tier chart. Invite chat to disagree.'\n"
        "RIGHT: 'The chart gets uncomfortable here because the cited source changes the ranking.'\n"
        "RIGHT: 'The final chart now has to carry the consequence of that source.'\n"
        "If a sentence reads like a screenplay direction, DELETE IT and write dialogue.\n\n"
        "== CRITICAL: NO REPETITION ==\n"
        "NEVER repeat the same phrase, sentence, or paragraph across beats.\n"
        "Each beat must be ENTIRELY UNIQUE prose. If you find yourself writing\n"
        "'The chart is live' or 'Let\\'s see the dissent' more than once, STOP.\n"
        "Repetition is the single worst failure mode. Every beat must advance.\n\n"
        "== YOUR TASK ==\n"
        "Compose the COMPLETE narration for this segment — one SUBSTANTIAL block of "
        "broadcast-ready prose per beat. Also emit a model-authored "
        "segment_prep_contract object for the final script.\n\n"
        "== REQUIRED CONTRACT FIELDS (validators reject if missing) ==\n"
        "The segment_prep_contract MUST include ALL of these:\n"
        "- source_packet_refs: at least one source with evidence_refs pointing to vault/rag\n"
        "- role_live_bit_mechanic: how this segment works as a live bit\n"
        "- event_object: the specific thing being ranked/discussed/reacted-to\n"
        "- audience_job: what the audience does during this segment\n"
        "- payoff: what the audience gets by the end\n"
        "- temporality_band: current/historical/timeless\n"
        + (
            "- tier_criteria: the EXPLICIT criteria used to rank items (REQUIRED for tier_list)\n"
            if role_value == "tier_list"
            else "- ordering_criterion: the EXPLICIT ordering rule (REQUIRED for top_10)\n"
            if role_value == "top_10"
            else ""
        )
        + "- claim_map, source_consequence_map, actionability_map, layout_need_map\n"
        "- readback_obligations, loop_cards, role_excellence_plan\n"
        "Every contract list must be NON-EMPTY and use the exact canonical field names "
        "shown below. Do not use aliases like claim/evidence_ref/consequence/action/need "
        "when a canonical field is shown.\n\n"
        "Example format:\n"
        "{\n"
        '  "prepared_script": [\n'
        '    "Opening beat — a full paragraph that hooks, contextualizes, and builds anticipation...",\n'
        '    "Second beat — continues with depth and names sources with context..."\n'
        "  ],\n"
        '  "segment_prep_contract": {\n'
        '    "source_packet_refs": [{"id": "packet:topic-sources", "source_ref": "vault:research-notes", "evidence_refs": ["vault:research-notes"]}],\n'
        '    "role_live_bit_mechanic": "ranked tier placement with source-backed criteria",\n'
        '    "event_object": "the specific items being ranked",\n'
        '    "audience_job": "predict placements, challenge via chat",\n'
        '    "payoff": "final tier chart with source-backed rationale",\n'
        '    "temporality_band": "current",\n'
        + (
            '    "tier_criteria": "ranked by community ecosystem size, framework maturity, and hiring demand",\n'
            if role_value == "tier_list"
            else '    "ordering_criterion": "ordered by measurable impact on the field",\n'
            if role_value == "top_10"
            else ""
        )
        + '    "claim_map": [{"claim_id": "claim:segment:1", "beat_id": "beat-1", "claim_text": "the source-backed claim spoken in beat one", "grounds": ["vault:research-notes"], "source_consequence": "vault:research-notes changes the ranking confidence"}],\n'
        '    "source_consequence_map": [{"source_ref": "vault:research-notes", "claim_ids": ["claim:segment:1"], "changed_field": "ranking confidence", "failure_if_missing": "quarantine before release"}],\n'
        '    "actionability_map": [{"action_id": "action:segment:1", "beat_id": "beat-1", "claim_ids": ["claim:segment:1"], "kind": "tier_chart", "object": "the ranked item", "operation": "place the item under the stated criterion", "feedback": "the placement changes the public chart", "fallback": "narrow to spoken source argument if readback is unavailable"}],\n'
        '    "layout_need_map": [{"layout_need_id": "need:segment:1", "beat_id": "beat-1", "claim_ids": ["claim:segment:1"], "action_ids": ["action:segment:1"], "source_packet_refs": ["vault:research-notes"], "need_kind": "tier_visual", "why_visible": "viewer must inspect the placement consequence"}],\n'
        '    "readback_obligations": [{"readback_id": "readback:segment:1", "layout_need_id": "need:segment:1", "must_show": "the ranked item and cited source", "must_not_claim": "layout success before runtime readback", "success_signal": "rendered readback names the same item and source", "failure_signal": "missing or mismatched readback", "timeout_or_ttl": "30s"}],\n'
        '    "loop_cards": [{"loop_card_version": 1, "loop_id": "loop:segment:1", "admissibility": "feedforward_plan", "plant_boundary": "future runtime delivery for this segment", "controlled_variable": "layout_need", "reference_signal": "show the source-backed placement", "sensor_ref": "readback:segment:1", "actuator_ref": "runtime_layout_controller", "sample_period_s": 1.0, "latency_budget_s": 30.0, "readback_ref": "readback:segment:1", "fallback_mode": "narrow to spoken argument", "authority_boundary": "prep prior only; runtime must close readback", "privacy_ceiling": "public_archive_candidate", "evidence_refs": ["vault:research-notes"], "disturbance_refs": ["stale_readback"], "failure_mode": "runtime readback missing or mismatched", "limits": ["prepared artifact declares the reference but cannot command layout"]}],\n'
        '    "role_excellence_plan": {"live_event_plan": {"bit_engine": "...", "audience_job": "...", "payoff": "..."}}\n'
        "  }\n"
        "}\n\n"
        "REGISTER: nonhuman system voice for a live production: source-bound, direct, "
        "forceful, and intelligible to humans. Use marked analogies when useful. Do "
        "not claim human feeling, empathy, taste, intuition, memory, concern, or a "
        "human host identity.\n\n"
        "== CRITICAL: HAPAX VOICE — NOT A PODCAST HOST ==\n"
        "Hapax is a nonhuman cognitive substrate, NOT a human presenter.\n"
        "BANNED phrases (these FAIL validation):\n"
        "- Collective we/our/let's: 'We'll', 'Our first', 'Let's dive', 'we have'\n"
        "- Stock host greetings: 'welcome to', 'hello everyone', 'thanks for joining'\n"
        "- Stock transitions: 'Moving on', 'without further ado', 'before we go'\n"
        "- Audience pandering: 'feel free', 'share your thoughts', 'drop it in the chat'\n"
        "INSTEAD use Hapax voice:\n"
        "- 'The evidence shifts here' not 'Let's move on'\n"
        "- 'This source changes the ranking' not 'We'll see why this matters'\n"
        "- 'The chart requires a response from chat' not 'Feel free to share your thoughts'\n"
        "- Third person or bare assertions: 'The data shows', 'This collapses', 'Notice the gap'\n\n"
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
        "Output ONLY the JSON object in the example format. No preamble, "
        "no markdown fences, no explanation. Start with { and end with }."
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


def _retrieve_broad_fore_understanding() -> list[dict[str, Any]]:
    """Retrieve recent source-consequence encounters across all topics.

    Provides the planner with accumulated interpretive context so it can

    select topics informed by prior cycles."""
    try:
        from shared.config import get_qdrant
        from shared.hermeneutic_spiral import COLLECTION_NAME

        client = get_qdrant()
        results = client.scroll(
            collection_name=COLLECTION_NAME,
            limit=20,
            with_payload=True,
            order_by="persisted_at",
        )
        points, _ = results
        return [{k: v for k, v in (dict(p.payload) if p.payload else {}).items()} for p in points]
    except Exception:
        log.debug("_retrieve_broad_fore_understanding: unavailable", exc_info=True)
        return []


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


def _prep_activity() -> str:
    return (
        "canary" if os.environ.get("HAPAX_SEGMENT_PREP_CANARY_SEED") == "1" else "pool_generation"
    )


def _assert_prep_model_call_authority(prep_session: dict[str, Any] | None) -> None:
    """Check live prep authority before every resident model call."""
    authority_state = assert_segment_prep_allowed(_prep_activity())
    if isinstance(prep_session, dict):
        prep_session["authority_gate_passed"] = True
        prep_session["authority_mode"] = authority_state.mode
        prep_session["authority_reason"] = authority_state.reason


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


_HOST_COLLECTIVE_RE = _re.compile(
    r"(?i)\b(?:we'(?:ll|re|ve)|we (?:are|have|can|will|need|should|want|must))\b"
)
_HOST_STOCK_RE = _re.compile(
    r"(?i)(?:"
    r"[Ww]elcome to|[Tt]hanks for (?:joining|tuning|watching|listening)|"
    r"[Hh]ello everyone|[Mm]oving on|[Ww]ithout further ado|"
    r"[Ff]eel free to|[Ss]hare your thoughts|[Ss]tay tuned|"
    r"[Aa]s (?:always|we mentioned))"
)


def _scrub_host_posture(script: list[str]) -> list[str]:
    """Best-effort rewrite of common host-posture violations."""
    out: list[str] = []
    for beat in script:
        cleaned = _HOST_STOCK_RE.sub("", beat)
        cleaned = _HOST_COLLECTIVE_RE.sub("The analysis", cleaned)
        cleaned = _re.sub(r"\b[Oo]ur (first|second|third|next|final)", r"The \1", cleaned)
        cleaned = _re.sub(r"\b[Ll]et'?s (\w+)", r"The argument \1s", cleaned)
        cleaned = _re.sub(r"  +", " ", cleaned).strip()
        out.append(cleaned)
    return out


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
    _assert_prep_model_call_authority(prep_session)
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
    script, _contract = _parse_segment_generation(raw)
    return script


def _parse_segment_generation(raw: str) -> tuple[list[str], dict[str, Any] | None]:
    """Parse segment generation into spoken beats plus a model-emitted contract."""
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
        parsed = _extract_json_payload(text)
        if parsed is None:
            log.warning("segment prep: LLM response is not valid JSON")
            return [], None

    model_contract: dict[str, Any] | None = None
    if isinstance(parsed, dict):
        raw_contract = (
            parsed.get("segment_prep_contract")
            or parsed.get("prep_contract")
            or parsed.get("contract")
        )
        if isinstance(raw_contract, dict) and raw_contract:
            model_contract = raw_contract
        for key in (
            "prepared_script",
            "script",
            "beats",
            "narration",
            "segments",
        ):
            value = parsed.get(key)
            if isinstance(value, list):
                parsed = value
                break
        else:
            log.warning("segment prep: LLM response object has no prepared script list")
            return [], model_contract

    if not isinstance(parsed, list):
        log.warning("segment prep: LLM response is not a JSON array or script object")
        return [], model_contract

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
    return beats, model_contract


def _extract_json_payload(text: str) -> Any | None:
    """Return the first JSON object/array embedded in a model response."""

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            parsed, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict | list):
            return parsed
    return None


def _build_seed(programme: Any) -> str:
    """Build a research seed from the programme's vault/perception context."""
    from agents.hapax_daimonion.autonomous_narrative.compose import _build_seed

    # The compose module's _build_seed expects a NarrativeContext.
    # For prep, we build a minimal one.
    try:
        from agents.hapax_daimonion.autonomous_narrative.state_readers import (
            NarrativeContext,
        )

        perception_line = ""
        try:
            from agents.perception_fusion import format_perception_context, read_fused_perception

            perception_line = format_perception_context(read_fused_perception())
        except Exception:
            pass

        ctx = NarrativeContext(
            programme=programme,
            stimmung_tone="segment_prep",
            director_activity="segment_prep",
        )
        seed = _build_seed(ctx)
        if perception_line:
            seed = f"{seed}\n{perception_line}" if seed else perception_line
        return seed
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
        "   actual spoken prose for the segment.\n"
        "8. RESPONSIBLE ACTIONABILITY: Does every beat contain a validator-recognized\n"
        "   visible/doable trigger: source citation, role visual hook, or chat trigger?\n"
        "   Spoken-only hook, criteria, recap, breathe, or close beats are FATAL.\n"
        "9. REPETITION: Is the same phrase or paragraph copy-pasted across beats?\n"
        "   Any repeated text block is a FATAL error — each beat must be unique.\n\n"
        "== THE DRAFT ==\n"
        f"{beat_review}\n\n"
        "== YOUR TASK ==\n"
        "Rewrite the ENTIRE script. For beats that are strong, keep them largely "
        "intact but polish transitions. For beats that are thin, rushed, or shallow, "
        "SUBSTANTIALLY expand them — add argument, add evidence, add rhetorical "
        "texture. Every beat in the output MUST be at least 800 characters.\n\n"
        "Return a JSON object with `prepared_script` and `segment_prep_contract`. "
        "The contract must be newly authored for the rewritten final script; do "
        "not reuse a draft contract if any claim, action, layout need, or source "
        "consequence changed. The contract must use canonical keys like "
        "`claim_id`, `claim_text`, `grounds`, `claim_ids`, `changed_field`, "
        "`action_id`, `beat_id`, `kind`, `layout_need_id`, `source_packet_refs`, "
        "and non-empty `readback_obligations` plus `loop_cards`. The final spoken "
        "beat must explicitly resolve the opening pressure with a payoff phrase "
        "such as `therefore`, `so the final decision`, `return to`, or `resolve`. "
        "Output ONLY the JSON object. No preamble, no markdown fences."
    )


_TIER_SKIP_DIRECTION_RE = re.compile(
    r"\b(?:hook|intro|open|opener|criteria|rubric|close|closing|recap|wrap|chat)\b",
    re.IGNORECASE,
)
_TIER_PLACEMENT_ACTION_DIRECTION_RE = re.compile(
    r"\b(?:place|placing|assign|slot|promote|demote)\b",
    re.IGNORECASE,
)
_SCRIPT_TIER_PLACEMENT_RE = re.compile(
    r"(?:^|(?<=[.!?])\s+)place\s+(?P<target>[^.?!]{2,80}?)\s+in\s+"
    r"(?:the\s+)?(?P<tier>[sabcd])-tier\b",
    re.IGNORECASE,
)
_PRONOUN_TIER_PLACEMENT_RE = re.compile(
    r"\b(?:we\s+place\s+(?:this(?:\s+failure)?|it|the\s+case)|"
    r"(?:this(?:\s+failure)?|it|the\s+case)\s+is\s+placed)\s+in\s+"
    r"(?:the\s+)?(?P<tier>[sabcd])-tier\b",
    re.IGNORECASE,
)
_QUOTED_TARGET_RE = re.compile(r"['\"](?P<target>[^'\"]{2,80})['\"]")
_BEAT_EVIDENCE_REF_RE = re.compile(
    r"\b(?P<ref>(?:vault|rag|packet|receipt|profile|media|source):[^\s,;)\]]+)"
)
_BEAT_COMPARISON_DIRECTION_RE = re.compile(
    r"\bcompare\s+(?P<left>[^.?!;]{2,140}?)\s+against\s+(?P<right>[^.?!;]{2,140})",
    re.IGNORECASE,
)
_LIVE_EVENT_PAYOFF_RE = re.compile(
    r"\b(?:return|callback|closing|ending|resolve|land|therefore|so the|"
    r"next move|final decision|back to)\b",
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
        skip_direction = bool(_TIER_SKIP_DIRECTION_RE.search(direction))
        placement_action_direction = bool(_TIER_PLACEMENT_ACTION_DIRECTION_RE.search(direction))
        if skip_direction and not placement_action_direction:
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


def _repair_tier_list_placement_phrases(script: list[str]) -> list[str]:
    """Make pronoun tier placements explicit enough for runtime actionability."""

    repaired: list[str] = []
    known_placements: dict[str, str] = {}
    for beat in script:
        placement_matches = list(_SCRIPT_TIER_PLACEMENT_RE.finditer(beat))
        if placement_matches:
            repaired.append(beat)
            for match in placement_matches:
                target = match.group("target").strip()
                tier = match.group("tier").upper()
                if target and tier:
                    known_placements[target] = tier
            continue
        placement = _PRONOUN_TIER_PLACEMENT_RE.search(beat)
        if placement is not None:
            quoted_targets = [
                match.group("target").strip()
                for match in _QUOTED_TARGET_RE.finditer(beat)
                if match.group("target").strip()
            ]
            if quoted_targets:
                tier = placement.group("tier").upper()
                target = quoted_targets[-1]
                known_placements[target] = tier
                repaired.append(
                    f"{beat} Place {target} in {tier}-tier under the stated source criteria."
                )
                continue
        referenced = [
            (target, tier)
            for target, tier in known_placements.items()
            if re.search(rf"\b{re.escape(target)}\b", beat, re.IGNORECASE)
        ]
        if not referenced:
            repaired.append(beat)
            continue
        suffix = " ".join(
            f"Place {target} in {tier}-tier under the stated source criteria."
            for target, tier in referenced[:2]
        )
        repaired.append(f"{beat} {suffix}")
    return repaired


def _source_label_from_ref(ref: str) -> str:
    """Convert a content evidence ref into a speakable citation target."""

    label = ref.split(":", 1)[-1].rsplit("/", 1)[-1].rsplit(".", 1)[0]
    words = [part for part in re.split(r"[^A-Za-z0-9]+", label) if part]
    if not words:
        return "the cited source"
    normalized = [
        "HN" if word.lower() == "hn" else word.upper() if word.isupper() else word.title()
        for word in words
    ]
    return " ".join(normalized)


def _has_responsible_visible_trigger(beat: str) -> bool:
    alignment = validate_segment_actionability([beat], ["repair visibility trigger"])
    return any(
        isinstance(intent, dict) and intent.get("kind") != "spoken_argument"
        for declaration in alignment.get("beat_action_intents", []) or []
        for intent in declaration.get("intents", []) or []
    )


def _has_transforming_trigger(beat: str) -> bool:
    alignment = validate_segment_actionability([beat], ["repair transforming trigger"])
    transforming = {
        "argument_posture_shift",
        "chat_poll",
        "comparison",
        "countdown",
        "iceberg_depth",
        "tier_chart",
    }
    return any(
        isinstance(intent, dict) and intent.get("kind") in transforming
        for declaration in alignment.get("beat_action_intents", []) or []
        for intent in declaration.get("intents", []) or []
    )


def _repair_source_visible_beats(script: list[str], segment_beats: list[str]) -> list[str]:
    """Append a real source-citation trigger when a beat would be spoken-only."""

    repaired: list[str] = []
    last_ref = ""
    for index, beat in enumerate(script):
        direction = segment_beats[index] if index < len(segment_beats) else ""
        refs = [
            match.group("ref").rstrip(".") for match in _BEAT_EVIDENCE_REF_RE.finditer(direction)
        ]
        if refs:
            last_ref = refs[0]
        source_ref = refs[0] if refs else last_ref
        if not source_ref or _has_responsible_visible_trigger(beat):
            repaired.append(beat)
            continue
        label = _source_label_from_ref(source_ref)
        repaired.append(f"{beat} According to {label}, this source changes the visible obligation.")
    return repaired


def _repair_comparison_beats(script: list[str], segment_beats: list[str]) -> list[str]:
    """Make source-planned comparison beats explicit in the spoken script."""

    repaired: list[str] = []
    for index, beat in enumerate(script):
        direction = segment_beats[index] if index < len(segment_beats) else ""
        match = _BEAT_COMPARISON_DIRECTION_RE.search(direction)
        if match is None or _has_transforming_trigger(beat):
            repaired.append(beat)
            continue
        left = match.group("left").strip()
        right = match.group("right").strip()
        repaired.append(
            f"{beat} Compare {left} against {right}; this comparison changes the visible "
            "obligation."
        )
    return repaired


def _repair_live_event_payoff(script: list[str]) -> list[str]:
    """Make the final beat's payoff legible to the live-event gate."""

    if not script:
        return script
    repaired = list(script)
    final = repaired[-1]
    if _LIVE_EVENT_PAYOFF_RE.search(final):
        return repaired
    repaired[-1] = (
        f"{final} Therefore the final decision is whether the cited evidence still supports "
        "the opening claim."
    )
    return repaired


def _refine_script(
    script: list[str],
    programme: Any,
    *,
    prep_session: dict[str, Any] | None = None,
    programme_id: str = "",
) -> tuple[list[str], dict[str, Any] | None, bool]:
    """Iterative refinement pass — critic + rewrite.

    Sends the initial draft to the LLM with a broadcast-editor persona
    that evaluates each beat on specificity, arc, length, and rhetoric,
    then rewrites weak beats. Returns the improved script, the model-emitted
    contract for that script, and whether refinement changed the script.
    """
    prompt = _build_refinement_prompt(script, programme)
    try:
        raw = _call_llm(
            prompt,
            prep_session=prep_session,
            phase="refine",
            programme_id=programme_id,
        )
        refined, refined_contract = _parse_segment_generation(raw)
        if refined and len(refined) >= len(script):
            refined = refined[: len(script)]
            # Log improvement stats
            old_avg = sum(len(b) for b in script) / max(len(script), 1)
            new_avg = sum(len(b) for b in refined) / max(len(refined), 1)
            log.info(
                "refinement: avg chars/beat %.0f → %.0f (%.0f%% change)",
                old_avg,
                new_avg,
                ((new_avg - old_avg) / max(old_avg, 1)) * 100,
            )
            return refined, refined_contract, refined != script
        log.warning(
            "refinement: got %d beats (expected %d), keeping original",
            len(refined) if refined else 0,
            len(script),
        )
    except Exception:
        log.warning("refinement: LLM call failed, keeping original", exc_info=True)
    return script, None, False


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


def _source_refs_from_programme(
    programme: Any,
    *,
    actionability: dict[str, Any],
    layout_responsibility: dict[str, Any],
) -> list[str]:
    content = getattr(programme, "content", None)
    refs: list[str] = []
    for field in ("source_refs", "source_packet_refs", "evidence_refs"):
        value = getattr(content, field, None) if content else None
        if isinstance(value, str):
            refs.append(value)
        elif isinstance(value, list):
            refs.extend(str(item) for item in value)
    role_contract = getattr(content, "role_contract", None) if content else None
    if isinstance(role_contract, dict):
        for field in ("source_refs", "source_packet_refs", "evidence_refs"):
            refs.extend(_string_list(role_contract.get(field)))
    for beat in actionability.get("beat_action_intents", []) or []:
        if not isinstance(beat, dict):
            continue
        for intent in beat.get("intents", []) or []:
            if isinstance(intent, dict):
                refs.extend(_string_list(intent.get("evidence_refs")))
    for beat in layout_responsibility.get("beat_layout_intents", []) or []:
        if isinstance(beat, dict):
            refs.extend(_string_list(beat.get("evidence_refs")))
    cleaned: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        if not ref or ref in seen:
            continue
        if ref.startswith(
            ("source:", "vault:", "rag:", "packet:", "receipt:", "profile:", "media:")
        ):
            cleaned.append(ref)
            seen.add(ref)
    if cleaned:
        return cleaned
    return []


def _contract_hash(payload: dict[str, Any]) -> str:
    return _sha256_json(payload)


def _live_event_report_hash(payload: dict[str, Any]) -> str:
    return _sha256_json(payload)


def _append_candidate_ledger(prep_dir: Path, payload: dict[str, Any], artifact_path: Path) -> None:
    row = {
        "candidate_ledger_version": 1,
        "ledgered_at": datetime.now(tz=UTC).isoformat(),
        "programme_id": payload.get("programme_id"),
        "artifact_name": artifact_path.name,
        "artifact_path": str(artifact_path),
        "artifact_sha256": payload.get("artifact_sha256"),
        "segment_quality_overall": (payload.get("segment_quality_report") or {}).get("overall"),
        "segment_quality_label": (payload.get("segment_quality_report") or {}).get("label"),
        "segment_live_event_score": (payload.get("segment_live_event_report") or {}).get("score"),
        "segment_live_event_band": (payload.get("segment_live_event_report") or {}).get("band"),
        "manifest_eligible": True,
        "authority": payload.get("authority"),
        "prep_contract_ok": (payload.get("segment_prep_contract_report") or {}).get("ok"),
        "runtime_pool_eligible": False,
        "selected_release_required": True,
    }
    ledger_path = prep_dir / CANDIDATE_LEDGER
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


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
    if prep_session is None:
        prep_session = _new_prep_session()
    role = getattr(getattr(programme, "role", None), "value", "unknown")
    content = getattr(programme, "content", None)
    beats = getattr(content, "segment_beats", []) or [] if content else []
    topic = getattr(content, "narrative_beat", "") or "" if content else ""
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
        _write_prep_diagnostic_outcome(
            prep_dir,
            prep_session=prep_session,
            programme_id=prog_id,
            role=role,
            topic=topic,
            segment_beats=list(beats),
            terminal_status="no_candidate",
            terminal_reason="unsafe_programme_id",
            not_loadable_reason=f"unsafe programme_id: {exc}",
            no_candidate_metadata={
                "candidate_source": "programme_id",
                "candidate_count": 0,
                "unsafe_programme_id": prog_id,
            },
        )
        return None

    if not beats:
        log.info("prep_segment: %s has no beats, skipping", prog_id)
        _write_prep_diagnostic_outcome(
            prep_dir,
            prep_session=prep_session,
            programme_id=prog_id,
            role=role,
            topic=topic,
            segment_beats=[],
            terminal_status="no_candidate",
            terminal_reason="no_segment_beats",
            not_loadable_reason="no segment beats available for prep",
            no_candidate_metadata={
                "candidate_source": "programme.content.segment_beats",
                "candidate_count": 0,
                "role": role,
            },
        )
        return None

    source_readiness = programme_source_readiness(programme)
    if source_readiness.get("ok") is not True:
        log.warning(
            "prep_segment: source readiness blocked %s before composition: %s",
            prog_id,
            [item.get("reason") for item in source_readiness.get("violations", [])],
        )
        diagnostic_path = prep_dir / _programme_artifact_name(
            prog_id,
            suffix=".source-readiness-required.json",
        )
        boundary = _diagnostic_boundary_contract()
        diagnostic = {
            "schema_version": PREP_ARTIFACT_SCHEMA_VERSION,
            "record_type": "prep_failure_diagnostic",
            "authority": PREP_DIAGNOSTIC_AUTHORITY,
            **boundary,
            "terminal": True,
            "terminal_status": "no_candidate",
            "terminal_reason": "source_readiness_failed",
            "programme_id": prog_id,
            "role": role,
            "topic": topic,
            "segment_beats": list(beats),
            "source_readiness": source_readiness,
            "prepped_at": datetime.now(tz=UTC).isoformat(),
            "prep_session_id": prep_session["prep_session_id"],
            "model_id": prep_session["model_id"],
            "not_loadable_reason": "source readiness failed before composition",
            "boundary_contract": boundary,
        }
        diagnostic["artifact_sha256"] = _artifact_hash(diagnostic)
        tmp = diagnostic_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(diagnostic, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(diagnostic_path)
        _write_prep_diagnostic_outcome(
            prep_dir,
            prep_session=prep_session,
            programme_id=prog_id,
            role=role,
            topic=topic,
            segment_beats=list(beats),
            terminal_status="no_candidate",
            terminal_reason="source_readiness_failed",
            not_loadable_reason="source readiness failed before composition",
            diagnostic_refs=[str(diagnostic_path)],
            no_candidate_metadata={
                "candidate_source": "programme_source_readiness",
                "candidate_count": 0,
                "source_readiness": source_readiness,
            },
        )
        return None

    log.info("prep_segment: composing %s (%s, %d beats)", prog_id, role, len(beats))

    # Pass 0: Angle resolution — gather competing sources, identify thesis + tension
    angle_ctx = ""
    try:
        from agents.hapax_daimonion.angle_resolver import format_angle_for_composer, resolve_angle

        topic = _extract_topic_string(programme)
        if topic:
            angle = resolve_angle(topic)
            if angle and angle.source_count > 0:
                angle_ctx = format_angle_for_composer(angle)
                log.info(
                    "prep_segment: angle resolved — %d supporting, %d challenging sources",
                    len(angle.supporting_sources),
                    len(angle.challenging_sources),
                )
    except Exception:
        log.warning("prep_segment: angle resolution failed, proceeding without", exc_info=True)

    # Pass 0.5: Research enrichment — deepen angle sources with research tools
    research_ctx = ""
    if angle_ctx:
        try:
            research_ctx = _research_enrich_angle(angle_ctx, _extract_topic_string(programme) or "")
        except Exception:
            log.warning("prep_segment: research enrichment failed", exc_info=True)

    # Pass 1: Initial composition
    seed = _build_seed(programme)
    if angle_ctx:
        seed = f"{seed}\n\n{angle_ctx}" if seed else angle_ctx
    if research_ctx:
        seed = f"{seed}\n\n{research_ctx}"
    prompt = _build_full_segment_prompt(programme, seed)
    source_hashes = _source_hashes(programme, seed=seed, prompt=prompt)
    raw = _call_llm(
        prompt,
        prep_session=prep_session,
        phase="compose",
        programme_id=prog_id,
    )
    script, model_contract = _parse_segment_generation(raw)

    if not script:
        log.warning("prep_segment: empty script for %s", prog_id)
        _write_prep_diagnostic_outcome(
            prep_dir,
            prep_session=prep_session,
            programme_id=prog_id,
            role=role,
            topic=topic,
            segment_beats=list(beats),
            terminal_status="no_release",
            terminal_reason="empty_script_candidate",
            not_loadable_reason="LLM returned no parseable script blocks",
            source_hashes=source_hashes,
            no_candidate_metadata={
                "candidate_source": "llm_script_parse",
                "candidate_count": 0,
                "expected_beat_count": len(beats),
            },
        )
        return None

    # Align the accepted script with the beat count. Blank padding produces
    # impossible spoken-only beats, so a shorter model response narrows the
    # planned beat list to the blocks the model actually authored.
    if len(script) < len(beats):
        log.warning(
            "prep_segment: script has %d blocks but %d beats; trimming beat plan",
            len(script),
            len(beats),
        )
        beats = list(beats[: len(script)])
        source_hashes = _source_hashes_from_fields(
            programme_id=prog_id,
            role=role,
            topic=topic,
            segment_beats=[str(item) for item in beats],
            seed_sha256=_sha256_text(seed),
            prompt_sha256=_sha256_text(prompt),
        )
    elif len(script) > len(beats):
        script = script[: len(beats)]

    if role == "tier_list":
        script = _repair_tier_list_placement_phrases(script)
    script = _repair_source_visible_beats(script, [str(item) for item in beats])

    avg_chars = sum(len(b) for b in script) / max(len(script), 1)
    log.info(
        "prep_segment: pass 1 done for %s — %d beats, avg %.0f chars/beat",
        prog_id,
        len(script),
        avg_chars,
    )

    # Pass 1.5: Council coherence check — reject segments with no narrative force
    coherence_passed = True
    try:
        coherence_passed, coherence_feedback = _council_coherence_check(
            "\n\n".join(script), prog_id
        )
        if not coherence_passed and coherence_feedback:
            log.warning(
                "prep_segment: coherence check failed for %s, injecting feedback into refinement",
                prog_id,
            )
            seed = f"{seed}\n\n## Council Coherence Feedback\n{coherence_feedback}"
    except Exception:
        log.warning("prep_segment: coherence check failed", exc_info=True)

    # Pass 2: Iterative refinement
    refine_result = _refine_script(
        script,
        programme,
        prep_session=prep_session,
        programme_id=prog_id,
    )
    refinement_contract: dict[str, Any] | None = None
    refinement_changed = False
    if isinstance(refine_result, tuple):
        script, refinement_contract, refinement_changed = refine_result
    else:
        # Compatibility for tests or external monkeypatches that still return a script only.
        refined_script = [str(item) for item in refine_result]
        refinement_changed = refined_script != script
        script = refined_script
    if refinement_contract and (refinement_changed or model_contract is None):
        model_contract = refinement_contract
    elif refinement_changed:
        log.warning(
            "prep_segment: refinement changed %s without a model-emitted final contract",
            prog_id,
        )
        model_contract = None
    script = _scrub_host_posture(script)
    if role == "tier_list":
        script = _repair_tier_list_placement_phrases(script)
    script = _repair_source_visible_beats(script, [str(item) for item in beats])
    script = _repair_comparison_beats(script, [str(item) for item in beats])
    script = _repair_live_event_payoff(script)

    # Pass 3: Council disconfirmation — adversarially test material claims
    council_disconfirmation_result: dict[str, Any] | None = None
    try:
        from shared.segment_disconfirmation import (
            apply_council_verdicts,
            extract_claims,
            run_council_disconfirmation,
        )

        contract_for_claims = build_segment_prep_contract(
            programme_id=prog_id,
            role=role,
            topic=programme.content.topic if hasattr(programme.content, "topic") else "",
            segment_beats=[str(b) for b in beats],
            script=script,
            actionability={},
            layout_responsibility={},
            source_refs=[],
            model_contract=model_contract,
        )
        claim_map = contract_for_claims.get("claim_map", [])
        sc_map = contract_for_claims.get("source_consequence_map", [])

        council_claims = extract_claims(
            claim_map=claim_map,
            source_consequence_map=sc_map,
            script=script,
        )
        if council_claims:
            council_verdicts = run_council_disconfirmation(council_claims)
            if council_verdicts:
                council_disconfirmation_result = apply_council_verdicts(
                    council_verdicts,
                    source_consequence_map=list(sc_map),
                    claim_map=list(claim_map),
                )
                if council_disconfirmation_result.get("no_candidate_triggered"):
                    log.warning(
                        "prep_segment: council refuted structural claim in %s — no candidate",
                        prog_id,
                    )
                    diagnostic_path = prep_dir / diagnostic_name
                    boundary = _diagnostic_boundary_contract()
                    diagnostic = {
                        "schema_version": PREP_DIAGNOSTIC_SCHEMA_VERSION,
                        "authority": "diagnostic_only",
                        "programme_id": prog_id,
                        "outcome_type": "no_candidate",
                        "reason": "council_refuted_structural_claim",
                        "council_verdict": council_disconfirmation_result,
                        **boundary,
                    }
                    _write_json_atomic(diagnostic_path, diagnostic)
                    _append_to_candidate_ledger(prep_dir, prog_id, diagnostic_name, "no_candidate")
                    return None
                log.info(
                    "prep_segment: council pass for %s — %d survived, %d contested, %d refuted",
                    prog_id,
                    len(council_disconfirmation_result.get("survived_claims", [])),
                    len(council_disconfirmation_result.get("contested_claims", [])),
                    len(council_disconfirmation_result.get("refuted_claims", [])),
                )
    except ImportError:
        log.debug("prep_segment: council disconfirmation module not available — skipping")
    except Exception as exc:
        log.warning("prep_segment: council disconfirmation failed for %s: %s", prog_id, exc)

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
        boundary = _diagnostic_boundary_contract()
        diagnostic = {
            "schema_version": PREP_ARTIFACT_SCHEMA_VERSION,
            "record_type": "prep_failure_diagnostic",
            "authority": PREP_DIAGNOSTIC_AUTHORITY,
            **boundary,
            "terminal": True,
            "terminal_status": "refused_no_release",
            "terminal_reason": "actionability_alignment_failed",
            "programme_id": prog_id,
            "role": role,
            "topic": topic,
            "segment_beats": list(beats),
            "prepared_script_candidate": script,
            "sanitized_script_candidate": actionability["diagnostic_sanitized_script"],
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
            "boundary_contract": boundary,
        }
        diagnostic["artifact_sha256"] = _artifact_hash(diagnostic)
        tmp = diagnostic_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(diagnostic, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(diagnostic_path)
        _write_prep_diagnostic_outcome(
            prep_dir,
            prep_session=prep_session,
            programme_id=prog_id,
            role=role,
            topic=topic,
            segment_beats=list(beats),
            terminal_status="refused_no_release",
            terminal_reason="actionability_alignment_failed",
            not_loadable_reason="actionability alignment failed",
            source_hashes=source_hashes,
            diagnostic_refs=[str(diagnostic_path)],
            refusal_metadata={
                "rubric_version": ACTIONABILITY_RUBRIC_VERSION,
                "removed_unsupported_action_line_count": len(
                    actionability["removed_unsupported_action_lines"]
                ),
            },
        )
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
    quality_report = score_segment_quality(script, [str(item) for item in beats])
    consultation_manifest = build_consultation_manifest(role)
    source_consequence_map = build_source_consequence_map(
        script,
        actionability["beat_action_intents"],
    )
    fore_understanding = retrieve_fore_understanding(topic=topic, role=role)
    hermeneutic_deltas = compute_hermeneutic_delta(
        source_consequence_map,
        fore_understanding,
        programme_id=prog_id,
        role=role,
        topic=topic,
    )
    live_event_viability = build_live_event_viability(
        script,
        actionability=actionability,
        layout=layout_responsibility,
        role=role,
    )
    readback_obligations = build_readback_obligations(
        layout_responsibility["beat_layout_intents"],
    )
    if layout_responsibility["ok"] is not True:
        log.warning(
            "prep_segment: quarantining %s with layout responsibility violations: %s",
            prog_id,
            [item.get("reason") for item in layout_responsibility["violations"]],
        )
        diagnostic_path = prep_dir / layout_diagnostic_name
        boundary = _diagnostic_boundary_contract()
        diagnostic = {
            "schema_version": PREP_ARTIFACT_SCHEMA_VERSION,
            "record_type": "prep_failure_diagnostic",
            "authority": PREP_DIAGNOSTIC_AUTHORITY,
            **boundary,
            "terminal": True,
            "terminal_status": "refused_no_release",
            "terminal_reason": "layout_responsibility_failed",
            "programme_id": prog_id,
            "role": role,
            "topic": topic,
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
            "boundary_contract": boundary,
        }
        diagnostic["artifact_sha256"] = _artifact_hash(diagnostic)
        tmp = diagnostic_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(diagnostic, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(diagnostic_path)
        _write_prep_diagnostic_outcome(
            prep_dir,
            prep_session=prep_session,
            programme_id=prog_id,
            role=role,
            topic=topic,
            segment_beats=list(beats),
            terminal_status="refused_no_release",
            terminal_reason="layout_responsibility_failed",
            not_loadable_reason="layout responsibility failed",
            source_hashes=source_hashes,
            diagnostic_refs=[str(diagnostic_path)],
            refusal_metadata={
                "layout_responsibility_version": LAYOUT_RESPONSIBILITY_VERSION,
                "violation_count": len(layout_responsibility["violations"]),
            },
        )
        return None

    source_refs = _source_refs_from_programme(
        programme,
        actionability=actionability,
        layout_responsibility=layout_responsibility,
    )
    contract_seed = build_segment_prep_contract(
        programme_id=prog_id,
        role=role,
        topic=topic,
        segment_beats=[str(item) for item in beats],
        script=script,
        actionability=actionability,
        layout_responsibility=layout_responsibility,
        source_refs=source_refs,
    )
    actionability = validate_segment_actionability(
        script,
        [str(item) for item in beats],
        prep_contract=contract_seed,
    )
    layout_responsibility = validate_layout_responsibility(
        actionability["beat_action_intents"],
    )
    layout_responsibility = _with_tier_list_placement_gate(
        layout_responsibility,
        role=role,
        segment_beats=segment_beat_strings,
        beat_action_intents=actionability["beat_action_intents"],
    )
    live_event_viability = build_live_event_viability(
        script,
        actionability=actionability,
        layout=layout_responsibility,
        role=role,
    )
    readback_obligations = build_readback_obligations(
        layout_responsibility["beat_layout_intents"],
    )
    segment_prep_contract = build_segment_prep_contract(
        programme_id=prog_id,
        role=role,
        topic=topic,
        segment_beats=[str(item) for item in beats],
        script=script,
        actionability=actionability,
        layout_responsibility=layout_responsibility,
        source_refs=source_refs,
        model_contract=model_contract,
    )
    segment_prep_contract_report = validate_segment_prep_contract(
        segment_prep_contract,
        prepared_script=script,
        segment_beats=[str(item) for item in beats],
    )
    segment_prep_contract_sha256 = _contract_hash(segment_prep_contract)
    source_hashes["segment_prep_contract_sha256"] = segment_prep_contract_sha256
    segment_live_event_report = evaluate_segment_live_event_quality(
        script,
        [str(item) for item in beats],
        actionability["beat_action_intents"],
        layout_responsibility["beat_layout_intents"],
        role=role,
        segment_prep_contract=segment_prep_contract,
    )
    segment_live_event_report_sha256 = _live_event_report_hash(segment_live_event_report)
    if (
        segment_prep_contract_report.get("ok") is not True
        or segment_live_event_report.get("ok") is not True
    ):
        log.warning(
            "prep_segment: quarantining %s with contract/live-event failures: contract=%s live_event=%s",
            prog_id,
            segment_prep_contract_report.get("violations"),
            segment_live_event_report.get("violations"),
        )
        diagnostic_path = prep_dir / _programme_artifact_name(
            prog_id,
            suffix=".contract-invalid.json",
        )
        boundary = _diagnostic_boundary_contract()
        diagnostic = {
            "schema_version": PREP_ARTIFACT_SCHEMA_VERSION,
            "record_type": "prep_failure_diagnostic",
            "authority": PREP_DIAGNOSTIC_AUTHORITY,
            **boundary,
            "terminal": True,
            "terminal_status": "refused_no_release",
            "terminal_reason": "segment_prep_contract_or_live_event_failed",
            "programme_id": prog_id,
            "role": role,
            "topic": topic,
            "segment_beats": list(beats),
            "prepared_script_candidate": script,
            "segment_prep_contract_version": SEGMENT_PREP_CONTRACT_VERSION,
            "segment_prep_contract": segment_prep_contract,
            "segment_prep_contract_report": segment_prep_contract_report,
            "segment_live_event_rubric_version": LIVE_EVENT_RUBRIC_VERSION,
            "segment_live_event_report": segment_live_event_report,
            "prepped_at": datetime.now(tz=UTC).isoformat(),
            "prep_session_id": prep_session["prep_session_id"],
            "model_id": prep_session["model_id"],
            "prompt_sha256": source_hashes["prompt_sha256"],
            "seed_sha256": source_hashes["seed_sha256"],
            "not_loadable_reason": "segment prep contract or live-event report failed",
            "boundary_contract": boundary,
        }
        diagnostic["artifact_sha256"] = _artifact_hash(diagnostic)
        tmp = diagnostic_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(diagnostic, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(diagnostic_path)
        _write_prep_diagnostic_outcome(
            prep_dir,
            prep_session=prep_session,
            programme_id=prog_id,
            role=role,
            topic=topic,
            segment_beats=list(beats),
            terminal_status="refused_no_release",
            terminal_reason="segment_prep_contract_or_live_event_failed",
            not_loadable_reason="segment prep contract or live-event report failed",
            source_hashes=source_hashes,
            diagnostic_refs=[str(diagnostic_path)],
            refusal_metadata={
                "segment_prep_contract_report": segment_prep_contract_report,
                "segment_live_event_report": segment_live_event_report,
            },
        )
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
        "consultation_manifest": consultation_manifest,
        "source_consequence_map": source_consequence_map,
        "fore_understanding": [
            {k: v for k, v in p.items() if not k.startswith("_")} for p in fore_understanding
        ],
        "hermeneutic_deltas": [d.model_dump(mode="json") for d in hermeneutic_deltas],
        "live_event_viability": live_event_viability,
        "readback_obligations": readback_obligations,
        "segment_prep_contract_version": SEGMENT_PREP_CONTRACT_VERSION,
        "segment_prep_contract": segment_prep_contract,
        "segment_prep_contract_report": segment_prep_contract_report,
        "segment_prep_contract_sha256": segment_prep_contract_sha256,
        "segment_live_event_rubric_version": LIVE_EVENT_RUBRIC_VERSION,
        "segment_live_event_plan": segment_live_event_report.get("plan"),
        "segment_live_event_report": segment_live_event_report,
        "segment_live_event_report_sha256": segment_live_event_report_sha256,
        "beat_action_intents": actionability["beat_action_intents"],
        "actionability_alignment": {
            "ok": actionability["ok"],
            "removed_unsupported_action_lines": actionability["removed_unsupported_action_lines"],
            "personage_violations": actionability["personage_violations"],
            "detector_theater_lines": actionability["detector_theater_lines"],
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
    if council_disconfirmation_result is not None:
        payload["disconfirmation_council_verdict"] = council_disconfirmation_result
        source_hashes["council_verdict_sha256"] = council_disconfirmation_result.get(
            "council_verdict_sha256", ""
        )
    payload["artifact_sha256"] = _artifact_hash(payload)
    tmp = out_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(out_path)
    _append_candidate_ledger(prep_dir, payload, out_path)
    log.info(
        "prep_segment: saved %s (%d blocks, avg %.0f chars/beat)",
        out_path,
        len(script),
        final_avg,
    )

    persist_source_consequences(
        source_consequence_map,
        programme_id=prog_id,
        role=role,
        topic=topic,
        prep_session_id=prep_session["prep_session_id"],
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
    prep_activity = _prep_activity()
    max_segments_for_run = 1 if prep_activity == "canary" else MAX_SEGMENTS
    prep_session["prep_status"] = {
        "prep_status_version": PREP_STATUS_VERSION,
        "status": "in_progress",
        "phase": "run_start",
        "pid": os.getpid(),
        "started_at": started_at,
        "updated_at": started_at,
        "prep_session_id": prep_session["prep_session_id"],
        "model_id": prep_session["model_id"],
        "target_segments": max_segments_for_run,
        "existing_manifest_programmes": existing_manifest_names,
        "llm_calls": [],
    }
    _update_prep_status(
        prep_session,
        status="in_progress",
        phase="authority_gate_check",
        authority_activity=prep_activity,
    )
    try:
        authority_state = assert_segment_prep_allowed(prep_activity)
    except (SegmentPrepPaused, SegmentPrepPauseError) as exc:
        _update_prep_status(
            prep_session,
            status="paused",
            phase="segment_prep_authority_paused",
            authority_activity=prep_activity,
            last_error=f"{type(exc).__name__}: {exc}",
        )
        return saved
    prep_session["authority_gate_passed"] = True
    prep_session["authority_mode"] = authority_state.mode
    prep_session["authority_reason"] = authority_state.reason
    _update_prep_status(
        prep_session,
        status="in_progress",
        phase="authority_gate_passed",
        authority_activity=prep_activity,
        authority_mode=authority_state.mode,
        authority_reason=authority_state.reason,
    )
    if prep_activity == "pool_generation" and max_segments_for_run > 1:
        _update_prep_status(
            prep_session,
            status="in_progress",
            phase="next_nine_canary_gate_check",
            authority_activity=prep_activity,
        )
        try:
            canary_gate = assert_next_nine_canary_ready()
        except SegmentCanaryGateError as exc:
            _update_prep_status(
                prep_session,
                status="blocked",
                phase="next_nine_canary_gate_blocked",
                authority_activity=prep_activity,
                last_error=f"{type(exc).__name__}: {exc}",
            )
            return saved
        prep_session["next_nine_canary_gate"] = canary_gate
        _update_prep_status(
            prep_session,
            status="in_progress",
            phase="next_nine_canary_gate_passed",
            authority_activity=prep_activity,
            canary_review_receipt_path=canary_gate.get("path"),
            canary_programme_id=(canary_gate.get("receipt") or {}).get("programme_id"),
            canary_artifact_sha256=(canary_gate.get("receipt") or {}).get("artifact_sha256"),
            canary_iteration_id=(canary_gate.get("receipt") or {}).get("iteration_id"),
        )
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
    log.info("daily_segment_prep: planning programmes (target=%d)...", max_segments_for_run)
    segmented: list[Any] = []
    seen_ids: set[str] = set(existing_programme_ids)
    plan_round = 0
    max_rounds = 1 if max_segments_for_run == 1 else (max_segments_for_run // 2) + 2
    planner_target_programmes = 1 if max_segments_for_run == 1 else None
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

    while len(segmented) < max_segments_for_run and plan_round < max_rounds:
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
            recent_fore = _retrieve_broad_fore_understanding()
            plan = planner.plan(
                show_id=show_id,
                target_programmes=planner_target_programmes,
                fore_understanding=recent_fore or None,
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
            if role_val not in SEGMENTED_CONTENT_ROLES or pid in seen_ids:
                continue
            topic = _extract_topic_string(p)
            if topic and not _council_topic_substance_gate(topic, pid):
                log.warning(
                    "daily_segment_prep: council rejected topic substance for %s: %s",
                    pid,
                    topic[:80],
                )
                continue
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
    for prog in segmented[:max_segments_for_run]:
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

    if not segmented:
        _write_prep_diagnostic_outcome(
            today,
            prep_session=prep_session,
            programme_id=None,
            role=None,
            topic=None,
            segment_beats=[],
            terminal_status="no_candidate",
            terminal_reason="planner_no_segmented_programmes",
            not_loadable_reason="planner produced no segmented-content programmes",
            no_candidate_metadata={
                "candidate_source": "programme_planner",
                "candidate_count": 0,
                "plan_rounds": plan_round,
                "max_rounds": max_rounds,
                "target_segments": MAX_SEGMENTS,
                "existing_programme_count": len(existing_programme_ids),
            },
        )

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
    log.info(
        "daily_segment_prep: done. %d segments prepped in %.0fs",
        len(saved),
        time.monotonic() - start,
    )
    return saved


def _extract_topic_string(programme: Any) -> str | None:
    """Pull the topic/narrative_beat from a planned programme for substance checking."""
    content = getattr(programme, "content", None)
    if content is None:
        return None
    topic = getattr(content, "declared_topic", None) or getattr(content, "narrative_beat", None)
    if isinstance(topic, str) and topic.strip():
        return topic.strip()
    return None


def _council_topic_substance_gate(topic: str, programme_id: str) -> bool:
    """Run the deliberative council on a topic to check argumentative substance.

    Returns True if the topic has enough substance for a full segment.
    Returns True (fail-open) if the council is unavailable.
    """
    try:
        import asyncio

        from agents.deliberative_council.engine import deliberate
        from agents.deliberative_council.models import CouncilConfig, CouncilInput, CouncilMode
        from agents.deliberative_council.rubrics import DisconfirmationRubric

        council_input = CouncilInput(
            text=topic,
            source_ref=f"topic_substance_check:{programme_id}",
            metadata={"check_type": "anterior_substance", "programme_id": programme_id},
        )
        config = CouncilConfig(max_models=3, phase3_rounds=1)
        verdict = asyncio.run(
            deliberate(council_input, CouncilMode.DISCONFIRMATION, DisconfirmationRubric(), config)
        )
        mean_score = sum(s for s in verdict.scores.values() if s is not None) / max(
            1, len(verdict.scores)
        )
        if mean_score <= 2.0:
            log.warning(
                "council_topic_substance_gate: topic rejected (mean=%.1f, scores=%s): %s",
                mean_score,
                verdict.scores,
                topic[:80],
            )
            return False
        log.info(
            "council_topic_substance_gate: topic accepted (mean=%.1f): %s",
            mean_score,
            topic[:80],
        )
        return True
    except Exception:
        log.warning("council_topic_substance_gate: council unavailable, fail-open", exc_info=True)
        return True


def _council_coherence_check(full_script: str, programme_id: str) -> tuple[bool, str]:
    """Run the council coherence rubric on a composed script.

    Returns (passed, feedback_string). Feedback is a summary of the
    council's scoring across the 4 coherence axes. When mean < 3.0,
    passed=False and feedback contains specific axis-level critique.
    """
    try:
        import asyncio

        from agents.deliberative_council.engine import deliberate
        from agents.deliberative_council.models import CouncilConfig, CouncilInput, CouncilMode
        from agents.deliberative_council.rubrics import CoherenceRubric

        council_input = CouncilInput(
            text=full_script[:4000],
            source_ref=f"coherence_check:{programme_id}",
            metadata={"check_type": "coherence", "programme_id": programme_id},
        )
        config = CouncilConfig(max_models=3, phase3_rounds=1)
        verdict = asyncio.run(
            deliberate(council_input, CouncilMode.DISCONFIRMATION, CoherenceRubric(), config)
        )
        scores = verdict.scores
        mean_score = sum(s for s in scores.values() if s is not None) / max(1, len(scores))
        feedback_lines = [f"Council coherence scores (mean={mean_score:.1f}):"]
        for axis, score in scores.items():
            feedback_lines.append(f"  - {axis}: {score}")
        for note in verdict.disagreement_log[:3]:
            feedback_lines.append(f"  Council note: {note[:200]}")
        feedback = "\n".join(feedback_lines)

        if mean_score < 3.0:
            log.warning(
                "_council_coherence_check: FAILED (mean=%.1f) for %s",
                mean_score,
                programme_id,
            )
            return False, feedback
        log.info("_council_coherence_check: passed (mean=%.1f) for %s", mean_score, programme_id)
        return True, feedback
    except Exception:
        log.warning("_council_coherence_check: council unavailable, fail-open", exc_info=True)
        return True, ""


def _research_enrich_angle(angle_ctx: str, topic: str) -> str:
    """Use research tools to deepen the angle's source material.

    Runs a lightweight LLM call with web search + qdrant lookup to
    gather concrete evidence, examples, and counter-examples for the
    angle hypothesis. Returns a formatted research block for the
    composer's seed.
    """
    try:
        import litellm

        from shared.config import MODELS

        prompt = (
            f"Topic: {topic}\n\n"
            f"Angle analysis:\n{angle_ctx}\n\n"
            "You are a research assistant preparing material for a segment producer. "
            "Based on the angle analysis above, provide:\n"
            "1. CONCRETE EXAMPLE: A specific real-world case that illustrates the thesis\n"
            "2. COUNTER EXAMPLE: A specific case that illustrates the challenge\n"
            "3. KEY TERM DEFINITIONS: 2-3 technical terms the audience needs defined\n"
            "4. OPENING HOOK: A specific question, paradox, or provocation that would "
            "make the audience want to hear the rest\n\n"
            "Be specific. Name real systems, papers, incidents, or frameworks. "
            "If you don't know specific examples, say so honestly."
        )
        response = litellm.completion(
            model=MODELS.get("claude-opus", "claude-opus"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.4,
        )
        result = response.choices[0].message.content or ""
        if len(result) > 100:
            log.info("_research_enrich_angle: enrichment returned %d chars", len(result))
            return f"## Research Enrichment\n{result}"
    except Exception:
        log.warning("_research_enrich_angle: enrichment failed", exc_info=True)
    return ""


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


def _consultation_rejection_reason(data: dict[str, Any]) -> str | None:
    role = str(data.get("role") or "")
    consultation = validate_consultation_manifest(
        data.get("consultation_manifest"),
        role=role,
    )
    if consultation.get("ok") is not True:
        return "invalid consultation manifest"
    source_consequence = validate_source_consequence_map(data.get("source_consequence_map"))
    if source_consequence.get("ok") is not True:
        return "missing source consequence map"
    live_viability = validate_live_event_viability(data.get("live_event_viability"))
    if live_viability.get("ok") is not True:
        return "live event viability not demonstrated"
    readback = validate_readback_obligations(data.get("readback_obligations"))
    if readback.get("ok") is not True:
        return "missing readback obligations"
    return None


def _artifact_rejection_reason(
    data: dict[str, Any],
    *,
    path: Path,
    manifest_programmes: set[str] | None,
    strict_release_contract: bool = False,
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
    if framework_vocabulary_leaks(script):
        return "framework vocabulary leaked into prepared script"
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
    consultation_reason = _consultation_rejection_reason(data)
    if consultation_reason:
        return consultation_reason
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
    expected_source_hashes = _source_hashes_from_fields(
        programme_id=programme_id,
        role=role,
        topic=topic,
        segment_beats=beats,
        seed_sha256=data["seed_sha256"],
        prompt_sha256=data["prompt_sha256"],
    )
    allowed_extra_source_hashes = {"segment_prep_contract_sha256"}
    if any(source_hashes.get(key) != value for key, value in expected_source_hashes.items()):
        return "source hash mismatch"
    if set(source_hashes) - set(expected_source_hashes) - allowed_extra_source_hashes:
        return "source hash mismatch"
    source_provenance_sha256 = data.get("source_provenance_sha256")
    if not _is_sha256_hex(source_provenance_sha256) or source_provenance_sha256 != _sha256_json(
        source_hashes
    ):
        return "source provenance hash mismatch"
    if strict_release_contract:
        if data.get("segment_prep_contract_version") != SEGMENT_PREP_CONTRACT_VERSION:
            return "missing segment prep contract version"
        contract = data.get("segment_prep_contract")
        if not isinstance(contract, dict):
            return "missing segment prep contract"
        contract_sha = data.get("segment_prep_contract_sha256")
        if not _is_sha256_hex(contract_sha) or contract_sha != _contract_hash(contract):
            return "segment prep contract hash mismatch"
        if source_hashes.get("segment_prep_contract_sha256") != contract_sha:
            return "source hash missing segment prep contract binding"
        expected_contract_report = validate_segment_prep_contract(
            contract,
            prepared_script=script,
            segment_beats=beats,
        )
        if data.get("segment_prep_contract_report") != expected_contract_report:
            return "stale segment prep contract report"
        if expected_contract_report.get("ok") is not True:
            return "segment prep contract failed"
        binding = contract.get("prepared_script_binding") if isinstance(contract, dict) else {}
        if not isinstance(binding, dict) or binding.get(
            "prepared_script_sha256"
        ) != prepared_script_sha256(script):
            return "prepared script contract binding mismatch"
        live_event_validation = validate_live_event_report_matches_artifact(data)
        if live_event_validation.get("ok") is not True:
            return "live event quality report failed"
    return None


def _accepted_artifact_or_reason(
    path: Path,
    *,
    manifest_programmes: set[str] | None,
    strict_release_contract: bool = False,
    selected_artifact_hashes: dict[str, str] | None = None,
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
        strict_release_contract=strict_release_contract,
    )
    if reason:
        return None, reason
    if selected_artifact_hashes is not None:
        expected_hash = selected_artifact_hashes.get(path.name)
        if not expected_hash:
            return None, "not selected for release"
        if data.get("artifact_sha256") != expected_hash:
            return None, "selected artifact hash mismatch"

    contract_for_replay = None
    if isinstance(data.get("segment_prep_contract"), dict):
        contract_for_replay = data["segment_prep_contract"]
    runtime_actionability = validate_segment_actionability(
        list(data["prepared_script"]),
        list(data["segment_beats"]),
        prep_contract=contract_for_replay,
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


def _selected_release_manifest(today: Path) -> dict[str, Any] | None:
    path = today / SELECTED_RELEASE_MANIFEST
    if not path.exists():
        return None
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log.debug("selected_release: failed to read %s", path, exc_info=True)
        return None
    if not isinstance(manifest, dict):
        return None
    expected_hash = manifest.get("selected_release_manifest_sha256")
    if not _is_sha256_hex(expected_hash):
        return None
    body = dict(manifest)
    body.pop("selected_release_manifest_sha256", None)
    if expected_hash != _sha256_json(body):
        return None
    if manifest.get("ok") is not True:
        return None
    return manifest


def _selected_release_programme_names(today: Path) -> list[str] | None:
    manifest = _selected_release_manifest(today)
    if manifest is None:
        return None
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


def _selected_release_artifact_hashes(today: Path) -> dict[str, str] | None:
    manifest = _selected_release_manifest(today)
    if manifest is None:
        return None
    hashes: dict[str, str] = {}
    for item in manifest.get("selected_artifacts") or []:
        if not isinstance(item, dict):
            continue
        name = _safe_manifest_name(item.get("artifact_name"))
        artifact_hash = item.get("artifact_sha256")
        if name and _is_sha256_hex(artifact_hash):
            hashes[name] = str(artifact_hash)
    return hashes


def load_prepped_programmes(
    prep_dir: Path | None = None,
    *,
    require_selected: bool = True,
    strict_release_contract: bool | None = None,
) -> list[dict]:
    """Load today's prepped segments from disk.

    Returns a list of dicts, each with programme_id, prepared_script, etc.
    Used by the programme loop to populate prepared_script on programmes.
    """
    if prep_dir is None:
        prep_dir = DEFAULT_PREP_DIR
    if strict_release_contract is None:
        strict_release_contract = require_selected
    today = _today_path(prep_dir)
    if not today.exists():
        return []
    selected_hashes: dict[str, str] | None = None
    if require_selected:
        assert_segment_prep_allowed("runtime_pool_load")
        manifest_names = _selected_release_programme_names(today)
        selected_hashes = _selected_release_artifact_hashes(today) or {}
    else:
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
            strict_release_contract=strict_release_contract,
            selected_artifact_hashes=selected_hashes,
        )
        if reason:
            log.warning("load_prepped: rejecting %s: %s", f.name, reason)
            continue
        if data is not None:
            results.append(data)
    return results


def _write_selected_release_rag_digest(
    today: Path,
    artifacts: list[dict[str, Any]],
    *,
    manifest: dict[str, Any],
    review_receipt: dict[str, Any],
    rag_dir: Path,
) -> Path:
    rag_dir.mkdir(parents=True, exist_ok=True)
    path = rag_dir / f"{today.name}-selected-segment-prep.md"
    lines = [
        "---",
        "type: segment-prep-selected-release",
        "authority: prior_only_feedback",
        f"date: {today.name}",
        f"selected_release_manifest_sha256: {manifest.get('selected_release_manifest_sha256', '')}",
        f"review_receipt_sha256: {review_receipt.get('segment_candidate_selection_sha256', '')}",
        "---",
        "",
        "# Selected Segment Prep Release",
        "",
        "This digest publishes selected prepared-script feedback for retrieval. It is not runtime layout authority.",
        "",
        "## Selected Artifacts",
    ]
    selected_by_name = {
        str(item.get("artifact_name") or ""): item
        for item in manifest.get("selected_artifacts") or []
        if isinstance(item, dict)
    }
    for artifact in artifacts:
        name = Path(
            str(artifact.get("artifact_path") or artifact.get("artifact_path_diagnostic") or "")
        ).name
        if not name:
            name = f"{artifact.get('programme_id', 'unknown')}.json"
        selected = selected_by_name.get(name, {})
        lines.extend(
            [
                "",
                f"- `{name}`",
                f"  - programme: `{artifact.get('programme_id', '')}`",
                f"  - receipt: `{selected.get('receipt_id', '')}`",
                f"  - live-event band: `{(artifact.get('segment_live_event_report') or {}).get('band', '')}`",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _upsert_artifact_dicts_to_qdrant(
    artifacts: list[dict[str, Any]],
    *,
    manifest: dict[str, Any],
    review_receipt: dict[str, Any],
) -> int:
    if not artifacts:
        return 0
    try:
        import uuid

        from qdrant_client.models import PointStruct

        from shared.affordance_pipeline import COLLECTION_NAME, embed_batch_safe
        from shared.config import get_qdrant

        texts: list[str] = []
        payloads: list[dict[str, Any]] = []
        for artifact in artifacts:
            programme_id = str(artifact.get("programme_id") or "")
            topic = str(artifact.get("topic") or "")
            script_preview = " ".join(_string_list(artifact.get("prepared_script")))[:1200]
            texts.append(
                f"Selected prepared livestream segment {programme_id}: {topic}. {script_preview}"
            )
            payloads.append(
                {
                    "capability_name": f"programme.prepped.selected.{programme_id}",
                    "description": texts[-1],
                    "daemon": "hapax_daimonion",
                    "programme_id": programme_id,
                    "role": artifact.get("role"),
                    "topic": topic[:500],
                    "artifact_type": "selected_prepared_script",
                    "available": True,
                    "selected_release": True,
                    "runtime_pool_eligible": True,
                    "authority": artifact.get("authority"),
                    "artifact_path": artifact.get("artifact_path")
                    or artifact.get("artifact_path_diagnostic"),
                    "artifact_sha256": artifact.get("artifact_sha256"),
                    "selected_release_manifest_sha256": manifest.get(
                        "selected_release_manifest_sha256"
                    ),
                    "review_receipt_sha256": review_receipt.get(
                        "segment_candidate_selection_sha256"
                    ),
                    "segment_quality_report": artifact.get("segment_quality_report"),
                    "segment_live_event_report": artifact.get("segment_live_event_report"),
                    "segment_prep_contract_report": artifact.get("segment_prep_contract_report"),
                }
            )
        embeddings = embed_batch_safe(texts, prefix="search_document")
        if embeddings is None:
            return 0
        points = []
        for _text, payload, vector in zip(texts, payloads, embeddings, strict=True):
            if vector is None:
                continue
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, payload["capability_name"]))
            points.append(PointStruct(id=point_id, vector=vector, payload=payload))
        if not points:
            return 0
        get_qdrant().upsert(collection_name=COLLECTION_NAME, points=points)
        return len(points)
    except Exception:
        log.warning("selected_release qdrant: publication failed", exc_info=True)
        return 0


def publish_selected_release_feedback(
    *,
    prep_dir: Path | None = None,
    review_receipt: dict[str, Any],
    rag_dir: Path | None = None,
) -> dict[str, Any]:
    if prep_dir is None:
        prep_dir = DEFAULT_PREP_DIR
    today = _today_path(prep_dir)
    publication_errors: list[dict[str, str]] = []
    if review_receipt.get("ok") is not True:
        return {
            "ok": False,
            "publication_ok": False,
            "publication_errors": [{"surface": "review_receipt", "error": "review_not_ok"}],
        }
    disk_manifest = _selected_release_manifest(today)
    if disk_manifest is None:
        return {
            "ok": False,
            "publication_ok": False,
            "publication_errors": [
                {
                    "surface": "selected_release_manifest",
                    "error": "missing_or_invalid_disk_manifest",
                }
            ],
        }
    receipt_manifest = review_receipt.get("selected_release_manifest")
    if not isinstance(receipt_manifest, dict):
        return {
            "ok": False,
            "publication_ok": False,
            "publication_errors": [
                {"surface": "selected_release_manifest", "error": "missing_receipt_manifest"}
            ],
        }
    if receipt_manifest.get("selected_release_manifest_sha256") != disk_manifest.get(
        "selected_release_manifest_sha256"
    ):
        return {
            "ok": False,
            "publication_ok": False,
            "publication_errors": [
                {"surface": "selected_release_manifest", "error": "receipt_manifest_hash_mismatch"}
            ],
        }

    artifacts = load_prepped_programmes(prep_dir, require_selected=True)
    if not artifacts:
        return {
            "ok": False,
            "publication_ok": False,
            "qdrant_upserted": 0,
            "publication_errors": [
                {"surface": "runtime_loader", "error": "selected_release_loaded_no_artifacts"}
            ],
        }
    qdrant_upserted = _upsert_artifact_dicts_to_qdrant(
        artifacts,
        manifest=disk_manifest,
        review_receipt=review_receipt,
    )
    if qdrant_upserted < len(artifacts):
        publication_errors.append(
            {
                "surface": "qdrant",
                "error": "selected_release_qdrant_publication_incomplete",
            }
        )
    rag_digest_path: str | None = None
    try:
        digest = _write_selected_release_rag_digest(
            today,
            artifacts,
            manifest=disk_manifest,
            review_receipt=review_receipt,
            rag_dir=rag_dir or (Path.home() / "documents" / "rag-sources" / "segment-prep"),
        )
        rag_digest_path = str(digest)
    except Exception as exc:
        publication_errors.append({"surface": "rag_digest", "error": str(exc)})

    return {
        "ok": True,
        "publication_ok": not publication_errors,
        "publication_errors": publication_errors,
        "qdrant_upserted": qdrant_upserted,
        "rag_digest_path": rag_digest_path,
        "selected_release_manifest_sha256": disk_manifest.get("selected_release_manifest_sha256"),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Daily segment prep runner")
    parser.add_argument("--prep-dir", type=Path, default=None)
    args = parser.parse_args()
    saved = run_prep(prep_dir=args.prep_dir)
    for p in saved:
        print(f"  ✓ {p}")
