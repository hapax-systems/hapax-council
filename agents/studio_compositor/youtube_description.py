"""YouTube video description auto-update with quota enforcement.

Writes the current research condition + active objective + stimmung snapshot
to the YouTube video description during livestream operation. Used by the
LRR Phase 9 content-programming loop (hook 3) and Phase 8 item 7.

Quota policy lives in ``config/youtube-quota.yaml``. The writer is the single
source of quota enforcement in the repo; no other code should call
``youtube.videos().update(snippet=...)`` directly.

Private-sentinel hygiene: every text input is scanned against the
``_PRIVATE_SENTINEL_PATTERN`` (the
``PRIVATE_SENTINEL_DO_NOT_PUBLISH_*`` family introduced by the
private/public cross-surface fixtures spec) and redacted before
description assembly. The interpersonal_transparency axiom forbids
private text from reaching the public YouTube description surface.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("youtube_description")

CONFIG_FILE = Path(__file__).parent.parent.parent / "config" / "youtube-quota.yaml"
QUOTA_FILE_DEFAULT = Path("/dev/shm/hapax-compositor/youtube-quota.json")

# Matches the ``PRIVATE_SENTINEL_DO_NOT_PUBLISH_*`` family used by the
# private/public cross-surface negative fixtures (see
# ``tests/shared/test_private_public_cross_surface_negative_fixtures.py``).
# Pattern intentionally broad: any token starting with the canonical
# sentinel prefix is treated as private and redacted, so a future
# rotation of the sentinel suffix does not bypass this gate.
_PRIVATE_SENTINEL_PATTERN = re.compile(r"PRIVATE_SENTINEL_DO_NOT_PUBLISH_[A-Za-z0-9_]+")
_PRIVATE_NONBROADCAST_MARKER_PATTERN = re.compile(
    r"("
    r"\bPRIVATE_(?:MEDIA_ROLE|SINK|SOURCE|AUDIO|ONLY)\b|"
    r"\bPUBLIC_FORBIDDEN\b|"
    r"\bOPERATOR_PRIVATE\b|"
    r"\bPRIVATE_ONLY\b|"
    r"private://|"
    r"\bhapax-(?:notification-)?private\b|"
    r"\boperator[-_ ]private\b|"
    r"\bprivacy[-_ ]blocked\b|"
    r"\bprivate[-_ ](?:audio|mode|only|state)\b|"
    r"\bprivate[-_ ]monitor\b|"
    r"\b(?:non|not|no)[-_ ]broadcast\b|"
    r"\bbus\.private\b|"
    r"\bchain\.private\b|"
    r"\brole\.private\b|"
    r"\baudio\.private[_\w.-]*\b"
    r")",
    re.IGNORECASE,
)
_UPPERCASE_PRIVATE_TOKEN_PATTERN = re.compile(r"\bPRIVATE\b")
_REDACTION_PLACEHOLDER = "[redacted]"
_PRIVATE_POSTURE_FIELDS = {
    "archive_ref_state",
    "broadcast_posture",
    "privacy_class",
    "privacy_label",
    "privacy_mode",
    "privacy_scope",
    "privacy_state",
    "public_private_mode",
    "public_private_posture",
    "redaction_privacy_posture",
}
_PRIVATE_POSTURE_VALUES = {
    "blocked",
    "operator_private",
    "private",
    "private_only",
    "public_forbidden",
    "redaction_required",
    "unknown_private",
}
_FALSE_PUBLIC_FLAGS = {
    "broadcast_safe",
    "public_broadcast",
    "public_broadcast_safe",
    "public_safe",
    "youtube_description_safe",
}
_TRUE_PRIVATE_FLAGS = {
    "no_broadcast",
    "non_broadcast",
    "not_broadcast",
    "private",
    "private_audio",
    "private_only",
}


class QuotaExhausted(Exception):
    """Raised when the daily quota budget is exhausted for today."""


def _load_config() -> dict[str, Any]:
    with CONFIG_FILE.open() as f:
        return yaml.safe_load(f)


def _pacific_date_now() -> str:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now(UTC).strftime("%Y-%m-%d")


def _read_quota_state(quota_file: Path) -> dict[str, Any]:
    fresh = {"date": _pacific_date_now(), "units_spent": 0, "stream_updates": {}}
    if not quota_file.exists():
        return fresh
    try:
        state = json.loads(quota_file.read_text())
    except (OSError, json.JSONDecodeError):
        return fresh
    # Same defensive pattern as the campaign of `fix(X): reject non-dict
    # root` PRs across SHM/JSON readers — a quota file containing a JSON
    # list/string/null would otherwise crash `state.get` with AttributeError.
    if not isinstance(state, dict):
        return fresh
    if state.get("date") != _pacific_date_now():
        return fresh
    return state


def _write_quota_state(quota_file: Path, state: dict[str, Any]) -> None:
    quota_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = quota_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(quota_file)


def check_and_debit(
    video_id: str,
    cfg: dict[str, Any] | None = None,
    quota_file: Path | None = None,
) -> None:
    """Verify quota allows another update, then debit its unit cost.

    Raises ``QuotaExhausted`` if either the per-stream cap or daily budget
    would be exceeded. Callers should catch + skip silently per the
    ``on_budget_exhausted`` policy.
    """
    cfg = cfg or _load_config()
    quota_file = quota_file or Path(cfg.get("quota_file", QUOTA_FILE_DEFAULT))

    state = _read_quota_state(quota_file)
    unit_cost = int(cfg["per_update_unit_cost"])
    daily_cap = int(cfg["daily_budget_units"])
    per_stream_cap = int(cfg["per_stream_max_updates"])

    if state["units_spent"] + unit_cost > daily_cap:
        raise QuotaExhausted(f"daily cap {daily_cap}u would be exceeded")

    per_stream_updates = int(state.get("stream_updates", {}).get(video_id, 0))
    if per_stream_updates + 1 > per_stream_cap:
        raise QuotaExhausted(f"per-stream cap {per_stream_cap} reached for {video_id}")

    state["units_spent"] += unit_cost
    state.setdefault("stream_updates", {})[video_id] = per_stream_updates + 1
    _write_quota_state(quota_file, state)


def description_text_has_private_marker(text: str | None) -> bool:
    """Return True when text carries private or non-broadcast marker tokens."""

    if not text:
        return False
    return bool(
        _PRIVATE_SENTINEL_PATTERN.search(text)
        or _PRIVATE_NONBROADCAST_MARKER_PATTERN.search(text)
        or _UPPERCASE_PRIVATE_TOKEN_PATTERN.search(text)
    )


def sanitize_description_text(text: str | None) -> str | None:
    """Return public-safe description text or ``None`` when it must be omitted.

    Returns ``None`` unchanged so the caller can preserve "field absent"
    semantics. Sentinel tokens are replaced with a neutral placeholder;
    explicit private/non-broadcast route markers cause the field to be
    omitted because those markers identify content that has no public
    description authority.
    """
    if text is None:
        return None
    redacted = _PRIVATE_SENTINEL_PATTERN.sub(_REDACTION_PLACEHOLDER, str(text))
    if _PRIVATE_NONBROADCAST_MARKER_PATTERN.search(
        redacted
    ) or _UPPERCASE_PRIVATE_TOKEN_PATTERN.search(redacted):
        return None
    redacted = re.sub(r"[ \t]+", " ", redacted).strip()
    return redacted or None


def _description_url_is_public_safe(url: Any) -> bool:
    if url is None:
        return False
    text = str(url).strip()
    return bool(text) and not description_text_has_private_marker(text)


def _metadata_blocks_public_description(value: Any, *, key: str | None = None) -> bool:
    key_l = key.lower() if isinstance(key, str) else None
    if key_l in _FALSE_PUBLIC_FLAGS and value is False:
        return True
    if key_l in _TRUE_PRIVATE_FLAGS and value is True:
        return True
    if key_l in _PRIVATE_POSTURE_FIELDS and isinstance(value, str):
        normalized = value.strip().lower().replace("-", "_")
        if normalized in _PRIVATE_POSTURE_VALUES:
            return True
    if isinstance(value, str):
        return description_text_has_private_marker(value)
    if isinstance(value, Mapping):
        return any(
            _metadata_blocks_public_description(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        )
    if isinstance(value, list | tuple | set):
        return any(_metadata_blocks_public_description(item) for item in value)
    return False


def _redact_attribution_entries(entries: list[Any] | None) -> list[Any] | None:
    """Return a copy of ``entries`` with any sentinel-bearing ``title`` /
    ``url`` fields replaced by the redaction placeholder.

    Sentinel-bearing URLs are dropped entirely (URLs cannot be
    meaningfully redacted in place — a redacted URL is not a URL); this
    matches the Sources block's existing "skip empty url" policy.
    """
    if not entries:
        return entries
    out: list[Any] = []
    for entry in entries:
        if _attribution_entry_blocks_public_description(entry):
            continue
        title = getattr(entry, "title", None)
        url = getattr(entry, "url", "")
        title_redacted = sanitize_description_text(title) if title else title
        url_safe = _description_url_is_public_safe(url)
        if not url_safe:
            # URL-bearing sentinel cannot be safely redacted in a URL
            # field. Likewise, private/non-broadcast source markers in a
            # URL mean the entire entry lacks public-description authority.
            continue
        if title_redacted == title:
            out.append(entry)
            continue
        out.append(_RedactedAttribution(entry=entry, title=title_redacted, url=url))
    return out


def _attribution_entry_blocks_public_description(entry: Any) -> bool:
    metadata = getattr(entry, "metadata", None)
    source = getattr(entry, "source", None)
    kind = getattr(entry, "kind", None)
    return (
        _metadata_blocks_public_description(metadata)
        or description_text_has_private_marker(source)
        or description_text_has_private_marker(kind)
    )


class _RedactedAttribution:
    """Lightweight wrapper preserving the original entry's attributes
    while overriding ``title`` (and any URL stripping) with redacted
    values.

    Avoids mutating the caller's entry objects — the live attribution
    pipeline reuses these instances across emission cycles.
    """

    def __init__(self, *, entry: Any, title: str | None, url: str) -> None:
        self._entry = entry
        self.title = title
        self.url = url
        self.kind = getattr(entry, "kind", "")
        self.emitted_at = getattr(entry, "emitted_at", 0)


def assemble_description(
    *,
    condition_id: str,
    claim_id: str | None,
    objective_title: str | None,
    substrate_model: str,
    reaction_count: int | None = None,
    extra: str | None = None,
    attributions: list[Any] | None = None,
    attribution_max: int = 50,
    attribution_max_chars: int = 5000,
) -> str:
    """Assemble a description snippet from current research state.

    YT bundle B2 wire-in: when ``attributions`` carries
    AttributionEntry objects (URLs accumulated by the chat URL
    pipeline + other AttributionSource producers), they're rendered
    in a "Sources / Attribution" section grouped by kind. Hard caps:
    ``attribution_max`` entries (newest first) and a total character
    budget of ``attribution_max_chars`` for the section so a runaway
    URL flood can never blow YouTube's 5000-char description ceiling.

    Private-sentinel hygiene: every text input (and attribution
    title/url) is scrubbed for the
    ``PRIVATE_SENTINEL_DO_NOT_PUBLISH_*`` token family before
    composition; sentinel-bearing URLs are dropped from the Sources
    block. This is the single gate between private metadata sources
    and the public YouTube description.
    """
    condition_id = sanitize_description_text(condition_id) or "unknown"
    claim_id = sanitize_description_text(claim_id)
    objective_title = sanitize_description_text(objective_title)
    substrate_model = sanitize_description_text(substrate_model) or "unknown"
    extra = sanitize_description_text(extra)
    attributions = _redact_attribution_entries(attributions)

    lines = [f"Condition: {condition_id}"]
    if claim_id:
        lines.append(f"Claim: {claim_id}")
    if objective_title:
        lines.append(f"Current objective: {objective_title}")
    lines.append(f"Substrate: {substrate_model}")
    if reaction_count is not None:
        lines.append(f"Reactions observed: {reaction_count}")
    if extra:
        lines.extend(["", extra])
    if attributions:
        attrib_block = _render_attribution_block(
            attributions, max_entries=attribution_max, max_chars=attribution_max_chars
        )
        if attrib_block:
            lines.extend(["", attrib_block])
    return "\n".join(lines)


def _render_attribution_block(
    entries: list[Any],
    *,
    max_entries: int,
    max_chars: int,
) -> str:
    """Render attribution entries as a grouped-by-kind section.

    Newest-first ordering; per-kind grouping; cap on entry count and
    total character budget so a chat URL flood never blows the
    description ceiling. Each entry renders as ``- {title or url}: {url}``
    when ``title`` is set, ``- {url}`` otherwise. De-duplicated by
    ``(kind, url)`` so multi-producer overlaps surface once.
    """
    if not entries:
        return ""
    # De-dup by (kind, url) — newest entry wins.
    seen: dict[tuple[str, str], Any] = {}
    for entry in sorted(entries, key=lambda e: getattr(e, "emitted_at", 0), reverse=True):
        key = (getattr(entry, "kind", ""), getattr(entry, "url", ""))
        if not key[1]:
            continue
        if key not in seen:
            seen[key] = entry
        if len(seen) >= max_entries:
            break
    if not seen:
        return ""
    by_kind: dict[str, list[Any]] = {}
    for entry in seen.values():
        by_kind.setdefault(entry.kind, []).append(entry)
    lines = ["Sources:"]
    for kind in sorted(by_kind.keys()):
        lines.append(f"  [{kind}]")
        for e in by_kind[kind]:
            label = e.title.strip() if getattr(e, "title", None) else None
            line = f"    - {label}: {e.url}" if label else f"    - {e.url}"
            lines.append(line)
    block = "\n".join(lines)
    if len(block) > max_chars:
        # Truncate at a line boundary just below the budget to keep
        # the section parseable rather than ending mid-URL.
        truncated_lines: list[str] = []
        running = 0
        for line in lines:
            if running + len(line) + 1 > max_chars - 50:  # 50-char overflow notice budget
                truncated_lines.append(f"  [...{len(lines) - len(truncated_lines)} more truncated]")
                break
            truncated_lines.append(line)
            running += len(line) + 1  # +1 for the join newline
        block = "\n".join(truncated_lines)
    return block


def update_video_description(
    video_id: str,
    description: str,
    *,
    dry_run: bool = False,
    cfg: dict[str, Any] | None = None,
    quota_file: Path | None = None,
) -> bool:
    """Update a YouTube video's description with quota enforcement.

    Returns True on success, False if quota-limited. Any other exception
    propagates (OAuth errors, API errors). When ``dry_run`` is True, the
    quota is still debited (so tests can exercise the rate-limiter) but
    no API call is made.
    """
    cfg = cfg or _load_config()
    try:
        check_and_debit(video_id, cfg=cfg, quota_file=quota_file)
    except QuotaExhausted as exc:
        policy = cfg.get("on_budget_exhausted", "skip_silent")
        if policy == "skip_silent":
            log.info("youtube_description: quota exhausted (%s); skipping", exc)
            return False
        raise

    if dry_run:
        log.info("youtube_description: dry-run update on %s (%d chars)", video_id, len(description))
        return True

    from shared.google_auth import get_google_credentials

    creds = get_google_credentials([cfg["oauth_scope"]])
    from googleapiclient.discovery import build

    service = build("youtube", "v3", credentials=creds)
    existing = service.videos().list(part="snippet", id=video_id).execute().get("items", [])
    if not existing:
        log.warning("youtube_description: no video %s visible to auth user", video_id)
        return False
    snippet = existing[0]["snippet"]
    snippet["description"] = description
    service.videos().update(part="snippet", body={"id": video_id, "snippet": snippet}).execute()
    return True
