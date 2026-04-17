"""LRR Phase 6 §4.B — transcript + impingement read-side firewall.

Write-side invariant: writes to the protected paths continue unchanged.
Read-side invariant: any Logos API endpoint, overlay surface, compositor
source, or logos-logic path rendering the content of these files to a
stream-visible surface must pass through this gate. When
``is_publicly_visible()`` is True, the gate returns the sentinel
:class:`TranscriptRedacted` instead of the file content.

Protected paths (per spec §3.4.B):
    ~/.local/share/hapax-daimonion/events-*.jsonl   (voice transcripts)
    ~/.local/share/hapax-daimonion/recordings/      (session WAVs + thumbs)
    /dev/shm/hapax-dmn/impingements.jsonl           (derived intent narratives)

Direct reads bypassing this gate are detected by
``scripts/scan-transcript-firewall-bypasses.py`` in CI.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from shared.stream_mode import is_publicly_visible


@dataclass(frozen=True)
class TranscriptRedacted:
    """Sentinel returned when a protected path is read while stream is public.

    Carries no content. Callers must handle this type explicitly — either
    render a safe placeholder (``"[redacted — stream is publicly visible]"``)
    or omit the field from the response entirely.

    The ``path`` field is retained so that observability surfaces can log
    the attempt (without the content) to indicate a consumer is requesting
    content that was refused.
    """

    path: Path
    reason: str = "redacted_stream_mode_public"


# Path predicates — evaluated at match-time to avoid caching a stale home dir.


def _hapax_daimonion_events_root() -> Path:
    return Path.home() / ".local" / "share" / "hapax-daimonion"


def _impingements_root() -> Path:
    return Path("/dev/shm/hapax-dmn")


def is_protected_transcript_path(path: Path) -> bool:
    """True iff ``path`` falls under any §3.4.B protected category.

    Matches:
      - ``events-*.jsonl`` anywhere under ``~/.local/share/hapax-daimonion/``
      - anything under ``~/.local/share/hapax-daimonion/recordings/``
      - ``/dev/shm/hapax-dmn/impingements.jsonl`` exactly

    Callers normalise their inputs via ``Path(x).expanduser().resolve()``
    before asking; this function trusts the input.
    """
    try:
        p = Path(path).expanduser()
    except Exception:
        return False

    dmn_root = _hapax_daimonion_events_root()
    imp_path = _impingements_root() / "impingements.jsonl"

    # events-*.jsonl anywhere under daimonion share dir
    try:
        if p.is_relative_to(dmn_root):
            if p.name.startswith("events-") and p.suffix == ".jsonl":
                return True
            if "recordings" in p.parts:
                return True
    except AttributeError:
        # is_relative_to is 3.9+; fall through if Python < 3.9 somehow
        pass

    return str(p) == str(imp_path)


def read_transcript_gate(path: Path) -> str | bytes | TranscriptRedacted:
    """Read ``path`` through the firewall.

    Returns:
        - The file's text content (``str``) when stream is private/off.
        - The file's bytes content (``bytes``) when the path is under the
          ``recordings/`` subtree (audio blobs, not text).
        - ``TranscriptRedacted`` when stream is publicly visible.

    Raises:
        ``FileNotFoundError`` when the path does not exist on disk (after
        passing the public-visible gate). This is the standard pathlib
        behavior — redaction only kicks in when the stream is publicly
        visible; a missing file on a private stream surfaces normally.

    Callers MUST check ``isinstance(result, TranscriptRedacted)`` before
    rendering the returned value. Rendering the sentinel's ``repr`` to a
    stream-visible surface would leak nothing (no content) but would
    confuse the consumer; treat as "content not available" and skip.
    """
    p = Path(path).expanduser()

    if is_publicly_visible():
        return TranscriptRedacted(path=p)

    # Binary read for recordings (WAVs, thumbnails); text for JSONL
    try:
        if "recordings" in p.parts:
            return p.read_bytes()
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Mixed bytes — fall back to bytes read
        return p.read_bytes()


def guard_content(value: str | bytes | TranscriptRedacted) -> str | bytes:
    """Extract content from a gate return, raising on redaction.

    Use in the common path where the caller has no sensible behavior on
    redaction and wants the exception to propagate up — e.g., a helper
    function that's unconditionally called only from private-mode paths.
    """
    if isinstance(value, TranscriptRedacted):
        raise PermissionError(f"transcript gate refused: {value.path} ({value.reason})")
    return value
