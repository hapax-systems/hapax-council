"""Voice assistant tool schemas and handlers for Pipecat function calling.

Defines FunctionSchema objects for each tool and async handlers that execute
when the LLM calls them mid-conversation.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from openai import OpenAI
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from qdrant_client.models import FieldCondition, Filter, MatchValue

from agents._config import embed, get_qdrant_grpc
from agents._google_auth import build_service
from agents.hapax_daimonion.desktop_tools import (
    DESKTOP_TOOL_SCHEMAS,
    handle_confirm_open_app,
    handle_focus_window,
    handle_get_desktop_state,
    handle_open_app,
    handle_switch_workspace,
)

if TYPE_CHECKING:
    from pipecat.services.openai.llm import OpenAILLMService

    from agents.hapax_daimonion.config import DaimonionConfig

log = logging.getLogger(__name__)

# Module-level state for SMS confirmation flow and config reference
_pending_sms: dict[str, dict] = {}
_daimonion_config = None

# Capturer instances — populated during tool registration
_webcam_capturer = None
_screen_capturer = None

# ---------------------------------------------------------------------------
# Tool schema definitions
# ---------------------------------------------------------------------------

_search_documents = FunctionSchema(
    name="search_documents",
    description=(
        "Search indexed documents, emails, calendar events, notes, "
        "and browsing history via semantic search"
    ),
    properties={
        "query": {
            "type": "string",
            "description": "Natural language search query",
        },
        "source_filter": {
            "type": "string",
            "enum": [
                "gmail",
                "gcalendar",
                "gdrive",
                "obsidian",
                "chrome",
                "claude-code",
                "weather",
                "git",
                "langfuse",
                "ambient-audio",
                "health_connect",
                "youtube",
            ],
            "description": "Optional: filter results to a specific source",
        },
        "max_results": {
            "type": "integer",
            "description": "Number of results to return (default 5)",
        },
    },
    required=["query"],
)

_search_drive = FunctionSchema(
    name="search_drive",
    description="Search Google Drive documents and files",
    properties={
        "query": {
            "type": "string",
            "description": "Natural language search query",
        },
        "max_results": {
            "type": "integer",
            "description": "Number of results to return (default 5)",
        },
    },
    required=["query"],
)

_get_calendar_today = FunctionSchema(
    name="get_calendar_today",
    description="Get today's and upcoming calendar events in real time",
    properties={
        "days_ahead": {
            "type": "integer",
            "description": "How many days to look ahead (default 2, max 7)",
        },
    },
    required=[],
)

_search_emails = FunctionSchema(
    name="search_emails",
    description="Search recent emails by sender, subject, or content",
    properties={
        "query": {
            "type": "string",
            "description": "Search query (natural language or Gmail search syntax)",
        },
        "max_results": {
            "type": "integer",
            "description": "Number of results (default 5)",
        },
        "recent_only": {
            "type": "boolean",
            "description": "If true, fetch directly from Gmail for freshest results",
        },
    },
    required=["query"],
)

_send_sms = FunctionSchema(
    name="send_sms",
    description=(
        "Prepare an SMS message for sending. Returns a confirmation prompt — "
        "the message is NOT sent until confirm_send_sms is called"
    ),
    properties={
        "recipient": {
            "type": "string",
            "description": "Contact name (e.g. 'Wife') or phone number",
        },
        "message": {
            "type": "string",
            "description": "The text message to send",
        },
    },
    required=["recipient", "message"],
)

_confirm_send_sms = FunctionSchema(
    name="confirm_send_sms",
    description="Confirm and send a previously prepared SMS message",
    properties={
        "confirmation_id": {
            "type": "string",
            "description": "The confirmation ID from the send_sms response",
        },
    },
    required=["confirmation_id"],
)

_analyze_scene = FunctionSchema(
    name="analyze_scene",
    description=("Capture images from cameras and/or screen and analyze what is visible"),
    properties={
        "cameras": {
            "type": "array",
            "items": {"type": "string", "enum": ["operator", "hardware", "screen"]},
            "description": "Which sources to capture (default: all available)",
        },
        "question": {
            "type": "string",
            "description": "Specific question about the scene (default: general description)",
        },
    },
    required=[],
)

_get_system_status = FunctionSchema(
    name="get_system_status",
    description="Check system health, infrastructure status, and GPU VRAM usage",
    properties={
        "category": {
            "type": "string",
            "enum": ["docker", "gpu", "services", "network", "voice"],
            "description": "Filter to a specific check group (default: summary of all)",
        },
    },
    required=[],
)

_generate_image = FunctionSchema(
    name="generate_image",
    description=(
        "Generate or edit an image using AI. Can optionally capture a photo "
        "from a camera first as a starting point. The result is saved to disk "
        "and displayed on screen."
    ),
    properties={
        "prompt": {
            "type": "string",
            "description": "What to generate or how to edit the captured image",
        },
        "camera_source": {
            "type": "string",
            "enum": ["operator", "hardware", "screen"],
            "description": "Optional: capture a photo first as input for editing",
        },
    },
    required=["prompt"],
)

# ── Consent query tools ────────────────────────────────────────────────

_check_consent_status = FunctionSchema(
    name="check_consent_status",
    description=(
        "Check a person's consent status — whether they have an active "
        "consent contract, what scope it covers, and what happens if they "
        "enter the room. Use when the operator asks about consent for a "
        "specific person (e.g. 'what's my wife's consent status?')."
    ),
    properties={
        "person_id": {
            "type": "string",
            "description": "Person identifier (e.g. 'wife', 'friend', 'guest')",
        },
    },
    required=["person_id"],
)

_describe_consent_flow = FunctionSchema(
    name="describe_consent_flow",
    description=(
        "Describe what happens when a new person enters the room — the "
        "consent detection, offering, and resolution flow. Use when the "
        "operator asks 'what happens if someone walks in?'"
    ),
    properties={},
    required=[],
)

_check_governance_health = FunctionSchema(
    name="check_governance_health",
    description=(
        "Check the governance heartbeat — overall consent and authority "
        "health score. Use when the operator asks about governance status, "
        "consent coverage, or system health."
    ),
    properties={},
    required=[],
)

_get_current_time = FunctionSchema(
    name="get_current_time",
    description="Get the current date and time",
    properties={},
    required=[],
)

_get_weather = FunctionSchema(
    name="get_weather",
    description="Get the latest weather conditions",
    properties={},
    required=[],
)

_get_briefing = FunctionSchema(
    name="get_briefing",
    description="Get today's system briefing summary and action items",
    properties={},
    required=[],
)

_query_scene_inventory = FunctionSchema(
    name="query_scene_inventory",
    description=(
        "Query what objects are currently visible in the scene. "
        "Returns detected objects with labels, cameras, confidence, and mobility."
    ),
    properties={
        "label": {
            "type": "string",
            "description": "Filter by object label (e.g. 'keyboard', 'person'). Omit for all.",
        },
        "camera": {
            "type": "string",
            "description": "Filter by camera role (e.g. 'brio-operator'). Omit for all.",
        },
    },
    required=[],
)

_highlight_detection = FunctionSchema(
    name="highlight_detection",
    description=(
        "Highlight a specific detected object in the detection overlay. "
        "Makes the halo pulse to draw operator attention."
    ),
    properties={
        "entity_id": {
            "type": "string",
            "description": "Entity ID from scene inventory to highlight.",
        },
        "annotation": {
            "type": "string",
            "description": "Optional text annotation to show near the object.",
        },
        "duration_s": {
            "type": "number",
            "description": "How long to highlight in seconds. Default 5.",
        },
    },
    required=["entity_id"],
)

_set_detection_layers = FunctionSchema(
    name="set_detection_layers",
    description=(
        "Control the detection overlay visibility and detail level. "
        "Tier 1 = ambient halos, tier 2 = labels on hover, tier 3 = full detail."
    ),
    properties={
        "visible": {
            "type": "boolean",
            "description": "Whether the detection overlay is visible.",
        },
        "tier": {
            "type": "integer",
            "description": "Detail tier: 1 (halos), 2 (hover labels), 3 (full). Default 1.",
            "enum": [1, 2, 3],
        },
    },
    required=["visible"],
)

_query_person_details = FunctionSchema(
    name="query_person_details",
    description=(
        "Get enriched details about a person visible in the scene — gaze direction, "
        "emotion, posture, gesture, action, depth, mobility, and dwell time."
    ),
    properties={
        "entity_id": {
            "type": "string",
            "description": "Entity ID of the person. Omit to get the first/operator person.",
        },
        "camera": {
            "type": "string",
            "description": "Filter by camera role. Omit for any camera.",
        },
    },
    required=[],
)

_query_object_motion = FunctionSchema(
    name="query_object_motion",
    description=(
        "Query temporal motion data for a tracked object — velocity, direction, "
        "dwell time, entering/exiting status, and sighting history."
    ),
    properties={
        "label": {
            "type": "string",
            "description": "Object label to query (e.g. 'cup', 'phone'). Omit if using entity_id.",
        },
        "entity_id": {
            "type": "string",
            "description": "Specific entity ID. Omit if using label.",
        },
    },
    required=[],
)

_query_scene_state = FunctionSchema(
    name="query_scene_state",
    description=(
        "Get the current scene classification state — scene type, CLIP scene state, "
        "audio scene, inferred activity, flow state, and object summary."
    ),
    properties={},
    required=[],
)

TOOL_SCHEMAS: list[FunctionSchema] = [
    _search_documents,
    _search_drive,
    _get_calendar_today,
    _search_emails,
    _send_sms,
    _confirm_send_sms,
    _analyze_scene,
    _get_system_status,
    _generate_image,
    _get_current_time,
    _get_weather,
    _get_briefing,
    _check_consent_status,
    _describe_consent_flow,
    _check_governance_health,
    _query_scene_inventory,
    _highlight_detection,
    _set_detection_layers,
    _query_person_details,
    _query_object_motion,
    _query_scene_state,
]


def get_tool_schemas(guest_mode: bool = False) -> ToolsSchema | None:
    """Return ToolsSchema for all voice tools. None if guest_mode."""
    if guest_mode:
        return None
    return ToolsSchema(standard_tools=TOOL_SCHEMAS + DESKTOP_TOOL_SCHEMAS)


# ---------------------------------------------------------------------------
# Tool handler implementations
# ---------------------------------------------------------------------------

_DOCUMENTS_COLLECTION = "documents"
_DEFAULT_MAX_RESULTS = 5
_MAX_MAX_RESULTS = 20
_SCORE_THRESHOLD = 0.3

# Legacy source_service values that should be included when filtering.
# The ingest pipeline changed tag names over time; OR-match covers both.
_SOURCE_ALIASES: dict[str, list[str]] = {
    "gdrive": ["gdrive", "drive"],
}


async def handle_search_documents(params) -> None:
    """Search Qdrant documents collection with semantic similarity."""
    query = params.arguments["query"]
    source = params.arguments.get("source_filter")
    max_results = min(params.arguments.get("max_results", _DEFAULT_MAX_RESULTS), _MAX_MAX_RESULTS)

    try:
        vector = embed(query, prefix="search_query")
        client = get_qdrant_grpc()

        query_filter = None
        if source:
            aliases = _SOURCE_ALIASES.get(source, [source])
            if len(aliases) == 1:
                query_filter = Filter(
                    must=[FieldCondition(key="source_service", match=MatchValue(value=aliases[0]))]
                )
            else:
                query_filter = Filter(
                    should=[
                        FieldCondition(key="source_service", match=MatchValue(value=v))
                        for v in aliases
                    ]
                )

        results = client.query_points(
            _DOCUMENTS_COLLECTION,
            query=vector,
            query_filter=query_filter,
            limit=max_results,
            score_threshold=_SCORE_THRESHOLD,
        )

        if not results.points:
            await params.result_callback("No relevant documents found.")
            return

        chunks = []
        for p in results.points:
            filename = p.payload.get("filename", "unknown")
            text = p.payload.get("text", "")
            source_svc = p.payload.get("source_service", "")
            chunks.append(f"[{filename} ({source_svc}), relevance={p.score:.2f}]\n{text}")

        await params.result_callback("\n\n---\n\n".join(chunks))

    except Exception as exc:
        log.exception("search_documents failed")
        await params.result_callback(f"Search failed: {exc}")


# ---------------------------------------------------------------------------
# get_calendar_today handler
# ---------------------------------------------------------------------------

_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
_GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


async def handle_get_calendar_today(params) -> None:
    """Fetch upcoming calendar events from Google Calendar API."""
    days_ahead = min(params.arguments.get("days_ahead", 2), 7)

    try:
        service = build_service("calendar", "v3", [_CALENDAR_SCOPE])
        now = datetime.now(UTC)
        time_max = now + timedelta(days=days_ahead)

        result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now.isoformat(),
                timeMax=time_max.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=20,
            )
            .execute()
        )

        events = result.get("items", [])
        if not events:
            await params.result_callback("Your calendar is clear — no upcoming events.")
            return

        lines = []
        for event in events:
            summary = event.get("summary", "(no title)")
            start = event["start"].get("dateTime", event["start"].get("date", ""))
            location = event.get("location", "")
            attendees = event.get("attendees", [])
            attendee_names = ", ".join(
                a.get("displayName", a.get("email", "")) for a in attendees[:5]
            )

            line = f"- {start}: {summary}"
            if location:
                line += f" @ {location}"
            if attendee_names:
                line += f" (with {attendee_names})"
            lines.append(line)

        await params.result_callback("\n".join(lines))

    except Exception as exc:
        log.exception("get_calendar_today failed")
        await params.result_callback(f"Calendar lookup failed: {exc}")


# ---------------------------------------------------------------------------
# search_emails handler
# ---------------------------------------------------------------------------


async def handle_search_emails(params) -> None:
    """Search emails via Qdrant or Gmail API."""
    query = params.arguments["query"]
    max_results = min(params.arguments.get("max_results", _DEFAULT_MAX_RESULTS), _MAX_MAX_RESULTS)
    recent_only = params.arguments.get("recent_only", False)

    try:
        if recent_only:
            await _search_emails_gmail(params, query, max_results)
        else:
            await _search_emails_qdrant(params, query, max_results)
    except Exception as exc:
        log.exception("search_emails failed")
        await params.result_callback(f"Email search failed: {exc}")


async def _search_emails_qdrant(params, query: str, max_results: int) -> None:
    """Search emails via Qdrant semantic search."""
    vector = embed(query, prefix="search_query")
    client = get_qdrant_grpc()
    query_filter = Filter(
        must=[FieldCondition(key="source_service", match=MatchValue(value="gmail"))]
    )
    results = client.query_points(
        _DOCUMENTS_COLLECTION,
        query=vector,
        query_filter=query_filter,
        limit=max_results,
        score_threshold=_SCORE_THRESHOLD,
    )
    if not results.points:
        await params.result_callback("No matching emails found.")
        return

    chunks = []
    for p in results.points:
        filename = p.payload.get("filename", "")
        text = p.payload.get("text", "")
        chunks.append(f"[{filename}, relevance={p.score:.2f}]\n{text}")
    await params.result_callback("\n\n---\n\n".join(chunks))


async def _search_emails_gmail(params, query: str, max_results: int) -> None:
    """Search emails directly via Gmail API for freshest results."""
    service = build_service("gmail", "v1", [_GMAIL_SCOPE])
    result = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    messages = result.get("messages", [])
    if not messages:
        await params.result_callback("No matching emails found.")
        return

    lines = []
    for msg_ref in messages[:max_results]:
        msg = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=msg_ref["id"],
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            )
            .execute()
        )
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        snippet = msg.get("snippet", "")
        lines.append(
            f"- From: {headers.get('From', '?')} | "
            f"Subject: {headers.get('Subject', '?')} | "
            f"Date: {headers.get('Date', '?')}\n  {snippet}"
        )
    await params.result_callback("\n".join(lines))


# ---------------------------------------------------------------------------
# send_sms / confirm_send_sms handlers
# ---------------------------------------------------------------------------


def _get_sms_password(pass_key: str) -> str:
    """Retrieve SMS gateway password from pass store."""
    result = subprocess.run(
        ["pass", "show", pass_key],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pass show {pass_key} failed: {result.stderr}")
    return result.stdout.strip()


async def handle_send_sms(params) -> None:
    """Prepare an SMS for sending — returns confirmation, does NOT send yet."""
    recipient = params.arguments["recipient"]
    message = params.arguments["message"]

    cfg = _daimonion_config
    if cfg is None:
        await params.result_callback({"status": "error", "detail": "SMS not configured"})
        return

    # Resolve contact name to phone number
    phone = cfg.sms_contacts.get(recipient)
    if phone is None:
        # Try case-insensitive lookup
        for name, number in cfg.sms_contacts.items():
            if name.lower() == recipient.lower():
                phone = number
                break

    if phone is None:
        # Check if recipient is already a phone number
        if recipient.startswith("+"):
            phone = recipient
        else:
            await params.result_callback(
                {
                    "status": "error",
                    "detail": f"Contact '{recipient}' not found. Known contacts: {', '.join(cfg.sms_contacts.keys())}",
                }
            )
            return

    confirmation_id = str(uuid.uuid4())[:8]
    _pending_sms[confirmation_id] = {
        "phone": phone,
        "message": message,
        "recipient": recipient,
        "created_at": time.monotonic(),
    }

    await params.result_callback(
        {
            "status": "pending_confirmation",
            "confirmation_id": confirmation_id,
            "recipient": recipient,
            "phone": phone,
            "message": message,
        }
    )


_PENDING_TTL_S = 120  # Pending confirmations expire after 2 minutes


async def handle_confirm_send_sms(params) -> None:
    """Confirm and send a previously prepared SMS."""
    confirmation_id = params.arguments["confirmation_id"]

    pending = _pending_sms.pop(confirmation_id, None)
    if pending is None:
        await params.result_callback(
            {
                "status": "error",
                "detail": "Confirmation not found or expired.",
            }
        )
        return

    # Check expiry
    if time.monotonic() - pending.get("created_at", 0) > _PENDING_TTL_S:
        await params.result_callback(
            {"status": "error", "detail": "Confirmation expired. Please prepare the SMS again."}
        )
        return

    cfg = _daimonion_config
    if cfg is None or not cfg.sms_gateway_host:
        await params.result_callback({"status": "error", "detail": "SMS gateway not configured"})
        return

    try:
        password = _get_sms_password(cfg.sms_gateway_pass_key)
        url = f"http://{cfg.sms_gateway_host}/messages"
        response = httpx.post(
            url,
            json={
                "phoneNumbers": [pending["phone"]],
                "textMessage": {"text": pending["message"]},
            },
            auth=(cfg.sms_gateway_user, password),
            timeout=10.0,
        )

        if response.status_code in (200, 201, 202):
            await params.result_callback(
                {
                    "status": "sent",
                    "recipient": pending["recipient"],
                    "phone": pending["phone"],
                }
            )
        else:
            await params.result_callback(
                {
                    "status": "error",
                    "detail": f"SMS gateway returned {response.status_code}: {response.text}",
                }
            )

    except Exception as exc:
        log.exception("SMS send failed")
        await params.result_callback({"status": "error", "detail": f"SMS send failed: {exc}"})


# ---------------------------------------------------------------------------
# analyze_scene handler
# ---------------------------------------------------------------------------


def _vision_analyze(images: list[str], question: str) -> str:
    """Send base64 images to Gemini Flash for visual analysis via LiteLLM."""
    from agents.hapax_daimonion.config import LITELLM_BASE

    base_url = LITELLM_BASE
    api_key = os.environ.get("LITELLM_API_KEY", "not-set")
    client = OpenAI(base_url=base_url, api_key=api_key)

    content = []
    for img in images:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img}"},
            }
        )
    content.append({"type": "text", "text": question or "Describe what you see in detail."})

    response = client.chat.completions.create(
        model="gemini-2.0-flash",
        messages=[{"role": "user", "content": content}],
        max_tokens=500,
    )
    return response.choices[0].message.content


async def handle_analyze_scene(params) -> None:
    """Capture images from cameras/screen and analyze with vision model."""
    cameras = params.arguments.get("cameras", ["operator", "hardware", "screen"])
    question = params.arguments.get("question", "Describe what you see.")

    try:
        images = []

        if _webcam_capturer is not None:
            for role in cameras:
                if role in ("operator", "hardware"):
                    _webcam_capturer.reset_cooldown(role)
                    frame = _webcam_capturer.capture(role)
                    if frame:
                        images.append(frame)

        if "screen" in cameras and _screen_capturer is not None:
            _screen_capturer.reset_cooldown()
            screen = _screen_capturer.capture()
            if screen:
                images.append(screen)

        if not images:
            await params.result_callback(
                "Couldn't capture any images — no cameras or screen available."
            )
            return

        analysis = _vision_analyze(images, question)
        await params.result_callback(analysis)

    except Exception as exc:
        log.exception("analyze_scene failed")
        await params.result_callback(f"Scene analysis failed: {exc}")


# ---------------------------------------------------------------------------
# get_system_status handler
# ---------------------------------------------------------------------------

_HEALTH_CACHE_PATH = Path.home() / ".cache" / "hapax" / "health-monitor" / "latest.json"
_HEALTH_CACHE_MAX_AGE_S = 900  # 15 minutes


async def _run_health_checks(category: str | None = None) -> list[dict]:
    """Run health checks, using cache if fresh enough."""
    # Try cache first
    if _HEALTH_CACHE_PATH.exists():
        age = time.time() - _HEALTH_CACHE_PATH.stat().st_mtime
        if age < _HEALTH_CACHE_MAX_AGE_S:
            try:
                data = json.loads(_HEALTH_CACHE_PATH.read_text())
                results = data if isinstance(data, list) else data.get("results", [])
                if category:
                    results = [r for r in results if r.get("group") == category]
                return results
            except Exception:
                pass

    # Fall back to running checks directly
    try:
        from agents.health_monitor import CHECK_REGISTRY

        all_results = []
        groups = (
            [category] if category and category in CHECK_REGISTRY else list(CHECK_REGISTRY.keys())
        )
        for group in groups:
            for check_fn in CHECK_REGISTRY.get(group, []):
                results = await check_fn()
                for r in results:
                    all_results.append(
                        {
                            "name": r.name,
                            "group": r.group,
                            "status": r.status.value
                            if hasattr(r.status, "value")
                            else str(r.status),
                            "message": r.message,
                        }
                    )
        return all_results
    except Exception as exc:
        log.warning("Health check execution failed: %s", exc)
        return []


async def handle_get_system_status(params) -> None:
    """Report current system health and infrastructure status."""
    category = params.arguments.get("category")

    try:
        results = await _run_health_checks(category)

        if not results:
            await params.result_callback("No health check results available.")
            return

        lines = []
        for r in results:
            name = r.get("name", "?")
            status = r.get("status", "?")
            message = r.get("message", "")
            lines.append(f"- {name}: {status} — {message}")

        await params.result_callback("\n".join(lines))

    except Exception as exc:
        log.exception("get_system_status failed")
        await params.result_callback(f"Status check failed: {exc}")


# ---------------------------------------------------------------------------
# search_drive handler (thin wrapper)
# ---------------------------------------------------------------------------


async def handle_search_drive(params) -> None:
    """Search Google Drive documents — queries both 'gdrive' and legacy 'drive' tags."""
    query = params.arguments["query"]
    max_results = min(params.arguments.get("max_results", _DEFAULT_MAX_RESULTS), _MAX_MAX_RESULTS)

    try:
        vector = embed(query, prefix="search_query")
        client = get_qdrant_grpc()

        query_filter = Filter(
            should=[
                FieldCondition(key="source_service", match=MatchValue(value="gdrive")),
                FieldCondition(key="source_service", match=MatchValue(value="drive")),
            ]
        )

        results = client.query_points(
            _DOCUMENTS_COLLECTION,
            query=vector,
            query_filter=query_filter,
            limit=max_results,
            score_threshold=_SCORE_THRESHOLD,
        )

        if not results.points:
            await params.result_callback("No Drive documents found.")
            return

        chunks = []
        for p in results.points:
            filename = p.payload.get("filename", "unknown")
            text = p.payload.get("text", "")
            source_svc = p.payload.get("source_service", "")
            chunks.append(f"[{filename} ({source_svc}), relevance={p.score:.2f}]\n{text}")

        await params.result_callback("\n\n---\n\n".join(chunks))

    except Exception as exc:
        log.exception("search_drive failed")
        await params.result_callback(f"Drive search failed: {exc}")


# ---------------------------------------------------------------------------
# generate_image handler
# ---------------------------------------------------------------------------

_IMAGE_OUTPUT_DIR = Path.home() / "Pictures" / "hapax-generated"


def _genai_generate_image(prompt: str) -> bytes | None:
    """Call Imagen 3.0 via google-genai SDK. Returns PNG bytes or None."""
    try:
        from google import genai

        client = genai.Client()
        response = client.models.generate_images(
            model="imagen-3.0-generate-002",
            prompt=prompt,
            config=genai.types.GenerateImagesConfig(number_of_images=1),
        )

        if not response.generated_images:
            return None

        return response.generated_images[0].image.image_bytes
    except Exception as exc:
        log.error("Imagen generation failed: %s", exc)
        return None


async def handle_generate_image(params) -> None:
    """Generate an image from a text prompt, save to disk, and display."""
    prompt = params.arguments["prompt"]
    camera = params.arguments.get("camera_source")

    try:
        # Optional camera capture — Imagen 3.0 is text-only, so the capture
        # enriches the prompt context rather than sending the image directly.
        input_image_b64 = None
        if camera == "screen" and _screen_capturer is not None:
            _screen_capturer.reset_cooldown()
            input_image_b64 = _screen_capturer.capture()
        elif camera in ("operator", "hardware") and _webcam_capturer is not None:
            _webcam_capturer.reset_cooldown(camera)
            input_image_b64 = _webcam_capturer.capture(camera)

        # Build prompt with camera context
        full_prompt = prompt
        if input_image_b64:
            full_prompt = f"Edit this image: {prompt}"

        # Generate image
        image_bytes = _genai_generate_image(full_prompt)

        if image_bytes is None:
            await params.result_callback({"status": "error", "detail": "No image generated"})
            return

        # Save to disk
        _IMAGE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = _IMAGE_OUTPUT_DIR / f"{timestamp}.png"
        output_path.write_bytes(image_bytes)

        # Display on screen
        subprocess.Popen(["xdg-open", str(output_path)])

        await params.result_callback(
            {
                "status": "generated",
                "path": str(output_path),
                "description": "Image saved and opened on screen",
            }
        )

    except Exception as exc:
        log.exception("generate_image failed")
        await params.result_callback(
            {"status": "error", "detail": f"Image generation failed: {exc}"}
        )


# ---------------------------------------------------------------------------
# Utility tool handlers
# ---------------------------------------------------------------------------

_WEATHER_DIR = Path.home() / "documents" / "rag-sources" / "weather"
_BRIEFING_PATH = Path(__file__).resolve().parent.parent.parent / "profiles" / "briefing.md"
_BRIEFING_MAX_CHARS = 2000


async def handle_get_current_time(params) -> None:
    """Return the current date and time in a spoken-natural format."""
    now = datetime.now()
    formatted = now.strftime("%A, %B %d, %Y at %-I:%M %p")
    await params.result_callback(formatted)


async def handle_get_weather(params) -> None:
    """Return the latest weather observation from disk."""
    try:
        weather_files = sorted(_WEATHER_DIR.glob("weather-*.md"))
        if not weather_files:
            await params.result_callback("No weather data available.")
            return

        latest = weather_files[-1]
        content = latest.read_text()

        # Return the markdown body (after frontmatter)
        parts = content.split("---", 2)
        if len(parts) >= 3:
            await params.result_callback(parts[2].strip())
        else:
            await params.result_callback(content.strip())

    except Exception as exc:
        log.exception("get_weather failed")
        await params.result_callback(f"Weather lookup failed: {exc}")


async def handle_get_briefing(params) -> None:
    """Return today's system briefing summary."""
    try:
        if not _BRIEFING_PATH.exists():
            await params.result_callback("No briefing available today.")
            return

        content = _BRIEFING_PATH.read_text()
        if len(content) > _BRIEFING_MAX_CHARS:
            content = content[:_BRIEFING_MAX_CHARS] + "\n\n[truncated]"
        await params.result_callback(content)

    except Exception as exc:
        log.exception("get_briefing failed")
        await params.result_callback(f"Briefing lookup failed: {exc}")


