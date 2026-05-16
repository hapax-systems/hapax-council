"""Content injector — any Hapax capability can inject content into the visual surface.

Provides a simple API for any agent, backend, or capability to write
content (JPEG, PIL Image, raw RGBA, or text) to the source protocol.
The Reverie ContentSourceManager picks it up automatically.

Usage:
    from agents.reverie.content_injector import inject_image, inject_text

    # From any agent:
    inject_image("my-agent-output", Path("/tmp/plot.png"), opacity=0.5)
    inject_text("status-message", "System healthy", opacity=0.3)
    inject_jpeg("camera-feed", Path("/dev/shm/hapax-compositor/c920-overhead.jpg"))
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("reverie.injector")

SOURCES_DIR = Path("/dev/shm/hapax-imagination/sources")


def inject_image(
    source_id: str,
    image_path: Path,
    opacity: float = 0.6,
    z_order: int = 10,
    blend_mode: str = "screen",
    tags: list[str] | None = None,
    ttl_ms: int = 0,
) -> bool:
    """Inject any image file (PNG, JPEG, BMP, etc.) into the visual surface."""
    try:
        from PIL import Image

        img = Image.open(image_path).convert("RGBA")
        return inject_rgba(
            source_id,
            img.tobytes("raw", "RGBA"),
            img.width,
            img.height,
            opacity=opacity,
            z_order=z_order,
            blend_mode=blend_mode,
            tags=tags,
            ttl_ms=ttl_ms,
        )
    except Exception:
        log.debug("Failed to inject image %s from %s", source_id, image_path, exc_info=True)
        return False


def inject_jpeg(
    source_id: str,
    jpeg_path: Path,
    opacity: float = 0.6,
    z_order: int = 10,
    blend_mode: str = "screen",
    tags: list[str] | None = None,
    ttl_ms: int = 0,
) -> bool:
    """Inject a JPEG file into the visual surface."""
    return inject_image(source_id, jpeg_path, opacity, z_order, blend_mode, tags, ttl_ms)


def inject_text(
    source_id: str,
    text: str,
    opacity: float = 0.5,
    z_order: int = 20,
    width: int = 640,
    height: int = 360,
    tags: list[str] | None = None,
    ttl_ms: int = 0,
) -> bool:
    """Inject rendered text into the visual surface."""
    try:
        from agents.imagination_source_protocol import _render_text_to_rgba

        rgba, w, h = _render_text_to_rgba(text, width, height)
        return inject_rgba(
            source_id,
            rgba,
            w,
            h,
            opacity=opacity,
            z_order=z_order,
            tags=tags,
            ttl_ms=ttl_ms,
        )
    except Exception:
        log.debug("Failed to inject text %s", source_id, exc_info=True)
        return False


def inject_rgba(
    source_id: str,
    rgba_data: bytes,
    width: int,
    height: int,
    opacity: float = 0.6,
    z_order: int = 10,
    blend_mode: str = "screen",
    tags: list[str] | None = None,
    ttl_ms: int = 0,
) -> bool:
    """Inject raw RGBA bytes into the visual surface. Lowest-level API."""
    source_dir = SOURCES_DIR / source_id
    source_dir.mkdir(parents=True, exist_ok=True)

    try:
        tmp_frame = source_dir / "frame.tmp"
        tmp_frame.write_bytes(rgba_data)
        tmp_frame.rename(source_dir / "frame.rgba")

        manifest = {
            "source_id": source_id,
            "content_type": "rgba",
            "width": width,
            "height": height,
            "opacity": opacity,
            "layer": 1,
            "blend_mode": blend_mode,
            "z_order": z_order,
            "ttl_ms": max(0, int(ttl_ms)),
            "tags": tags or [],
        }

        tmp = source_dir / "manifest.tmp"
        tmp.write_text(json.dumps(manifest))
        tmp.rename(source_dir / "manifest.json")
        return True
    except Exception:
        log.debug("Failed to inject rgba %s", source_id, exc_info=True)
        return False


def inject_url(
    source_id: str,
    url: str,
    opacity: float = 0.6,
    z_order: int = 10,
    tags: list[str] | None = None,
    ttl_ms: int = 0,
) -> bool:
    """Fetch content from a URL and inject into the visual surface.

    Tries image first. If not an image (HTML, text, JSON), extracts
    text content and renders it visually.
    """
    try:
        import io

        import httpx

        resp = httpx.get(url, timeout=10, follow_redirects=True)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")

        if "image" in content_type:
            from PIL import Image

            img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
            return inject_rgba(
                source_id,
                img.tobytes("raw", "RGBA"),
                img.width,
                img.height,
                opacity=opacity,
                z_order=z_order,
                tags=tags or ["web", "image"],
                ttl_ms=ttl_ms,
            )

        # Non-image: extract text and render
        text = _extract_web_text(resp.text, content_type)
        if text:
            return inject_text(
                source_id,
                text[:500],
                opacity=opacity,
                z_order=z_order,
                tags=tags or ["web", "text"],
                ttl_ms=ttl_ms,
            )
        return False
    except Exception:
        log.debug("Failed to inject URL %s from %s", source_id, url, exc_info=True)
        return False


def inject_search(
    source_id: str,
    query: str,
    opacity: float = 0.5,
    z_order: int = 15,
    tags: list[str] | None = None,
) -> bool:
    """Inject web search results as rendered text on the visual surface."""
    try:
        import httpx

        resp = httpx.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": "1"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        abstract = data.get("AbstractText", "")
        if not abstract:
            results = data.get("RelatedTopics", [])
            lines = [r.get("Text", "")[:100] for r in results[:5] if isinstance(r, dict)]
            abstract = "\n".join(lines) if lines else f"No results for: {query}"
        return inject_text(
            source_id,
            abstract[:500],
            opacity=opacity,
            z_order=z_order,
            tags=tags or ["web", "search"],
        )
    except Exception:
        log.debug("Failed to inject search %s for %s", source_id, query, exc_info=True)
        return False


def _extract_web_text(html: str, content_type: str) -> str:
    """Extract readable text from web content."""
    if "json" in content_type:
        import json as json_mod

        try:
            data = json_mod.loads(html)
            return json_mod.dumps(data, indent=2)[:500]
        except Exception:
            return html[:500]

    if "html" in content_type:
        import re

        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:500]

    return html[:500]


def remove_source(source_id: str) -> None:
    """Remove a source from the visual surface."""
    import shutil

    source_dir = SOURCES_DIR / source_id
    if source_dir.exists():
        shutil.rmtree(source_dir, ignore_errors=True)
