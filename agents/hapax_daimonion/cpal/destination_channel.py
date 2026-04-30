"""CPAL TTS destination classification and route compatibility.

Every Hapax TTS utterance is classified as ``livestream`` or ``private`` at
synthesis time. Those legacy labels are now metrics/classification labels only:
playback callsites must resolve them through ``shared.voice_output_router`` so
public voice binds to the broadcast policy target and private voice fails closed
unless the exact private monitor route has fresh evidence.

**Classification rules** (order matters — first match wins):

1. Impingement ``source`` starts with ``"operator.sidechat"`` → PRIVATE.
2. Impingement ``content["channel"] == "sidechat"`` → PRIVATE.
3. Impingement ``content["kind"] == "debug"`` → PRIVATE.
4. ``voice_register == TEXTMODE`` AND the impingement was sidechat-origin
   (covered by 1/2 above; the register alone does not flip destination).
5. Otherwise → LIVESTREAM.

The register gate (rule 4) is intentionally subordinate: TEXTMODE can
be set by HOMAGE packages unrelated to sidechat (e.g., a BitchX lineage
announcement); those still belong on the livestream. Only when TEXTMODE
coincides with a sidechat-origin impingement do we route private — and
rules 1/2 already catch that case.

**Feature flag**: ``HAPAX_TTS_DESTINATION_ROUTING_ACTIVE`` (default ``1``).
The flag parser remains for dashboards and legacy controls, but it no longer
authorizes fallback to ``HAPAX_TTS_TARGET`` or the system default for private
routes.

**Telemetry**: Prometheus counter ``hapax_tts_destination_total{destination}``
increments on every classification. The classification is also logged at
INFO level; the log message never contains the utterance body or
operator-identifying content, only the chosen destination and a short
provenance tag.
"""

from __future__ import annotations

import logging
import os
from enum import StrEnum
from pathlib import Path
from typing import Any

from shared.voice_output_router import (
    DEFAULT_PRIVATE_MONITOR_STATUS_PATH,
    VoiceOutputDestination,
    VoiceRouteResult,
    media_role_for_route,
    resolve_voice_output_route,
    target_for_route,
)
from shared.voice_register import VoiceRegister

log = logging.getLogger(__name__)


DESTINATION_ROUTING_ENV: str = "HAPAX_TTS_DESTINATION_ROUTING_ACTIVE"
"""Legacy feature flag parser. It does not permit private/default fallback."""

DEFAULT_TARGET_ENV: str = "HAPAX_TTS_TARGET"
"""Legacy default target env var. Semantic routing no longer consumes it."""

LIVESTREAM_SINK: str = "hapax-livestream"
"""Legacy livestream sink label retained for dashboards and compatibility."""

PRIVATE_SINK: str = "hapax-private"
"""Private null sink that is audible only through the exact monitor bridge."""


class DestinationChannel(StrEnum):
    """Where an utterance plays back.

    ``LIVESTREAM`` — public broadcast path. Every utterance defaults
    here unless classification explicitly diverts it.

    ``PRIVATE`` — operator-only path (sidechat replies, debug narration).
    Operator is the audience, not the stream audience.
    """

    LIVESTREAM = "livestream"
    PRIVATE = "private"


def is_routing_active() -> bool:
    """Return ``True`` when per-utterance destination routing is on.

    Reads ``HAPAX_TTS_DESTINATION_ROUTING_ACTIVE`` on every call (no
    caching) so an operator flipping the flag at runtime via a systemd
    drop-in reload takes effect on the next utterance.

    Default: ``True`` (unset, empty, or "1" → active). Only the literal
    "0" forces legacy behavior.
    """
    raw = os.environ.get(DESTINATION_ROUTING_ENV)
    if raw is None:
        return True
    return raw.strip() != "0"


def _extract_content(impingement: Any) -> dict[str, Any]:
    """Pull the ``content`` dict off an impingement-like object.

    We do a ``getattr`` rather than isinstance-checking because the
    impingement path accepts both Pydantic ``Impingement`` instances
    and the simpler mock objects tests use. Returns an empty dict on
    anything that doesn't look like an impingement.
    """
    content = getattr(impingement, "content", None)
    if isinstance(content, dict):
        return content
    return {}


