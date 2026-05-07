"""Machine-readable pause gate for segment-prep activities.

The pause file is an operational interlock, not a quality evaluator. It lets
timers, services, and manual runners fail closed while research/review work is
underway, without changing the resident-model or selected-release contracts.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATE_ENV = "HAPAX_STATE"
AUTHORITY_FILE_ENV = "HAPAX_SEGMENT_PREP_AUTHORITY_FILE"
AUTHORITY_MODE_ENV = "HAPAX_SEGMENT_PREP_AUTHORITY_MODE"
AUTHORITY_REASON_ENV = "HAPAX_SEGMENT_PREP_AUTHORITY_REASON"
PAUSE_FILE_ENV = "HAPAX_SEGMENT_PREP_PAUSE_FILE"
PAUSE_MODE_ENV = "HAPAX_SEGMENT_PREP_PAUSE_MODE"
PAUSE_REASON_ENV = "HAPAX_SEGMENT_PREP_PAUSE_REASON"

ACTIVITIES: tuple[str, ...] = (
    "research",
    "docs",
    "audit",
    "canary",
    "pool_generation",
    "runtime_pool_load",
)

MODE_ALLOWED: dict[str, tuple[str, ...]] = {
    "open": ACTIVITIES,
    "paused": (),
    "research_only": ("research",),
    "docs_only": ("research", "docs", "audit"),
    "ancillary_only": ("research", "docs", "audit"),
    "canary_allowed": ("research", "docs", "audit", "canary"),
    "pool_generation_allowed": (
        "research",
        "docs",
        "audit",
        "canary",
        "pool_generation",
    ),
    "runtime_pool_load_allowed": ACTIVITIES,
}

MODE_ALIASES: dict[str, str] = {
    "": "open",
    "off": "open",
    "none": "open",
    "unpaused": "open",
    "all": "open",
    "all_allowed": "open",
    "hard_paused": "paused",
    "pause": "paused",
    "pool_allowed": "pool_generation_allowed",
    "generation_allowed": "pool_generation_allowed",
    "runtime_allowed": "runtime_pool_load_allowed",
}


class SegmentPrepPauseError(RuntimeError):
    """Raised when the pause state cannot be read or normalized."""


class SegmentPrepPaused(RuntimeError):
    """Raised when an activity is blocked by the current pause state."""


@dataclass(frozen=True)
class SegmentPrepPauseState:
    mode: str
    allowed_activities: tuple[str, ...]
    reason: str = ""
    updated_at: str = ""
    updated_by: str = ""
    source: str = "default"
    path: str | None = None

    def allows(self, activity: str) -> bool:
        return normalize_activity(activity) in self.allowed_activities

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "mode": self.mode,
            "allowed_activities": list(self.allowed_activities),
            "reason": self.reason,
            "updated_at": self.updated_at,
            "updated_by": self.updated_by,
            "source": self.source,
            "path": self.path,
        }


def _env_map(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def normalize_mode(mode: str | None) -> str:
    key = str(mode or "").strip().lower().replace("-", "_")
    key = MODE_ALIASES.get(key, key)
    if key not in MODE_ALLOWED:
        raise SegmentPrepPauseError(
            f"unknown segment-prep pause mode {mode!r}; "
            f"known modes: {', '.join(sorted(MODE_ALLOWED))}"
        )
    return key


def normalize_activity(activity: str) -> str:
    key = str(activity).strip().lower().replace("-", "_")
    if key not in ACTIVITIES:
        raise SegmentPrepPauseError(
            f"unknown segment-prep activity {activity!r}; known activities: {', '.join(ACTIVITIES)}"
        )
    return key


def pause_state_path(
    path: Path | str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    if path is not None:
        return Path(path).expanduser()
    env_map = _env_map(env)
    if explicit := env_map.get(AUTHORITY_FILE_ENV) or env_map.get(PAUSE_FILE_ENV):
        return Path(explicit).expanduser()
    state_root = Path(env_map.get(STATE_ENV, str(Path.home() / "hapax-state"))).expanduser()
    return state_root / "segment-prep" / "prep-authority.json"


def _state_from_mode(
    mode: str,
    *,
    reason: str = "",
    updated_at: str = "",
    updated_by: str = "",
    source: str,
    path: Path | None,
) -> SegmentPrepPauseState:
    normalized = normalize_mode(mode)
    return SegmentPrepPauseState(
        mode=normalized,
        allowed_activities=MODE_ALLOWED[normalized],
        reason=reason,
        updated_at=updated_at,
        updated_by=updated_by,
        source=source,
        path=str(path) if path is not None else None,
    )


def load_pause_state(
    path: Path | str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> SegmentPrepPauseState:
    env_map = _env_map(env)
    resolved = pause_state_path(path, env=env_map)

    if override := env_map.get(AUTHORITY_MODE_ENV) or env_map.get(PAUSE_MODE_ENV):
        reason = env_map.get(AUTHORITY_REASON_ENV) or env_map.get(PAUSE_REASON_ENV, "")
        source_env = AUTHORITY_MODE_ENV if env_map.get(AUTHORITY_MODE_ENV) else PAUSE_MODE_ENV
        return _state_from_mode(
            override,
            reason=reason,
            updated_at="",
            updated_by="",
            source=f"env:{source_env}",
            path=resolved,
        )

    if not resolved.exists():
        return _state_from_mode("research_only", source=f"missing:{resolved}", path=resolved)

    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SegmentPrepPauseError(
            f"cannot read segment-prep pause state {resolved}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise SegmentPrepPauseError(f"segment-prep pause state {resolved} must be a JSON object")

    mode = payload.get("mode")
    if not isinstance(mode, str) or not mode.strip():
        return _state_from_mode(
            "research_only",
            reason=str(payload.get("reason", "authority file missing mode")),
            updated_at=str(payload.get("updated_at", "")),
            updated_by=str(payload.get("updated_by", "")),
            source=f"file_missing_mode:{resolved}",
            path=resolved,
        )

    return _state_from_mode(
        mode,
        reason=str(payload.get("reason", "")),
        updated_at=str(payload.get("updated_at", "")),
        updated_by=str(payload.get("updated_by", "")),
        source=f"file:{resolved}",
        path=resolved,
    )


def save_pause_state(
    mode: str,
    *,
    reason: str = "",
    updated_by: str | None = None,
    path: Path | str | None = None,
    env: Mapping[str, str] | None = None,
) -> SegmentPrepPauseState:
    resolved = pause_state_path(path, env=env)
    state = _state_from_mode(
        mode,
        reason=reason,
        updated_at=datetime.now(tz=UTC).isoformat(),
        updated_by=updated_by or os.environ.get("USER", "unknown"),
        source=f"file:{resolved}",
        path=resolved,
    )
    resolved.parent.mkdir(parents=True, exist_ok=True)
    tmp = resolved.with_suffix(resolved.suffix + ".tmp")
    tmp.write_text(
        json.dumps(state.to_payload(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(resolved)
    return state


def clear_pause_state(
    path: Path | str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    resolved = pause_state_path(path, env=env)
    try:
        resolved.unlink()
    except FileNotFoundError:
        pass
    return resolved


def blocked_message(activity: str, state: SegmentPrepPauseState) -> str:
    reason = f"; reason: {state.reason}" if state.reason else ""
    return (
        f"segment-prep activity {normalize_activity(activity)!r} is blocked by "
        f"pause mode {state.mode!r} from {state.source}{reason}"
    )


def assert_segment_prep_allowed(
    activity: str = "pool_generation",
    *,
    path: Path | str | None = None,
    env: Mapping[str, str] | None = None,
) -> SegmentPrepPauseState:
    normalized_activity = normalize_activity(activity)
    state = load_pause_state(path, env=env)
    if not state.allows(normalized_activity):
        raise SegmentPrepPaused(blocked_message(normalized_activity, state))
    return state


def _print_status(state: SegmentPrepPauseState, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(state.to_payload(), sort_keys=True))
        return
    allowed = ", ".join(state.allowed_activities) if state.allowed_activities else "none"
    print(f"segment-prep pause mode: {state.mode}")
    print(f"allowed activities: {allowed}")
    if state.reason:
        print(f"reason: {state.reason}")
    print(f"source: {state.source}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Segment-prep pause gate")
    parser.add_argument("--check", action="store_true", help="fail unless the activity is allowed")
    parser.add_argument("--activity", default="pool_generation", help="activity to check")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("--status", action="store_true", help="print the current pause state")
    parser.add_argument("--set", dest="set_mode", help="write a pause mode")
    parser.add_argument("--reason", default="", help="reason to store with --set")
    parser.add_argument("--updated-by", default=None, help="operator/session label for --set")
    parser.add_argument("--clear", action="store_true", help="remove the pause file")
    parser.add_argument("--path", type=Path, default=None, help="override pause-state file path")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    try:
        if args.clear:
            path = clear_pause_state(args.path)
            state = _state_from_mode("research_only", source=f"cleared:{path}", path=path)
        elif args.set_mode:
            state = save_pause_state(
                args.set_mode,
                reason=args.reason,
                updated_by=args.updated_by,
                path=args.path,
            )
        else:
            state = load_pause_state(args.path)

        if args.check:
            assert_segment_prep_allowed(args.activity, path=args.path)
            if args.json:
                print(json.dumps({"ok": True, **state.to_payload()}, sort_keys=True))
            else:
                print(f"segment-prep activity {normalize_activity(args.activity)!r} allowed")
            return 0

        if args.status or args.set_mode or args.clear or args.json:
            _print_status(state, json_output=args.json)
        return 0
    except Exception as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        else:
            print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
