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
from cadence_controller import CadenceController, load_config
from cbip_calibration import crop_to_roi, load_camera_calibration
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

# Use the mDNS hostname instead of a hardcoded LAN IP so DHCP shuffles
# don't silence the fleet. The council advertises itself as
# ``hapax-podium.local`` via avahi-daemon
# (``systemctl is-active avahi-daemon`` confirms; ``avahi-browse -atrp``
# shows the published name).
#
# 2026-04-21 audit: an earlier comment claimed avahi assigned a `-2`
# suffix because another device on the LAN claimed the unsuffixed name.
# Live verification on Pi-1 disproved that — ``ping hapax-podium.local``
# resolves to the council's wlan0 IP cleanly. Pi-1 + Pi-2 had been
# silently dropping POSTs against the broken `-2` URL for ~21h until
# the IR Pi fleet revival on 2026-04-21.
DEFAULT_WORKSTATION = "http://hapax-podium.local:8051"
DEFAULT_CAPTURE_SIZE = (1920, 1080)
MOTION_THRESHOLD = 0.01
MOTION_TIMEOUT_S = 30.0

# Per-role rotation correction (2026-04-21). Pi NoIR cameras are mounted
# at non-standard angles "out of necessity" per operator. Captured frames
# are rotated by ``ROLE_ROTATION_CW_DEG[role]`` degrees clockwise via
# cv2.rotate before downstream processing (YOLO, hand detection, screen
# detection, debug-frame save) so every consumer sees an upright image.
#
# Live verification 2026-04-21:
# * desk: head-on portrait, captured 90° CCW → +90° CW corrects
# * room: wide-angle, captured 90° CCW → +90° CW corrects
# * overhead: top-down (no correction needed; verify when Pi-6 reachable)
#
# Rotation values must be one of {0, 90, 180, 270}; cv2.rotate has no
# arbitrary-angle path. Daemon ignores other values and logs a warning.
ROLE_ROTATION_CW_DEG: dict[str, int] = {
    "desk": 90,
    "room": 90,
    "overhead": 0,
}
_CV2_ROTATE_FOR: dict[int, int] = {
    90: cv2.ROTATE_90_CLOCKWISE,
    180: cv2.ROTATE_180,
    270: cv2.ROTATE_90_COUNTERCLOCKWISE,
}
# #143 — fallback POST interval.  The cadence controller drives the real post
# rate; this is only used when the controller is unavailable (e.g. test mode).
POST_INTERVAL_S = 2.0

