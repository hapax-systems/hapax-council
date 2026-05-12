"""omg.lol weblog Publisher ABC subclass — V5 publication-bus integration.

Per cc-task ``pub-bus-omg-rss`` (Phase 1b — sibling to the
fanout helper). Wraps :class:`shared.omg_lol_client.OmgLolClient` with
the V5 publication-bus invariants: AllowlistGate (per entry-id),
legal-name-leak guard, and the canonical Counter.

Use:

    client = OmgLolClient(...)
    publisher = OmgLolWeblogPublisher(client=client, address="hapax")
    result = publisher.publish(PublisherPayload(target="entry-1", text=body))

The ``target`` is the weblog entry ID; the ``address`` is set on the
publisher (one publisher instance per omg.lol address).
"""

from __future__ import annotations

import logging
import re
from typing import Any, ClassVar

from agents.publication_bus.publisher_kit import (
    Publisher,
    PublisherPayload,
    PublisherResult,
)
from agents.publication_bus.publisher_kit.allowlist import (
    AllowlistGate,
    load_allowlist,
)

log = logging.getLogger(__name__)

OMG_WEBLOG_SURFACE: str = "omg-lol-weblog-bearer-fanout"
"""Stable surface identifier; mirrored in
:data:`agents.publication_bus.surface_registry.SURFACE_REGISTRY`."""

DEFAULT_OMG_WEBLOG_ALLOWLIST: AllowlistGate = load_allowlist(
    OMG_WEBLOG_SURFACE,
    permitted=[],
)
"""Empty default allowlist — operator-curated entry IDs added via
class-level reassignment (matches the BridgyPublisher convention).
Future: dynamic allowlist sourced from a registered weblog manifest."""

_MONTH_LOCATION_RE = re.compile(r"^\s*(\d{4})-(\d{2})")
_UNSAFE_COLLECTION_LOCATIONS = {"/weblog", "/weblog/"}
_METADATA_OUTPUT_ORDER = ("Date", "Title", "Type", "Location", "Tags", "Slug")
_PAYLOAD_METADATA_TO_WEBLOG_FIELD = {
    "date": "Date",
    "title": "Title",
    "type": "Type",
    "location": "Location",
    "tags": "Tags",
    "slug": "Slug",
}


class _WeblogSourceError(ValueError):
    """Payload text cannot be normalized into a safe weblog entry source."""


def _split_metadata_block(text: str) -> tuple[dict[str, str], str]:
    """Split an omg.lol weblog metadata block from the markdown body.

    omg.lol accepts a YAML-like block at the top of an entry, but current
    production drafts use simple ``Key: value`` metadata whose values can
    themselves contain colons. A line-oriented parser is enough for this
    publisher and avoids rejecting operator-approved titles like ``Show HN:
    ...`` before they reach the upstream weblog parser.
    """

    if not text.startswith("---\n"):
        return {}, text

    end = text.find("\n---\n", 4)
    if end == -1:
        raise _WeblogSourceError("malformed weblog metadata block")

    raw_metadata = text[4:end]
    body = text[end + len("\n---\n") :]
    metadata: dict[str, str] = {}
    for line in raw_metadata.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            raise _WeblogSourceError(f"malformed weblog metadata line: {stripped!r}")
        key, value = stripped.split(":", 1)
        key = key.strip()
        if not key:
            raise _WeblogSourceError("empty weblog metadata key")
        metadata[key] = value.strip().strip('"')

    return metadata, body


def _field_value(metadata: dict[str, str], field: str) -> str | None:
    for key, value in metadata.items():
        if key.lower() == field.lower():
            return value.strip()
    return None


def _set_field(metadata: dict[str, str], field: str, value: str) -> None:
    for key in list(metadata):
        if key.lower() == field.lower() and key != field:
            del metadata[key]
    metadata[field] = value


def _metadata_value(value: object) -> str:
    if isinstance(value, (list, tuple, set)):
        text = ", ".join(str(item).strip() for item in value if str(item).strip())
    else:
        text = str(value).strip()
    if "\n" in text or "\r" in text:
        raise _WeblogSourceError("weblog metadata values must be single-line")
    return text.strip('"')


def _normalize_location(location: str) -> str:
    normalized = location.strip()
    if not normalized.startswith("/"):
        raise _WeblogSourceError(f"weblog Location must be an absolute path: {location!r}")
    if "://" in normalized:
        raise _WeblogSourceError(f"weblog Location must not be a full URL: {location!r}")
    return normalized


