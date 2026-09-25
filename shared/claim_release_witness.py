"""provider_wall witness for a governed claim release.

Binds a claim incumbent to its native trace through its relay record, then asks the shared
quota readers whether a provider-native wall that certainly began after the incumbent's last
served turn is still live. A lease is released on a wall, never on silence: the proof needs a
wall's *earliest* bound strictly after the last turn (a late-dated wall would release a live
lease), the same provider pool, and a wall the shared predicate still holds live.

This module parses no provider stream and no quota row. Walls and turns come from the shared
readers in ``shared.quota_headroom`` (``read_wall_signals``, ``wall_is_live``,
``last_served_turn``); until they exist the witness is typed unavailable. Everything it cannot
bind (no relay, another session, no native thread, an unknown platform, no served turn) is
``unknown`` and refuses: an unwalled or unobservable holder is never released on this witness.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

from shared.sdlc_claim import ClaimPublicationError

if TYPE_CHECKING:
    from shared.sdlc_claim import ClaimLeaseIncumbent

_READER_NAMES = ("read_wall_signals", "wall_is_live", "last_served_turn")
_PLATFORM_FAMILY = {"codex": "codex"}


def _unknown(detail: str) -> ClaimPublicationError:
    return ClaimPublicationError(
        "claim_release_wall_unknown",
        "the holder cannot be bound to a provider wall; use self_yield, terminal_task or a "
        "recorded operator_release instead",
        detail,
    )


def _shared_readers() -> ModuleType:
    try:
        module = importlib.import_module("shared.quota_headroom")
    except ImportError:
        module = None
    missing = [
        name
        for name in _READER_NAMES
        if module is None or not callable(getattr(module, name, None))
    ]
    if missing:
        raise ClaimPublicationError(
            "claim_release_witness_verifier_unavailable",
            "provider_wall needs the shared wall and last-turn readers; until they are "
            "installed use self_yield, terminal_task or a recorded operator_release",
            "missing: " + ", ".join(missing),
        )
    return module  # type: ignore[return-value]


def _relay_record(home: Path, role: str) -> dict[str, Any]:
    path = home / ".cache" / "hapax" / "relay" / f"{role}.yaml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _unknown(f"no relay record for {role}") from exc
    try:
        record, _end = json.JSONDecoder().raw_decode(text.lstrip())
    except ValueError as exc:
        raise _unknown(f"relay record for {role} does not begin with a JSON object") from exc
    if not isinstance(record, dict):
        raise _unknown(f"relay record for {role} is not an object")
    return record


def _codex_trace(home: Path, thread: str) -> Path:
    codex_home = Path(os.environ.get("CODEX_HOME") or home / ".codex")
    matches = sorted((codex_home / "sessions").glob(f"*/*/*/rollout-*-{thread}.jsonl"))
    if len(matches) != 1:
        raise _unknown(f"{len(matches)} rollouts for native thread {thread}")
    return matches[0]


def _codex_model_provider(trace: Path) -> str | None:
    try:
        with trace.open(encoding="utf-8") as handle:
            first = json.loads(handle.readline())
    except (OSError, ValueError):
        return None
    payload = first.get("payload") if isinstance(first, dict) else None
    value = payload.get("model_provider") if isinstance(payload, dict) else None
    return value if isinstance(value, str) and value else None


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str) and value:
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def verify_provider_wall(
    incumbent: ClaimLeaseIncumbent,
    now: datetime,
    *,
    home: Path | None = None,
    readers: Any = None,
) -> dict[str, object]:
    """Return evidence that the incumbent's provider pool walled after its last turn."""

    readers = readers or _shared_readers()
    home = home or Path.home()
    if incumbent.session_id is None:
        raise _unknown("the lease names no session")
    relay = _relay_record(home, incumbent.role)
    if relay.get("session_id") != incumbent.session_id:
        raise _unknown("the relay record belongs to another session")
    family = _PLATFORM_FAMILY.get(str(relay.get("platform", "")))
    if family is None:
        raise _unknown(f"no provider-wall binding for platform {relay.get('platform')!r}")
    thread = relay.get("native_thread_id") or relay.get("native_thread")
    if not isinstance(thread, str) or not thread:
        raise _unknown("the relay record names no native thread")
    trace = _codex_trace(home, thread)
    provider = _codex_model_provider(trace)
    if provider is None:
        raise _unknown("the native trace names no model provider")
    last_turn = _as_datetime(readers.last_served_turn(trace))
    if last_turn is None:
        raise _unknown("the native trace shows no served turn")

    rows = list(readers.read_wall_signals(family, now=now))
    proven = []
    for wall in rows:
        if getattr(wall, "label", None) != "wall-signal":
            continue
        details = getattr(wall, "details", None) or {}
        earliest = _as_datetime(details.get("earliest_at"))
        if (
            earliest is not None
            and earliest > last_turn
            and details.get("model_provider") == provider
            and readers.wall_is_live(wall, rows, now=now)
        ):
            proven.append((earliest, wall))
    if not proven:
        raise ClaimPublicationError(
            "claim_release_wall_not_proven",
            "no live provider wall certainly began after the holder's last served turn; "
            "wait for one, or use another witness",
            json.dumps(
                {"last_served_turn": last_turn.isoformat(), "wall_rows_seen": len(rows)},
                sort_keys=True,
            ),
        )
    earliest, wall = min(proven, key=lambda item: item[0])
    resets_at = _as_datetime(getattr(wall, "resets_at", None))
    return {
        "family": family,
        "model_provider": provider,
        "trace_sha256": hashlib.sha256(str(trace).encode("utf-8")).hexdigest(),
        "last_served_turn": last_turn.isoformat(),
        "wall_earliest_at": earliest.isoformat(),
        "wall_observed_at": str(getattr(wall, "observed_at", "")),
        "wall_resets_at": resets_at.isoformat() if resets_at else None,
        "wall_window": getattr(wall, "window", None),
        "wall_source": getattr(wall, "source", None),
        "checked_at": now.astimezone(UTC).isoformat(),
    }
