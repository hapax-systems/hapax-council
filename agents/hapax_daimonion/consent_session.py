"""Voice consent session — LLM-mediated consent conversation via Pipecat.

A purpose-built voice conversation for offering consent to guests in
an ambient sensing environment. The LLM handles natural language
understanding; all consent decisions are made by tool functions.

State machine: ANNOUNCE → LISTEN → CLARIFY (max 3) → CONFIRM → RESOLVE

The consent session is a separate PipelineTask that shares the audio
transport with the main voice daemon. It runs when
ConsentStateTracker.needs_notification fires.

Composition:
- STT/TTS/LLM from existing pipeline builders
- ConsentStateTracker for state management (Batch 1)
- ConsentRegistry.create_contract() for contract creation
- ConsentGatedWriter for persistence enforcement
- EventLog for audit trail
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# ── Consent prompt ───────────────────────────────────────────────────

CONSENT_SYSTEM_PROMPT = """\
You are managing a consent conversation for an ambient sensing system. \
Your ONLY job is to explain what the system records and understand the \
guest's response. You are NOT the assistant — you are the consent facilitator.

WHAT THE SYSTEM RECORDS:
- Audio from the room microphone (conversations, music, ambient sound)
- Video from cameras in the room
- Presence detection (who is in the room)

WHAT HAPPENS WITH RECORDINGS:
- Audio is transcribed and indexed for the operator's personal search
- Video frames are analyzed for activity detection
- Nothing is shared with anyone or sent to the cloud
- The guest can ask to see or export any data about them at any time
- The guest can revoke consent at any time and all their data is deleted

YOUR BEHAVIOR:
- Start by briefly explaining what's recorded and asking if they're OK with it
- If they say yes: call record_consent_decision with decision="grant"
- If they say no: call record_consent_decision with decision="refuse"
- If they ask a question: answer it from the information above, then ask again
- If they give an ambiguous answer ("I guess", "whatever"): ask for clarification
- If they want partial consent (audio but not video): call record_consent_decision \
with the specific scope they agreed to

