"""registry.py — Service registry and routing logic for Takeout ingestion.

Maps Takeout service names to parser modules, paths within the ZIP,
and default metadata. The registry is the single source of truth for
which services we support and how to handle them.
"""

from __future__ import annotations

from shared.takeout.models import ServiceConfig

SERVICE_REGISTRY: dict[str, ServiceConfig] = {
    # ── Tier 1: High signal, well-structured ──
    "chrome": ServiceConfig(
        parser="chrome",
        takeout_path="Chrome",
        tier=1,
        data_path="structured",
        modality_defaults=["text", "behavioral", "knowledge"],
        content_type="browser_history",
    ),
    "search": ServiceConfig(
        parser="activity",
        takeout_path="My Activity/Search",
        tier=1,
        data_path="structured",
        modality_defaults=["text", "behavioral", "knowledge", "temporal"],
        content_type="search_query",
    ),
    "keep": ServiceConfig(
        parser="keep",
        takeout_path="Keep",
        tier=1,
        data_path="unstructured",
        modality_defaults=["text", "knowledge"],
        content_type="note",
    ),
    "youtube": ServiceConfig(
        parser="activity",
        takeout_path="My Activity/YouTube",
        tier=1,
        data_path="structured",
        modality_defaults=["media", "behavioral", "temporal"],
        content_type="video_watch",
    ),
    "youtube_full": ServiceConfig(
        parser="youtube",
        takeout_path="YouTube and YouTube Music",
        tier=1,
        data_path="structured",
        modality_defaults=["media", "behavioral", "temporal"],
        content_type="video_watch",
    ),
    "calendar": ServiceConfig(
        parser="calendar",
        takeout_path="Calendar",
        tier=1,
        data_path="structured",
        modality_defaults=["temporal", "social"],
        content_type="calendar_event",
    ),
    "contacts": ServiceConfig(
        parser="contacts",
        takeout_path="Contacts",
        tier=1,
        data_path="structured",
        modality_defaults=["social"],
        content_type="contact",
    ),
    "tasks": ServiceConfig(
        parser="tasks",
        takeout_path="Tasks",
        tier=1,
        data_path="unstructured",
        modality_defaults=["text", "knowledge", "behavioral"],
        content_type="task",
    ),
    # ── Tier 2: High volume, needs care ──
    "gmail": ServiceConfig(
        parser="gmail",
        takeout_path="Mail",
        tier=2,
        data_path="unstructured",
        modality_defaults=["text", "social", "temporal"],
        content_type="email",
    ),
    "drive": ServiceConfig(
        parser="drive",
        takeout_path="Drive",
        tier=2,
        data_path="unstructured",
        modality_defaults=["text", "knowledge"],
        content_type="document",
    ),
    "chat": ServiceConfig(
        parser="chat",
        takeout_path="Google Chat",
        tier=2,
        data_path="unstructured",
        modality_defaults=["text", "social", "temporal"],
        content_type="chat_message",
    ),
    # ── Tier 3: Supplementary signal ──
    "maps": ServiceConfig(
        parser="location",
        takeout_path="Location History",
        alt_paths=["Timeline"],
        tier=3,
        data_path="structured",
        modality_defaults=["spatial", "temporal", "behavioral"],
        content_type="location",
    ),
    "photos": ServiceConfig(
        parser="photos",
        takeout_path="Google Photos",
        tier=3,
        data_path="structured",
        modality_defaults=["media", "spatial", "temporal"],
        content_type="photo",
    ),
    "purchases": ServiceConfig(
        parser="purchases",
        takeout_path="Purchases",
        tier=3,
        data_path="structured",
        modality_defaults=["behavioral"],
        content_type="purchase",
    ),
    "gemini": ServiceConfig(
        parser="activity",
        takeout_path="My Activity/Gemini Apps",
        tier=3,
        data_path="unstructured",
        modality_defaults=["text", "knowledge", "temporal"],
        content_type="ai_conversation",
        experimental=True,
    ),
}


def detect_services(zip_names: list[str]) -> dict[str, ServiceConfig]:
    """Detect which services are present in a Takeout ZIP.

    Args:
        zip_names: List of file paths within the ZIP (from ZipFile.namelist()).

    Returns:
        Dict of service_name → ServiceConfig for services found in the ZIP.
        Each config's ``takeout_path`` is updated to the actual matched path
        (may be an alt_path) so parsers look in the right folder.
    """
    found: dict[str, ServiceConfig] = {}

    for name, config in SERVICE_REGISTRY.items():
        # Build candidate paths: primary + alternates
        candidates = [config.takeout_path] + list(config.alt_paths)

        matched = False
        for candidate in candidates:
            prefixes = [
                f"Takeout/{candidate}/",
                f"{candidate}/",
            ]
            for prefix in prefixes:
                if any(zn.startswith(prefix) for zn in zip_names):
                    # Return a copy with takeout_path set to the matched path
                    from dataclasses import replace

                    found[name] = replace(config, takeout_path=candidate)
                    matched = True
                    break
            if matched:
                break

    return found