def classify_destination(
    impingement: Any,
    *,
    voice_register: VoiceRegister | None = None,
) -> DestinationChannel:
    """Decide which destination an impingement-origin utterance belongs on.

    See module docstring for the rules. Defensive to malformed inputs —
    anything that doesn't match an explicit private signal returns
    ``LIVESTREAM`` (the safe default for broadcast).

    Parameters
    ----------
    impingement
        The triggering impingement (or any object exposing ``source`` and
        ``content``). ``None`` is tolerated and maps to ``LIVESTREAM``.
    voice_register
        Current HOMAGE voice register, if CPAL supplies one. Used only
        in combination with the sidechat rules; register alone never
        flips destination.

    Returns
    -------
    DestinationChannel
    """
    if impingement is None:
        return DestinationChannel.LIVESTREAM

    source = getattr(impingement, "source", "") or ""
    content = _extract_content(impingement)
    channel = content.get("channel")
    kind = content.get("kind")

    # Rule 1: operator-sidechat provenance.
    if isinstance(source, str) and source.startswith("operator.sidechat"):
        return DestinationChannel.PRIVATE

    # Rule 2: explicit channel tag on the impingement content.
    if channel == "sidechat":
        return DestinationChannel.PRIVATE

    # Rule 3: debug utterances.
    if kind == "debug":
        return DestinationChannel.PRIVATE

    # Rule 4: TEXTMODE alone does NOT route private (see module docstring).
    # It would only combine with sidechat provenance, which rules 1/2
    # already captured. This branch exists so adding a future sidechat
    # register signal remains a one-line change.
    _ = voice_register  # intentionally unused at the top level

    return DestinationChannel.LIVESTREAM


def resolve_target(destination: DestinationChannel) -> str | None:
    """Translate a ``DestinationChannel`` to a pw-cat ``--target`` sink name.

    Legacy compatibility helper for older callers. New callsites should use
    :func:`resolve_route` and inspect the returned route envelope before
    playback. A blocked route returns ``None`` here, but callers must not treat
    that as permission to use the system default.
    """
    return target_for_route(resolve_route(destination))


def resolve_route(
    destination: DestinationChannel,
    *,
    private_monitor_status_path: Path = DEFAULT_PRIVATE_MONITOR_STATUS_PATH,
    now: float | None = None,
) -> VoiceRouteResult:
    """Resolve a legacy destination channel through the semantic route API.

    The old ``PRIVATE`` / ``LIVESTREAM`` labels remain stable for metrics and
    classification, but playback routing now flows through typed semantic
    destinations and fail-closed evidence checks.
    """
    semantic = {
        DestinationChannel.LIVESTREAM: VoiceOutputDestination.PUBLIC_BROADCAST,
        DestinationChannel.PRIVATE: VoiceOutputDestination.PRIVATE_ASSISTANT_MONITOR,
    }[destination]
    return resolve_voice_output_route(
        semantic,
        private_monitor_status_path=private_monitor_status_path,
        now=now,
    )


# pw-cat ``--media-role`` values for each destination. The role
# selects which WirePlumber role-based loopback the stream lands in.
# ``Assistant`` for PRIVATE keeps the existing duck behavior + can be
# routed to ``hapax-private`` via ``50-hapax-voice-duck.conf``.
# ``Broadcast`` for LIVESTREAM is the new role added 2026-04-26 to
# allow a per-destination split — it lands in
# ``loopback.sink.role.broadcast`` whose ``preferred-target`` is
# ``hapax-voice-fx-capture`` (broadcast chain). Without this split,
# both kinds of stream share role=Assistant and wireplumber's policy
# can't tell them apart, forcing the operator to choose between leak
# protection and broadcast TTS.
PRIVATE_MEDIA_ROLE: str = "Assistant"
BROADCAST_MEDIA_ROLE: str = "Broadcast"


