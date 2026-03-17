"""EffectRunner — manages all effects with adaptive resolution tiers."""

from __future__ import annotations

import logging
import time
from enum import Enum
from pathlib import Path

import cv2
import numpy as np

from agents.studio_fx.base import BaseEffect
from agents.studio_fx.perception import PerceptionReader, PerceptionSnapshot

log = logging.getLogger(__name__)

SNAPSHOT_DIR = Path("/dev/shm/hapax-compositor")
# Read the RAW compositor output, not the GL-effected one.
# fx-snapshot.jpg has the old GStreamer shader chain applied;
# snapshot.jpg is the clean composited multi-camera tile.
INPUT_PATH = SNAPSHOT_DIR / "snapshot.jpg"
FX_REQUEST_PATH = SNAPSHOT_DIR / "fx-request.txt"

# Resolution tiers (height-based, width computed from aspect ratio)
TIER_ACTIVE_H = 1080
TIER_PREVIEW_H = 480
TIER_WARM_H = 270

# Smooth mode: ring buffer for delayed frames
SMOOTH_RING_SIZE = 15  # ~1 second at 15fps
SMOOTH_DELAY = 10  # frames of delay (~0.7s)
SMOOTH_BLEND_ALPHA = 0.80  # blend weight for smooth layer


class Tier(Enum):
    ACTIVE = "active"
    PREVIEW = "preview"
    WARM = "warm"
    COLD = "cold"


class _EffectSlot:
    """Runtime wrapper around an effect instance with tier tracking."""

    __slots__ = ("effect", "tier", "last_frame_ms")

    def __init__(self, effect: BaseEffect, tier: Tier) -> None:
        self.effect = effect
        self.tier = tier
        self.last_frame_ms: float = 0.0


