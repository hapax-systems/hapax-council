"""Imagination content resolver — rasterizes slow content references to JPEG.

Resolves "slow" content kinds (text, qdrant_query, url) from imagination
fragments into JPEG images on /dev/shm. "Fast" kinds (camera_frame, file)
are skipped — handled by the Rust visual surface.
"""

from __future__ import annotations

import json
import logging
import shutil
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from agents.imagination import ContentReference, ImaginationFragment

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONTENT_DIR = Path("/dev/shm/hapax-imagination/content")
RENDER_WIDTH = 1920
RENDER_HEIGHT = 1080
SLOW_KINDS = {"text", "qdrant_query", "url"}
CAMERA_FRAME_DIR = "/dev/shm/hapax-compositor"
FAST_KINDS = {"camera_frame", "file"}
MAX_SLOTS = 4

# ---------------------------------------------------------------------------
# Font loading
# ---------------------------------------------------------------------------

_FONT_PATH = Path("/usr/share/fonts/TTF/JetBrainsMono-Regular.ttf")


def _load_font(size: int = 36) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a monospace font with fallback to Pillow default."""
    if _FONT_PATH.exists():
        return ImageFont.truetype(str(_FONT_PATH), size)
    return ImageFont.load_default(size=size)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def cleanup_content_dir(content_dir: Path | None = None) -> None:
    """Delete all *.jpg files in the content directory."""
    d = content_dir or CONTENT_DIR
    for jpg in d.glob("*.jpg"):
        try:
            jpg.unlink()
        except OSError:
            log.warning("Failed to remove %s", jpg)


def resolve_text(
    ref: ContentReference,
    content_dir: Path | None = None,
    fragment_id: str = "unknown",
    index: int = 0,
) -> Path | None:
    """Rasterize text to a JPEG image (white text on black background)."""
    d = content_dir or CONTENT_DIR
    d.mkdir(parents=True, exist_ok=True)

    img = Image.new("RGB", (RENDER_WIDTH, RENDER_HEIGHT), color=(0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = _load_font(36)

    # Word-wrap each line to fit within the image
    max_chars = 80
    lines: list[str] = []
    for raw_line in ref.source.split("\n"):
        wrapped = textwrap.wrap(raw_line, width=max_chars) or [""]
        lines.extend(wrapped)

    # Compute total text height for vertical centering
    line_height = 44  # approximate for size-36 font
    total_height = line_height * len(lines)
    y_start = max(0, (RENDER_HEIGHT - total_height) // 2)

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w = bbox[2] - bbox[0]
        x = max(0, (RENDER_WIDTH - text_w) // 2)
        y = y_start + i * line_height
        draw.text((x, y), line, fill=(255, 255, 255), font=font)

    out_path = d / f"{fragment_id}-{index}.jpg"
    img.save(out_path, "JPEG", quality=85)
    log.debug("Resolved text → %s", out_path)
    return out_path


def resolve_references(
    fragment: ImaginationFragment,
    content_dir: Path | None = None,
) -> list[Path]:
    """Resolve all slow content references in a fragment to JPEG files."""
    results: list[Path] = []
    for i, ref in enumerate(fragment.content_references):
        if ref.kind not in SLOW_KINDS:
            continue
        path: Path | None = None
        if ref.kind == "text":
            path = resolve_text(ref, content_dir, fragment.id, i)
        elif ref.kind == "qdrant_query":
            path = _resolve_qdrant(ref, content_dir, fragment.id, i)
        elif ref.kind == "url":
            path = _resolve_url(ref, content_dir, fragment.id, i)
        if path is not None:
            results.append(path)
    return results


def write_slot_manifest(
    fragment: ImaginationFragment,
    resolved_paths: list[Path],
    manifest_path: Path,
) -> None:
    """Write a slot manifest JSON for the Rust content texture manager."""
    slots = []
    resolved_idx = 0

    for i, ref in enumerate(fragment.content_references[:MAX_SLOTS]):
        if ref.kind == "camera_frame":
            path = f"{CAMERA_FRAME_DIR}/{ref.source}.jpg"
        elif ref.kind == "file":
            path = ref.source
        elif resolved_idx < len(resolved_paths):
            path = str(resolved_paths[resolved_idx])
            resolved_idx += 1
        else:
            continue

        slots.append(
            {
                "index": i,
                "path": path,
                "kind": ref.kind,
                "salience": ref.salience,
            }
        )

    manifest = {
        "fragment_id": fragment.id,
        "slots": slots,
        "continuation": fragment.continuation,
        "material": fragment.material,
    }

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = manifest_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest))
    tmp.rename(manifest_path)


def resolve_references_staged(
    fragment: ImaginationFragment,
    staging_dir: Path | None = None,
    active_dir: Path | None = None,
) -> list[Path]:
    """Resolve content references to staging, then atomically swap to active."""
    staging = staging_dir or (CONTENT_DIR / "staging")
    active = active_dir or (CONTENT_DIR / "active")

    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    resolved = resolve_references(fragment, content_dir=staging)
    write_slot_manifest(fragment, resolved, staging / "slots.json")

    old = active.with_name("old")
    if active.exists():
        active.rename(old)
    staging.rename(active)
    if old.exists():
        shutil.rmtree(old, ignore_errors=True)

    return resolved


# ---------------------------------------------------------------------------
# Private resolvers
# ---------------------------------------------------------------------------


def _resolve_qdrant(
    ref: ContentReference,
    content_dir: Path | None,
    fragment_id: str,
    index: int,
) -> Path | None:
    """Query Qdrant for the top result and rasterize its text."""
    try:
        from shared.config import embed, get_qdrant

        client = get_qdrant()
        vector = embed(ref.query or ref.source)
        results = client.search(
            collection_name=ref.source,
            query_vector=vector,
            limit=1,
        )
        if not results:
            log.debug("Qdrant query returned no results for %s", ref.source)
            return None
        text = str(results[0].payload.get("text", "")) if results[0].payload else ""
        if not text:
            return None
        text_ref = ContentReference(kind="text", source=text, query=None, salience=ref.salience)
        return resolve_text(text_ref, content_dir, fragment_id, index)
    except Exception:
        log.warning("Qdrant resolve failed", exc_info=True)
        return None


def _resolve_url(
    ref: ContentReference,
    content_dir: Path | None,
    fragment_id: str,
    index: int,
) -> Path | None:
    """Fetch an image URL, resize to fit 1920x1080, paste centered on black."""
    try:
        import io

        import httpx

        d = content_dir or CONTENT_DIR
        d.mkdir(parents=True, exist_ok=True)

        resp = httpx.get(ref.source, timeout=5.0)
        resp.raise_for_status()

        src = Image.open(io.BytesIO(resp.content)).convert("RGB")
        # Resize to fit within render dimensions, preserving aspect ratio
        src.thumbnail((RENDER_WIDTH, RENDER_HEIGHT), Image.LANCZOS)

        canvas = Image.new("RGB", (RENDER_WIDTH, RENDER_HEIGHT), color=(0, 0, 0))
        paste_x = (RENDER_WIDTH - src.width) // 2
        paste_y = (RENDER_HEIGHT - src.height) // 2
        canvas.paste(src, (paste_x, paste_y))

        out_path = d / f"{fragment_id}-{index}.jpg"
        canvas.save(out_path, "JPEG", quality=85)
        log.debug("Resolved URL → %s", out_path)
        return out_path
    except Exception:
        log.warning("URL resolve failed for %s", ref.source, exc_info=True)
        return None
