"""Re-export from hapax-demo package for backwards compatibility."""

from demo.pipeline.vram import *  # noqa: F401, F403
from demo.pipeline.vram import (  # noqa: F401
    ensure_vram_available,
    get_vram_free_mb,
    unload_ollama_models,
)
