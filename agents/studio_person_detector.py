"""Studio Person Detector — lightweight YOLOv8n person detection on camera snapshots.

Reads per-camera JPEG snapshots from /dev/shm and writes detection
results as JSON. Runs as a separate process for failure isolation.

Usage:
    uv run python -m agents.studio_person_detector
"""

import argparse
import json
import logging
import signal
import sys
import time
from pathlib import Path

from shared.cameras import CAMERA_ROLES

log = logging.getLogger(__name__)

SNAPSHOT_DIR = Path("/dev/shm/hapax-compositor")
DETECTION_OUTPUT = SNAPSHOT_DIR / "person-detection.json"
SKIP_FILES = {"snapshot.jpg", "fx-snapshot.jpg", "consent-state.txt"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Studio person detector")
    parser.add_argument("--fps", type=float, default=2.0, help="Detection rate per camera")
    parser.add_argument("--confidence", type=float, default=0.4, help="Min detection confidence")
    parser.add_argument("--device", default="cuda:0", help="Inference device")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    from shared.log_setup import configure_logging

    configure_logging(agent="studio-person-detector", level="DEBUG" if args.verbose else None)

    try:
        from ultralytics import YOLO
    except ImportError:
        log.error("ultralytics not installed. Run: uv pip install ultralytics")
        sys.exit(1)

    log.info("Loading YOLOv8n model...")
    model = YOLO("yolov8n.pt")
    model.to(args.device)
    log.info("Model loaded on %s", args.device)

    running = True

    def _shutdown(signum: int, frame: object) -> None:
        nonlocal running
        log.info("Shutting down")
        running = False

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    interval = 1.0 / args.fps

    while running:
        results: dict[str, object] = {"timestamp": time.time(), "cameras": {}}
        cameras: dict[str, object] = {}

        for role in CAMERA_ROLES:
            snap_path = SNAPSHOT_DIR / f"{role}.jpg"
            if not snap_path.exists():
                continue

            try:
                preds = model.predict(
                    str(snap_path),
                    classes=[0],  # person only
                    conf=args.confidence,
                    verbose=False,
                    device=args.device,
                )
                boxes = []
                if preds and len(preds) > 0:
                    for box in preds[0].boxes:
                        x1, y1, x2, y2 = box.xyxy[0].tolist()
                        conf = float(box.conf[0])
                        boxes.append(
                            {
                                "x1": round(x1),
                                "y1": round(y1),
                                "x2": round(x2),
                                "y2": round(y2),
                                "confidence": round(conf, 3),
                            }
                        )
                cameras[role] = {
                    "person_count": len(boxes),
                    "boxes": boxes,
                }
            except Exception as exc:
                log.debug("Detection failed for %s: %s", role, exc)
                cameras[role] = {"person_count": 0, "boxes": []}

        results["cameras"] = cameras

        # Atomic write
        try:
            tmp = DETECTION_OUTPUT.with_suffix(".tmp")
            tmp.write_text(json.dumps(results))
            tmp.rename(DETECTION_OUTPUT)
        except OSError:
            pass

        # Summary log every 30 iterations
        if int(time.time()) % 30 == 0:
            total = sum(
                c.get("person_count", 0)  # type: ignore[union-attr]
                for c in cameras.values()
            )
            log.debug("Detection: %d persons across %d cameras", total, len(cameras))

        time.sleep(interval)


if __name__ == "__main__":
    main()
