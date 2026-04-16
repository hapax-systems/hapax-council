"""shared/stream_mode.py — Stream mode reader/writer (LRR Phase 6 §2).

Tracks the livestream's current broadcast posture: OFF, PRIVATE, PUBLIC, or
PUBLIC_RESEARCH. Distinct from ``working_mode`` (which governs R&D vs
research-experiment degradation); this axis governs what the stream surface
is exposing to the outside world.

The mode file is written by the ``hapax-stream-mode`` CLI and read by:

- ``studio_compositor.toggle_livestream`` — gates which output sinks are active
- ``logos/api/routes/*`` — applies response redaction (per Phase 6 §4)
- ``hapax-logos`` frontend — via ``/api/stream/mode`` poll, drives
  ``StreamAwarenessContext`` defense-in-depth
- ``studio_compositor.chat_reactor`` — tighter cooldowns in public_research
- ``hapax_daimonion.persona`` — scientific-register selection in
  public_research
- Phase 6 §5 stimmung auto-private closed loop — may force transitions
- Phase 6 §6 presence-detect T0 block — blocks public/public_research if
  presence without contract

**Fail-closed invariant (per Phase 6 §2):** if any consumer fails to read
the mode (file missing, permission denied, malformed), it treats the mode as
``PUBLIC`` (most-restrictive for broadcast safety). This is the OPPOSITE of
``working_mode``'s fail-open default — broadcast safety demands the most
restrictive fallback, not the most permissive.

See ``docs/superpowers/specs/2026-04-15-lrr-phase-6-governance-finalization-design.md``
§2 for the full design.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path


class StreamMode(StrEnum):
    OFF = "off"
    PRIVATE = "private"
    PUBLIC = "public"
    PUBLIC_RESEARCH = "public_research"


STREAM_MODE_FILE = Path.home() / ".cache" / "hapax" / "stream-mode"


def get_stream_mode(path: Path | None = None) -> StreamMode:
    """Read the current stream mode. Fails CLOSED to PUBLIC on any error.

    Fail-closed semantics: broadcast safety demands that a missing or
    malformed mode file is treated as the most-restrictive broadcast
    posture (``PUBLIC``), not as the safest-to-stream posture. Callers
    that want a default-off behavior should use ``get_stream_mode_or_off()``.
    """
    file = path if path is not None else STREAM_MODE_FILE
    try:
        return StreamMode(file.read_text().strip())
    except (FileNotFoundError, ValueError, PermissionError, OSError):
        return StreamMode.PUBLIC


def get_stream_mode_or_off(path: Path | None = None) -> StreamMode:
    """Read the current stream mode, defaulting to OFF on any error.

    Use this when the caller's "unknown state" default should be "stream
    not running" rather than "stream broadcasting publicly." Typical use:
    dashboards, documentation surfaces, diagnostic queries that merely
    want to report state. NOT for broadcast-gate decisions — those must
    use ``get_stream_mode()`` with its fail-closed semantics.
    """
    file = path if path is not None else STREAM_MODE_FILE
    try:
        return StreamMode(file.read_text().strip())
    except (FileNotFoundError, ValueError, PermissionError, OSError):
        return StreamMode.OFF


def set_stream_mode(mode: StreamMode, path: Path | None = None) -> None:
    """Write the stream mode atomically."""
    file = path if path is not None else STREAM_MODE_FILE
    file.parent.mkdir(parents=True, exist_ok=True)
    tmp = file.with_suffix(".tmp")
    tmp.write_text(mode.value)
    tmp.replace(file)


def is_off(path: Path | None = None) -> bool:
    """True when the stream is not running."""
    return get_stream_mode_or_off(path) == StreamMode.OFF


def is_private(path: Path | None = None) -> bool:
    """True when the stream is running private-only (MediaMTX local relay)."""
    return get_stream_mode_or_off(path) == StreamMode.PRIVATE


def is_public(path: Path | None = None) -> bool:
    """True when the stream is in the bare public mode (not research-visible)."""
    return get_stream_mode_or_off(path) == StreamMode.PUBLIC


def is_public_research(path: Path | None = None) -> bool:
    """True only in public_research — research-mode surface exposure gate."""
    return get_stream_mode_or_off(path) == StreamMode.PUBLIC_RESEARCH


def is_publicly_visible(path: Path | None = None) -> bool:
    """True when stream-mode is public OR public_research — the redaction gate.

    Fail-closed: if the state cannot be read, returns True (most restrictive).
    """
    return get_stream_mode(path) in (StreamMode.PUBLIC, StreamMode.PUBLIC_RESEARCH)


def is_research_visible(path: Path | None = None) -> bool:
    """True only in public_research — the research-mode surface exposure gate.

    Fail-closed: if the state cannot be read, returns False (the
    most-restrictive treatment for research-surface exposure is to keep
    the research surface hidden).
    """
    try:
        return get_stream_mode_or_off(path) == StreamMode.PUBLIC_RESEARCH
    except Exception:
        return False


# ── Filesystem deny-list (LRR Phase 6 §4.C) ─────────────────────────────────
#
# Path prefixes / suffixes that must NEVER render on a stream-visible surface
# regardless of stream-mode. Belt-and-suspenders to the Phase 8 terminal
# capture regex which has known failure modes (e.g. `tree ~/.password-store/`
# renders the filesystem structure but per-line regex obscuration does not
# catch filesystem rendering). This gate blocks the PATH itself regardless
# of the rendering mechanism.

DENY_PATH_PREFIXES: tuple[str, ...] = (
    # Pass password store — never a path to render
    str(Path.home() / ".password-store"),
    # GPG secrets
    str(Path.home() / ".gnupg"),
    # SSH keys
    str(Path.home() / ".ssh"),
    # Hapax runtime secrets file created by hapax-secrets.service
    "/run/user/1000/hapax-secrets.env",
    # Personal vault — ontologically operator-only
    str(Path.home() / "Documents" / "Personal"),
    # Work vault — employer-boundary content per corporate_boundary
    str(Path.home() / "Documents" / "Work"),
)

DENY_PATH_SUFFIXES: tuple[str, ...] = (
    # Any .envrc — these hold direnv-loaded secrets
    ".envrc",
    # Any raw .env file
    ".env",
)

# Filenames (exact match on the terminal component) that are always denied
# regardless of directory. Catches things like an operator running
# `cat id_rsa` from an unexpected cwd.
DENY_FILENAMES: frozenset[str] = frozenset(
    {
        "id_rsa",
        "id_ed25519",
        "id_ecdsa",
        "id_rsa.pub",
        "id_ed25519.pub",
        "id_ecdsa.pub",
        "credentials.json",
        "secrets.json",
        "token.json",
        ".netrc",
    }
)


def is_path_stream_safe(path: Path | str) -> bool:
    """Return True iff ``path`` is safe to render on a stream-visible surface.

    Conservative — fails closed (returns False) on ambiguous paths. Callers
    that render file paths in chat responses, tool output, briefing
    content, terminal capture, or any Logos file-viewer surface MUST
    consult this before rendering, regardless of the current stream-mode.

    Rules (any one → not safe):
      1. Path resolves to a prefix in DENY_PATH_PREFIXES
      2. Path ends with a suffix in DENY_PATH_SUFFIXES
      3. Basename matches DENY_FILENAMES exactly
    """
    try:
        p = Path(path).expanduser()
    except Exception:
        return False

    s = str(p)
    for prefix in DENY_PATH_PREFIXES:
        if s == prefix or s.startswith(prefix + "/"):
            return False
    for suffix in DENY_PATH_SUFFIXES:
        if s.endswith(suffix):
            return False
    return p.name not in DENY_FILENAMES