def resolve_role(destination: DestinationChannel) -> str:
    """Translate a ``DestinationChannel`` to a pw-cat ``--media-role``.

    Behavior:

    * ``PRIVATE`` → :data:`PRIVATE_MEDIA_ROLE` (``"Assistant"``).
      Wireplumber's existing assistant role-based loopback handles
      ducking + routing.
    * ``LIVESTREAM`` → :data:`BROADCAST_MEDIA_ROLE` (``"Broadcast"``).
      A separate role-based loopback (added 2026-04-26 to
      ``50-hapax-voice-duck.conf``) routes Broadcast streams to
      ``hapax-voice-fx-capture`` so they reach the livestream chain.

    The split is what lets wireplumber simultaneously enforce the
    ``feedback_l12_equals_livestream_invariant`` (livestream gets
    voice) AND ``interpersonal_transparency`` (private cognition stays
    on operator monitor). Before the split, both rules used
    ``role=Assistant`` and wireplumber had to pick one target —
    either broadcast (leak risk) or private (silent stream).
    """
    route = resolve_route(destination)
    return media_role_for_route(route) or (
        PRIVATE_MEDIA_ROLE if destination == DestinationChannel.PRIVATE else BROADCAST_MEDIA_ROLE
    )


class _DestinationCounter:
    """``hapax_tts_destination_total{destination}`` counter wrapper.

    Pre-registers one child per ``DestinationChannel`` value so scrapes
    always see the full label set, even before the first utterance fires.
    Degrades to a no-op if ``prometheus_client`` is unavailable (tests,
    minimal installs) — classification must never crash because metrics
    are missing.
    """

    def __init__(self) -> None:
        self._counter: Any = None
        try:
            from prometheus_client import Counter
        except ImportError:  # pragma: no cover — prometheus-client is a hard dep
            log.debug("prometheus_client unavailable; destination counter disabled")
            return
        try:
            self._counter = Counter(
                "hapax_tts_destination_total",
                "CPAL TTS utterances grouped by destination sink",
                ["destination"],
            )
        except ValueError:
            # Duplicate registration (tests reloading the module).
            from prometheus_client import REGISTRY

            self._counter = REGISTRY._names_to_collectors.get(  # noqa: SLF001
                "hapax_tts_destination_total"
            )
        if self._counter is not None:
            for dest in DestinationChannel:
                try:
                    self._counter.labels(destination=dest.value).inc(0)
                except Exception:  # pragma: no cover — label init is best-effort
                    log.debug("destination counter label init failed", exc_info=True)

    def inc(self, destination: DestinationChannel) -> None:
        if self._counter is None:
            return
        try:
            self._counter.labels(destination=destination.value).inc()
        except Exception:  # pragma: no cover
            log.debug("destination counter inc failed", exc_info=True)


_counter = _DestinationCounter()


def record_destination(destination: DestinationChannel) -> None:
    """Increment the Prometheus counter for ``destination``.

    Call this exactly once per classified utterance (at classification
    time, not at playback time, so the counter tracks intent even when
    the subprocess spawn fails).
    """
    _counter.inc(destination)


def classify_and_record(
    impingement: Any,
    *,
    voice_register: VoiceRegister | None = None,
) -> DestinationChannel:
    """One-shot helper: classify the impingement, increment the counter, log.

    The INFO log includes only the destination and the impingement's
    ``source`` tag — never the narrative body, operator text, or any
    payload that could leak private content into stdout. Callers that
    need structured per-utterance telemetry should emit
    ``hapax_span`` / ``hapax_event`` separately.
    """
    destination = classify_destination(impingement, voice_register=voice_register)
    record_destination(destination)
    source = getattr(impingement, "source", None) if impingement is not None else None
    log.info(
        "CPAL TTS destination resolved: destination=%s source=%s",
        destination.value,
        source or "<none>",
    )
    return destination


__all__ = [
    "DESTINATION_ROUTING_ENV",
    "DEFAULT_TARGET_ENV",
    "BROADCAST_MEDIA_ROLE",
    "LIVESTREAM_SINK",
    "PRIVATE_MEDIA_ROLE",
    "PRIVATE_SINK",
    "DestinationChannel",
    "classify_and_record",
    "classify_destination",
    "is_routing_active",
    "record_destination",
    "resolve_route",
    "resolve_role",
    "resolve_target",
]