# ---------------------------------------------------------------------------
# Consent query handlers
# ---------------------------------------------------------------------------


async def handle_check_consent_status(params) -> None:
    """Check consent status for a specific person."""
    person_id = params.arguments.get("person_id", "")
    try:
        from agents._governance import load_contracts
        from shared.governance.consent_channels import GuestContext, build_channel_menu

        registry = load_contracts()
        contract = registry.get_contract_for(person_id)

        if contract and contract.active:
            result = (
                f"{person_id} has an active consent contract.\n"
                f"Scope: {', '.join(sorted(contract.scope))}.\n"
                f"Created: {contract.created_at}.\n"
                f"If they enter the room, the system will recognize their consent "
                f"and operate normally for the consented data categories."
            )
        else:
            menu = build_channel_menu(guest=GuestContext())
            available = [o for o in menu.offers if o.available]
            channels = ", ".join(o.channel.name for o in available[:3])
            result = (
                f"{person_id} does NOT have an active consent contract.\n"
                f"If they enter the room:\n"
                f"1. The system detects their presence within ~5 seconds\n"
                f"2. All data persistence pauses immediately\n"
                f"3. The system offers consent via voice conversation\n"
                f"4. Available channels: {channels}\n"
                f"5. If they accept, a contract is created and data flows normally\n"
                f"6. If they refuse, everything captured during their visit is deleted"
            )

        # Check blast radius if contract exists
        if contract and contract.active:
            try:
                from logos.data.governance import collect_revocation_blast_radius

                blast = collect_revocation_blast_radius(person_id)
                if blast.total_items > 0:
                    result += (
                        f"\n\nRevocation impact: {blast.total_items} items would be purged "
                        f"({blast.qdrant_points} Qdrant points, {blast.carrier_facts} carrier facts)."
                    )
            except Exception:
                pass

    except Exception as e:
        result = f"Error checking consent status: {e}"

    await params.result_callback(result)


