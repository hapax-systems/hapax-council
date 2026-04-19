"""CPAL TTS destination routing.

The PipeWire split (``~/.config/pipewire/pipewire.conf.d/hapax-stream-split.conf``)
creates two sinks:

* ``hapax-livestream`` → Studio 24c LEFT (public utterances, music,
  anything broadcast-bound).
* ``hapax-private`` → Studio 24c RIGHT (sidechat replies, debug narration,
  operator-private).

Every Hapax TTS utterance gets classified into one of these destinations
at synthesis time. The default stays ``livestream`` (matching the
systemd drop-in ``HAPAX_TTS_TARGET=hapax-livestream``); only utterances
the operator explicitly initiated via the sidechat (or that are debug /
TEXTMODE+sidechat) divert to the private sink.

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
Setting ``0`` forces every utterance to ``HAPAX_TTS_TARGET`` (legacy
single-sink behavior), bypassing classification entirely.

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
from typing import Any

from shared.voice_register import VoiceRegister

log = logging.getLogger(__name__)


DESTINATION_ROUTING_ENV: str = "HAPAX_TTS_DESTINATION_ROUTING_ACTIVE"
"""Feature flag. ``1`` (default) = classify per utterance. ``0`` = legacy
(always hit ``HAPAX_TTS_TARGET``)."""

DEFAULT_TARGET_ENV: str = "HAPAX_TTS_TARGET"
"""Environment variable holding the default/livestream sink. Set by the
daimonion systemd drop-in."""

LIVESTREAM_SINK: str = "hapax-livestream"
"""Canonical livestream sink name. Matches
``~/.config/pipewire/pipewire.conf.d/hapax-stream-split.conf``."""

PRIVATE_SINK: str = "hapax-private"
"""Canonical private sink name. Operator-only (24c RIGHT)."""


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

    Behavior matrix:

    * Routing active + ``LIVESTREAM`` → ``HAPAX_TTS_TARGET`` (or
      ``LIVESTREAM_SINK`` when the env var is unset).
    * Routing active + ``PRIVATE`` → ``PRIVATE_SINK``.
    * Routing inactive (flag off) → ``HAPAX_TTS_TARGET`` for every
      destination, falling through to ``None`` (default wireplumber
      routing) when the env var is unset.

    ``None`` is returned when no explicit sink should be passed to
    ``pw-cat --target`` — callers treat that as "system default sink".
    """
    default_target = os.environ.get(DEFAULT_TARGET_ENV) or None

    if not is_routing_active():
        return default_target

    if destination == DestinationChannel.PRIVATE:
        return PRIVATE_SINK

    # LIVESTREAM — prefer the env var (systemd drop-in sets it), fall
    # back to the canonical sink name if somehow unset.
    if default_target:
        return default_target
    return LIVESTREAM_SINK


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
    "LIVESTREAM_SINK",
    "PRIVATE_SINK",
    "DestinationChannel",
    "classify_and_record",
    "classify_destination",
    "is_routing_active",
    "record_destination",
    "resolve_target",
]
