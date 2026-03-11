"""VRAM management for GPU-intensive pipeline stages."""
from __future__ import annotations

import logging
import subprocess
import time

import httpx

log = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434"
TTS_VRAM_MB = 8000


def get_vram_free_mb() -> int:
    """Get free GPU VRAM in MB via nvidia-smi."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return int(result.stdout.strip().split("\n")[0])
    except (FileNotFoundError, ValueError, subprocess.TimeoutExpired):
        pass
    return 0


def unload_ollama_models() -> list[str]:
    """Unload all Ollama models from GPU. Returns list of unloaded model names."""
    unloaded: list[str] = []
    try:
        response = httpx.get(f"{OLLAMA_URL}/api/ps", timeout=5)
        models = response.json().get("models", [])
        for model in models:
            name = model["name"]
            log.info("Unloading Ollama model: %s", name)
            httpx.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": name, "keep_alive": 0},
                timeout=10,
            )
            unloaded.append(name)
    except httpx.HTTPError as e:
        log.warning("Could not reach Ollama to unload models: %s", e)
    return unloaded


def ensure_vram_available(required_mb: int = TTS_VRAM_MB, timeout: int = 30) -> None:
    """Ensure enough VRAM is free, unloading Ollama models if necessary."""
    free = get_vram_free_mb()
    if free >= required_mb:
        log.info("VRAM OK: %d MB free (need %d MB)", free, required_mb)
        return

    log.info("VRAM low: %d MB free, need %d MB. Unloading Ollama models...", free, required_mb)
    unloaded = unload_ollama_models()

    if not unloaded:
        log.warning("No Ollama models to unload. VRAM may be insufficient.")
        return

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        free = get_vram_free_mb()
        if free >= required_mb:
            log.info("VRAM freed: %d MB available", free)
            return
        time.sleep(1)

    free = get_vram_free_mb()
    if free < required_mb:
        log.warning(
            "VRAM still low after unload: %d MB free (need %d MB). "
            "TTS may fail or be slow.",
            free, required_mb,
        )