CRITICAL RULES:
- NEVER assume consent from ambiguous responses
- NEVER pressure the guest or ask "are you sure?" after a refusal
- Accept refusal immediately and gracefully
- Maximum 3 clarification rounds, then say the operator can help
- You MUST call record_consent_decision when you get a clear answer
- Keep responses short (1-3 sentences)
"""

# ── Tool schemas ─────────────────────────────────────────────────────

CONSENT_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "record_consent_decision",
            "description": (
                "Record the guest's consent decision. Call this when the guest "
                "gives a clear affirmative or negative response."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "decision": {
                        "type": "string",
                        "enum": ["grant", "refuse"],
                        "description": "The guest's decision: grant or refuse consent",
                    },
                    "scope": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Data categories consented to. "
                            "Options: audio, video, transcription, presence. "
                            "Only include categories the guest explicitly agreed to. "
                            "For a full yes, include all. For refusal, leave empty."
                        ),
                    },
                },
                "required": ["decision"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_clarification",
            "description": (
                "Log that clarification was needed. Call when the guest's "
                "response is ambiguous and you need to ask again."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Why clarification is needed",
                    },
                },
                "required": ["reason"],
            },
        },
    },
]


# ── Consent session state ────────────────────────────────────────────


@dataclass
class ConsentSessionState:
    """Tracks the consent conversation progress."""

    clarification_count: int = 0
    max_clarifications: int = 3
    decision: str | None = None  # "grant" | "refuse" | None
    scope: list[str] = field(default_factory=list)
    resolved: bool = False
    started_at: float = field(default_factory=time.time)
    guest_first_seen: float = 0.0


# ── Tool handlers ────────────────────────────────────────────────────


def handle_record_consent_decision(
    state: ConsentSessionState,
    consent_tracker: object | None = None,
    event_log: object | None = None,
    **kwargs,
) -> str:
    """Handle the record_consent_decision tool call.

    This is where the actual consent decision is recorded. The LLM
    classifies the utterance; this function records the decision.
    """
    decision = kwargs.get("decision", "")
    scope = kwargs.get("scope", [])

    if decision not in ("grant", "refuse"):
        return json.dumps({"error": f"Invalid decision: {decision}. Must be 'grant' or 'refuse'."})

    state.decision = decision
    state.scope = scope if isinstance(scope, list) else []
    state.resolved = True

    if decision == "grant":
        # Create consent contract
        scope_set = (
            frozenset(scope)
            if scope
            else frozenset({"audio", "video", "transcription", "presence"})
        )
        try:
            from agents._governance import load_contracts

            registry = load_contracts()
            contract = registry.create_contract(
                person_id="guest",
                scope=scope_set,
            )
            log.info(
                "Consent granted via voice session: %s (scope: %s)", contract.id, sorted(scope_set)
            )

            if consent_tracker is not None:
                consent_tracker.grant_consent()

            if event_log is not None:
                event_log.emit(
                    "consent_granted_voice",
                    contract_id=contract.id,
                    scope=sorted(scope_set),
                )

            return json.dumps(
                {
                    "status": "recorded",
                    "decision": "grant",
                    "contract_id": contract.id,
                    "scope": sorted(scope_set),
                    "message": "Thank them naturally and let them know they can change their mind anytime.",
                }
            )
        except Exception as e:
            log.error("Failed to create consent contract: %s", e)
            return json.dumps({"error": f"Failed to create contract: {e}"})

    else:  # refuse
        log.info("Consent refused via voice session")

        if consent_tracker is not None:
            consent_tracker.refuse_consent()

        if event_log is not None:
            event_log.emit("consent_refused_voice")

        # Trigger purge of person-adjacent data from this session
        _purge_session_data(state.guest_first_seen)

        return json.dumps(
            {
                "status": "recorded",
                "decision": "refuse",
                "message": (
                    "Acknowledge gracefully. Say something like: "
                    "'No problem at all — the system will keep everything paused while you're here.'"
                ),
            }
        )


def handle_request_clarification(
    state: ConsentSessionState,
    **kwargs,
) -> str:
    """Handle the request_clarification tool call."""
    reason = kwargs.get("reason", "unclear response")
    state.clarification_count += 1

    if state.clarification_count >= state.max_clarifications:
        return json.dumps(
            {
                "status": "max_clarifications_reached",
                "message": (
                    "You've asked for clarification several times. Suggest that "
                    "the operator can explain in person: 'I want to make sure I get "
                    "this right — [operator] can walk you through it if that's easier.'"
                ),
            }
        )

    log.info(
        "Consent clarification requested (%d/%d): %s",
        state.clarification_count,
        state.max_clarifications,
        reason,
    )
    return json.dumps(
        {
            "status": "clarifying",
            "round": state.clarification_count,
            "max_rounds": state.max_clarifications,
        }
    )


def _purge_session_data(guest_first_seen: float) -> None:
    """Purge FLAC segments and any derived data from the guest's visit.

    Called when consent is refused. Identifies FLAC segments overlapping
    with the guest's presence and deletes them.
    """

    raw_dir = Path.home() / "audio-recording" / "raw"
    archive_dir = Path.home() / "audio-recording" / "archive"

    if not raw_dir.exists():
        return

    # FLAC files are named rec-YYYYMMDD-HHMMSS.flac with 15-min segments
    # Find any created after guest_first_seen
    purged = 0
    for flac in raw_dir.glob("rec-*.flac"):
        try:
            if flac.stat().st_mtime >= guest_first_seen:
                flac.unlink()
                purged += 1
                log.info("Purged FLAC segment: %s", flac.name)
        except Exception:
            pass

    # Also check archive for any processed copies
    if archive_dir.exists():
        for md_file in archive_dir.glob("*.md"):
            try:
                if md_file.stat().st_mtime >= guest_first_seen:
                    md_file.unlink()
                    purged += 1
            except Exception:
                pass

    if purged:
        log.info("Purged %d files from consent refusal", purged)


# ── Session builder ──────────────────────────────────────────────────


def build_consent_tools_for_llm(
    llm_service,
    consent_tracker=None,
    event_log=None,
):
    """Register consent tool handlers on an LLM service.

    Uses the same pattern as tools.register_tool_handlers() but with
    only the two consent tools.
    """
    state = ConsentSessionState()

    if consent_tracker is not None:
        state.guest_first_seen = getattr(consent_tracker, "_guest_first_seen", 0.0) or 0.0

    async def _on_record_decision(function_name, tool_call_id, args, llm, context, result_callback):
        result = handle_record_consent_decision(
            state, consent_tracker=consent_tracker, event_log=event_log, **args
        )
        await result_callback(result)

    async def _on_clarification(function_name, tool_call_id, args, llm, context, result_callback):
        result = handle_request_clarification(state, **args)
        await result_callback(result)

    llm_service.register_function("record_consent_decision", _on_record_decision)
    llm_service.register_function("request_clarification", _on_clarification)

    return state
