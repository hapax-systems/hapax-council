"""Legacy import aliases for the Pi edge platter detector."""

from __future__ import annotations

import sys
from pathlib import Path

_MODULE_DIR = Path(__file__).resolve().parent
if str(_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_MODULE_DIR))

from ir_platter import (  # noqa: E402
    PlatterObject,
    detect_album_cover,
    detect_platter_objects,
    extract_album_crop,
    extract_platter_crop,
    platter_objects_payload,
)

__all__ = [
    "PlatterObject",
    "detect_album_cover",
    "detect_platter_objects",
    "extract_album_crop",
    "extract_platter_crop",
    "platter_objects_payload",
]
