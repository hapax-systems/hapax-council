"""YouTube thumbnail rotation core (ytb-003 Phase 1).

Reads the existing compositor snapshot at
``/dev/shm/hapax-compositor/snapshot.jpg``, scales it to 1280x720
JPEG, and uploads via ``youtube.thumbnails().set(videoId, media_body=)``.
The compositor's face-obscure pipeline (#129) pixelates every camera
frame before the snapshot tap is written, so the thumbnail path is
privacy-safe without an additional gate here.

This Phase-1 ship is the minimum viable rotator: a 30 min wakeup loop
that polls the snapshot, renders the JPEG, calls thumbnails.set, and
records the rotation in a Prometheus counter. Follow-ups land:

- ``ytb-003`` Phase 2: chronicle salience subscriber (replace the
  fixed cadence with event-driven capture on
  ``salience >= 0.7 + 120s chapter stability``).
- ``ytb-007`` follow-up: per-VOD-boundary cadence.
- A/B retention + CTR-driven selection (out of scope for ytb-003).

## Auth

Uses ``shared.google_auth.build_service`` with the
``youtube.force-ssl`` scope and the YouTube-streaming sub-channel
token (``google/token-youtube-streaming``); falls back to the main
account token when the sub-channel token is missing. Same path the
description syncer + video-id publisher use.

## Quota

50 units per ``thumbnails.set`` × 48 rotations/day (every 30 min) =
2,400 units/day. Well under the 10k default daily cap.

## Configuration

| env var | default | meaning |
|---|---|---|
| ``HAPAX_YOUTUBE_VIDEO_ID`` | (required) | Target VOD/live video ID |
| ``HAPAX_THUMBNAIL_SNAPSHOT_PATH`` | ``/dev/shm/hapax-compositor/snapshot.jpg`` | Source frame |
| ``HAPAX_THUMBNAIL_TICK_S`` | ``1800`` (30 min) | Rotation cadence |
| ``HAPAX_THUMBNAIL_DRY_RUN`` | unset | When set, skips the API call (logs intent) |
"""

from __future__ import annotations

import io
import json
import logging
import os
import signal as _signal
import threading
from collections.abc import Callable
from pathlib import Path

from prometheus_client import REGISTRY, CollectorRegistry, Counter

log = logging.getLogger(__name__)

DEFAULT_SNAPSHOT_PATH = Path(
    os.environ.get(
        "HAPAX_THUMBNAIL_SNAPSHOT_PATH",
        "/dev/shm/hapax-compositor/snapshot.jpg",
    )
)
DEFAULT_TICK_S: float = float(os.environ.get("HAPAX_THUMBNAIL_TICK_S", "1800"))
DEFAULT_SLOT_DIR = Path(
    os.environ.get(
        "HAPAX_THUMBNAIL_SLOT_DIR",
        str(Path.home() / ".cache/hapax/thumbnail-rotator/slots"),
    )
)
SLOT_NAMES = ("a", "b")

# YouTube's recommended thumbnail dimensions; staying on the canonical
# size avoids re-encoding by the YT pipeline. JPEG quality 85 keeps
# under ~500 KB for typical compositor output (well below the 50 MB
# upload ceiling).
THUMBNAIL_WIDTH = 1280
THUMBNAIL_HEIGHT = 720
JPEG_QUALITY = 85