async def handle_describe_consent_flow(params) -> None:
    """Describe the consent detection and offering flow."""
    try:
        from shared.governance.consent_channels import build_channel_menu, check_channel_sufficiency

        sufficient, uncovered = check_channel_sufficiency()
        menu = build_channel_menu()
        available = [o for o in menu.offers if o.available]

        result = (
            "When someone enters this room, here's what happens:\n\n"
            "1. DETECTION: The camera detects a new face (face count goes above 1) "
            "or the microphone detects a non-operator voice. This takes ~2.5 seconds.\n\n"
            "2. DEBOUNCE: The system waits 5 seconds of sustained presence to avoid "
            "false triggers from someone just popping their head in.\n\n"
            "3. CURTAILMENT: All data persistence pauses immediately. The system "
            "continues perceiving (face detection, audio classification) but does NOT "
            "store, transcribe, or index anything about the guest.\n\n"
            "4. OFFERING: The system speaks through the speakers, explaining what it "
            "records and asking if the guest is comfortable. The guest can say yes, no, "
            "or ask questions. An LLM understands their natural language response.\n\n"
            "5. RESOLUTION:\n"
            "   - Accept: A consent contract is created. Data flows normally.\n"
            "   - Refuse: Everything captured during the visit is deleted.\n"
            "   - Questions: The system answers up to 3 clarifications.\n\n"
            f"Available consent channels ({len(available)}):\n"
        )
        for o in available:
            result += f"  - {o.channel.name} (friction: {o.friction.total:.1f})\n"
        result += f"\nChannel sufficiency: {'adequate' if sufficient else f'gaps in: {uncovered}'}"

    except Exception as e:
        result = f"Error describing consent flow: {e}"

    await params.result_callback(result)


