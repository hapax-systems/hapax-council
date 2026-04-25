"""Per-source caption routing policy (ytb-009 Phase 3).

Reads the YAML schema documented at ``config/caption-routing.yaml``
and decides whether a caption with a given ``speaker`` tag should be
routed into the in-band CEA-708 caption track.

Decision order:
1. Explicit ``deny`` list wins. A speaker on both lists is denied.
2. Explicit ``allow`` list passes.
3. Empty/None speaker (operator narration with no tag) is allowed
   unconditionally — operator's own speech is the default source per
   the routing config's preamble.
4. Otherwise the file's ``default`` field decides (``allow`` or
   ``deny``). Defaults to ``allow`` when the field is absent so a
   minimal/empty config still yields visible captions.

The routing layer enforces this BEFORE the GStreamer encoder sees
the caption, mirroring the
``axioms/contracts/publication/*.yaml`` posture.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from agents.live_captions.writer import CaptionWriter

log = logging.getLogger(__name__)

DEFAULT_ROUTING_CONFIG = Path(
    os.environ.get(
        "HAPAX_CAPTION_ROUTING_CONFIG",
        "config/caption-routing.yaml",
    )
)


@dataclass(frozen=True)
class RoutingPolicy:
    """Loaded allow/deny policy for caption routing."""

    allow: frozenset[str] = field(default_factory=frozenset)
    deny: frozenset[str] = field(default_factory=frozenset)
    default_allow: bool = True

    @classmethod
    def load(cls, path: Path = DEFAULT_ROUTING_CONFIG) -> RoutingPolicy:
        """Load policy from YAML; missing file → default-allow + empty lists.

        Malformed YAML logs and falls back to default-allow with empty
        lists rather than raising — a broken config file should not
        gate the live broadcast captions track. Operator sees the
        warning + default-allow behavior, can fix the config without a
        daemon restart by re-loading.
        """
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            log.info("caption routing config absent at %s; default-allow", path)
            return cls()
        except (yaml.YAMLError, OSError):
            log.warning(
                "caption routing config unreadable at %s; default-allow",
                path,
                exc_info=True,
            )
            return cls()
        if not isinstance(data, dict):
            return cls()
        allow_raw = data.get("allow") or []
        deny_raw = data.get("deny") or []
        default_raw = str(data.get("default", "allow")).lower()
        allow = frozenset(_clean_list(allow_raw))
        deny = frozenset(_clean_list(deny_raw))
        return cls(
            allow=allow,
            deny=deny,
            default_allow=default_raw == "allow",
        )

    def allows(self, speaker: str | None) -> bool:
        """True iff a caption from ``speaker`` should be routed.

        See module docstring for the decision order.
        """
        if not speaker:
            return True
        if speaker in self.deny:
            return False
        if speaker in self.allow:
            return True
        return self.default_allow


def _clean_list(value: object) -> list[str]:
    """Coerce a YAML list field to ``list[str]``; tolerate None."""
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if isinstance(v, str | int | float)]


class RoutedCaptionWriter:
    """``CaptionWriter`` wrapper that applies a ``RoutingPolicy`` per emit.

    Constructor parameters
    ----------------------
    policy:
        RoutingPolicy decision source. Tests inject a stub; production
        wires ``RoutingPolicy.load()``.
    writer:
        Underlying ``CaptionWriter`` (or any object with the same
        ``emit()`` signature).

    Captions denied by the policy are dropped silently (logged at
    debug). Allowed captions pass through unchanged. The wrapper
    increments no metrics — observability for filtered captions
    will land alongside the GStreamer attachment in the alpha lane.
    """

    def __init__(self, *, policy: RoutingPolicy, writer: CaptionWriter) -> None:
        self._policy = policy
        self._writer = writer
        # Lock around policy swap so a config reload mid-emit doesn't
        # split a route-decision across two policies.
        self._lock = threading.Lock()

    def emit(
        self,
        *,
        ts: float,
        text: str,
        duration_ms: int = 0,
        speaker: str | None = None,
    ) -> bool:
        """Apply policy then forward; return True iff caption was emitted."""
        with self._lock:
            policy = self._policy
        if not policy.allows(speaker):
            log.debug("caption from %r filtered by routing policy", speaker)
            return False
        self._writer.emit(ts=ts, text=text, duration_ms=duration_ms, speaker=speaker)
        return True

    def reload_policy(self, path: Path = DEFAULT_ROUTING_CONFIG) -> None:
        """Hot-swap the underlying policy without daemon restart."""
        new_policy = RoutingPolicy.load(path)
        with self._lock:
            self._policy = new_policy


__all__ = ["DEFAULT_ROUTING_CONFIG", "RoutedCaptionWriter", "RoutingPolicy"]