def prepare_thumbnail_jpeg(snapshot_path: Path) -> bytes | None:
    """Read a compositor snapshot and return a 1280x720 JPEG byte string.

    Returns ``None`` when the snapshot is missing or unreadable —
    callers should treat this as "no rotation this tick" rather than
    error out. Pillow's ``thumbnail()`` preserves aspect ratio and
    fits within the bounding box; the compositor's natural aspect is
    16:9 so the resize is exact, but a defensive call here means the
    function still produces something correct on a non-16:9 input.
    """
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(snapshot_path) as img:
            img.load()
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.thumbnail((THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            return out.getvalue()
    except (FileNotFoundError, OSError, UnidentifiedImageError):
        log.warning("snapshot read failed at %s", snapshot_path, exc_info=True)
        return None


class ThumbnailRotator:
    """Periodic compositor-snapshot → YouTube thumbnail rotator.

    Constructor parameters
    ----------------------
    video_id:
        Target YouTube video ID. Falls back to ``HAPAX_YOUTUBE_VIDEO_ID``
        env var. Without one, every tick logs "no_video_id" and skips.
    upload_fn:
        ``(video_id, jpeg_bytes) -> str`` callable. Production wires
        ``_default_upload_fn`` which builds the YouTube service via
        ``shared.google_auth.build_service``. Tests inject a mock.
    snapshot_path:
        Source JPEG path. Defaults to the compositor's snapshot tap.
    tick_s:
        Rotation cadence. 30 min default keeps quota at ~2400 u/day.
    dry_run:
        When True (or ``HAPAX_THUMBNAIL_DRY_RUN`` env var is set),
        logs intent without calling the API. Useful for first-deploy
        smoke testing.
    """

    def __init__(
        self,
        *,
        video_id: str | None = None,
        upload_fn: Callable[[str, bytes], str] | None = None,
        snapshot_path: Path = DEFAULT_SNAPSHOT_PATH,
        tick_s: float = DEFAULT_TICK_S,
        dry_run: bool = False,
        slot_dir: Path = DEFAULT_SLOT_DIR,
        registry: CollectorRegistry = REGISTRY,
    ) -> None:
        self._video_id = video_id or os.environ.get("HAPAX_YOUTUBE_VIDEO_ID", "").strip() or None
        self._upload_fn = upload_fn
        self._snapshot_path = snapshot_path
        self._tick_s = max(60.0, tick_s)
        self._dry_run = dry_run or bool(os.environ.get("HAPAX_THUMBNAIL_DRY_RUN", "").strip())
        self._slot_dir = slot_dir
        self._stop_evt = threading.Event()

        self.rotations_total = Counter(
            "hapax_broadcast_yt_thumbnail_rotations_total",
            "YouTube thumbnail rotations attempted, broken down by outcome.",
            ["result", "slot"],
            registry=registry,
        )

    def _next_slot(self) -> str:
        """Return the slot to use this rotation; persist for the next.

        Slot state persists at ``{slot_dir}/state.json`` as
        ``{"next_slot": "a"|"b"}``. First-ever start defaults to ``a``;
        the file is written before this method returns so a crash
        between slot selection and upload still preserves the
        intended alternation. Read failures default to ``a`` rather
        than blocking the rotation.
        """
        state_path = self._slot_dir / "state.json"
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            current = str(state.get("next_slot", "a"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            current = "a"
        if current not in SLOT_NAMES:
            current = "a"
        flipped = SLOT_NAMES[(SLOT_NAMES.index(current) + 1) % len(SLOT_NAMES)]
        try:
            self._slot_dir.mkdir(parents=True, exist_ok=True)
            tmp = state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"next_slot": flipped}), encoding="utf-8")
            tmp.replace(state_path)
        except OSError:
            log.warning("slot-state write failed at %s", state_path, exc_info=True)
        return current

    def _persist_slot_jpeg(self, slot: str, jpeg: bytes) -> None:
        """Persist the just-uploaded JPEG to ``{slot_dir}/slot-{name}.jpg``.

        Best-effort: failures log without raising. The slot file is
        operator-visible — they can inspect both A and B current
        thumbnails without round-tripping through the YouTube UI.
        """
        try:
            self._slot_dir.mkdir(parents=True, exist_ok=True)
            (self._slot_dir / f"slot-{slot}.jpg").write_bytes(jpeg)
        except OSError:
            log.warning("slot persist failed for %s at %s", slot, self._slot_dir, exc_info=True)

    def run_once(self) -> str:
        """Process one rotation; return the result label.

        Phase 3 (A/B retention): each rotation alternates between two
        named slots. The slot for this tick is selected from persistent
        state (so the alternation survives daemon restarts), the
        compositor snapshot is captured fresh, the JPEG is persisted
        to the slot file (operator-visible), and the upload happens
        from the in-memory bytes. The Prometheus counter carries a
        ``slot=a|b`` label so quota + outcome can be split per slot.
        """
        slot = self._next_slot()
        if not self._video_id:
            log.debug("no HAPAX_YOUTUBE_VIDEO_ID set; skipping rotation")
            self.rotations_total.labels(result="no_video_id", slot=slot).inc()
            return "no_video_id"

        jpeg = prepare_thumbnail_jpeg(self._snapshot_path)
        if jpeg is None:
            self.rotations_total.labels(result="no_snapshot", slot=slot).inc()
            return "no_snapshot"

        # Persist the captured JPEG to the slot file regardless of
        # upload outcome — operators inspecting the slot directory
        # see what the captured frame would have been.
        self._persist_slot_jpeg(slot, jpeg)

        if self._dry_run:
            log.info(
                "DRY RUN — would set thumbnail for %s slot=%s (%d bytes)",
                self._video_id,
                slot,
                len(jpeg),
            )
            self.rotations_total.labels(result="dry_run", slot=slot).inc()
            return "dry_run"

        try:
            result = self._upload(self._video_id, jpeg)
        except Exception:  # noqa: BLE001
            log.exception("thumbnail upload raised for video_id=%s", self._video_id)
            self.rotations_total.labels(result="error", slot=slot).inc()
            return "error"
        self.rotations_total.labels(result=result, slot=slot).inc()
        return result

    def run_forever(self) -> None:
        for sig in (_signal.SIGTERM, _signal.SIGINT):
            try:
                _signal.signal(sig, lambda *_: self._stop_evt.set())
            except ValueError:
                pass

        log.info(
            "thumbnail rotator starting; tick=%.1fs dry_run=%s video_id=%s",
            self._tick_s,
            self._dry_run,
            self._video_id or "<unset>",
        )
        while not self._stop_evt.is_set():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001
                log.exception("tick failed; continuing on next cadence")
            self._stop_evt.wait(self._tick_s)

    def run_forever_salience_triggered(self, trigger, *, poll_s: float = 5.0) -> None:
        """Salience-triggered loop (Phase 2).

        Polls ``trigger.should_fire()`` every ``poll_s`` seconds; when
        it returns True, runs a rotation. The 5 s default poll keeps
        cursor advance responsive without burning CPU on idle ticks.

        ``trigger`` is duck-typed on ``should_fire() -> bool`` (production
        wires :class:`SalienceTrigger`; tests inject a stub). Failures
        in the trigger or rotation are logged but never raise — the
        loop keeps running on the next poll.
        """
        for sig in (_signal.SIGTERM, _signal.SIGINT):
            try:
                _signal.signal(sig, lambda *_: self._stop_evt.set())
            except ValueError:
                pass

        log.info(
            "thumbnail rotator starting (salience-triggered); poll=%.1fs dry_run=%s video_id=%s",
            poll_s,
            self._dry_run,
            self._video_id or "<unset>",
        )
        while not self._stop_evt.is_set():
            try:
                if trigger.should_fire():
                    self.run_once()
            except Exception:  # noqa: BLE001
                log.exception("salience-triggered tick failed; continuing on next poll")
            self._stop_evt.wait(poll_s)

    def stop(self) -> None:
        self._stop_evt.set()

    def _upload(self, video_id: str, jpeg: bytes) -> str:
        upload = self._upload_fn or _default_upload_fn
        return upload(video_id, jpeg)


def _default_upload_fn(video_id: str, jpeg: bytes) -> str:
    """Production upload path: build YouTube service + call thumbnails.set.

    Returns ``"ok"`` on success, ``"auth_error"`` if auth fails before
    the network call, ``"error"`` on any other failure. Never raises;
    the caller's try/except catches anything that slips through, but
    mapping the common failures here keeps the metric labels stable.
    """
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaInMemoryUpload

    from shared.google_auth import (
        YOUTUBE_STREAMING_TOKEN_PASS_KEY,
        build_service,
    )

    try:
        service = build_service(
            "youtube",
            "v3",
            ["https://www.googleapis.com/auth/youtube.force-ssl"],
            pass_key=YOUTUBE_STREAMING_TOKEN_PASS_KEY,
        )
    except Exception:  # noqa: BLE001
        log.exception("YouTube service init failed for thumbnail upload")
        return "auth_error"

    media = MediaInMemoryUpload(jpeg, mimetype="image/jpeg", resumable=False)
    try:
        service.thumbnails().set(videoId=video_id, media_body=media).execute()
    except HttpError:
        log.exception("thumbnails.set HttpError for video_id=%s", video_id)
        return "error"
    except Exception:  # noqa: BLE001
        log.exception("thumbnails.set unexpected error for video_id=%s", video_id)
        return "error"
    return "ok"


__all__ = ["ThumbnailRotator", "prepare_thumbnail_jpeg"]