async def handle_check_governance_health(params) -> None:
    """Check governance heartbeat and consent coverage."""
    try:
        from logos.data.governance import collect_governance_heartbeat

        hb = collect_governance_heartbeat()
        result = f"Governance health: {hb.label.upper()} ({hb.score})\n\nComponents:\n"
        for name, score in sorted(hb.components.items()):
            result += f"  - {name}: {score}\n"
        if hb.issues:
            result += "\nIssues:\n"
            for issue in hb.issues:
                result += f"  - {issue}\n"
        if hb.coverage:
            result += (
                f"\nConsent coverage:\n"
                f"  - Active contracts: {hb.coverage.active_contracts}\n"
                f"  - Persons covered: {', '.join(hb.coverage.persons_covered) or 'none'}\n"
            )

    except Exception as e:
        result = f"Error checking governance health: {e}"

    await params.result_callback(result)


# ---------------------------------------------------------------------------
# Scene inventory + detection overlay tools
# ---------------------------------------------------------------------------

PERCEPTION_STATE_PATH = Path.home() / ".cache" / "hapax-daimonion" / "perception-state.json"


async def handle_query_scene_inventory(params) -> None:
    """Query the scene inventory for visible objects."""
    label_filter = params.arguments.get("label", "")
    camera_filter = params.arguments.get("camera", "")

    try:
        data = json.loads(PERCEPTION_STATE_PATH.read_text())
        inventory = data.get("scene_inventory", {})
        objects = inventory.get("objects", [])

        if label_filter:
            objects = [o for o in objects if o.get("label", "") == label_filter]
        if camera_filter:
            objects = [o for o in objects if o.get("camera", "") == camera_filter]

        if not objects:
            result = "No objects matching that query in the scene inventory."
        else:
            lines = [f"Scene inventory: {len(objects)} objects"]
            for o in objects[:10]:
                lines.append(
                    f"  - {o.get('label')} (id: {o.get('entity_id')}) "
                    f"on {o.get('camera')}, "
                    f"confidence: {o.get('confidence', 0):.0%}, "
                    f"mobility: {o.get('mobility', 'unknown')}, "
                    f"seen: {o.get('seen_count', 0)}x"
                )
            result = "\n".join(lines)
    except (FileNotFoundError, json.JSONDecodeError):
        result = "Scene inventory unavailable (perception not running)."
    except Exception as e:
        result = f"Error querying scene inventory: {e}"

    await params.result_callback(result)


