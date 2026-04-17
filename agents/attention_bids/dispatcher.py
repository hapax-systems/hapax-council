"""LRR Phase 8 item 10 — attention-bid delivery dispatcher.

The bidder (``bidder.py``) decides *whether* Hapax should bid for
operator attention. This module decides *how* the bid is surfaced.
Every accepted bid:

* Is stimmung-gated: critical / degraded stimmung suppresses delivery so
  Hapax doesn't bid during a moment the operator explicitly cannot
  attend to.
* Is rate-limited per channel: default 15 minutes between bids on the
  same channel (see ``HYSTERESIS_MINUTES_DEFAULT``).
* Gets dispatched to every enabled channel in ``config/attention-bids.yaml``.
  Channels are side-effects — pure write-to-file or notification — so
  the dispatcher stays restart-safe.
* Is appended to ``~/hapax-state/attention-bids.jsonl`` for observability.

Channels:

* ``ntfy`` — notify via :func:`shared.notify.send_notification`.
* ``visual_flash`` — writes a trigger file at
  ``/dev/shm/hapax-attention-bids/active.json`` that the Logos surface
  polls.
* ``tts`` — writes a trigger file at
  ``/dev/shm/hapax-attention-bids/tts.json``. The daimonion side routes
  TTS to a DEDICATED operator-only PipeWire sink per the spec, so the
  bid never touches stream audio.
* ``stream_deck_led`` — writes a trigger file at
  ``/dev/shm/hapax-attention-bids/led.json`` that the Stream Deck
  adapter (Phase 8 item 6) can read on its next poll.

The channel trigger files are written atomically (``tmp`` + ``rename``)
so a reader is never handed a half-written JSON.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents.attention_bids.bidder import AttentionBid

log = logging.getLogger(__name__)

TRIGGER_DIR = Path("/dev/shm/hapax-attention-bids")
LOG_PATH = Path.home() / "hapax-state" / "attention-bids.jsonl"
CONFIG_PATH = Path("config/attention-bids.yaml")

HYSTERESIS_MINUTES_DEFAULT: int = 15
STIMMUNG_SUPPRESS_STATES: frozenset[str] = frozenset({"critical", "degraded"})
STIMMUNG_STRESS_SUPPRESS_THRESHOLD: float = 0.80

DEFAULT_CHANNELS: tuple[str, ...] = ("ntfy",)
ALL_CHANNELS: tuple[str, ...] = ("ntfy", "visual_flash", "tts", "stream_deck_led")


# ── Channel enable config ───────────────────────────────────────────────────


@dataclass(frozen=True)
class ChannelConfig:
    enabled_channels: tuple[str, ...]
    hysteresis_minutes: int = HYSTERESIS_MINUTES_DEFAULT


def default_channel_config() -> ChannelConfig:
    return ChannelConfig(enabled_channels=DEFAULT_CHANNELS)


def load_channel_config(path: Path | None = None) -> ChannelConfig:
    """Load ``config/attention-bids.yaml``. Missing / malformed → defaults.

    Tolerates unknown channel names by dropping them (and logging once).
    """
    path = path or CONFIG_PATH
    if not path.exists():
        return default_channel_config()
    try:
        import yaml

        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        log.exception("attention-bids config unreadable at %s — using defaults", path)
        return default_channel_config()
    if not isinstance(raw, dict):
        return default_channel_config()

    channels_raw = raw.get("enabled_channels") or list(DEFAULT_CHANNELS)
    if not isinstance(channels_raw, list):
        channels_raw = list(DEFAULT_CHANNELS)

    validated: list[str] = []
    for c in channels_raw:
        if isinstance(c, str) and c in ALL_CHANNELS:
            validated.append(c)
        else:
            log.warning("unknown attention-bid channel %r ignored", c)

    hyst = raw.get("hysteresis_minutes", HYSTERESIS_MINUTES_DEFAULT)
    try:
        hyst_int = max(0, int(hyst))
    except (TypeError, ValueError):
        hyst_int = HYSTERESIS_MINUTES_DEFAULT

    return ChannelConfig(
        enabled_channels=tuple(validated) if validated else DEFAULT_CHANNELS,
        hysteresis_minutes=hyst_int,
    )


# ── Stimmung suppression ────────────────────────────────────────────────────


def _stimmung_suppresses(stimmung: dict[str, Any]) -> str | None:
    """Return a reason-string if the bid should be suppressed, else ``None``."""
    stance = stimmung.get("stance") if isinstance(stimmung, dict) else None
    if isinstance(stance, str) and stance in STIMMUNG_SUPPRESS_STATES:
        return f"stimmung_stance={stance}"
    stress = stimmung.get("operator_stress") if isinstance(stimmung, dict) else None
    if isinstance(stress, dict):
        try:
            value = float(stress.get("value", 0.0))
        except (TypeError, ValueError):
            value = 0.0
        if value >= STIMMUNG_STRESS_SUPPRESS_THRESHOLD:
            return f"stress_value={value:.2f}"
    return None


# ── Dispatch ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DispatchResult:
    delivered: tuple[str, ...]
    suppressed: str | None = None
    throttled: tuple[str, ...] = ()
    log_line: dict[str, Any] = field(default_factory=dict)


Notifier = Callable[[str, str], None]


def _default_notifier(title: str, body: str) -> None:
    from shared.notify import send_notification

    send_notification(title=title, body=body, topic="hapax-attention")


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _append_log(entry: dict[str, Any], log_path: Path) -> None:
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        log.debug("attention-bid log write failed", exc_info=True)


def dispatch_bid(
    bid: AttentionBid,
    *,
    stimmung: dict[str, Any] | None = None,
    now_epoch: float | None = None,
    last_delivered_at: dict[str, float] | None = None,
    config: ChannelConfig | None = None,
    trigger_dir: Path | None = None,
    log_path: Path | None = None,
    notifier: Notifier | None = None,
) -> DispatchResult:
    """Route a single accepted bid to its enabled channels.

    ``last_delivered_at`` is a ``{channel: epoch-seconds}`` dict the caller
    persists across calls; it is mutated in place with the new delivery
    timestamp for each channel that actually delivered. Pass ``{}`` on the
    first call.
    """
    stimmung = stimmung or {}
    now = now_epoch if now_epoch is not None else time.time()
    config = config or default_channel_config()
    trigger_dir = trigger_dir or TRIGGER_DIR
    log_path = log_path or LOG_PATH
    notifier = notifier or _default_notifier
    state = last_delivered_at if last_delivered_at is not None else {}

    suppress_reason = _stimmung_suppresses(stimmung)
    entry: dict[str, Any] = {
        "ts": now,
        "source": bid.source,
        "summary": bid.summary,
        "salience": bid.salience,
        "objective_id": bid.objective_id,
    }
    if suppress_reason is not None:
        entry["suppressed"] = suppress_reason
        _append_log(entry, log_path)
        return DispatchResult(delivered=(), suppressed=suppress_reason, log_line=entry)

    delivered: list[str] = []
    throttled: list[str] = []
    hysteresis_s = config.hysteresis_minutes * 60

    for channel in config.enabled_channels:
        last = state.get(channel)
        if last is not None and now - last < hysteresis_s:
            throttled.append(channel)
            continue
        try:
            _deliver_one(channel, bid, trigger_dir=trigger_dir, notifier=notifier, now=now)
        except Exception:
            log.exception("attention-bid delivery failed on channel=%s", channel)
            continue
        delivered.append(channel)
        state[channel] = now

    entry["delivered"] = delivered
    entry["throttled"] = throttled
    _append_log(entry, log_path)
    return DispatchResult(
        delivered=tuple(delivered),
        throttled=tuple(throttled),
        log_line=entry,
    )


def _deliver_one(
    channel: str,
    bid: AttentionBid,
    *,
    trigger_dir: Path,
    notifier: Notifier,
    now: float,
) -> None:
    payload = {
        "ts": now,
        "source": bid.source,
        "summary": bid.summary,
        "salience": bid.salience,
        "objective_id": bid.objective_id,
    }
    if channel == "ntfy":
        notifier(f"Hapax bid: {bid.source}", bid.summary or "(no summary)")
    elif channel == "visual_flash":
        _atomic_write_json(trigger_dir / "active.json", payload)
    elif channel == "tts":
        _atomic_write_json(trigger_dir / "tts.json", payload)
    elif channel == "stream_deck_led":
        _atomic_write_json(trigger_dir / "led.json", payload)
    else:
        log.warning("unknown attention-bid channel %r dropped", channel)
