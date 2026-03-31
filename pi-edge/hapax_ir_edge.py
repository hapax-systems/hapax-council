#!/usr/bin/env python3
"""hapax_ir_edge.py — Pi NoIR edge inference daemon.

Captures IR frames from Pi Camera Module 3 NoIR, runs person detection
(YOLOv8n TFLite), face landmarks, hand detection, and screen detection.
POSTs structured JSON reports to the workstation council API every 2-3s.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import cv2
import httpx
import numpy as np  # noqa: TC002 — Pi-side code
from ir_biometrics import BiometricTracker
from ir_hands import detect_hands_nir, detect_screens_nir
from ir_inference import FaceLandmarkDetector, YoloDetector
from ir_report import build_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("hapax-ir-edge")

DEFAULT_WORKSTATION = "http://192.168.68.80:8051"
DEFAULT_CAPTURE_SIZE = (640, 480)
MOTION_THRESHOLD = 0.01
MOTION_TIMEOUT_S = 30.0
POST_INTERVAL_S = 2.0


class IrEdgeDaemon:
    """Main daemon: capture, infer, POST."""

    def __init__(
        self,
        role: str,
        hostname: str,
        workstation_url: str = DEFAULT_WORKSTATION,
        save_frame_interval: int = 0,
    ) -> None:
        self._role = role
        self._hostname = hostname
        self._workstation_url = workstation_url
        self._running = False
        self._prev_frame: np.ndarray | None = None
        self._last_detection_time: float = 0.0
        self._save_debug_frame = False
        self._save_interval = save_frame_interval
        self._frame_count = 0
        self._captures_dir = Path.home() / "hapax-edge" / "captures"
        if self._save_interval > 0:
            self._captures_dir.mkdir(parents=True, exist_ok=True)

        self._yolo = YoloDetector()
        self._face = FaceLandmarkDetector()
        self._biometrics = BiometricTracker(fps=30.0)

        self._client = httpx.AsyncClient(
            base_url=workstation_url,
            timeout=httpx.Timeout(10.0, connect=5.0),
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=1),
        )

    def request_debug_frame(self) -> None:
        """Flag the daemon to save the next frame for debugging."""
        self._save_debug_frame = True
        log.info("Debug frame capture requested")

    def start(self) -> None:
        """Start the capture + inference loop."""
        self._running = True
        log.info("Starting IR edge daemon: role=%s, target=%s", self._role, self._workstation_url)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._main_loop())
        finally:
            loop.run_until_complete(self._client.aclose())
            loop.close()

    def _capture_frame(self) -> tuple[np.ndarray, np.ndarray]:
        """Capture a frame via rpicam-still. Returns (color, greyscale)."""
        import os
        import subprocess
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=True) as f:
            path = f.name

        subprocess.run(
            [
                "rpicam-still",
                "-o",
                path,
                "--immediate",
                "--width",
                str(DEFAULT_CAPTURE_SIZE[0]),
                "--height",
                str(DEFAULT_CAPTURE_SIZE[1]),
                "--nopreview",
                "-n",
            ],
            capture_output=True,
            timeout=10,
        )

        empty = np.zeros(DEFAULT_CAPTURE_SIZE[::-1], dtype=np.uint8)
        if not os.path.exists(path):
            return cv2.cvtColor(empty, cv2.COLOR_GRAY2BGR), empty
        color = cv2.imread(path, cv2.IMREAD_COLOR)
        os.unlink(path)
        if color is None:
            return cv2.cvtColor(empty, cv2.COLOR_GRAY2BGR), empty
        grey = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
        return color, grey

    async def _main_loop(self) -> None:
        """Main inference + POST loop."""
        last_post = 0.0
        log.info("Camera capture via rpicam-still at %s", DEFAULT_CAPTURE_SIZE)

        while self._running:
            t0 = time.monotonic()

            color, grey = await asyncio.get_event_loop().run_in_executor(None, self._capture_frame)

            self._handle_frame_saves(grey)
            motion_delta = self._compute_motion(grey)

            time_since_detection = time.monotonic() - self._last_detection_time
            skip_inference = (
                motion_delta < MOTION_THRESHOLD and time_since_detection > MOTION_TIMEOUT_S
            )

            persons: list[dict] = []
            hands: list[dict] = []
            screens: list[dict] = []
            inference_ms = 0

            if not skip_inference:
                t_infer = time.monotonic()

                # Use color for YOLO (trained on RGB), greyscale for hand/screen detection
                raw_persons = self._yolo.detect_persons(color)

                for p in raw_persons:
                    face_data = self._face.detect(grey, p["bbox"])
                    if face_data is not None:
                        p.update(face_data)
                        avg_ear = (face_data.get("ear_left", 0) + face_data.get("ear_right", 0)) / 2
                        self._biometrics.update_ear(avg_ear, time.monotonic())
                    persons.append(p)

                if persons:
                    self._last_detection_time = time.monotonic()

                hands = detect_hands_nir(grey)
                screens = detect_screens_nir(grey)

                inference_ms = int((time.monotonic() - t_infer) * 1000)

            # rPPG: only update when face landmarks produced head_pose data
            self._update_rppg(persons, grey)

            now = time.monotonic()
            if now - last_post >= POST_INTERVAL_S:
                report = self._build_report(
                    motion_delta, persons, hands, screens, grey, inference_ms
                )
                await self._post_report(report)
                last_post = now

            elapsed = time.monotonic() - t0
            sleep_time = max(0.05, (1.0 / 5.0) - elapsed)
            await asyncio.sleep(sleep_time)

    def _compute_motion(self, grey: np.ndarray) -> float:
        """Frame differencing for motion detection."""
        if self._prev_frame is None:
            self._prev_frame = grey.copy()
            return 1.0

        diff = cv2.absdiff(grey, self._prev_frame)
        self._prev_frame = grey.copy()
        return float(np.mean(diff)) / 255.0

    def _handle_frame_saves(self, grey: np.ndarray) -> None:
        if self._save_debug_frame:
            cv2.imwrite(f"/tmp/ir_debug_{self._role}.jpg", grey)
            log.info("Debug frame saved to /tmp/ir_debug_%s.jpg", self._role)
            self._save_debug_frame = False
        self._frame_count += 1
        if self._save_interval > 0 and self._frame_count % self._save_interval == 0:
            ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
            cv2.imwrite(str(self._captures_dir / f"{self._role}_{ts}.jpg"), grey)

    def _update_rppg(self, persons: list[dict], grey: np.ndarray) -> None:
        if not persons:
            return
        best = max(persons, key=lambda p: p.get("confidence", 0))
        head_pose = best.get("head_pose", {})
        if not (head_pose and head_pose.get("yaw") is not None):
            return
        bbox = best["bbox"]
        fy1, fy2 = bbox[1], bbox[1] + int((bbox[3] - bbox[1]) * 0.3)
        fx1, fx2 = bbox[0], bbox[2]
        if fy2 > fy1 and fx2 > fx1:
            forehead = grey[fy1:fy2, fx1:fx2]
            if forehead.size > 0:
                self._biometrics.update_rppg_intensity(float(np.mean(forehead)))

    def _build_report(self, motion_delta, persons, hands, screens, grey, inference_ms):
        return build_report(
            self._hostname,
            self._role,
            motion_delta,
            persons,
            hands,
            screens,
            grey,
            inference_ms,
            self._biometrics.snapshot(),
        )

    async def _post_report(self, report) -> None:
        """POST detection report to workstation."""
        try:
            resp = await self._client.post(
                f"/api/pi/{self._role}/ir",
                content=report.model_dump_json(),
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code == 429:
                log.debug("Throttled by workstation")
            elif resp.status_code != 200:
                log.warning("POST failed: %d %s", resp.status_code, resp.text[:100])
        except httpx.ConnectError:
            log.debug("Workstation unreachable")
        except Exception:
            log.warning("POST error", exc_info=True)

    def stop(self) -> None:
        self._running = False


def main() -> None:
    parser = argparse.ArgumentParser(description="Hapax IR Edge Inference Daemon")
    parser.add_argument("--role", required=True, choices=["desk", "room", "overhead"])
    parser.add_argument("--hostname", default=None)
    parser.add_argument("--workstation", default=DEFAULT_WORKSTATION)
    parser.add_argument("--save-frames", type=int, default=0, help="Save every Nth frame")
    args = parser.parse_args()

    hostname = args.hostname or f"hapax-{args.role}"
    daemon = IrEdgeDaemon(
        role=args.role,
        hostname=hostname,
        workstation_url=args.workstation,
        save_frame_interval=args.save_frames,
    )

    def _sigterm(signum, frame):  # noqa: ANN001
        log.info("Received signal %d, shutting down", signum)
        daemon.stop()

    def _sigusr1(signum, frame):  # noqa: ANN001
        daemon.request_debug_frame()

    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGINT, _sigterm)
    signal.signal(signal.SIGUSR1, _sigusr1)
    daemon.start()


if __name__ == "__main__":
    main()
