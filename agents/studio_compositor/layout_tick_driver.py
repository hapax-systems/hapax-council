"""Periodic driver that calls ``apply_layout_switch`` from inside the
compositor process.

cc-task: ``u6-periodic-tick-driver``.

The U6 substrate (PR #2324) shipped the ``hapax_compositor_layout_active``
gauge + ``LayoutStore.set_active()``. PR #2376 shipped the
``apply_layout_switch`` adapter that combines selection + cooldown +
mutate. But until this driver, no caller invoked the adapter
periodically — so the live system sat on ``garage-door`` (the
``LayoutStore.__init__`` default) forever, with the gauge stuck at
``hapax_compositor_layout_active{layout="garage-door"} 1.0``.

This driver lives **inside the compositor process** because the
``LayoutStore`` is in-process state — running the driver as a separate
systemd unit would require IPC or cross-process file-watching. The
state_provider below reads the four input signals from the well-known
SHM/dotcache files used by ``director_loop``:

* ``stream_mode`` — ``~/.cache/hapax/stream-mode`` via ``shared.stream_mode``
* ``consent_safe_active`` — env-flag ``HAPAX_CONSENT_EGRESS_GATE`` (gate
  is retired by default per ``consent_live_egress.py``)
* ``vinyl_playing`` — ``/dev/shm/hapax-compositor/vinyl-operator-active.flag``
  (operator override) OR fresh+confident ``album-state.json``
* ``director_activity`` — last entry of
  ``~/hapax-state/stream-experiment/director-intent.jsonl``

Each tick, ``apply_layout_switch`` is called; we additionally increment
``hapax_layout_switch_dispatched_total{layout, reason}`` regardless of
whether the cooldown gate accepted the switch, so the operator can prove
the driver is alive even when the surface looks frozen.

Reversibility:

* ``HAPAX_LAYOUT_TICK_DISABLED=1`` skips driver startup entirely.
* The thread is daemon=True; compositor SIGTERM brings it down with
  the rest of the process.

Per ``feedback_no_expert_system_rules`` — the driver is a pure dispatcher;
all selection logic lives in ``layout_switcher.select_layout`` which is
already a typed declarative policy (priority order, no thresholds).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import asdict, is_dataclass, replace
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Env-flag gate. Operator can disable by setting this to any non-empty
# truthy value. Defaults to ENABLED — feature-forward per operator
# directive ``feedback_features_on_by_default``.
ENV_DISABLE: str = "HAPAX_LAYOUT_TICK_DISABLED"

# Tick cadence — 30s matches the LayoutSwitcher.DEFAULT_COOLDOWN_S so
# we tick once per cooldown window. Faster ticks would just hit the
# cooldown; slower ticks would miss vinyl-flap events.
DEFAULT_DRIVER_INTERVAL_S: float = 30.0

# Director intent staleness — anything older than this is treated as
# "no current director activity" so a long stall doesn't pin the
# layout into vinyl-focus on a stale react-tick.
DIRECTOR_INTENT_STALE_S: float = 180.0

# Vinyl evidence staleness — album-state confidence decays after this.
VINYL_STATE_STALE_S: float = 60.0
VINYL_CONFIDENCE_THRESHOLD: float = 0.5

# Well-known signal files. Duplicated from director_loop.py to avoid
# pulling that heavy module's transitive imports into the driver.
ALBUM_STATE_FILE: Path = Path("/dev/shm/hapax-compositor/album-state.json")
VINYL_OPERATOR_OVERRIDE_FLAG: Path = Path("/dev/shm/hapax-compositor/vinyl-operator-active.flag")
DIRECTOR_INTENT_JSONL: Path = Path(
    os.path.expanduser("~/hapax-state/stream-experiment/director-intent.jsonl")
)
SEGMENT_STATE_FILE: Path = Path("/dev/shm/hapax-compositor/active-segment.json")
SEGMENT_LAYOUT_RECEIPT_FILE: Path = Path("/dev/shm/hapax-compositor/segment-layout-receipt.json")
SUPPORTED_SEGMENT_LAYOUT_PRESSURE_KINDS: frozenset[str] = frozenset(
    {
        "tier",
        "tier_status",
        "tier_status_surface",
        "tier_list_surface",
        "ranked",
        "ranked_list",
        "ranked_list_surface",
        "chat",
        "chat_response",
        "chat_participation_surface",
        "comparison",
        "comparison_surface",
        "compare",
        "source_comparison",
        "source_comparison_surface",
        "evidence_visible",
        "action_visible",
        "comparison_visible",
        "source_visible",
        "readability_held",
        "referent_visible",
    }
)
FORBIDDEN_SEGMENT_LAYOUT_PROPOSAL_FIELDS: frozenset[str] = frozenset(
    {
        "layout",
        "layout_id",
        "layoutId",
        "layout_name",
        "requested_layout",
        "selected_layout",
        "target_layout",
        "active_layout",
        "layout_command",
        "surface",
        "surfaces",
        "surface_id",
        "surfaceId",
        "coordinates",
        "coordinate",
        "x",
        "y",
        "w",
        "h",
        "width",
        "height",
        "shm",
        "shm_path",
        "segment_cues",
        "cues",
        "cue",
        "command",
        "commands",
        "preset",
        "z_order",
        "z-order",
    }
)
FORBIDDEN_SEGMENT_LAYOUT_PROPOSAL_KEY_TOKENS: frozenset[str] = frozenset(
    "".join(ch for ch in field.lower() if ch.isalnum())
    for field in FORBIDDEN_SEGMENT_LAYOUT_PROPOSAL_FIELDS
)


def _is_disabled() -> bool:
    """Return True iff the operator has set ``HAPAX_LAYOUT_TICK_DISABLED``."""
    val = os.environ.get(ENV_DISABLE, "").strip().lower()
    return val in {"1", "true", "yes", "on", "enabled"}


def _read_stream_mode() -> str | None:
    """Read the current stream mode as the string the switcher expects.

    Returns ``"deep"`` if the live mode is research-focused; otherwise
    ``None`` so the switcher falls through to the default. We treat any
    error as "no signal" so the driver never accidentally trips
    consent-safe.
    """
    try:
        from shared.stream_mode import StreamMode, get_stream_mode

        mode = get_stream_mode()
        if mode == StreamMode.PUBLIC_RESEARCH:
            return "deep"
    except Exception:
        log.debug("read_stream_mode failed", exc_info=True)
    return None


def _read_consent_safe_active() -> bool:
    """The retired layout-swap gate is opt-in via env-flag (see
    ``consent_live_egress.py``). When set, the driver routes to
    consent-safe even though the face-obscure pipeline (#129) is the
    authoritative privacy enforcer — operator may want both belt-and-
    suspenders during an interview."""
    val = os.environ.get("HAPAX_CONSENT_EGRESS_GATE", "").strip().lower()
    return val in {"1", "true", "yes", "on", "enabled"}


def _read_vinyl_playing() -> bool:
    """Operator override flag OR fresh+confident album-state."""
    try:
        if VINYL_OPERATOR_OVERRIDE_FLAG.exists():
            return True
        if not ALBUM_STATE_FILE.exists():
            return False
        age = time.time() - ALBUM_STATE_FILE.stat().st_mtime
        if age > VINYL_STATE_STALE_S:
            return False
        data = json.loads(ALBUM_STATE_FILE.read_text())
        conf = float(data.get("confidence") or 0.0)
        return conf >= VINYL_CONFIDENCE_THRESHOLD
    except Exception:
        log.debug("read_vinyl_playing failed", exc_info=True)
        return False


def _read_director_activity() -> str | None:
    """Tail the last entry of director-intent.jsonl for ``activity``.

    We do not parse the entire file — only the last line. Files are
    rotated by ``director_loop._maybe_rotate_jsonl`` so the tail stays
    bounded. Returns ``None`` on missing/stale/unparseable.
    """
    try:
        if not DIRECTOR_INTENT_JSONL.exists():
            return None
        age = time.time() - DIRECTOR_INTENT_JSONL.stat().st_mtime
        if age > DIRECTOR_INTENT_STALE_S:
            return None
        # Read the last 4KB of the file — enough for the last entry,
        # and bounded so a runaway file doesn't blow memory.
        with DIRECTOR_INTENT_JSONL.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            offset = max(0, size - 4096)
            f.seek(offset)
            tail = f.read().decode("utf-8", errors="replace")
        last_line = ""
        for line in tail.splitlines():
            stripped = line.strip()
            if stripped:
                last_line = stripped
        if not last_line:
            return None
        rec = json.loads(last_line)
        activity = rec.get("activity")
        if isinstance(activity, str) and activity:
            return activity
    except Exception:
        log.debug("read_director_activity failed", exc_info=True)
    return None


def build_state_provider() -> Any:
    """Return a zero-arg callable that yields the dict the driver expects.

    Each call re-reads the underlying files so live state changes
    propagate at the next tick.
    """

    def _provider() -> dict[str, object]:
        segment_pressure = _read_segment_layout_pressure()
        return {
            "consent_safe_active": _read_consent_safe_active(),
            "vinyl_playing": _read_vinyl_playing(),
            "director_activity": _read_director_activity(),
            "stream_mode": _read_stream_mode(),
            **segment_pressure,
        }

    return _provider


def _read_segment_layout_pressure(
    path: Path = SEGMENT_STATE_FILE,
    *,
    now: float | None = None,
) -> dict[str, object]:
    """Read current-beat proposal-only layout pressure from active segment SHM.

    The prepared artifact is not layout authority. We only consume
    ``current_beat_layout_intents[].needs`` as bounded pressure, then the
    runtime controller decides from rendered readback.
    """

    ts = time.time() if now is None else now
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"segment_layout_intents": (), "segment_layout_pressure_seen": False}
    if not isinstance(raw, dict) or not raw.get("programme_id"):
        return {"segment_layout_intents": (), "segment_layout_pressure_seen": False}
    try:
        file_mtime = path.stat().st_mtime
    except OSError:
        file_mtime = ts

    prepared_artifact_ref = _prepared_artifact_ref(raw.get("prepared_artifact_ref"))
    current_beat_index = _optional_int(raw.get("current_beat_index"))
    responsible_hosting, hosting_refusals = _segment_hosting_pressure(raw)
    proposals = _dict_items(raw.get("current_beat_layout_intents"))
    intents: list[Any] = []
    refusals: list[dict[str, object]] = list(hosting_refusals if not proposals else ())
    for index, proposal in enumerate(proposals):
        proposal_intents, proposal_refusals = _proposal_needs_to_intents(
            proposal,
            root=raw,
            index=index,
            now=file_mtime,
            prepared_artifact_ref=prepared_artifact_ref,
            current_beat_index=current_beat_index,
        )
        intents.extend(proposal_intents)
        refusals.extend(proposal_refusals)
    if responsible_hosting and not proposals:
        refusals.append(
            {
                "programme_id": _optional_str(raw.get("programme_id")),
                "beat_index": current_beat_index,
                "need_index": None,
                "need_kind": None,
                "reason": "missing_current_beat_layout_intents",
                "supported_kinds": sorted(SUPPORTED_SEGMENT_LAYOUT_PRESSURE_KINDS),
                "forbidden_fields": (),
                "authority_ref": prepared_artifact_ref,
            }
        )
    return {
        "segment_layout_intents": tuple(intents),
        "segment_layout_refusals": tuple(refusals),
        "segment_layout_pressure_seen": bool(proposals) or responsible_hosting,
        "prepared_artifact_ref": prepared_artifact_ref,
        "segment_action_intents_ref": _segment_action_intents_ref(
            path=path,
            raw=raw,
            prepared_artifact_ref=prepared_artifact_ref,
        ),
        "segment_playback_ref": _optional_str(raw.get("segment_playback_ref")),
    }


def _proposal_needs_to_intents(
    proposal: dict[str, object],
    *,
    root: dict[str, object],
    index: int,
    now: float,
    prepared_artifact_ref: str | None,
    current_beat_index: int | None,
) -> tuple[tuple[Any, ...], tuple[dict[str, object], ...]]:
    from agents.studio_compositor.segment_layout_control import SegmentActionIntent

    needs = _dict_items(proposal.get("needs"))
    if not needs and isinstance(proposal.get("needs"), list | tuple):
        needs = tuple({"kind": item} for item in proposal["needs"] if isinstance(item, str))  # type: ignore[index]
    if not needs:
        return (), ()

    out: list[SegmentActionIntent] = []
    refusals: list[dict[str, object]] = []
    read_mtime = _optional_float(proposal.get("read_mtime")) or now
    proposal_forbidden = _forbidden_segment_layout_fields(
        {key: value for key, value in proposal.items() if key != "needs"}
    )
    if proposal_forbidden:
        return (), (
            {
                "programme_id": _optional_str(root.get("programme_id")),
                "beat_index": current_beat_index,
                "need_index": None,
                "need_kind": None,
                "reason": "forbidden_segment_layout_authority_field",
                "supported_kinds": sorted(SUPPORTED_SEGMENT_LAYOUT_PRESSURE_KINDS),
                "forbidden_fields": proposal_forbidden,
                "authority_ref": prepared_artifact_ref,
            },
        )
    for need_index, need in enumerate(needs):
        forbidden_fields = _forbidden_segment_layout_fields(need)
        if forbidden_fields:
            refusals.append(
                {
                    "programme_id": _optional_str(root.get("programme_id")),
                    "beat_index": current_beat_index,
                    "need_index": need_index,
                    "need_kind": _optional_str(need.get("kind")) or _optional_str(need.get("need")),
                    "reason": "forbidden_segment_layout_authority_field",
                    "supported_kinds": sorted(SUPPORTED_SEGMENT_LAYOUT_PRESSURE_KINDS),
                    "forbidden_fields": forbidden_fields,
                    "authority_ref": prepared_artifact_ref,
                }
            )
            continue
        mapped_kind = _need_to_segment_intent_kind(need, proposal=proposal)
        if mapped_kind is None:
            refusals.append(
                {
                    "programme_id": _optional_str(root.get("programme_id")),
                    "beat_index": current_beat_index,
                    "need_index": need_index,
                    "need_kind": _optional_str(need.get("kind")) or _optional_str(need.get("need")),
                    "reason": "unsupported_segment_layout_need",
                    "supported_kinds": sorted(SUPPORTED_SEGMENT_LAYOUT_PRESSURE_KINDS),
                    "forbidden_fields": forbidden_fields,
                    "authority_ref": prepared_artifact_ref,
                }
            )
            continue
        ttl_ms = _optional_float(need.get("ttl_ms")) or _optional_float(proposal.get("ttl_ms"))
        ttl_s = (ttl_ms / 1000.0) if ttl_ms is not None else 30.0
        evidence_refs = _evidence_refs(need) or _evidence_refs(proposal)
        if prepared_artifact_ref:
            evidence_refs = (*evidence_refs, prepared_artifact_ref)
        if not evidence_refs:
            continue
        priority = _optional_int(need.get("priority"))
        if priority is None:
            priority = (_optional_int(proposal.get("priority")) or 50) - need_index
        stable_id = _optional_str(need.get("intent_id")) or (
            f"{root.get('programme_id')}:{current_beat_index}:layout-need-{index}-{need_index}"
        )
        out.append(
            SegmentActionIntent(
                intent_id=stable_id,
                kind=mapped_kind,
                requested_at=read_mtime,
                priority=priority,
                evidence_refs=evidence_refs,
                ttl_s=ttl_s,
                programme_id=_optional_str(root.get("programme_id")),
                beat_index=current_beat_index,
                target_ref=_target_ref_for_need(need),
                authority_ref=prepared_artifact_ref,
                requested_layout=None,
                expected_effects=_expected_effects_for_need(need, mapped_kind=mapped_kind),
                spoken_text_ref=None,
            )
        )
    return tuple(out), tuple(refusals)


def _need_to_segment_intent_kind(
    need: dict[str, object],
    *,
    proposal: dict[str, object] | None = None,
) -> str | None:
    from agents.studio_compositor.segment_layout_control import LayoutNeedKind

    kind = _optional_str(need.get("kind")) or _optional_str(need.get("need"))
    if kind is None:
        return None
    posture_hints = _proposal_posture_hints(need, proposal)
    if "chatprompt" in posture_hints:
        return LayoutNeedKind.CHAT_RESPONSE.value
    if "tierstatus" in posture_hints or (
        "rankedvisual" in posture_hints and _proposal_mentions(need, proposal, "tier")
    ):
        return LayoutNeedKind.TIER_STATUS.value
    if "rankedvisual" in posture_hints:
        return LayoutNeedKind.RANKED_LIST.value
    mapping = {
        "tier": LayoutNeedKind.TIER_STATUS,
        "tier_status": LayoutNeedKind.TIER_STATUS,
        "tier_status_surface": LayoutNeedKind.TIER_STATUS,
        "tier_list_surface": LayoutNeedKind.TIER_STATUS,
        "ranked": LayoutNeedKind.RANKED_LIST,
        "ranked_list": LayoutNeedKind.RANKED_LIST,
        "ranked_list_surface": LayoutNeedKind.RANKED_LIST,
        "chat": LayoutNeedKind.CHAT_RESPONSE,
        "chat_response": LayoutNeedKind.CHAT_RESPONSE,
        "chat_participation_surface": LayoutNeedKind.CHAT_RESPONSE,
        "comparison": LayoutNeedKind.SOURCE_COMPARISON,
        "comparison_surface": LayoutNeedKind.SOURCE_COMPARISON,
        "compare": LayoutNeedKind.SOURCE_COMPARISON,
        "source_comparison": LayoutNeedKind.SOURCE_COMPARISON,
        "source_comparison_surface": LayoutNeedKind.SOURCE_COMPARISON,
        "evidence_visible": LayoutNeedKind.ARTIFACT_DETAIL,
        "action_visible": LayoutNeedKind.PROGRAMME_CONTEXT,
        "comparison_visible": LayoutNeedKind.SOURCE_COMPARISON,
        "source_visible": LayoutNeedKind.ARTIFACT_DETAIL,
        "readability_held": LayoutNeedKind.ARTIFACT_DETAIL,
        "referent_visible": LayoutNeedKind.ARTIFACT_DETAIL,
    }
    mapped = mapping.get(kind)
    if mapped is not None:
        return mapped.value
    return None


def _proposal_posture_hints(
    need: dict[str, object],
    proposal: dict[str, object] | None,
) -> frozenset[str]:
    values: list[str] = []
    values.extend(_string_tuple(need.get("proposed_postures")))
    values.extend(_string_tuple(need.get("proposed_posture")))
    values.extend(_string_tuple(need.get("posture")))
    if proposal is not None:
        values.extend(_string_tuple(proposal.get("proposed_postures")))
        values.extend(_string_tuple(proposal.get("proposed_posture")))
        values.extend(_string_tuple(proposal.get("posture")))
    return frozenset(_token(value) for value in values)


def _proposal_mentions(
    need: dict[str, object],
    proposal: dict[str, object] | None,
    token: str,
) -> bool:
    needle = _token(token)
    for value in _walk_strings(need):
        if needle in _token(value):
            return True
    if proposal is not None:
        for value in _walk_strings(proposal):
            if needle in _token(value):
                return True
    return False


def _expected_effects_for_need(
    need: dict[str, object],
    *,
    mapped_kind: str | None = None,
) -> tuple[str, ...]:
    explicit = (
        _string_tuple(need.get("expected_effects"))
        or _string_tuple(need.get("expected_effect"))
        or _string_tuple(need.get("expected_visible_effect"))
    )
    if explicit:
        return explicit
    if mapped_kind == "show_tier_status":
        return ("ward:tier-panel",)
    if mapped_kind == "show_ranked_list":
        return ("ward:ranked-list-panel",)
    if mapped_kind == "show_chat_response":
        return ("ward:chat-panel",)
    if mapped_kind == "show_source_comparison":
        return ("ward:compare-panel",)
    if mapped_kind == "show_programme_context":
        return ("ward:programme-context",)
    if mapped_kind == "show_artifact_detail":
        return ("ward:artifact-detail-panel",)
    kind = _optional_str(need.get("kind")) or ""
    if "tier" in kind:
        return ("ward:tier-panel",)
    if "rank" in kind or "list" in kind:
        return ("ward:ranked-list-panel",)
    if "chat" in kind:
        return ("ward:chat-panel",)
    if "compar" in kind:
        return ("ward:compare-panel",)
    if "action" in kind:
        return ("ward:programme-context",)
    if "evidence" in kind or "source" in kind or "readability" in kind or "referent" in kind:
        return ("ward:artifact-detail-panel",)
    return ()


def _evidence_refs(value: dict[str, object]) -> tuple[str, ...]:
    return _string_tuple(value.get("evidence_refs")) or _string_tuple(value.get("evidence_ref"))


def _target_ref_for_need(need: dict[str, object]) -> str | None:
    return (
        _optional_str(need.get("target_ref"))
        or _optional_str(need.get("target"))
        or _optional_str(need.get("source_action_kind"))
        or _optional_str(need.get("source_affordance"))
    )


def _forbidden_segment_layout_fields(value: object, *, prefix: str = "") -> tuple[str, ...]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str):
                continue
            field_path = f"{prefix}.{key}" if prefix else key
            canonical = "".join(ch for ch in key.lower() if ch.isalnum())
            if canonical in FORBIDDEN_SEGMENT_LAYOUT_PROPOSAL_KEY_TOKENS:
                found.append(field_path)
            found.extend(_forbidden_segment_layout_fields(nested, prefix=field_path))
    elif isinstance(value, list | tuple):
        for index, nested in enumerate(value):
            found.extend(_forbidden_segment_layout_fields(nested, prefix=f"{prefix}[{index}]"))
    return tuple(dict.fromkeys(found))


def _segment_hosting_pressure(raw: dict[str, object]) -> tuple[bool, tuple[dict[str, object], ...]]:
    hosting_context = raw.get("hosting_context")
    token = _hosting_context_token(hosting_context)
    if token in {"nonresponsiblestatic", "legacydefault", "nonresponsible"}:
        return False, ()
    if token in {
        "hapaxresponsiblelive",
        "responsiblehosting",
        "responsiblelive",
        "responsible",
        "explicitfallback",
    }:
        return True, ()
    return True, (
        {
            "programme_id": _optional_str(raw.get("programme_id")),
            "beat_index": _optional_int(raw.get("current_beat_index")),
            "need_index": None,
            "need_kind": None,
            "reason": "missing_or_unsupported_hosting_context",
            "supported_kinds": sorted(SUPPORTED_SEGMENT_LAYOUT_PRESSURE_KINDS),
            "forbidden_fields": (),
            "authority_ref": _prepared_artifact_ref(raw.get("prepared_artifact_ref")),
        },
    )


def _hosting_context_token(value: object) -> str:
    if isinstance(value, dict):
        nested = value.get("mode") or value.get("hosting_context")
        return _token(str(nested or ""))
    if isinstance(value, str):
        return _token(value)
    return ""


def _walk_strings(value: object) -> tuple[str, ...]:
    out: list[str] = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for nested in value.values():
            out.extend(_walk_strings(nested))
    elif isinstance(value, list | tuple):
        for nested in value:
            out.extend(_walk_strings(nested))
    return tuple(out)


def _token(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _dict_items(value: object) -> tuple[dict[str, object], ...]:
    if isinstance(value, dict):
        return (value,)
    if isinstance(value, list | tuple):
        return tuple(item for item in value if isinstance(item, dict))
    return ()


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str) and value:
        return (value,)
    if isinstance(value, list | tuple):
        return tuple(str(item) for item in value if isinstance(item, str) and item)
    return ()


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: object) -> int | None:
    try:
        if isinstance(value, bool) or value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: object) -> float | None:
    try:
        if isinstance(value, bool) or value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _prepared_artifact_ref(value: object) -> str | None:
    if isinstance(value, dict):
        sha = (
            _optional_str(value.get("artifact_sha256"))
            or _optional_str(value.get("sha256"))
            or _optional_str(value.get("sha"))
        )
        if sha is None:
            return None
        return f"prepared_artifact:{sha}"
    text = _optional_str(value)
    if text is None:
        return None
    return text if text.startswith("prepared_artifact:") else f"prepared_artifact:{text}"


def _segment_action_intents_ref(
    *,
    path: Path,
    raw: dict[str, object],
    prepared_artifact_ref: str | None,
) -> str:
    try:
        stat = path.stat()
        file_ref = f"active-segment:{stat.st_mtime_ns}"
    except OSError:
        file_ref = "active-segment:unstatable"
    segment_id = _optional_str(raw.get("programme_id")) or "unknown-segment"
    if prepared_artifact_ref:
        return f"{file_ref}:{segment_id}:{prepared_artifact_ref}"
    return f"{file_ref}:{segment_id}"


class _LayoutStoreAdapter:
    """Adapt ``LayoutStore`` to the ``apply_layout_switch`` contract.

    The adapter expects ``layout_state`` with ``mutate(fn)`` and
    ``loader`` with ``load(name)``. ``LayoutStore`` exposes
    ``set_active(name)`` and ``get(name)`` instead. The adapter wraps
    a single store so both call shapes route to the same in-process
    state.

    ``mutate`` is called by the adapter as
    ``layout_state.mutate(lambda _previous: new_layout)`` — we ignore
    the lambda's return value and instead call ``store.set_active``
    using the layout's ``name`` attribute (every Layout pydantic model
    carries ``name``). ``load`` returns the cached Layout from the
    store; if the store hasn't loaded the named layout yet we trigger
    a directory rescan and try again.
    """

    def __init__(self, store: Any) -> None:
        self._store = store

    def load(self, name: str) -> Any:
        layout = self._store.get(name)
        if layout is None:
            # Fresh layout file may have appeared since last scan.
            self._store.reload_changed()
            layout = self._store.get(name)
        if layout is None:
            raise KeyError(f"layout {name!r} not loaded in LayoutStore")
        return layout

    def mutate(self, fn: Any) -> None:
        # The adapter calls fn(previous_layout) → new_layout. We use
        # the Layout's name to drive set_active so the gauge + the
        # downstream layout consumers all see the swap.
        previous = self._store.get_active()
        new_layout = fn(previous)
        name = getattr(new_layout, "name", None)
        if not isinstance(name, str) or not name:
            raise ValueError("layout returned from mutate() lacks a 'name' attribute")
        self._store.set_active(name)

    def get_active(self) -> Any:
        return self._store.get_active()

    def active_name(self) -> str | None:
        return self._store.active_name()

    def list_available(self) -> list[str]:
        return self._store.list_available()


class _RenderedLayoutStateAdapter(_LayoutStoreAdapter):
    """Bridge LayoutStore templates into rendered LayoutState authority."""

    def __init__(self, store: Any, rendered_layout_state: Any) -> None:
        super().__init__(store)
        self._rendered_layout_state = rendered_layout_state

    def get_active(self) -> Any:
        return self._rendered_layout_state.get()

    def active_name(self) -> str | None:
        layout = self.get_active()
        name = getattr(layout, "name", None)
        return name if isinstance(name, str) and name else None

    def mutate(self, fn: Any) -> None:
        previous = self._rendered_layout_state.get()
        new_layout = fn(previous)
        name = getattr(new_layout, "name", None)
        if not isinstance(name, str) or not name:
            raise ValueError("layout returned from mutate() lacks a 'name' attribute")
        self._rendered_layout_state.mutate(lambda _previous: new_layout)
        if not self._store.set_active(name):
            raise KeyError(f"layout {name!r} not loaded in LayoutStore")


def _emit_dispatch_counter(layout_name: str, reason: str) -> None:
    """Increment ``hapax_layout_switch_dispatched_total`` if available."""
    try:
        from agents.studio_compositor import metrics as _metrics

        counter = getattr(_metrics, "HAPAX_LAYOUT_SWITCH_DISPATCHED_TOTAL", None)
        if counter is not None:
            counter.labels(layout=layout_name, reason=reason).inc()
    except Exception:
        log.debug("layout-tick dispatch counter increment failed", exc_info=True)


def _driver_tick(
    *,
    state_provider: Any,
    layout_state: Any,
    loader: Any,
    switcher: Any,
) -> Any | None:
    """One iteration: segment-responsible tick first, then legacy switcher."""
    from agents.studio_compositor.layout_switcher import (
        apply_layout_switch,
        select_layout,
    )

    state = state_provider()
    tick_now = time.time()
    responsible_receipt = _maybe_apply_responsible_segment_layout(
        state=state,
        layout_state=layout_state,
        loader=loader,
        switcher=switcher,
        now=tick_now,
    )
    if responsible_receipt is not None:
        _emit_dispatch_counter(
            responsible_receipt.selected_layout or "none",
            responsible_receipt.reason.value,
        )
        _write_segment_layout_receipt(responsible_receipt)
        return responsible_receipt

    selection = select_layout(
        consent_safe_active=bool(state.get("consent_safe_active", False)),
        vinyl_playing=bool(state.get("vinyl_playing", False)),
        director_activity=state.get("director_activity"),
        stream_mode=state.get("stream_mode"),
    )
    _emit_dispatch_counter(selection.layout_name, selection.trigger)
    try:
        apply_layout_switch(
            layout_state,
            loader,
            switcher,
            consent_safe_active=bool(state.get("consent_safe_active", False)),
            vinyl_playing=bool(state.get("vinyl_playing", False)),
            director_activity=state.get("director_activity"),
            stream_mode=state.get("stream_mode"),
        )
    except KeyError:
        # Unknown layout name in the loader — log + skip; the
        # ``install-compositor-layouts.sh`` script must run to deploy
        # the layout JSONs the switcher knows about. We still emitted
        # the dispatch counter so the operator sees the reason.
        log.warning(
            "layout-tick: layout %r not loaded; running scripts/"
            "install-compositor-layouts.sh deploys the missing JSON",
            selection.layout_name,
        )
    return None


def _maybe_apply_responsible_segment_layout(
    *,
    state: dict[str, object],
    layout_state: Any,
    loader: Any,
    switcher: Any,
    now: float,
) -> Any | None:
    intents = state.get("segment_layout_intents")
    intent_tuple = intents if isinstance(intents, tuple) else ()
    pressure_seen = bool(state.get("segment_layout_pressure_seen")) or bool(
        state.get("segment_layout_refusals")
    )

    from agents.studio_compositor.segment_layout_control import (
        LayoutDecisionReason,
        LayoutDecisionStatus,
        LayoutPosture,
        LayoutResponsibilityController,
        SegmentLayoutState,
    )

    responsible_state: dict[str, object] = getattr(
        switcher,
        "_responsible_segment_state",
        {},
    )
    if not hasattr(switcher, "_responsible_segment_state"):
        switcher._responsible_segment_state = responsible_state
    readback = _runtime_layout_readback(
        layout_state=layout_state,
        state=state,
        now=now,
    )
    decision_state = SegmentLayoutState(
        current_layout=readback.active_layout,
        current_posture=responsible_state.get("current_posture")
        or _posture_for_layout(readback.active_layout),
        active_need_id=_optional_str(responsible_state.get("active_need_id")),
        active_priority=_optional_int(responsible_state.get("active_priority")) or 0,
        switched_at=_optional_float(responsible_state.get("switched_at")),
    )
    if not intent_tuple:
        if not pressure_seen:
            return None
        refusal_items = state.get("segment_layout_refusals")
        proposal_refusals = (
            tuple(dict(item) for item in refusal_items if isinstance(item, dict))
            if isinstance(refusal_items, tuple | list)
            else ()
        )
        receipt = LayoutResponsibilityController(
            available_layouts=_available_layout_names(loader),
        ).decide(
            (),
            readback=readback,
            state=decision_state,
            now=now,
        )
        return replace(
            receipt,
            refusal_metadata={
                **dict(receipt.refusal_metadata),
                "proposal_refusals": proposal_refusals,
                "message": (
                    "active segment supplied layout pressure, but no supported proposal-only "
                    "need survived validation; legacy/default layout is suppressed for this tick"
                ),
            },
        )
    receipt = LayoutResponsibilityController(
        available_layouts=_available_layout_names(loader),
    ).decide(
        intent_tuple,
        readback=readback,
        state=decision_state,
        now=now,
    )

    if receipt.status is LayoutDecisionStatus.ACCEPTED:
        responsible_state.update(
            {
                "current_posture": receipt.selected_posture,
                "active_need_id": receipt.need_id,
                "active_priority": _intent_priority(intent_tuple, receipt.need_id),
                "switched_at": responsible_state.get("switched_at") or now,
            }
        )
        return receipt

    mutation_reasons = {
        LayoutDecisionReason.DEFAULT_STATIC_LAYOUT_IN_RESPONSIBLE_HOSTING,
        LayoutDecisionReason.RENDERED_READBACK_MISMATCH,
        LayoutDecisionReason.SAFETY_FALLBACK,
        LayoutDecisionReason.EXPLICIT_FALLBACK,
    }
    if (
        receipt.status not in {LayoutDecisionStatus.HELD, LayoutDecisionStatus.FALLBACK}
        or receipt.reason not in mutation_reasons
        or receipt.selected_layout is None
    ):
        return receipt

    previous_rendered_layout = _active_rendered_layout(layout_state)
    before_hash = _layout_state_hash(previous_rendered_layout)
    try:
        new_layout = loader.load(receipt.selected_layout)
        layout_state.mutate(lambda _previous: new_layout)
    except KeyError:
        return replace(
            receipt,
            status=LayoutDecisionStatus.HELD,
            reason=LayoutDecisionReason.UNSUPPORTED_LAYOUT,
            applied_layout_changes=(),
            unsatisfied_effects=tuple(
                dict.fromkeys((*receipt.unsatisfied_effects, f"layout:{receipt.selected_layout}"))
            ),
            refusal_metadata={
                **dict(receipt.refusal_metadata),
                "missing_layout": receipt.selected_layout,
                "message": "selected responsible layout is unavailable in runtime loader",
            },
        )

    after_hash = _layout_state_hash(_active_rendered_layout(layout_state))
    responsible_state.update(
        {
            "current_posture": receipt.selected_posture
            if receipt.selected_posture is not LayoutPosture.NON_RESPONSIBLE_FALLBACK
            else None,
            "active_need_id": receipt.need_id,
            "active_priority": _intent_priority(intent_tuple, receipt.need_id),
            "switched_at": now,
        }
    )
    return replace(
        receipt,
        applied_layout_changes=(receipt.selected_layout,),
        receipt_metadata={
            **dict(receipt.receipt_metadata),
            "runtime_mutation": "rendered_layout_state",
            "accepted_requires_future_readback": True,
            "layout_state_before_hash": before_hash,
            "layout_state_after_hash": after_hash,
        },
    )


def _runtime_layout_readback(
    *,
    layout_state: Any,
    state: dict[str, object],
    now: float,
) -> Any:
    from agents.studio_compositor.segment_layout_control import RuntimeLayoutReadback

    layout = _active_rendered_layout(layout_state)
    active_layout = getattr(layout, "name", None)
    active_layout_name = active_layout if isinstance(active_layout, str) else None
    active_wards = _active_ward_ids(layout)
    safety_state = "consent_safe_active" if bool(state.get("consent_safe_active", False)) else None
    ward_properties = _ward_property_readbacks(active_wards, state, now=now)
    return RuntimeLayoutReadback(
        readback_ref=_runtime_readback_ref(
            active_layout_name=active_layout_name,
            ward_properties=ward_properties,
            now=now,
        ),
        observed_at=now,
        active_layout=active_layout_name,
        active_wards=active_wards,
        ward_properties=ward_properties,
        camera_available=_optional_bool(state.get("camera_available")),
        safety_state=safety_state,
        chat_available=_optional_bool(state.get("chat_available")),
        media_available=_optional_bool(state.get("media_available")),
        segment_playback_ref=_optional_str(state.get("segment_playback_ref")),
        segment_action_intents_ref=_optional_str(state.get("segment_action_intents_ref")),
    )


def _active_rendered_layout(layout_state: Any) -> Any:
    if hasattr(layout_state, "get_active"):
        return layout_state.get_active()
    if hasattr(layout_state, "get"):
        return layout_state.get()
    return None


def _active_ward_ids(layout: Any) -> tuple[str, ...]:
    if layout is None:
        return ()
    active_source_ids: set[str] = set()
    assignments = getattr(layout, "assignments", ()) or ()
    if assignments:
        for assignment in assignments:
            opacity = getattr(assignment, "opacity", 1.0)
            if isinstance(opacity, int | float) and float(opacity) <= 0.0:
                continue
            source_id = getattr(assignment, "source", None)
            if isinstance(source_id, str) and source_id:
                active_source_ids.add(source_id)
    else:
        active_source_ids = {
            source.id
            for source in (getattr(layout, "sources", ()) or ())
            if isinstance(getattr(source, "id", None), str)
        }
    return tuple(
        source.id
        for source in (getattr(layout, "sources", ()) or ())
        if isinstance(getattr(source, "id", None), str) and source.id in active_source_ids
    )


def _ward_property_readbacks(
    active_wards: tuple[str, ...],
    state: dict[str, object],
    *,
    now: float,
) -> dict[str, dict[str, object]]:
    supplied = state.get("ward_properties")
    blit_readbacks = _recent_blit_readbacks(active_wards, now=now)
    if not blit_readbacks:
        return {}
    try:
        from agents.studio_compositor.ward_properties import resolve_ward_properties
    except Exception:
        log.debug("layout-tick: ward property import failed", exc_info=True)
        return {}

    out: dict[str, dict[str, object]] = {}
    for ward_id in active_wards:
        blit = blit_readbacks.get(ward_id)
        if blit is None:
            continue
        if isinstance(supplied, dict) and isinstance(supplied.get(ward_id), dict):
            out[ward_id] = dict(supplied[ward_id])
        else:
            try:
                props = resolve_ward_properties(ward_id)
            except Exception:
                log.debug("layout-tick: ward property read failed for %s", ward_id, exc_info=True)
                continue
            if is_dataclass(props):
                out[ward_id] = asdict(props)
            elif isinstance(props, dict):
                out[ward_id] = dict(props)
            else:
                out[ward_id] = {}
        source_pixels = _optional_float(blit.get("source_pixels"))
        effective_alpha = _optional_float(blit.get("effective_alpha"))
        out[ward_id].update(
            {
                "visible": bool(out[ward_id].get("visible") is True)
                and source_pixels is not None
                and source_pixels > 0
                and effective_alpha is not None
                and effective_alpha > 0.0,
                "rendered_blit": True,
                "rendered_at": blit.get("observed_at"),
                "source_pixels": source_pixels,
                "effective_alpha": effective_alpha,
            }
        )
    return out


def _recent_blit_readbacks(
    active_wards: tuple[str, ...],
    *,
    now: float,
) -> dict[str, dict[str, object]]:
    try:
        from agents.studio_compositor.fx_chain import recent_blit_readbacks
    except Exception:
        log.debug("layout-tick: blit readback import failed", exc_info=True)
        return {}
    try:
        return recent_blit_readbacks(active_wards, now=now)
    except Exception:
        log.debug("layout-tick: blit readback read failed", exc_info=True)
        return {}


def _runtime_readback_ref(
    *,
    active_layout_name: str | None,
    ward_properties: dict[str, dict[str, object]],
    now: float,
) -> str:
    rendered_wards = sorted(
        ward_id for ward_id, props in ward_properties.items() if props.get("rendered_blit") is True
    )
    if rendered_wards:
        rendered_hash = hashlib.sha256(",".join(rendered_wards).encode("utf-8")).hexdigest()[:12]
        return f"rendered-blit-readback:{active_layout_name or 'none'}:{rendered_hash}:{int(now)}"
    return f"rendered-layout-state:{active_layout_name or 'none'}:no-fresh-blit:{int(now)}"


def _available_layout_names(loader: Any) -> tuple[str, ...]:
    if hasattr(loader, "list_available"):
        try:
            return tuple(str(name) for name in loader.list_available())
        except Exception:
            log.debug("layout-tick: list_available failed", exc_info=True)
    store = getattr(loader, "_store", None)
    layouts = getattr(store, "layouts", None)
    if isinstance(layouts, dict):
        return tuple(str(name) for name in layouts)
    return ()


def _posture_for_layout(layout_name: str | None) -> Any | None:
    if layout_name is None:
        return None
    from agents.studio_compositor.segment_layout_control import POSTURE_TO_LAYOUT

    for posture, posture_layout in POSTURE_TO_LAYOUT.items():
        if posture_layout == layout_name:
            return posture
    return None


def _intent_priority(intents: tuple[Any, ...], need_id: str | None) -> int:
    if need_id is None:
        return 0
    for intent in intents:
        if getattr(intent, "intent_id", None) == need_id:
            return _optional_int(getattr(intent, "priority", None)) or 0
    return 0


def _optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _write_segment_layout_receipt(receipt: Any) -> None:
    payload = json.dumps(receipt.visible_metadata, sort_keys=True)
    try:
        SEGMENT_LAYOUT_RECEIPT_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SEGMENT_LAYOUT_RECEIPT_FILE.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(SEGMENT_LAYOUT_RECEIPT_FILE)
    except OSError:
        log.debug("layout-tick: segment layout receipt write failed", exc_info=True)


def _layout_state_hash(layout: Any) -> str | None:
    if layout is None:
        return None
    if hasattr(layout, "model_dump"):
        payload = json.dumps(layout.model_dump(mode="json"), sort_keys=True, default=str)
    else:
        payload = repr(layout)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_layout_tick_loop(
    *,
    layout_state: Any,
    loader: Any,
    switcher: Any,
    state_provider: Any,
    interval_s: float = DEFAULT_DRIVER_INTERVAL_S,
    stop_event: Any | None = None,
    iterations: int | None = None,
    sleep_fn: Any = time.sleep,
) -> int:
    """Tick driver loop. Returns count of iterations executed.

    Parameters mirror ``layout_switcher.run_layout_switch_loop`` but
    add the dispatch counter side-effect via ``_driver_tick``. Tests
    inject ``iterations`` or set ``stop_event`` for bounded runs;
    production passes neither (runs until daemon thread exits).
    """
    iter_count = 0
    while True:
        if stop_event is not None:
            try:
                if stop_event.is_set():
                    break
            except Exception:
                log.debug("stop_event.is_set() failed; continuing", exc_info=True)
        if iterations is not None and iter_count >= iterations:
            break
        try:
            _driver_tick(
                state_provider=state_provider,
                layout_state=layout_state,
                loader=loader,
                switcher=switcher,
            )
        except Exception:
            log.warning("layout-tick driver tick raised; loop continues", exc_info=True)
        iter_count += 1
        sleep_fn(interval_s)
    return iter_count


def start_layout_tick_driver(compositor: Any) -> threading.Thread | None:
    """Start the layout-tick daemon thread alongside the compositor.

    Returns the thread object so callers can ``.join()`` in tests; in
    production the thread is daemon=True and dies with the process.
    Returns ``None`` if disabled by env-flag or if the LayoutStore has
    not been initialized on the compositor (defensive).
    """
    if _is_disabled():
        log.info("layout-tick driver disabled via %s", ENV_DISABLE)
        return None

    store = getattr(compositor, "_layout_store", None)
    if store is None:
        log.warning("compositor._layout_store missing — layout-tick driver not started")
        return None

    from agents.studio_compositor.layout_switcher import LayoutSwitcher

    initial = store.active_name() or "garage-door"
    switcher = LayoutSwitcher(initial_layout=initial)
    switcher._responsible_segment_state = {}  # type: ignore[attr-defined]
    rendered_layout_state = getattr(compositor, "layout_state", None)
    adapter = (
        _RenderedLayoutStateAdapter(store, rendered_layout_state)
        if rendered_layout_state is not None
        else _LayoutStoreAdapter(store)
    )

    state_provider = build_state_provider()

    def _target() -> None:
        log.info(
            "layout-tick driver started (interval=%.1fs initial=%s)",
            DEFAULT_DRIVER_INTERVAL_S,
            initial,
        )
        run_layout_tick_loop(
            layout_state=adapter,
            loader=adapter,
            switcher=switcher,
            state_provider=state_provider,
            interval_s=DEFAULT_DRIVER_INTERVAL_S,
        )

    thread = threading.Thread(target=_target, daemon=True, name="layout-tick-driver")
    thread.start()
    compositor._layout_tick_thread = thread  # type: ignore[attr-defined]
    return thread


__all__ = [
    "ALBUM_STATE_FILE",
    "DEFAULT_DRIVER_INTERVAL_S",
    "DIRECTOR_INTENT_JSONL",
    "DIRECTOR_INTENT_STALE_S",
    "ENV_DISABLE",
    "SEGMENT_LAYOUT_RECEIPT_FILE",
    "SEGMENT_STATE_FILE",
    "VINYL_CONFIDENCE_THRESHOLD",
    "VINYL_OPERATOR_OVERRIDE_FLAG",
    "VINYL_STATE_STALE_S",
    "build_state_provider",
    "run_layout_tick_loop",
    "start_layout_tick_driver",
]
