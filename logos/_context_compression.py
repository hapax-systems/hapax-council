"""logos/_context_compression.py — Re-export shim for shared.context_compression."""

from shared.context_compression import (  # noqa: F401
    FORCE_TOKENS_DEFAULT,
    FORCE_TOKENS_RETRIEVAL,
    FORCE_TOKENS_VOICE,
    _get_compressor,
    compress_history,
    compressor_available,
    to_toon,
)