async def handle_highlight_detection(params) -> None:
    """Highlight a detection in the overlay via directive bridge."""
    entity_id = params.arguments.get("entity_id", "")
    annotation = params.arguments.get("annotation", "")
    duration_s = params.arguments.get("duration_s", 5)

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            directive = {
                "detection_highlight": entity_id,
                "detection_annotation_text": annotation,
                "source": "voice-tool",
            }
            resp = await client.post(
                "http://localhost:8051/api/logos/directive",
                json=directive,
            )
            if resp.status_code == 200:
                result = (
                    f"Highlighting {entity_id}"
                    + (f" with annotation '{annotation}'" if annotation else "")
                    + f" for {duration_s}s."
                )
            else:
                result = f"Directive failed: {resp.status_code}"
    except Exception as e:
        result = f"Error posting highlight directive: {e}"

    await params.result_callback(result)


async def handle_set_detection_layers(params) -> None:
    """Control detection overlay visibility and tier via directive bridge."""
    visible = params.arguments.get("visible", True)
    tier = params.arguments.get("tier", 1)

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            directive = {
                "detection_layer_visible": visible,
                "detection_tier": tier,
                "source": "voice-tool",
            }
            resp = await client.post(
                "http://localhost:8051/api/logos/directive",
                json=directive,
            )
            if resp.status_code == 200:
                state = "visible" if visible else "hidden"
                result = f"Detection overlay set to {state}, tier {tier}."
            else:
                result = f"Directive failed: {resp.status_code}"
    except Exception as e:
        result = f"Error posting layer directive: {e}"

    await params.result_callback(result)


