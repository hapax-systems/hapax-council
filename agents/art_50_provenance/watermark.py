"""Visible disclosure watermarking for the image-only MVP."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

from agents.art_50_provenance.models import WatermarkRecord


def _output_format_for_mime(mime_type: str, source_format: str | None) -> str:
    if mime_type == "image/jpeg":
        return "JPEG"
    if mime_type == "image/webp":
        return "WEBP"
    if mime_type == "image/tiff":
        return "TIFF"
    return source_format or "PNG"


def apply_visible_watermark(
    image_bytes: bytes,
    *,
    credential_id: str,
    disclosure_text: str,
    mime_type: str,
) -> tuple[bytes, WatermarkRecord]:
    """Draw a visible Article 50 disclosure label into image bytes."""

    with Image.open(BytesIO(image_bytes)) as opened:
        output_format = _output_format_for_mime(mime_type, opened.format)
        base = opened.convert("RGBA")

    draw = ImageDraw.Draw(base)
    font = ImageFont.load_default()
    label = f"{disclosure_text} | {credential_id}"
    bbox = draw.textbbox((0, 0), label, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    pad = 8
    margin = 10
    x = max(margin, base.width - text_w - (pad * 2) - margin)
    y = max(margin, base.height - text_h - (pad * 2) - margin)
    rect = (x, y, min(base.width - margin, x + text_w + (pad * 2)), y + text_h + (pad * 2))
    draw.rounded_rectangle(rect, radius=4, fill=(0, 0, 0, 190), outline=(255, 255, 255, 220))
    draw.text((x + pad, y + pad), label, fill=(255, 255, 255, 255), font=font)

    out = BytesIO()
    if output_format == "PNG":
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("Art50CredentialId", credential_id)
        metadata.add_text("Art50Disclosure", disclosure_text)
        base.save(out, format="PNG", pnginfo=metadata)
    elif output_format == "JPEG":
        base.convert("RGB").save(out, format="JPEG", quality=95)
    elif output_format == "WEBP":
        base.save(out, format="WEBP", quality=95)
    elif output_format == "TIFF":
        base.save(out, format="TIFF")
    else:
        base.save(out, format=output_format)
    payload = out.getvalue()
    return (
        payload,
        WatermarkRecord(
            credential_id=credential_id,
            disclosure_text=disclosure_text,
            method="visible-bottom-right-label",
            position="bottom-right",
            output_format=output_format,
            byte_length=len(payload),
        ),
    )


__all__ = ["apply_visible_watermark"]
