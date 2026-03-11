"""Illustration generation pipeline using Gemini image generation API."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import yaml

from agents.demo_models import IllustrationSpec

log = logging.getLogger(__name__)

PERSONAS_PATH = Path(__file__).resolve().parent.parent.parent / "profiles" / "demo-personas.yaml"


def load_illustration_style(audience: str) -> str:
    """Load illustration_style from persona YAML for the given audience."""
    try:
        data = yaml.safe_load(PERSONAS_PATH.read_text())
        archetypes = data.get("archetypes", {})
        persona = archetypes.get(audience, {})
        return persona.get("illustration_style", "")
    except Exception:
        return ""


def _build_prompt(spec: IllustrationSpec) -> str:
    """Combine illustration prompt with style keywords."""
    parts = []
    if spec.style:
        parts.append(f"Style: {spec.style}.")
    parts.append(spec.prompt)
    if spec.negative_prompt:
        parts.append(f"Do NOT include: {spec.negative_prompt}")
    return " ".join(parts)


async def _generate_single(
    spec: IllustrationSpec,
    output_path: Path,
) -> Path | None:
    """Generate a single illustration via Gemini API.

    Returns the saved image path, or None on failure.
    """
    try:
        from google import genai

        client = genai.Client()

        prompt = _build_prompt(spec)
        log.info("Generating illustration: %s", prompt[:80])

        response = client.models.generate_images(
            model="imagen-3.0-generate-002",
            prompt=prompt,
            config=genai.types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio=spec.aspect_ratio,
            ),
        )

        if not response.generated_images:
            log.warning("No images returned for prompt: %s", prompt[:60])
            return None

        image = response.generated_images[0]
        image_bytes = image.image.image_bytes
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(image_bytes)
        log.info("Saved illustration: %s (%.1f KB)", output_path.name, len(image_bytes) / 1024)
        return output_path

    except Exception as e:
        log.error("Illustration generation failed: %s", e)
        return None


async def generate_illustrations(
    specs: list[tuple[str, IllustrationSpec]],
    output_dir: Path,
    on_progress: Callable[[str], None] | None = None,
) -> list[Path | None]:
    """Generate illustrations for each spec.

    Returns list of saved PNG paths (or None for failed generations).
    Caller should fall back to title-card for None entries.
    """
    if not specs:
        return []

    progress = on_progress or (lambda _: None)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path | None] = []

    for i, (name, spec) in enumerate(specs, 1):
        progress(f"Generating illustration {i}/{len(specs)}: {name}")
        output_path = output_dir / f"{name}.png"
        path = await _generate_single(spec, output_path)
        paths.append(path)

    generated = sum(1 for p in paths if p is not None)
    progress(f"Generated {generated}/{len(specs)} illustrations")
    return paths
