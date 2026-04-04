"""Vision observer — standalone visual surface description sensor.

Reads the rendered frame from hapax-imagination, calls gemini-flash
to produce a one-sentence description, writes to SHM. Any consumer
(DMN reverberation, VLA, etc.) reads the output file.

Usage:
    uv run python -m agents.vision_observer
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger("vision_observer")

FRAME_PATH = Path("/dev/shm/hapax-visual/frame.jpg")
IMAGINATION_PATH = Path("/dev/shm/hapax-dmn/imagination-current.json")
OUTPUT_DIR = Path("/dev/shm/hapax-vision")

SYSTEM_PROMPT = (
    "You are observing a visual display surface. Describe what you see "
    "in one concrete sentence: colors, shapes, motion, text fragments, "
    "spatial arrangement. Do not evaluate quality. Do not describe system "
    "health. Only describe visual appearance."
)


async def _call_vision_model(frame_b64: str, narrative: str) -> str:
    """Call gemini-flash via LiteLLM to describe the visual surface."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        base_url="http://localhost:4000",
        api_key=os.environ.get("LITELLM_API_KEY", "sk-dummy"),
    )
    user_content: list[dict] = [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{frame_b64}"}},
    ]
    if narrative:
        user_content.append({"type": "text", "text": f"The system intended to show: {narrative}"})
    resp = await client.chat.completions.create(
        model="gemini-flash",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.1,
        max_tokens=150,
        extra_body={"thinking": {"type": "disabled", "budget_tokens": 0}},
    )
    return resp.choices[0].message.content.strip()


async def observe(
    frame_path: Path = FRAME_PATH,
    imagination_path: Path = IMAGINATION_PATH,
    output_dir: Path = OUTPUT_DIR,
) -> None:
    """One observation cycle: read frame, call LLM, write result."""
    if not frame_path.exists():
        log.debug("No frame at %s, skipping", frame_path)
        return

    try:
        frame_b64 = base64.b64encode(frame_path.read_bytes()).decode()
    except OSError:
        log.debug("Failed to read frame", exc_info=True)
        return

    narrative = ""
    try:
        if imagination_path.exists():
            data = json.loads(imagination_path.read_text(encoding="utf-8"))
            narrative = data.get("narrative", "")
    except (OSError, json.JSONDecodeError):
        pass

    try:
        result = await _call_vision_model(frame_b64, narrative)
    except Exception:
        log.warning("Vision model call failed", exc_info=True)
        return

    if not result:
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    obs_path = output_dir / "observation.txt"
    status_path = output_dir / "status.json"

    try:
        tmp = obs_path.with_suffix(".tmp")
        tmp.write_text(result, encoding="utf-8")
        tmp.rename(obs_path)

        status = {"timestamp": time.time(), "length": len(result)}
        tmp_s = status_path.with_suffix(".tmp")
        tmp_s.write_text(json.dumps(status), encoding="utf-8")
        tmp_s.rename(status_path)
        log.info("Observation written (%d chars)", len(result))
    except OSError:
        log.warning("Failed to write observation", exc_info=True)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(observe())
