#!/usr/bin/env python3
"""Smoke test for Hapax Reverie visual pipeline.

Exercises the full end-to-end chain:
  Python imagination → shm slots.json → Rust ContentTextureManager → WGSL compositing

Takes screenshots at each stage for visual verification.
Requires: hapax-imagination binary running (systemctl --user start hapax-imagination)

Usage:
    uv run python scripts/smoke_test_reverie.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# --- Paths ---

FRAME_PATH = Path("/dev/shm/hapax-visual/frame.jpg")
PIPELINE_DIR = Path("/dev/shm/hapax-imagination/pipeline")
CONTENT_DIR = Path("/dev/shm/hapax-imagination/content")
ACTIVE_DIR = CONTENT_DIR / "active"
STAGING_DIR = CONTENT_DIR / "staging"
PLAN_PATH = PIPELINE_DIR / "plan.json"
UNIFORMS_PATH = PIPELINE_DIR / "uniforms.json"
MANIFEST_PATH = ACTIVE_DIR / "slots.json"
OUTPUT_DIR = Path("output/reverie-smoke-test")
UDS_SOCKET = Path(f"{Path.home() / '.cache'}/hapax-imagination.sock")

MATERIAL_MAP = {"water": 0, "fire": 1, "earth": 2, "air": 3, "void": 4}


# --- Helpers ---


def wait_for_frame(timeout_s: float = 5.0) -> bool:
    """Wait for the frame file to be updated."""
    if not FRAME_PATH.exists():
        return False
    start_mtime = FRAME_PATH.stat().st_mtime
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(0.1)
        if FRAME_PATH.exists() and FRAME_PATH.stat().st_mtime > start_mtime:
            return True
    return False


def capture_frame(name: str) -> Path | None:
    """Copy current frame to output directory with a name."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not FRAME_PATH.exists():
        print(f"  [SKIP] {name} — no frame available")
        return None
    dest = OUTPUT_DIR / f"{name}.jpg"
    shutil.copy2(FRAME_PATH, dest)
    print(f"  [OK] {name} → {dest}")
    return dest


def rasterize_text(text: str, path: Path, color: tuple = (255, 255, 255)) -> None:
    """Create a simple text JPEG for content testing."""
    img = Image.new("RGB", (1920, 1080), color=(0, 0, 0))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/TTF/JetBrainsMono-Regular.ttf", 72)
    except OSError:
        font = ImageFont.load_default(size=48)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (1920 - text_w) // 2
    y = (1080 - text_h) // 2
    draw.text((x, y), text, fill=color, font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=85)


def write_uniforms(material: str = "water", salience: float = 0.0) -> None:
    """Write uniforms.json with material and salience."""
    data = {
        "custom": [float(MATERIAL_MAP.get(material, 0))],
        "slot_opacities": [salience, 0.0, 0.0, 0.0],
    }
    UNIFORMS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = UNIFORMS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.rename(UNIFORMS_PATH)


def write_manifest(
    fragment_id: str,
    slots: list[dict],
    material: str = "water",
    continuation: bool = False,
) -> None:
    """Write slots.json manifest for ContentTextureManager."""
    manifest = {
        "fragment_id": fragment_id,
        "slots": slots,
        "continuation": continuation,
        "material": material,
    }
    ACTIVE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest))
    tmp.rename(MANIFEST_PATH)


