"""agents/_clap.py — Shim for shared.clap.

Re-exports CLAP audio-text embedding API during shared/ dissolution.
Will be replaced with vendored code when shared/ is deleted (phase 3.8).
"""

from shared.clap import (  # noqa: F401
    CLAP_EMBED_DIM,
    CLAP_SAMPLE_RATE,
    classify_zero_shot,
    embed_audio,
    embed_text,
    unload_model,
)
