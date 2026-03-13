"""Source-qualified behavior naming for multi-source perception.

Convention: ``{base_name}:{source_id}`` — colon-separated, both segments validated.
Unqualified names (no colon) are legal for singleton backends with no multi-source
semantics (e.g., ``timeline_mapping``, ``stream_bitrate``).

This is pure string algebra used by parameterized backends, the wiring layer,
and governance chain binding. Centralized here to prevent convention divergence.
"""

from __future__ import annotations

import re

from agents.hapax_voice.primitives import Behavior

SEPARATOR = ":"

_SOURCE_ID_RE = re.compile(r"^[a-z0-9_]+$")


def validate_source_id(source: str) -> None:
    """Validate a source identifier. Raises ValueError if invalid.

    Valid source IDs: lowercase letters, digits, underscores, non-empty.
    """
    if not source:
        raise ValueError("Source ID must not be empty")
    if not _SOURCE_ID_RE.match(source):
        raise ValueError(
            f"Source ID must be lowercase alphanumeric + underscore, got {source!r}"
        )


def qualify(base: str, source: str) -> str:
    """Qualify a base behavior name with a source identifier.

    >>> qualify("audio_energy_rms", "monitor_mix")
    'audio_energy_rms:monitor_mix'
    """
    if not base:
        raise ValueError("Base name must not be empty")
    validate_source_id(source)
    return f"{base}{SEPARATOR}{source}"


def parse(qualified: str) -> tuple[str, str | None]:
    """Parse a behavior name into (base, source) or (name, None) if unqualified.

    >>> parse("audio_energy_rms:monitor_mix")
    ('audio_energy_rms', 'monitor_mix')
    >>> parse("stream_bitrate")
    ('stream_bitrate', None)
    """
    if not qualified:
        raise ValueError("Behavior name must not be empty")
    if SEPARATOR in qualified:
        base, source = qualified.split(SEPARATOR, maxsplit=1)
        return base, source
    return qualified, None


def is_qualified(name: str) -> bool:
    """Return True if the behavior name contains a source qualifier."""
    return SEPARATOR in name


def behaviors_for_source(
    behaviors: dict[str, Behavior], source: str
) -> dict[str, Behavior]:
    """Filter a behaviors dict to only those matching a specific source.

    Returns a dict keyed by the full qualified name.
    """
    suffix = f"{SEPARATOR}{source}"
    return {k: v for k, v in behaviors.items() if k.endswith(suffix)}


def behaviors_for_base(
    behaviors: dict[str, Behavior], base: str
) -> dict[str, Behavior]:
    """Filter a behaviors dict to all sources providing a given base name.

    Includes both qualified names (``base:source``) and unqualified names
    that match the base exactly.
    """
    prefix = f"{base}{SEPARATOR}"
    return {
        k: v for k, v in behaviors.items() if k.startswith(prefix) or k == base
    }