# ---------------------------------------------------------------------------
# Scene intelligence tools (classification consumption)
# ---------------------------------------------------------------------------


async def handle_query_person_details(params) -> None:
    """Query enriched details about a person in the scene."""
    entity_id = params.arguments.get("entity_id", "")
    camera_filter = params.arguments.get("camera", "")

    try:
        data = json.loads(PERCEPTION_STATE_PATH.read_text())
        inventory = data.get("scene_inventory", {})
        objects = inventory.get("objects", [])

        # Filter to persons
        persons = [o for o in objects if o.get("label") == "person"]
        if entity_id:
            persons = [o for o in persons if o.get("entity_id") == entity_id]
        if camera_filter:
            persons = [o for o in persons if o.get("camera") == camera_filter]

        if not persons:
            result = "No persons matching that query in the scene."
        else:
            lines = []
            for p in persons[:5]:
                eid = p.get("entity_id", "?")
                cam = p.get("camera", "?")
                parts = [f"Person {eid} on {cam}:"]
                for key in (
                    "gaze_direction",
                    "emotion",
                    "posture",
                    "gesture",
                    "action",
                    "depth",
                    "mobility",
                ):
                    val = p.get(key)
                    if val and val not in ("unknown", "none", "None"):
                        parts.append(f"  {key}: {val}")
                # Dwell time from first_seen/last_seen
                first = p.get("first_seen", 0)
                last = p.get("last_seen", 0)
                if first and last:
                    dwell = last - first
                    parts.append(f"  dwell: {dwell:.0f}s")
                parts.append(f"  seen_count: {p.get('seen_count', 0)}")
                lines.append("\n".join(parts))
            result = "\n\n".join(lines)
    except (FileNotFoundError, json.JSONDecodeError):
        result = "Person details unavailable (perception not running)."
    except Exception as e:
        result = f"Error querying person details: {e}"

    await params.result_callback(result)


