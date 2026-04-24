"""In-memory state for the Content-ID watcher.

Holds the last-seen snapshot of each tracked broadcast / VOD plus
per-VOD enrol-time so we can age-out polling after the post-archive
1-hour high-risk window. State is process-local: the daemon's first
poll after a restart establishes a fresh baseline (no spurious change
events), at the cost of missing a YouTube edit that landed during the
restart window. The trade-off is deliberate — persisting state would
demand write-on-every-tick durability that does not earn its
complexity for a watcher whose primary value is sub-60s detection on
the post-archive video.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

# Polling cadence + lifecycle constants. Exported here so tests can
# parametrise without re-importing daemon-internal modules.
LIVE_POLL_INTERVAL_S: float = 60.0
VOD_POLL_INTERVAL_S: float = 300.0  # five minutes
VOD_POLL_TTL_S: float = 3600.0  # one hour post-archive


@dataclass
class WatcherState:
    """Process-local state for one watcher instance.

    Attributes:
        live_snapshots: broadcast_id → field-snapshot dict from the most
            recent ``liveBroadcasts.list`` poll.
        vod_snapshots: video_id → field-snapshot dict from the most
            recent ``videos.list`` poll.
        vod_first_polled_at: video_id → wall-clock time when the VOD
            first entered the post-archive poll queue. Used to expire
            after ``VOD_POLL_TTL_S``.
    """

    live_snapshots: dict[str, dict] = field(default_factory=dict)
    vod_snapshots: dict[str, dict] = field(default_factory=dict)
    vod_first_polled_at: dict[str, float] = field(default_factory=dict)

    def enroll_vod(self, video_id: str, *, now: float | None = None) -> None:
        """Add a VOD to the post-archive poll queue if not already present."""
        if video_id in self.vod_first_polled_at:
            return
        self.vod_first_polled_at[video_id] = now if now is not None else time.time()

    def expire_vods(self, *, now: float | None = None) -> list[str]:
        """Drop VODs whose TTL elapsed. Returns the list of expired ids."""
        deadline = (now if now is not None else time.time()) - VOD_POLL_TTL_S
        expired = [
            vid for vid, enrolled_at in self.vod_first_polled_at.items() if enrolled_at < deadline
        ]
        for vid in expired:
            self.vod_first_polled_at.pop(vid, None)
            self.vod_snapshots.pop(vid, None)
        return expired

    def vods_in_queue(self) -> tuple[str, ...]:
        """Return the currently-enrolled VOD ids, oldest first."""
        return tuple(
            vid for vid, _ in sorted(self.vod_first_polled_at.items(), key=lambda kv: kv[1])
        )