class EffectRunner:
    """Single-threaded runner that manages effects at mixed resolution tiers."""

    def __init__(
        self,
        effects: list[BaseEffect],
        *,
        target_fps: float = 15.0,
        active_name: str = "clean",
        v4l2_device: str = "/dev/video50",
    ) -> None:
        self._target_fps = target_fps
        self._smooth_mode = False
        self._frame_interval = 1.0 / target_fps
        self._perception = PerceptionReader()
        self._v4l2_device = v4l2_device
        self._cam: object | None = None  # pyvirtualcam.Camera or None
        self._running = False
        self._last_request_mtime: float = 0.0
        self._input_mtime: float = 0.0

        # Build slots — the requested active gets ACTIVE, all others PREVIEW
        self._slots: dict[str, _EffectSlot] = {}
        for fx in effects:
            if fx.name == active_name:
                tier = Tier.ACTIVE
            else:
                tier = Tier.PREVIEW
            self._slots[fx.name] = _EffectSlot(fx, tier)

        self._active_name = active_name if active_name in self._slots else "clean"

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Main loop.  Blocks until stop() is called."""
        self._running = True
        self._init_virtualcam()
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

        log.info(
            "EffectRunner started — %d effects, active=%s, target=%.0ffps",
            len(self._slots),
            self._active_name,
            self._target_fps,
        )

        while self._running:
            loop_start = time.monotonic()
            try:
                self._tick()
            except Exception:
                log.exception("Tick error (continuing)")
            elapsed = time.monotonic() - loop_start
            sleep_for = self._frame_interval - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)

        self._shutdown_virtualcam()
        log.info("EffectRunner stopped")

    def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    # Tier management
    # ------------------------------------------------------------------

    def switch_active(self, name: str) -> bool:
        """Promote *name* to active, demote the current active to preview."""
        # Handle smooth mode toggle — only change if explicitly specified
        if name.endswith("+smooth"):
            name = name[:-7]  # strip '+smooth'
            self._smooth_mode = True
            log.info("Smooth mode enabled for %s", name)
        elif name.endswith("-smooth"):
            name = name[:-7]
            self._smooth_mode = False
            log.info("Smooth mode disabled for %s", name)
        # Otherwise keep current smooth state

        if name not in self._slots:
            log.warning("Unknown effect: %s", name)
            return False
        if name == self._active_name:
            return True

        old_slot = self._slots.get(self._active_name)
        new_slot = self._slots[name]

        # Demote old
        if old_slot is not None:
            old_slot.tier = Tier.PREVIEW
            h = TIER_PREVIEW_H
            w = _width_for_height(h, old_slot.effect.width, old_slot.effect.height)
            old_slot.effect.resize(w, h)
            log.info("Demoted %s → preview (%dx%d)", old_slot.effect.name, w, h)

        # Promote new
        new_slot.tier = Tier.ACTIVE
        h = TIER_ACTIVE_H
        w = _width_for_height(h, new_slot.effect.width, new_slot.effect.height)
        new_slot.effect.resize(w, h)
        self._active_name = name
        log.info("Promoted %s → active (%dx%d)", name, w, h)
        return True

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        """One frame cycle."""
        # Check for preset switch request
        self._check_fx_request()

        # Read source frame
        frame = self._read_input()
        if frame is None:
            return

        src_h, src_w = frame.shape[:2]
        p = self._perception.read()
        t = time.monotonic()

        # Maintain frame ring buffer for smooth mode
        if not hasattr(self, "_frame_ring"):
            self._frame_ring: list[np.ndarray] = []
        self._frame_ring.append(frame.copy())
        if len(self._frame_ring) > SMOOTH_RING_SIZE:
            self._frame_ring.pop(0)

        # Get the delayed frame for smooth composite (or None if not enough frames)
        smooth_frame: np.ndarray | None = None
        if len(self._frame_ring) > SMOOTH_DELAY:
            smooth_frame = self._frame_ring[-(SMOOTH_DELAY + 1)]

        # Pre-compute resized frames per tier
        resized: dict[Tier, np.ndarray] = {Tier.ACTIVE: frame}
        for tier, target_h in ((Tier.PREVIEW, TIER_PREVIEW_H), (Tier.WARM, TIER_WARM_H)):
            if target_h < src_h:
                tw = _width_for_height(target_h, src_w, src_h)
                resized[tier] = cv2.resize(frame, (tw, target_h), interpolation=cv2.INTER_AREA)
            else:
                resized[tier] = frame

        # Process ACTIVE effect every tick (fast path)
        active_output: np.ndarray | None = None
        active_slot = self._slots.get(self._active_name)
        if active_slot is not None and active_slot.tier == Tier.ACTIVE:
            tier_frame = resized.get(Tier.ACTIVE, frame)
            try:
                t0 = time.monotonic()
                result = active_slot.effect.process(tier_frame, p, t)
                dt_ms = (time.monotonic() - t0) * 1000.0
                active_slot.last_frame_ms = dt_ms
            except Exception:
                log.exception("Active effect %s crashed", self._active_name)
                result = tier_frame
            # Write live-only version
            self._write_snapshot(self._active_name, result)
            live_result = result

            # Write live+smooth composite: effected LIVE + raw DELAYED blend
            # The smooth layer is the RAW past frame (unprocessed) — creates
            # maximum visual contrast between effected present and natural past
            if smooth_frame is not None:
                try:
                    live_f = result.astype(np.float32)
                    # Resize smooth_frame to match result if needed
                    sh, sw = smooth_frame.shape[:2]
                    rh, rw = result.shape[:2]
                    if (sh, sw) != (rh, rw):
                        sf = cv2.resize(smooth_frame, (rw, rh))
                    else:
                        sf = smooth_frame
                    # Desaturate and dim the smooth layer slightly for temporal depth
                    smooth_gray = cv2.cvtColor(sf, cv2.COLOR_BGR2GRAY)
                    smooth_tinted = cv2.cvtColor(smooth_gray, cv2.COLOR_GRAY2BGR)
                    smooth_tinted = (smooth_tinted.astype(np.float32) * 0.7).astype(np.uint8)
                    smooth_f = smooth_tinted.astype(np.float32)
                    # Screen blend: bright areas of both layers combine
                    a = live_f / 255.0
                    b = smooth_f / 255.0 * SMOOTH_BLEND_ALPHA
                    screen = 1.0 - (1.0 - a) * (1.0 - b)
                    composite = np.clip(screen * 255, 0, 255).astype(np.uint8)
                    self._write_snapshot(self._active_name + "-smooth", composite)
                except Exception:
                    log.debug("Smooth composite failed", exc_info=True)
                    self._write_snapshot(self._active_name + "-smooth", result)
            else:
                # Not enough frames yet — just write live as smooth too
                self._write_snapshot(self._active_name + "-smooth", result)

            # Write active output ONCE — either smooth composite or live only
            if self._smooth_mode and smooth_frame is not None:
                try:
                    active_output = composite  # type: ignore[possibly-undefined]
                except NameError:
                    active_output = live_result
            else:
                active_output = live_result
            self._write_snapshot("active", active_output)

        # Round-robin ONE preview effect per tick (keeps previews fresh without lag)
        if not hasattr(self, "_preview_idx"):
            self._preview_idx = 0
        preview_names = [
            n for n, s in self._slots.items() if s.tier == Tier.PREVIEW and n != self._active_name
        ]
        if preview_names:
            preview_name = preview_names[self._preview_idx % len(preview_names)]
            self._preview_idx += 1
            pslot = self._slots[preview_name]
            tier_frame = resized.get(Tier.PREVIEW)
            if tier_frame is not None:
                try:
                    result = pslot.effect.process(tier_frame, p, t)
                    self._write_snapshot(preview_name, result)
                except Exception:
                    log.debug("Preview %s failed", preview_name, exc_info=True)

        # Write active output to v4l2
        if active_output is not None:
            self._write_virtualcam(active_output)

    def _read_input(self) -> np.ndarray | None:
        """Read the compositor's fx-snapshot.jpg, skip if unchanged."""
        try:
            st = INPUT_PATH.stat()
            if st.st_mtime_ns == self._input_mtime:
                return None  # no new frame
            data = INPUT_PATH.read_bytes()
            self._input_mtime = st.st_mtime_ns
            if len(data) < 100:
                return None
            frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
            return frame
        except FileNotFoundError:
            return None
        except OSError:
            log.debug("Failed to read input frame", exc_info=True)
            return None

    def set_smooth_mode(self, enabled: bool) -> None:
        """Enable/disable live+smooth composite output."""
        self._smooth_mode = enabled
        log.info("Smooth mode: %s", "on" if enabled else "off")

    def _check_fx_request(self) -> None:
        """Poll fx-request.txt for preset switch commands."""
        try:
            st = FX_REQUEST_PATH.stat()
            if st.st_mtime == self._last_request_mtime:
                return
            self._last_request_mtime = st.st_mtime
            requested = FX_REQUEST_PATH.read_text(encoding="utf-8").strip()
            if requested and requested != self._active_name:
                log.info("FX request: %s → %s", self._active_name, requested)
                self.switch_active(requested)
        except FileNotFoundError:
            pass
        except OSError:
            log.debug("Failed to read fx-request", exc_info=True)

    def _write_snapshot(self, name: str, frame: np.ndarray) -> None:
        """Write effect output as JPEG to /dev/shm."""
        out_path = SNAPSHOT_DIR / f"fx-{name}.jpg"
        tmp_path = SNAPSHOT_DIR / f"fx-{name}.jpg.tmp"
        try:
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                tmp_path.write_bytes(buf.tobytes())
                tmp_path.rename(out_path)
        except OSError:
            log.debug("Failed to write snapshot for %s", name, exc_info=True)

    # ------------------------------------------------------------------
    # pyvirtualcam (optional)
    # ------------------------------------------------------------------

    def _init_virtualcam(self) -> None:
        """Try to open pyvirtualcam.  Graceful fallback to snapshot-only."""
        try:
            import pyvirtualcam

            self._cam = pyvirtualcam.Camera(
                width=1920,
                height=1080,
                fps=int(self._target_fps),
                device=self._v4l2_device,
            )
            log.info("pyvirtualcam opened on %s", self._v4l2_device)
        except ImportError:
            log.info("pyvirtualcam not installed — snapshot-only mode")
            self._cam = None
        except Exception:
            log.warning("Failed to open pyvirtualcam — snapshot-only mode", exc_info=True)
            self._cam = None

    def _write_virtualcam(self, frame: np.ndarray) -> None:
        if self._cam is None:
            return
        try:
            # pyvirtualcam expects RGB, we have BGR
            h, w = frame.shape[:2]
            if (w, h) != (1920, 1080):
                frame = cv2.resize(frame, (1920, 1080))
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            self._cam.send(rgb)
        except Exception:
            log.debug("virtualcam write failed", exc_info=True)

    def _shutdown_virtualcam(self) -> None:
        if self._cam is not None:
            try:
                self._cam.close()
            except Exception:
                pass
            self._cam = None

    # ------------------------------------------------------------------
    # Benchmark helper
    # ------------------------------------------------------------------

    def benchmark(self, iterations: int = 100) -> dict[str, float]:
        """Run each effect N times on a synthetic frame, return avg ms."""
        # Generate a test frame at 1080p
        test_frame = np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8)
        p = PerceptionSnapshot()
        results: dict[str, float] = {}

        for name, slot in self._slots.items():
            # Reset to active resolution for fair benchmark
            slot.effect.resize(1920, 1080)
            # Warm up
            for _ in range(3):
                slot.effect.process(test_frame, p, 0.0)

            t0 = time.monotonic()
            for i in range(iterations):
                slot.effect.process(test_frame, p, float(i) / 15.0)
            elapsed = (time.monotonic() - t0) * 1000.0
            avg = elapsed / iterations
            results[name] = round(avg, 2)
            log.info("Benchmark %s: %.2fms avg (%d iters)", name, avg, iterations)

        return results


def _width_for_height(target_h: int, src_w: int, src_h: int) -> int:
    """Compute width preserving aspect ratio, rounded to nearest even."""
    if src_h == 0:
        return target_h * 16 // 9
    w = int(target_h * src_w / src_h)
    return w + (w % 2)  # ensure even