def _derive_default_location(metadata: dict[str, str], target: str) -> str | None:
    date = _field_value(metadata, "Date")
    slug = _field_value(metadata, "Slug") or target
    if not date or not slug:
        return None
    match = _MONTH_LOCATION_RE.match(date)
    if match is None:
        return None
    year, month = match.groups()
    return f"/{year}/{month}/{slug}"


def _render_metadata_block(metadata: dict[str, str], body: str) -> str:
    lines: list[str] = []
    emitted: set[str] = set()

    for field in _METADATA_OUTPUT_ORDER:
        value = _field_value(metadata, field)
        if value is not None:
            lines.append(f"{field}: {value}")
            emitted.add(field.lower())

    for key, value in metadata.items():
        if key.lower() not in emitted:
            lines.append(f"{key}: {value}")

    return "---\n" + "\n".join(lines) + "\n---\n\n" + body.lstrip("\n")


def _compose_weblog_source(payload: PublisherPayload) -> tuple[str, str | None]:
    metadata, body = _split_metadata_block(payload.text)
    payload_metadata = payload.metadata or {}

    if not metadata and not payload_metadata:
        return payload.text, None

    for payload_key, field in _PAYLOAD_METADATA_TO_WEBLOG_FIELD.items():
        if payload_key in payload_metadata and payload_metadata[payload_key] is not None:
            _set_field(metadata, field, _metadata_value(payload_metadata[payload_key]))

    if _field_value(metadata, "Slug") is None:
        _set_field(metadata, "Slug", payload.target)

    expected_location: str | None = None
    explicit_location = _field_value(metadata, "Location")
    if explicit_location:
        normalized_location = _normalize_location(explicit_location)
        if normalized_location in _UNSAFE_COLLECTION_LOCATIONS:
            derived = _derive_default_location(metadata, payload.target)
            if derived is None:
                raise _WeblogSourceError(
                    f"unsafe weblog Location {normalized_location!r}; provide Date and Slug "
                    "or payload.metadata['location']"
                )
            normalized_location = derived
        _set_field(metadata, "Location", normalized_location)
        expected_location = normalized_location
    else:
        expected_location = _derive_default_location(metadata, payload.target)

    return _render_metadata_block(metadata, body), expected_location


def _extract_entry(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    response = result.get("response")
    if isinstance(response, dict) and isinstance(response.get("entry"), dict):
        return response["entry"]
    return result


class OmgLolWeblogPublisher(Publisher):
    """Publishes a single weblog entry to one operator-owned omg.lol address.

    ``payload.target`` is the weblog entry ID; ``payload.text`` is the
    raw markdown body (omg.lol expects ``Content-Type: text/markdown``).
    The address is set on the publisher (one instance per omg.lol
    address); this lets the V5 chain dispatch to multiple addresses by
    composing multiple instances rather than threading address through
    every payload.
    """

    surface_name: ClassVar[str] = OMG_WEBLOG_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_OMG_WEBLOG_ALLOWLIST
    requires_legal_name: ClassVar[bool] = False

    def __init__(self, *, client: Any, address: str) -> None:
        self.client = client
        self.address = address

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        if not getattr(self.client, "enabled", True):
            return PublisherResult(
                refused=True,
                detail="omg-lol client disabled — no operator bearer-token",
            )
        try:
            content, expected_location = _compose_weblog_source(payload)
        except _WeblogSourceError as exc:
            return PublisherResult(refused=True, detail=str(exc))

        result = self.client.set_entry(self.address, payload.target, content=content)
        if result is None:
            return PublisherResult(error=True, detail="omg-lol set_entry returned None")

        entry = _extract_entry(result)
        returned_location = (
            entry.get("location") if isinstance(entry.get("location"), str) else None
        )
        if (
            expected_location is not None
            and returned_location is not None
            and returned_location != expected_location
        ):
            return PublisherResult(
                error=True,
                detail=(
                    "omg-lol returned Location "
                    f"{returned_location!r}; expected {expected_location!r}"
                ),
            )

        entry_id = entry.get("entry") or entry.get("id") or payload.target
        detail = str(entry_id)
        if returned_location:
            detail = f"{detail} {returned_location}"
        return PublisherResult(ok=True, detail=detail)


__all__ = [
    "DEFAULT_OMG_WEBLOG_ALLOWLIST",
    "OMG_WEBLOG_SURFACE",
    "OmgLolWeblogPublisher",
]
