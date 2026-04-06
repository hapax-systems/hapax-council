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
from ir_album import detect_album_cover, extract_album_crop
from ir_biometrics import BiometricTracker
from ir_hands import detect_hands_nir, detect_screens_nir
from ir_inference import FaceLandmarkDetector, YoloDetector
from ir_models import IrDetectionReport  # noqa: TC002 — Pi-side code
from ir_report import build_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("hapax-ir-edge")

DEFAULT_WORKSTATION = "http://192.168.68.80:8051"
DEFAULT_CAPTURE_SIZE = (1920, 1080)
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

        self._latest_jpeg: bytes = b""
        self._latest_album_jpeg: bytes = b""
        self._latest_album_detection: dict | None = None
        self._latest_jpeg_lock = __import__("threading").Lock()

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

                # Album cover detection (overhead camera only)
                if self._role == "overhead":
                    album_det = detect_album_cover(grey)
                    if album_det is not None:
                        crop = extract_album_crop(color, album_det, output_size=640)
                        if crop is not None:
                            _, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
                            with self._latest_jpeg_lock:
                                self._latest_album_jpeg = buf.tobytes()
                                self._latest_album_detection = album_det
                    else:
                        with self._latest_jpeg_lock:
                            self._latest_album_detection = None

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
        # Always cache latest frame as JPEG for HTTP serving
        _, buf = cv2.imencode(".jpg", grey, [cv2.IMWRITE_JPEG_QUALITY, 85])
        with self._latest_jpeg_lock:
            self._latest_jpeg = buf.tobytes()

        if self._save_debug_frame:
            cv2.imwrite(f"/tmp/ir_debug_{self._role}.jpg", grey)
            log.info("Debug frame saved to /tmp/ir_debug_%s.jpg", self._role)
            self._save_debug_frame = False
        self._frame_count += 1
        if self._save_interval > 0 and self._frame_count % self._save_interval == 0:
            ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
            cv2.imwrite(str(self._captures_dir / f"{self._role}_{ts}.jpg"), grey)

    def _update_rppg(self, persons: list[dict], grey: np.ndarray) -> None:
        self._biometrics.face_detected = False
        if not persons:
            return
        best = max(persons, key=lambda p: p.get("confidence", 0))
        head_pose = best.get("head_pose", {})
        if not (head_pose and head_pose.get("yaw") is not None):
            return
        self._biometrics.face_detected = True
        bbox = best["bbox"]
        fy1, fy2 = bbox[1], bbox[1] + int((bbox[3] - bbox[1]) * 0.3)
        fx1, fx2 = bbox[0], bbox[2]
        if fy2 > fy1 and fx2 > fx1:
            forehead = grey[fy1:fy2, fx1:fx2]
            if forehead.size > 0:
                self._biometrics.update_rppg_intensity(float(np.mean(forehead)))

    def _build_report(
        self, motion_delta, persons, hands, screens, grey, inference_ms
    ) -> IrDetectionReport:
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

    async def _post_report(self, report: IrDetectionReport) -> None:
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


FRAME_SERVER_PORT = 8090


class _FrameHandler:
    """HTTP handler that serves the latest IR frame as JPEG."""

    def __init__(self, daemon: IrEdgeDaemon) -> None:
        self._daemon = daemon

    def __call__(self, environ, start_response):
        path = environ["PATH_INFO"]

        if path == "/frame.jpg":
            with self._daemon._latest_jpeg_lock:
                data = self._daemon._latest_jpeg
            if data:
                start_response(
                    "200 OK",
                    [
                        ("Content-Type", "image/jpeg"),
                        ("Content-Length", str(len(data))),
                        ("Cache-Control", "no-cache"),
                    ],
                )
                return [data]
            start_response("503 No Frame", [("Content-Type", "text/plain")])
            return [b"no frame yet"]

        if path == "/album.jpg":
            with self._daemon._latest_jpeg_lock:
                data = self._daemon._latest_album_jpeg
            if data:
                start_response(
                    "200 OK",
                    [
                        ("Content-Type", "image/jpeg"),
                        ("Content-Length", str(len(data))),
                        ("Cache-Control", "no-cache"),
                    ],
                )
                return [data]
            start_response("404 No Album", [("Content-Type", "text/plain")])
            return [b"no album detected"]

        if path == "/album.json":
            import json as _json

            with self._daemon._latest_jpeg_lock:
                det = self._daemon._latest_album_detection
            if det:
                body = _json.dumps(det).encode()
                start_response(
                    "200 OK",
                    [
                        ("Content-Type", "application/json"),
                        ("Content-Length", str(len(body))),
                    ],
                )
                return [body]
            start_response("404 No Album", [("Content-Type", "text/plain")])
            return [b"no album detected"]

        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"not found"]


def _start_frame_server(daemon: IrEdgeDaemon) -> None:
    """Start a minimal WSGI HTTP server for on-demand frame access."""
    import threading
    from wsgiref.simple_server import WSGIServer, make_server

    class _QuietServer(WSGIServer):
        def handle_error(self, request, client_address):
            pass  # suppress tracebacks from client disconnects

    try:
        server = make_server(
            "0.0.0.0", FRAME_SERVER_PORT, _FrameHandler(daemon), server_class=_QuietServer
        )
        server.timeout = 1
        log.info("Frame server on :%d/frame.jpg", FRAME_SERVER_PORT)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
    except Exception:
        log.warning("Frame server failed to start", exc_info=True)


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
    _start_frame_server(daemon)
    daemon.start()


if __name__ == "__main__":
    main()
