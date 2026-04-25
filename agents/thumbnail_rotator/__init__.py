"""YouTube thumbnail rotator (ytb-003).

Periodically captures the current compositor output snapshot, scales
it to YouTube's recommended 1280x720, and uploads via the YouTube Data
API ``thumbnails.set`` endpoint. The face-obscure pipeline (#129)
already pixelates every camera frame before it reaches the snapshot
tap, so this thumbnail path is privacy-safe by construction.

Public surface lives in :mod:`agents.thumbnail_rotator.rotator`.
"""

from agents.thumbnail_rotator.rotator import (
    ThumbnailRotator,
    prepare_thumbnail_jpeg,
)
from agents.thumbnail_rotator.salience_trigger import SalienceTrigger

__all__ = ["SalienceTrigger", "ThumbnailRotator", "prepare_thumbnail_jpeg"]
