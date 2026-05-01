"""Voice output router — semantic API for director audio route selection.

Caller asks for an audio surface by ROLE (``assistant`` / ``broadcast`` /
``private_monitor`` / ``notification``), not a raw PipeWire target name.
Router returns the actual sink + provenance + a fail-closed marker if
the target role is unavailable.

This module is the thin role-keyed semantic API the cc-task
``voice-output-router-semantic-api`` calls for. It deliberately does
NOT duplicate the existing ``shared.voice_output_router`` policy
machinery (which carries witness gates, fallback policies, dry-run
probing, etc.) — that module remains the policy authority. The
purpose of this module is to give the director a single line of
intent — "give me the broadcast sink" — without it having to know
about witness gates or fallback logic.

Out of scope (separate cc-tasks):
  - Witness emission to the world surface
    → ``world-surface-health-audio-adapter``
  - Director rewrite to call this API
    → ``director-loop-semantic-audio-route``
  - PipeWire conf.d changes

Out of scope (this module is API-only):
  - Live PipeWire link surgery
  - Sink-existence checks against pw-cli (caller may inject a
    ``sink_present`` callback to upgrade ``provenance="config_role"``
    to ``provenance="unavailable"`` when the live graph lacks the sink)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

import yaml

log = logging.getLogger(__name__)

VoiceRole = Literal["assistant", "broadcast", "private_monitor", "notification"]
VOICE_ROLES: Final[tuple[VoiceRole, ...]] = (
    "assistant",
    "broadcast",
    "private_monitor",
    "notification",
)
_VOICE_ROLE_SET: Final[frozenset[str]] = frozenset(VOICE_ROLES)

DEFAULT_ROUTES_PATH: Final[Path] = (
    Path(__file__).resolve().parent.parent / "config" / "voice-output-routes.yaml"
)

Provenance = Literal["config_role", "fallback", "unavailable"]


class VoiceRoleRouterError(ValueError):
    """Raised when the router cannot serve a request safely."""


@dataclass(frozen=True)
class RouteResult:
    """Resolved route for one semantic role.

    ``sink_name`` is the PipeWire sink identifier the caller should
    pass to ``pw-cat --target=...``. ``None`` when the role is
    configured but the sink isn't available right now (per the
    operator-injected ``sink_present`` check).
    """

    role: VoiceRole
    sink_name: str | None
    provenance: Provenance
    live_at: str
    description: str | None = None


class VoiceOutputRouter:
    """YAML-config-driven role → PipeWire sink resolver.

    The router lazy-loads ``config/voice-output-routes.yaml`` on the
    first ``route()`` call and reloads automatically when the file's
    mtime advances. No daemon thread; reload is synchronous and cheap.

    A ``sink_present`` predicate may be injected at construction time
    to upgrade ``"config_role"`` results to ``"unavailable"`` when the
    live PipeWire graph doesn't carry the configured sink. The router
    itself never inspects the live graph — that's caller policy.
    """

    def __init__(
        self,
        *,
        routes_path: Path | None = None,
        sink_present: Callable[[str], bool] | None = None,
    ) -> None:
        self._routes_path = routes_path if routes_path is not None else DEFAULT_ROUTES_PATH
        self._sink_present = sink_present
        self._mapping: dict[VoiceRole, dict[str, str]] = {}
        self._loaded_mtime: float | None = None

    def _load_if_stale(self) -> None:
        try:
            mtime = self._routes_path.stat().st_mtime
        except FileNotFoundError:
            self._mapping = {}
            self._loaded_mtime = None
            return
        if self._loaded_mtime is not None and self._loaded_mtime == mtime:
            return
        try:
            data = yaml.safe_load(self._routes_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            log.warning(
                "voice_role_router: failed to read %s; treating as empty",
                self._routes_path,
                exc_info=True,
            )
            self._mapping = {}
            self._loaded_mtime = mtime
            return
        roles_section = data.get("roles") if isinstance(data, dict) else None
        mapping: dict[VoiceRole, dict[str, str]] = {}
        if isinstance(roles_section, dict):
            for raw_role, raw_entry in roles_section.items():
                if raw_role not in _VOICE_ROLE_SET or not isinstance(raw_entry, dict):
                    continue
                sink_name = raw_entry.get("sink_name")
                if not isinstance(sink_name, str) or not sink_name.strip():
                    continue
                description = raw_entry.get("description")
                mapping[raw_role] = {  # type: ignore[index]
                    "sink_name": sink_name.strip(),
                    "description": (description.strip() if isinstance(description, str) else ""),
                }
        self._mapping = mapping
        self._loaded_mtime = mtime

    def route(self, role: VoiceRole | str) -> RouteResult:
        """Resolve one semantic role to a sink_name + provenance.

        Raises ``VoiceRoleRouterError`` for an unknown role string —
        the operator's audio policy is bounded to four roles, and a
        typo in caller code is a programmer error, not a runtime
        condition that should be silently masked.
        """

        if role not in _VOICE_ROLE_SET:
            raise VoiceRoleRouterError(f"unknown voice role {role!r}; valid roles: {VOICE_ROLES!r}")
        self._load_if_stale()
        live_at = datetime.now(tz=UTC).isoformat()
        entry = self._mapping.get(role)  # type: ignore[arg-type]
        if entry is None:
            return RouteResult(
                role=role,  # type: ignore[arg-type]
                sink_name=None,
                provenance="unavailable",
                live_at=live_at,
            )
        sink_name = entry["sink_name"]
        if self._sink_present is not None and not self._sink_present(sink_name):
            return RouteResult(
                role=role,  # type: ignore[arg-type]
                sink_name=None,
                provenance="unavailable",
                live_at=live_at,
                description=entry.get("description") or None,
            )
        return RouteResult(
            role=role,  # type: ignore[arg-type]
            sink_name=sink_name,
            provenance="config_role",
            live_at=live_at,
            description=entry.get("description") or None,
        )

    def known_roles(self) -> tuple[VoiceRole, ...]:
        """Return the roles currently configured (operator dashboard helper)."""

        self._load_if_stale()
        return tuple(role for role in VOICE_ROLES if role in self._mapping)


__all__ = [
    "DEFAULT_ROUTES_PATH",
    "VOICE_ROLES",
    "Provenance",
    "RouteResult",
    "VoiceOutputRouter",
    "VoiceRole",
    "VoiceRoleRouterError",
]