# Metric label for prometheus scraping: hapax_ir_cadence_state{pi_role="..."}.
_METRIC_PATH = Path.home() / "hapax-edge" / "metrics" / "cadence.prom"


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
        # #143 — activity-gated cadence controller.
        self._cadence = CadenceController(config=load_config())
        self._cbip_calibration = load_camera_calibration(self._role, hostname=self._hostname)
        self._rpicam_calibration_args = self._cbip_calibration.rpicam_still_args()
        if self._cbip_calibration.source_paths:
            log.info(
                "CBIP calibration loaded for %s from %s",
                self._role,
                ", ".join(self._cbip_calibration.source_paths),
            )
        if self._cbip_calibration.roi is not None:
            roi = self._cbip_calibration.roi
            log.info(
                "CBIP ROI locked for %s: x=%d y=%d width=%d height=%d",
                self._role,
                roi.x,
                roi.y,
                roi.width,
                roi.height,
            )
        if self._rpicam_calibration_args:
            log.info(
                "CBIP capture controls locked for %s: %s",
                self._role,
                " ".join(self._rpicam_calibration_args),
            )

        self._client = httpx.AsyncClient(
            base_url=workstation_url,
            timeout=httpx.Timeout(10.0, connect=5.0),
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=1),
        )

        self._latest_jpeg: bytes = b""
        self._latest_album_jpeg: bytes = b""
        self._latest_album_detection: dict | None = None
        self._latest_jpeg_lock = __import__("threading").Lock()

        # Phase 3 of `ir-perception-replace-zones-with-vlm-classification` —
        # frame-level rich-vocabulary classifier. Replaces the fixed
        # five-zone enum at the producer source. The runner's motion gate
        # + cache cap the actual VLM call rate to roughly one per minute
        # on a static desk.
        from vlm_classifier import MotionGatedVlmRunner

        self._vlm_runner = MotionGatedVlmRunner()

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

        command = [
            "rpicam-still",
            "-o",
            path,
            "--immediate",
            "--width",
            str(DEFAULT_CAPTURE_SIZE[0]),
            "--height",
            str(DEFAULT_CAPTURE_SIZE[1]),
            *self._rpicam_calibration_args,
            "--nopreview",
            "-n",
        ]
        subprocess.run(
            command,
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
        # Per-role rotation correction (2026-04-21). Cameras are mounted
        # at non-standard angles; rotate captured frames upright before
        # downstream processing so YOLO + hand detection + saved debug
        # frames all share a single upright reference.
        rotation_deg = ROLE_ROTATION_CW_DEG.get(self._role, 0)
        if rotation_deg in _CV2_ROTATE_FOR:
            color = cv2.rotate(color, _CV2_ROTATE_FOR[rotation_deg])
        elif rotation_deg != 0:
            log.warning(
                "ignoring unsupported ROLE_ROTATION_CW_DEG[%s]=%d (must be 0/90/180/270)",
                self._role,
                rotation_deg,
            )
        if self._cbip_calibration.roi is not None:
            color = crop_to_roi(color, self._cbip_calibration)
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

                hands = detect_hands_nir(grey, motion_delta=motion_delta)
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

            # #143 — feed cadence controller with observed activity and let it
            # decide the post/sleep interval for this tick.
            hand_count = sum(1 for h in hands if h)
            person_count = len(persons)
            self._cadence.record_activity(
                persons=person_count,
                hands=hand_count,
                motion_delta=motion_delta,
            )
            self._cadence.evaluate()

            now = time.monotonic()
            cadence_interval_s = self._cadence.get_sleep_duration()
            if now - last_post >= cadence_interval_s:
                # Phase 3: classify hand semantics via VLM (motion-gated).
                # Pass the latest cached JPEG so the runner sees the same
                # frame the report references; ``None`` is returned when
                # the runner's motion gate / cache / failure paths
                # decline to call the VLM this tick.
                with self._latest_jpeg_lock:
                    latest_jpeg = self._latest_jpeg
                tick = self._vlm_runner.tick(latest_jpeg)
                report = self._build_report(
                    motion_delta,
                    persons,
                    hands,
                    screens,
                    grey,
                    inference_ms,
                    hand_semantics=tick.semantics,
                )
                await self._post_report(report)
                last_post = now
                self._write_cadence_metric()

            elapsed = time.monotonic() - t0
            sleep_time = max(0.05, cadence_interval_s - elapsed)
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
        self,
        motion_delta,
        persons,
        hands,
        screens,
        grey,
        inference_ms,
        hand_semantics: dict | None = None,
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
            cadence_state=self._cadence.state,
            cadence_interval_s=self._cadence.get_sleep_duration(),
            hand_semantics=hand_semantics,
        )

    def _write_cadence_metric(self) -> None:
        """Write a prometheus textfile exposing current cadence state.

        Textfile format so node_exporter's textfile collector can scrape it;
        avoids running a prometheus_client HTTP server on the Pi.
        """
        try:
            _METRIC_PATH.parent.mkdir(parents=True, exist_ok=True)
            snap = self._cadence.snapshot()
            state_num = {"QUIESCENT": 0, "IDLE": 1, "ACTIVE": 2, "HOT": 3}.get(
                self._cadence.state, 1
            )
            lines = [
                "# HELP hapax_ir_cadence_state Current cadence state "
                "(0=QUIESCENT, 1=IDLE, 2=ACTIVE, 3=HOT).",
                "# TYPE hapax_ir_cadence_state gauge",
                f'hapax_ir_cadence_state{{pi_role="{self._role}"}} {state_num}',
                "# HELP hapax_ir_cadence_interval_seconds Active post interval (s).",
                "# TYPE hapax_ir_cadence_interval_seconds gauge",
                f'hapax_ir_cadence_interval_seconds{{pi_role="{self._role}"}} {snap["interval_s"]}',
                "",
            ]
            _METRIC_PATH.write_text("\n".join(lines))
        except OSError:
            log.debug("cadence metric write failed", exc_info=True)

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