def check_binary_running() -> bool:
    """Check if hapax-imagination is running."""
    result = subprocess.run(
        ["systemctl", "--user", "is-active", "hapax-imagination"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() == "active"


# --- Test Stages ---


def stage_0_baseline() -> None:
    """Capture baseline — procedural field only, no content."""
    print("\n=== Stage 0: Baseline (procedural field, no content) ===")
    write_uniforms(salience=0.0)
    time.sleep(1)
    capture_frame("00-baseline-procedural")


def stage_1_materialization() -> None:
    """Test materialization from substrate with increasing salience."""
    print("\n=== Stage 1: Materialization (salience ramp) ===")
    rasterize_text("REVERIE", ACTIVE_DIR / "test-0.jpg")
    for i, salience in enumerate([0.1, 0.3, 0.5, 0.7, 1.0]):
        write_uniforms(material="water", salience=salience)
        write_manifest(
            fragment_id=f"mat-{i}",
            slots=[
                {
                    "index": 0,
                    "path": str(ACTIVE_DIR / "test-0.jpg"),
                    "kind": "text",
                    "salience": salience,
                }
            ],
            material="water",
        )
        time.sleep(0.8)
        capture_frame(f"01-materialization-{salience:.1f}")


def stage_2_materials() -> None:
    """Test each material quality."""
    print("\n=== Stage 2: Material quality (water/fire/earth/air/void) ===")
    rasterize_text("MATERIAL", ACTIVE_DIR / "test-0.jpg")
    for material in ["water", "fire", "earth", "air", "void"]:
        write_uniforms(material=material, salience=0.8)
        write_manifest(
            fragment_id=f"mat-{material}",
            slots=[
                {
                    "index": 0,
                    "path": str(ACTIVE_DIR / "test-0.jpg"),
                    "kind": "text",
                    "salience": 0.8,
                }
            ],
            material=material,
        )
        time.sleep(1.0)
        capture_frame(f"02-material-{material}")


def stage_3_dwelling_trace() -> None:
    """Test dwelling trace — high salience then rapid drop."""
    print("\n=== Stage 3: Dwelling trace (fadeout luminance boost) ===")
    rasterize_text("DWELLING", ACTIVE_DIR / "test-0.jpg")
    # High salience
    write_uniforms(material="earth", salience=1.0)
    write_manifest(
        fragment_id="dwell-1",
        slots=[
            {"index": 0, "path": str(ACTIVE_DIR / "test-0.jpg"), "kind": "text", "salience": 1.0}
        ],
        material="earth",
    )
    time.sleep(1.5)
    capture_frame("03-dwelling-before")
    # Drop salience — trace boost should brighten the fadeout
    write_uniforms(material="earth", salience=0.1)
    write_manifest(
        fragment_id="dwell-2",
        slots=[
            {"index": 0, "path": str(ACTIVE_DIR / "test-0.jpg"), "kind": "text", "salience": 0.1}
        ],
        material="earth",
    )
    time.sleep(0.5)
    capture_frame("03-dwelling-fadeout")
    time.sleep(2.0)
    capture_frame("03-dwelling-trace")


def stage_4_multi_slot() -> None:
    """Test multiple content slots simultaneously."""
    print("\n=== Stage 4: Multi-slot compositing ===")
    for i, text in enumerate(["SLOT-0", "SLOT-1", "SLOT-2", "SLOT-3"]):
        rasterize_text(text, ACTIVE_DIR / f"test-{i}.jpg")
    write_uniforms(material="fire", salience=0.7)
    write_manifest(
        fragment_id="multi-1",
        slots=[
            {
                "index": i,
                "path": str(ACTIVE_DIR / f"test-{i}.jpg"),
                "kind": "text",
                "salience": 0.7 - i * 0.1,
            }
            for i in range(4)
        ],
        material="fire",
    )
    time.sleep(1.5)
    capture_frame("04-multi-slot")


def stage_5_cleanup() -> None:
    """Clean up — fade everything out."""
    print("\n=== Stage 5: Cleanup ===")
    write_uniforms(salience=0.0)
    write_manifest(fragment_id="cleanup", slots=[], material="water")
    time.sleep(2)
    capture_frame("05-cleanup")


# --- Main ---


def main() -> None:
    print("Hapax Reverie Smoke Test")
    print("=" * 40)

    if not check_binary_running():
        print("[ERROR] hapax-imagination is not running. Start with:")
        print("  systemctl --user start hapax-imagination")
        return

    if not FRAME_PATH.exists():
        print("[WARN] No frame file yet — waiting 3s for first frame...")
        time.sleep(3)
        if not FRAME_PATH.exists():
            print("[ERROR] Still no frame. Check logs:")
            print("  journalctl --user -u hapax-imagination --since '1 min ago'")
            return

    # Clean previous test output
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)

    stage_0_baseline()
    stage_1_materialization()
    stage_2_materials()
    stage_3_dwelling_trace()
    stage_4_multi_slot()
    stage_5_cleanup()

    print(f"\n{'=' * 40}")
    print(f"Screenshots saved to: {OUTPUT_DIR}/")
    print(f"Total: {len(list(OUTPUT_DIR.glob('*.jpg')))} frames captured")


if __name__ == "__main__":
    main()
