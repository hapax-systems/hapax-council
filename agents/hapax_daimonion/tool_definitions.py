"""Concrete tool capability definitions for all 26 daimonion tools.

Each tool from tools_openai.py is migrated to a ToolCapability instance
with formal category, resource tier, consent, backend, and confirmation
metadata. The build_registry() function is the single entry point.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from agents.hapax_daimonion.tool_capability import (
    ToolCapability,
    ToolCategory,
    ToolRegistry,
)
from shared.capability import CapabilityRegistry, ResourceTier

log = logging.getLogger(__name__)


def _cap(
    name: str,
    handler: Callable,
    schema: dict,
    tool_category: ToolCategory = ToolCategory.INFORMATION,
    resource_tier: ResourceTier = ResourceTier.LIGHT,
    requires_consent: list[str] | None = None,
    requires_backends: list[str] | None = None,
    requires_confirmation: bool = False,
    timeout_s: float = 3.0,
) -> ToolCapability:
    return ToolCapability(
        name=name,
        description=schema.get("function", {}).get("description", ""),
        schema=schema,
        handler=handler,
        tool_category=tool_category,
        resource_tier=resource_tier,
        requires_consent=requires_consent or [],
        requires_backends=requires_backends or [],
        requires_confirmation=requires_confirmation,
        timeout_s=timeout_s,
    )


def build_registry(
    guest_mode: bool = False,
    config=None,
    webcam_capturer=None,
    screen_capturer=None,
    capability_registry: CapabilityRegistry | None = None,
) -> ToolRegistry:
    """Build the tool registry with all capabilities.

    This replaces the flat (tools, handlers) tuple from get_openai_tools().
    """
    if guest_mode:
        return ToolRegistry(capability_registry)

    from agents.hapax_daimonion.tools_openai import get_openai_tools

    tools_list, handler_map = get_openai_tools(
        guest_mode=False,
        config=config,
        webcam_capturer=webcam_capturer,
        screen_capturer=screen_capturer,
    )

    schema_by_name: dict[str, dict] = {}
    for schema in tools_list:
        fname = schema.get("function", {}).get("name", "")
        if fname:
            schema_by_name[fname] = schema

    _META: dict[str, tuple] = {
        "get_current_time": (ToolCategory.INFORMATION, ResourceTier.INSTANT, [], [], False, 1.0),
        "get_weather": (ToolCategory.INFORMATION, ResourceTier.LIGHT, [], [], False, 3.0),
        "get_briefing": (ToolCategory.INFORMATION, ResourceTier.LIGHT, [], [], False, 3.0),
        "get_system_status": (ToolCategory.INFORMATION, ResourceTier.LIGHT, [], [], False, 3.0),
        "get_calendar_today": (ToolCategory.INFORMATION, ResourceTier.LIGHT, [], [], False, 3.0),
        "get_desktop_state": (
            ToolCategory.INFORMATION,
            ResourceTier.INSTANT,
            [],
            ["hyprland"],
            False,
            1.0,
        ),
        "search_documents": (ToolCategory.INFORMATION, ResourceTier.LIGHT, [], [], False, 3.0),
        "search_drive": (
            ToolCategory.INFORMATION,
            ResourceTier.LIGHT,
            ["corporate_boundary"],
            [],
            False,
            3.0,
        ),
        "search_emails": (
            ToolCategory.INFORMATION,
            ResourceTier.LIGHT,
            ["corporate_boundary"],
            [],
            False,
            3.0,
        ),
        "check_consent_status": (
            ToolCategory.INFORMATION,
            ResourceTier.INSTANT,
            [],
            [],
            False,
            1.0,
        ),
        "describe_consent_flow": (
            ToolCategory.INFORMATION,
            ResourceTier.INSTANT,
            [],
            [],
            False,
            1.0,
        ),
        "check_governance_health": (
            ToolCategory.INFORMATION,
            ResourceTier.LIGHT,
            [],
            [],
            False,
            3.0,
        ),
        "analyze_scene": (
            ToolCategory.INFORMATION,
            ResourceTier.HEAVY,
            ["interpersonal_transparency"],
            ["vision"],
            False,
            5.0,
        ),
        "query_scene_inventory": (
            ToolCategory.INFORMATION,
            ResourceTier.LIGHT,
            ["interpersonal_transparency"],
            ["vision"],
            False,
            3.0,
        ),
        "generate_image": (ToolCategory.ACTION, ResourceTier.HEAVY, [], [], False, 10.0),
        "send_sms": (ToolCategory.ACTION, ResourceTier.LIGHT, [], ["phone"], True, 3.0),
        "confirm_send_sms": (ToolCategory.ACTION, ResourceTier.LIGHT, [], ["phone"], False, 3.0),
        "highlight_detection": (
            ToolCategory.CONTROL,
            ResourceTier.INSTANT,
            [],
            ["vision"],
            False,
            1.0,
        ),
        "set_detection_layers": (
            ToolCategory.CONTROL,
            ResourceTier.INSTANT,
            [],
            ["vision"],
            False,
            1.0,
        ),
        "focus_window": (
            ToolCategory.CONTROL,
            ResourceTier.INSTANT,
            [],
            ["hyprland"],
            False,
            1.0,
        ),
        "switch_workspace": (
            ToolCategory.CONTROL,
            ResourceTier.INSTANT,
            [],
            ["hyprland"],
            False,
            1.0,
        ),
        "open_app": (ToolCategory.CONTROL, ResourceTier.LIGHT, [], ["hyprland"], True, 3.0),
        "confirm_open_app": (
            ToolCategory.CONTROL,
            ResourceTier.LIGHT,
            [],
            ["hyprland"],
            False,
            3.0,
        ),
        "close_window": (
            ToolCategory.CONTROL,
            ResourceTier.INSTANT,
            [],
            ["hyprland"],
            False,
            1.0,
        ),
        "move_window": (
            ToolCategory.CONTROL,
            ResourceTier.INSTANT,
            [],
            ["hyprland"],
            False,
            1.0,
        ),
        "resize_window": (
            ToolCategory.CONTROL,
            ResourceTier.INSTANT,
            [],
            ["hyprland"],
            False,
            1.0,
        ),
    }

    registry = ToolRegistry(capability_registry)

    for name, handler in handler_map.items():
        schema = schema_by_name.get(name)
        if schema is None:
            log.debug("Tool %s has handler but no schema, skipping", name)
            continue
        meta = _META.get(name)
        if meta is None:
            log.debug("Tool %s has no metadata, registering with defaults", name)
            registry.register(_cap(name, handler, schema))
            continue
        cat, tier, consent, backends, confirm, timeout = meta
        registry.register(
            _cap(
                name,
                handler,
                schema,
                tool_category=cat,
                resource_tier=tier,
                requires_consent=consent,
                requires_backends=backends,
                requires_confirmation=confirm,
                timeout_s=timeout,
            )
        )

    log.info("Tool registry built: %d capabilities", len(registry.all_tools()))
    return registry
