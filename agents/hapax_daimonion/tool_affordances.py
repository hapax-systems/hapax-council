"""Gibson-verb affordance descriptions for all daimonion tools.

Each description captures what the tool AFFORDS to cognition — what it
lets the agent perceive, retrieve, act on, or control — using ecological
vocabulary (observe, retrieve, search, assess, detect, send, generate, etc.).
Descriptions never leak implementation details.
"""

from __future__ import annotations

# (tool_name, affordance_description) — order matches tool_definitions._META
TOOL_AFFORDANCES: list[tuple[str, str]] = [
    # --- Information tools ---
    (
        "get_current_time",
        "Observe the current date and time to orient temporal awareness and schedule reasoning",
    ),
    (
        "get_weather",
        "Retrieve current weather conditions and forecast to ground environmental context",
    ),
    (
        "get_briefing",
        "Retrieve the operator's daily briefing to establish situational awareness and open loops",
    ),
    (
        "get_system_status",
        "Assess the health and operational state of all running infrastructure services",
    ),
    (
        "get_calendar_today",
        "Retrieve today's scheduled events to anticipate commitments and temporal constraints",
    ),
    (
        "get_desktop_state",
        "Observe the current window layout, focused application, and workspace arrangement",
    ),
    (
        "search_documents",
        "Search the operator's personal knowledge base for relevant documents and notes",
    ),
    (
        "search_drive",
        "Search corporate drive files to locate work documents within the employer boundary",
    ),
    (
        "search_emails",
        "Search corporate email to retrieve messages and threads within the employer boundary",
    ),
    (
        "check_consent_status",
        "Observe which consent contracts are active and whether data handling is currently permitted",
    ),
    (
        "describe_consent_flow",
        "Retrieve the consent acquisition workflow for a given data category or person",
    ),
    (
        "check_governance_health",
        "Assess axiom compliance and governance integrity across the running system",
    ),
    (
        "analyze_scene",
        "Observe and interpret the current visual scene using camera perception with depth analysis",
    ),
    (
        "query_scene_inventory",
        "Retrieve detected objects and spatial relationships from the current visual scene",
    ),
    # --- Action tools ---
    (
        "generate_image",
        "Generate a visual image from a descriptive prompt for creative or communicative purposes",
    ),
    (
        "send_sms",
        "Compose and stage a text message for delivery to a specified phone contact",
    ),
    (
        "confirm_send_sms",
        "Confirm and deliver a previously staged text message after operator approval",
    ),
    # --- Control tools ---
    (
        "highlight_detection",
        "Direct visual attention to a specific detection layer in the perception overlay",
    ),
    (
        "set_detection_layers",
        "Configure which perception detection layers are visible in the visual overlay",
    ),
    (
        "focus_window",
        "Shift desktop focus to a named window to bring it into the operator's attention",
    ),
    (
        "switch_workspace",
        "Navigate to a different desktop workspace to change the operator's working context",
    ),
    (
        "open_app",
        "Stage the launch of an application, pending operator confirmation before execution",
    ),
    (
        "confirm_open_app",
        "Confirm and launch a previously staged application after operator approval",
    ),
    (
        "close_window",
        "Dismiss a specified window to reduce visual clutter and reclaim attention space",
    ),
    (
        "move_window",
        "Reposition a window on the desktop to reorganize the spatial working arrangement",
    ),
    (
        "resize_window",
        "Adjust the dimensions of a window to change how much screen space it occupies",
    ),
    # --- Phone tools ---
    (
        "find_phone",
        "Trigger an audible signal on the operator's phone to locate it in physical space",
    ),
    (
        "lock_phone",
        "Secure the operator's phone by remotely engaging its lock screen",
    ),
    (
        "send_to_phone",
        "Deliver a notification or content payload to the operator's phone for mobile access",
    ),
    (
        "media_control",
        "Control media playback on the operator's phone to pause, play, or skip content",
    ),
    (
        "phone_notifications",
        "Retrieve recent notifications from the operator's phone to surface mobile activity",
    ),
]
