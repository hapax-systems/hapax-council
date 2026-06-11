"""Voice witness watchdog — the consumer of voice-output-witness.json.

Audit SS6.2 (CASE-VOICE-FOUNDATION-20260610): the witness records the truth
about voice output (drops, playback, staleness); nothing consumed it — a 4.5h
total outage produced zero alert lines. This watchdog is the trivial consumer:

- **drop-streak**: N distinct drops observed with no intervening successful
  playback → ntfy (priority=high).
- **witness staleness**: witness file missing, malformed, or older than the
  staleness threshold → ntfy. A fresh witness means the daimonion is alive
  and publishing; a stale one means the voice path is unwitnessed.

Quiet on healthy. Alerts are cooldown-gated per condition and the cooldown is
cleared on recovery, so a fresh incident alerts immediately. Streak state
persists across ticks in a small JSON state file.

Run one tick: ``uv run python -m agents.voice_witness_watchdog --print``

Install (timer pattern, single-user systemd):

    cp systemd/units/hapax-voice-witness-watchdog.service \
       systemd/units/hapax-voice-witness-watchdog.timer \
       ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now hapax-voice-witness-watchdog.timer
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from agents.hapax_daimonion.voice_output_witness import (
    WITNESS_PATH,
    VoiceOutputWitness,
    read_voice_output_witness,
)

log = logging.getLogger(__name__)

DEFAULT_STATE_PATH: Path = Path.home() / ".cache" / "hapax" / "voice-witness-watchdog.json"
DEFAULT_DROP_STREAK_THRESHOLD: int = 3
DEFAULT_STALENESS_THRESHOLD_S: float = 1800.0
DEFAULT_ALERT_COOLDOWN_S: float = 3600.0

# Witness reader states that mean "the voice path is unwitnessed right now".
_UNWITNESSED_STATUSES = frozenset({"missing", "malformed", "stale"})


@dataclass
class Alert:
    """A condition that crossed its threshold this tick."""

    kind: str  # "drop_streak" | "witness_stale"
    title: str
    body: str
    priority: str = "high"
    tags: list[str] = field(default_factory=lambda: ["rotating_light", "voice-witness"])


@dataclass
class WatchdogConfig:
    """Config — env-overridable, CLI-overridable."""

    witness_path: Path = WITNESS_PATH
    state_path: Path = DEFAULT_STATE_PATH
    drop_streak_threshold: int = DEFAULT_DROP_STREAK_THRESHOLD
    staleness_threshold_s: float = DEFAULT_STALENESS_THRESHOLD_S
    alert_cooldown_s: float = DEFAULT_ALERT_COOLDOWN_S
    enable_ntfy: bool = True

    @classmethod
    def from_env(cls) -> WatchdogConfig:
        config = cls()
        witness = os.environ.get("HAPAX_VOICE_WITNESS_PATH")
        if witness:
            config.witness_path = Path(witness)
        state = os.environ.get("HAPAX_VOICE_WITNESS_WATCHDOG_STATE_PATH")
        if state:
            config.state_path = Path(state)
        config.drop_streak_threshold = _env_int(
            "HAPAX_VOICE_WITNESS_DROP_STREAK_THRESHOLD", config.drop_streak_threshold
        )
        config.staleness_threshold_s = _env_float(
            "HAPAX_VOICE_WITNESS_STALENESS_THRESHOLD_S", config.staleness_threshold_s
        )
        config.alert_cooldown_s = _env_float(
            "HAPAX_VOICE_WITNESS_ALERT_COOLDOWN_S", config.alert_cooldown_s
        )
        ntfy_raw = os.environ.get("HAPAX_VOICE_WITNESS_ENABLE_NTFY")
        if ntfy_raw is not None:
            config.enable_ntfy = ntfy_raw.strip().lower() not in {"", "0", "false", "no", "off"}
        return config


@dataclass
class TickResult:
    """Outcome of a single watchdog tick."""

    witness_status: str
    drop_streak: int
    alerts: list[Alert]


def run_tick(
    config: WatchdogConfig,
    *,
    now: float | None = None,
    send: Callable[[Alert], None] | None = None,
) -> TickResult:
    """Read the witness once, update streak state, alert on threshold crossings."""
    current = now if now is not None else time.time()
    witness = read_voice_output_witness(
        config.witness_path, now=current, max_age_s=config.staleness_threshold_s
    )
    state = _load_state(config.state_path)
    alerted: dict[str, float] = {str(k): float(v) for k, v in (state.get("alerted") or {}).items()}
    streak = int(state.get("drop_streak", 0))
    last_seen_drop_ts = state.get("last_drop_ts")

    alerts: list[Alert] = []

    if witness.status in _UNWITNESSED_STATUSES:
        # Streak state is preserved untouched: a dead witness is not evidence
        # that the drops stopped.
        if _cooldown_allows("witness_stale", alerted, current, config.alert_cooldown_s):
            alerts.append(_staleness_alert(witness, config))
            alerted["witness_stale"] = current
    else:
        alerted.pop("witness_stale", None)
        streak, last_seen_drop_ts = _update_streak(witness, streak, last_seen_drop_ts)
        if streak >= config.drop_streak_threshold:
            if _cooldown_allows("drop_streak", alerted, current, config.alert_cooldown_s):
                alerts.append(_drop_streak_alert(witness, streak))
                alerted["drop_streak"] = current
        else:
            alerted.pop("drop_streak", None)

    if alerts and config.enable_ntfy:
        sender = send if send is not None else _send_via_notify
        for alert in alerts:
            try:
                sender(alert)
            except Exception:
                log.warning("voice-witness-watchdog: alert send failed: %s", alert.title)

    _write_state(
        config.state_path,
        {
            "version": 1,
            "updated_at": current,
            "witness_status": str(witness.status),
            "drop_streak": streak,
            "last_drop_ts": last_seen_drop_ts,
            "alerted": alerted,
        },
    )
    return TickResult(witness_status=str(witness.status), drop_streak=streak, alerts=alerts)


# ── Streak / alert logic ─────────────────────────────────────────────────────


def _update_streak(
    witness: VoiceOutputWitness,
    streak: int,
    last_seen_drop_ts: object,
) -> tuple[int, str | None]:
    drop_ts = (witness.last_drop or {}).get("ts")
    if not drop_ts:
        return 0, None
    success_ts = (witness.last_successful_playback or {}).get("ts")
    if success_ts and _parse_ts(success_ts) >= _parse_ts(drop_ts):
        return 0, str(drop_ts)
    if drop_ts != last_seen_drop_ts:
        return streak + 1, str(drop_ts)
    return streak, str(drop_ts)


def _cooldown_allows(kind: str, alerted: dict[str, float], now: float, cooldown_s: float) -> bool:
    last_sent = alerted.get(kind)
    return last_sent is None or (now - last_sent) >= cooldown_s


def _staleness_alert(witness: VoiceOutputWitness, config: WatchdogConfig) -> Alert:
    return Alert(
        kind="witness_stale",
        title="Voice witness watchdog: witness UNWITNESSED",
        body=(
            f"voice-output-witness is {witness.status}: "
            f"reason={witness.blocker_drop_reason} "
            f"age={witness.freshness_s:.0f}s "
            f"threshold={config.staleness_threshold_s:.0f}s "
            f"path={config.witness_path}"
        ),
    )


def _drop_streak_alert(witness: VoiceOutputWitness, streak: int) -> Alert:
    drop = witness.last_drop or {}
    return Alert(
        kind="drop_streak",
        title="Voice witness watchdog: drop-streak",
        body=(
            f"{streak} consecutive voice drops without successful playback; "
            f"last reason={drop.get('reason')} "
            f"source={drop.get('source')} ts={drop.get('ts')}"
        ),
    )


def _send_via_notify(alert: Alert) -> None:
    from shared import notify

    notify.send_notification(alert.title, alert.body, priority=alert.priority, tags=alert.tags)


# ── State / parsing helpers ──────────────────────────────────────────────────


def _parse_ts(ts: str) -> float:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _load_state(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return default


# ── CLI ──────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voice-witness-watchdog",
        description="Alert on voice-output-witness drop-streak / staleness.",
    )
    parser.add_argument("--witness-path", type=Path, default=None)
    parser.add_argument("--state-path", type=Path, default=None)
    parser.add_argument("--drop-streak-threshold", type=int, default=None)
    parser.add_argument("--staleness-threshold-s", type=float, default=None)
    parser.add_argument("--alert-cooldown-s", type=float, default=None)
    parser.add_argument("--no-ntfy", action="store_true", help="Evaluate without sending.")
    parser.add_argument("--print", action="store_true", help="Print the tick summary.")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("HAPAX_VOICE_WITNESS_WATCHDOG_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = _build_parser().parse_args(list(argv) if argv is not None else None)

    config = WatchdogConfig.from_env()
    if args.witness_path is not None:
        config.witness_path = args.witness_path
    if args.state_path is not None:
        config.state_path = args.state_path
    if args.drop_streak_threshold is not None:
        config.drop_streak_threshold = args.drop_streak_threshold
    if args.staleness_threshold_s is not None:
        config.staleness_threshold_s = args.staleness_threshold_s
    if args.alert_cooldown_s is not None:
        config.alert_cooldown_s = args.alert_cooldown_s
    if args.no_ntfy:
        config.enable_ntfy = False

    result = run_tick(config)
    for alert in result.alerts:
        log.warning("voice-witness-watchdog: %s — %s", alert.title, alert.body)
    if args.print:
        print(
            json.dumps(
                {
                    "witness_status": result.witness_status,
                    "drop_streak": result.drop_streak,
                    "alerts": [{"kind": a.kind, "title": a.title} for a in result.alerts],
                },
                indent=2,
                sort_keys=True,
            )
        )
    # Alerting is the job — a firing alert is not a unit failure.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