async def handle_query_object_motion(params) -> None:
    """Query temporal motion data for a tracked object."""
    label_filter = params.arguments.get("label", "")
    entity_id = params.arguments.get("entity_id", "")

    try:
        data = json.loads(PERCEPTION_STATE_PATH.read_text())
        inventory = data.get("scene_inventory", {})
        objects = inventory.get("objects", [])

        if entity_id:
            objects = [o for o in objects if o.get("entity_id") == entity_id]
        elif label_filter:
            objects = [o for o in objects if o.get("label") == label_filter]

        if not objects:
            result = "No objects matching that query."
        else:
            now = time.time()
            lines = []
            for o in objects[:5]:
                eid = o.get("entity_id", "?")
                label = o.get("label", "?")
                parts = [f"{label} ({eid}):"]
                parts.append(f"  mobility: {o.get('mobility', 'unknown')}")
                parts.append(f"  mobility_score: {o.get('mobility_score', 0):.2f}")
                parts.append(f"  seen_count: {o.get('seen_count', 0)}")

                first = o.get("first_seen", 0)
                last = o.get("last_seen", 0)
                if first and last:
                    dwell = last - first
                    parts.append(f"  dwell: {dwell:.0f}s")
                    age = now - last
                    parts.append(f"  last_seen: {age:.0f}s ago")

                # Sighting-based velocity estimation
                sightings = o.get("raw_sightings", [])
                if len(sightings) >= 2:
                    s0 = sightings[0]
                    s1 = sightings[-1]
                    dt = s1.get("t", 0) - s0.get("t", 0)
                    if dt > 0:
                        box0 = s0.get("box", [0, 0, 0, 0])
                        box1 = s1.get("box", [0, 0, 0, 0])
                        cx0 = (box0[0] + box0[2]) / 2
                        cy0 = (box0[1] + box0[3]) / 2
                        cx1 = (box1[0] + box1[2]) / 2
                        cy1 = (box1[1] + box1[3]) / 2
                        dx = cx1 - cx0
                        dy = cy1 - cy0
                        import math

                        dist = math.sqrt(dx * dx + dy * dy)
                        velocity = dist / dt
                        direction = math.degrees(math.atan2(dy, dx))
                        parts.append(f"  velocity: {velocity:.3f} px/s")
                        parts.append(f"  direction: {direction:.0f}°")

                # Camera history
                cameras = o.get("camera_history", [])
                if cameras:
                    parts.append(f"  cameras: {', '.join(cameras)}")

                lines.append("\n".join(parts))
            result = "\n\n".join(lines)
    except (FileNotFoundError, json.JSONDecodeError):
        result = "Object motion data unavailable (perception not running)."
    except Exception as e:
        result = f"Error querying object motion: {e}"

    await params.result_callback(result)


