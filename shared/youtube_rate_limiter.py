"""YouTube Data API v3 daily quota bucket (per-endpoint, persistent).

Per-endpoint daily budgets persisted to disk so process restart doesn't
reset a 24h budget. Consumed by :class:`shared.youtube_api_client.YouTubeApiClient`
when an instance is supplied.

Default budgets are conservative — they assume the default 10k/day cap.
Operator adjusts via env vars after ytb-OG3 quota extension lands.

Note: this is API-quota accounting (units/day), not per-actor rate
limiting — there is one operator and one channel by axiom.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

log = logging.getLogger(__name__)

STATE_PATH = Path(
    os.environ.get(
        "HAPAX_YT_RATE_LIMIT_STATE",
        str(Path.home() / ".cache/hapax/yt-rate-limit-state.json"),
    )
)

DAILY_CAP = int(os.environ.get("HAPAX_YT_QUOTA_DAILY_CAP", "10000"))

ENDPOINT_DAILY_BUDGET: dict[str, int] = {
    "videos.insert": 9600,
    "captions.insert": 2000,
    "thumbnails.set": 2400,
    "liveBroadcasts.cuepoint": 1000,
    "liveBroadcasts.insert": 200,
    "liveBroadcasts.bind": 200,
    "liveBroadcasts.transition": 600,
    "videos.update": 1500,
    "channels.update": 500,
    "channelSections.insert": 150,
    "playlistItems.insert": 300,
    "liveBroadcasts.list": 2000,
    "liveStreams.list": 200,
    "videos.list": 500,
    "search.list": 100,
}


@dataclass
class _EndpointState:
    used_today: int = 0
    last_call_ts: float = 0.0


@dataclass
class _State:
    day_utc_start: float = 0.0
    per_endpoint: dict[str, _EndpointState] = field(default_factory=dict)

    @staticmethod
    def current_day_start() -> float:
        now = dt.datetime.now(dt.UTC)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.timestamp()

    def maybe_roll_day(self) -> None:
        current = self.current_day_start()
        if current > self.day_utc_start:
            log.info("day rollover; resetting all endpoint counters")
            self.day_utc_start = current
            self.per_endpoint = {}


class QuotaBucket:
    """Daily YouTube API quota accounting keyed on (endpoint, day).

    Thread-safe; one instance per process. ``try_acquire`` deducts the
    cost and returns False when an endpoint's daily budget is exhausted.
    """

    def __init__(
        self,
        state_path: Path = STATE_PATH,
        daily_cap: int = DAILY_CAP,
        endpoint_budgets: dict[str, int] | None = None,
    ) -> None:
        self._lock = Lock()
        self._state_path = state_path
        self._daily_cap = daily_cap
        self._endpoint_budgets = endpoint_budgets or ENDPOINT_DAILY_BUDGET
        self._state = self._load()

    def _load(self) -> _State:
        if not self._state_path.exists():
            s = _State()
            s.day_utc_start = _State.current_day_start()
            return s
        try:
            raw = json.loads(self._state_path.read_text())
            s = _State(day_utc_start=raw.get("day_utc_start", 0.0))
            for k, v in raw.get("per_endpoint", {}).items():
                s.per_endpoint[k] = _EndpointState(**v)
            s.maybe_roll_day()
            return s
        except Exception as exc:
            log.warning("state parse failed: %s; starting fresh", exc)
            s = _State()
            s.day_utc_start = _State.current_day_start()
            return s

    def _persist(self) -> None:
        tmp = self._state_path.with_suffix(".tmp")
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "day_utc_start": self._state.day_utc_start,
            "per_endpoint": {
                k: {"used_today": v.used_today, "last_call_ts": v.last_call_ts}
                for k, v in self._state.per_endpoint.items()
            },
        }
        tmp.write_text(json.dumps(payload))
        tmp.replace(self._state_path)

    def try_acquire(self, endpoint: str, cost: int = 1) -> bool:
        with self._lock:
            self._state.maybe_roll_day()
            budget = self._endpoint_budgets.get(endpoint, max(50, self._daily_cap // 20))
            st = self._state.per_endpoint.setdefault(endpoint, _EndpointState())
            if st.used_today + cost > budget:
                log.warning(
                    "endpoint %s budget exhausted: %d/%d (cost=%d)",
                    endpoint,
                    st.used_today,
                    budget,
                    cost,
                )
                return False
            st.used_today += cost
            st.last_call_ts = time.time()
            self._persist()
            return True

    def remaining(self, endpoint: str) -> int:
        with self._lock:
            self._state.maybe_roll_day()
            budget = self._endpoint_budgets.get(endpoint, max(50, self._daily_cap // 20))
            st = self._state.per_endpoint.get(endpoint, _EndpointState())
            return max(0, budget - st.used_today)

    @classmethod
    def default(cls) -> QuotaBucket:
        return cls()
