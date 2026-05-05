"""Image fingerprinting for the Article 50 image MVP."""

from __future__ import annotations

import hashlib
from io import BytesIO
from typing import Any

from PIL import Image

from agents.art_50_provenance.models import FingerprintBundle


class PdqUnavailable(RuntimeError):
    """Raised when a caller requires native PDQ but the runtime lacks it."""


def _hex_from_bits(bits: Any) -> str:
    flat = [bool(value) for value in bits]
    value = 0
    for bit in flat:
        value = (value << 1) | int(bit)
    return f"{value:0{len(flat) // 4}x}"


def _phash_hex(image: Image.Image) -> str:
    import imagehash

    return str(imagehash.phash(image.convert("RGB")))


def _native_pdq_hex(image: Image.Image) -> str | None:
    """Best-effort native PDQ hook.

    The Python PDQ package is not a hard dependency of this repo. If a production
    runtime installs a compatible module, this hook accepts the common
    ``compute``/``hash`` return shapes and normalizes them to a 256-bit hex
    string. Unknown shapes return ``None`` so callers can either fall back or
    fail closed.
    """

    try:
        import numpy as np
        import pdqhash  # type: ignore[import-not-found]
    except Exception:
        return None

    arr = np.asarray(image.convert("RGB"))
    compute = getattr(pdqhash, "compute", None) or getattr(pdqhash, "hash", None)
    if compute is None:
        return None
    result = compute(arr)
    if isinstance(result, tuple):
        result = result[0]
    if isinstance(result, str):
        cleaned = result.lower().removeprefix("0x")
        return cleaned if len(cleaned) == 64 else None
    if isinstance(result, int):
        return f"{result:064x}"
    try:
        return _hex_from_bits(result)
    except TypeError:
        return None


def _fallback_pdq_dct_hex(image: Image.Image) -> str:
    """Return a deterministic 256-bit DCT perceptual hash.

    This is not represented as native PDQ. It exists to keep dry-run packets
    testable while preserving an explicit ``pdq_status=fallback`` marker until a
    production lane adds the native PDQ dependency.
    """

    import cv2
    import numpy as np

    gray = image.convert("L").resize((64, 64), Image.Resampling.LANCZOS)
    arr = np.asarray(gray, dtype=np.float32)
    dct = cv2.dct(arr)
    block = dct[:16, :16].reshape(-1)
    median = float(np.median(block[1:]))
    return _hex_from_bits(block > median)


def compute_image_fingerprints(
    image_bytes: bytes,
    *,
    mime_type: str,
    require_native_pdq: bool = False,
) -> FingerprintBundle:
    """Compute cryptographic and perceptual fingerprints for image bytes."""

    sha256 = hashlib.sha256(image_bytes).hexdigest()
    with Image.open(BytesIO(image_bytes)) as opened:
        image = opened.convert("RGB")
        width, height = image.size
        phash = _phash_hex(image)
        native_pdq = _native_pdq_hex(image)
        if native_pdq is not None:
            pdq = native_pdq
            pdq_status = "native"
            pdq_algorithm = "pdq"
        elif require_native_pdq:
            raise PdqUnavailable("native PDQ package is required but not installed")
        else:
            pdq = _fallback_pdq_dct_hex(image)
            pdq_status = "fallback"
            pdq_algorithm = "org.hapax.pdq-dct-v0"

    return FingerprintBundle(
        mime_type=mime_type,
        width=width,
        height=height,
        sha256=sha256,
        phash=phash,
        pdq=pdq,
        pdq_status=pdq_status,
        pdq_algorithm=pdq_algorithm,
    )


def phash_distance(left_hex: str, right_hex: str) -> int:
    """Hamming distance between two 64-bit imagehash pHash strings."""

    return (int(left_hex, 16) ^ int(right_hex, 16)).bit_count()


__all__ = [
    "PdqUnavailable",
    "compute_image_fingerprints",
    "phash_distance",
]