async def handle_query_scene_state(params) -> None:
    """Query the current scene classification state."""
    try:
        data = json.loads(PERCEPTION_STATE_PATH.read_text())

        scene_type = data.get("scene_type", "unknown")
        scene_state_clip = data.get("scene_state_clip", "")
        audio_scene = data.get("audio_scene", "silence")
        activity_mode = data.get("activity_mode", "unknown")
        production = data.get("production_activity", "")
        flow_state = data.get("flow_state", "idle")
        flow_score = data.get("flow_score", 0.0)

        lines = [
            "Scene classification state:",
            f"  scene_type (SigLIP): {scene_type}",
        ]
        if scene_state_clip:
            lines.append(f"  scene_state (CLIP): {scene_state_clip}")
        lines.append(f"  audio_scene: {audio_scene}")
        if production:
            lines.append(f"  production_activity: {production}")
        lines.append(f"  activity_mode: {activity_mode}")
        lines.append(f"  flow: {flow_state} ({flow_score:.2f})")

        # Object summary
        inventory = data.get("scene_inventory", {})
        objects = inventory.get("objects", [])
        if objects:
            person_count = sum(1 for o in objects if o.get("label") == "person")
            other_labels = sorted(
                {o.get("label", "") for o in objects if o.get("label") != "person"}
            )
            lines.append(f"  persons: {person_count}")
            if other_labels:
                lines.append(f"  objects: {', '.join(other_labels)}")

        result = "\n".join(lines)
    except (FileNotFoundError, json.JSONDecodeError):
        result = "Scene state unavailable (perception not running)."
    except Exception as e:
        result = f"Error querying scene state: {e}"

    await params.result_callback(result)


# ---------------------------------------------------------------------------
# Module-level state initialization
# ---------------------------------------------------------------------------


def init_tool_state(config: DaimonionConfig, webcam_capturer=None, screen_capturer=None) -> None:
    """Initialize module-level state needed by tool handlers.

    Called by both register_tool_handlers (Pipecat path) and
    get_openai_tools (conversation pipeline path).
    """
    global _daimonion_config, _webcam_capturer, _screen_capturer
    _daimonion_config = config
    _webcam_capturer = webcam_capturer
    _screen_capturer = screen_capturer


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_tool_handlers(
    llm: OpenAILLMService,
    config: DaimonionConfig,
    webcam_capturer=None,
    screen_capturer=None,
) -> None:
    """Register all async tool handlers on the LLM service.

    Args:
        llm: Pipecat OpenAILLMService instance.
        config: Voice daemon configuration.
        webcam_capturer: Optional WebcamCapturer for analyze_scene.
        screen_capturer: Optional ScreenCapturer for analyze_scene.
    """
    if not config.tools_enabled:
        log.info("Tools disabled by config")
        return

    init_tool_state(config, webcam_capturer, screen_capturer)

    llm.register_function("search_documents", handle_search_documents)
    llm.register_function("get_calendar_today", handle_get_calendar_today)
    llm.register_function("search_emails", handle_search_emails)
    llm.register_function("search_drive", handle_search_drive)
    llm.register_function("send_sms", handle_send_sms)
    llm.register_function("confirm_send_sms", handle_confirm_send_sms)
    llm.register_function("analyze_scene", handle_analyze_scene)
    llm.register_function("get_system_status", handle_get_system_status)
    llm.register_function("generate_image", handle_generate_image)
    llm.register_function("get_current_time", handle_get_current_time)
    llm.register_function("get_weather", handle_get_weather)
    llm.register_function("get_briefing", handle_get_briefing)

    llm.register_function("focus_window", handle_focus_window)
    llm.register_function("switch_workspace", handle_switch_workspace)
    llm.register_function("open_app", handle_open_app)
    llm.register_function("confirm_open_app", handle_confirm_open_app)
    llm.register_function("get_desktop_state", handle_get_desktop_state)

    # Consent query tools
    llm.register_function("check_consent_status", handle_check_consent_status)
    llm.register_function("describe_consent_flow", handle_describe_consent_flow)
    llm.register_function("check_governance_health", handle_check_governance_health)

    # Scene inventory / detection overlay tools
    llm.register_function("query_scene_inventory", handle_query_scene_inventory)
    llm.register_function("highlight_detection", handle_highlight_detection)
    llm.register_function("set_detection_layers", handle_set_detection_layers)

    # Scene intelligence tools (classification consumption)
    llm.register_function("query_person_details", handle_query_person_details)
    llm.register_function("query_object_motion", handle_query_object_motion)
    llm.register_function("query_scene_state", handle_query_scene_state)

    log.info("Registered %d voice tools", len(TOOL_SCHEMAS) + len(DESKTOP_TOOL_SCHEMAS))
