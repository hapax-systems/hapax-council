"""shared/context_compression.py — TOON + LLMLingua-2 compression primitives.

Two orthogonal compression layers for LLM context:
- to_toon(): structured data → TOON format (lossless, 40-60% token savings)
- compress_history(): conversation history → compressed (lossy, ~3x savings)
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

log = logging.getLogger(__name__)

# Lazy-loaded LLMLingua compressor singleton
_compressor = None
_compressor_load_attempted = False


def to_toon(data: dict | BaseModel | list) -> str:
    """Serialize structured data to TOON format for LLM context injection.

    Accepts dicts, Pydantic models, or lists. Returns a compact TOON string
    that uses ~40-60% fewer tokens than equivalent JSON.
    """
    import toon

    if isinstance(data, BaseModel):
        data = data.model_dump()
    return toon.encode(data)


def _get_compressor():
    """Lazy-load the LLMLingua-2 compressor. Returns None if unavailable."""
    global _compressor, _compressor_load_attempted
    if _compressor_load_attempted:
        return _compressor
    _compressor_load_attempted = True
    try:
        from llmlingua import PromptCompressor

        _compressor = PromptCompressor(
            model_name="microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank",
            use_llmlingua2=True,
            device_map="cpu",
        )
        log.info("LLMLingua-2 compressor loaded (BERT-base, CPU)")
    except Exception:
        log.warning("LLMLingua-2 unavailable — history compression disabled", exc_info=True)
    return _compressor


def compress_history(
    messages: list[dict],
    keep_recent: int = 5,
    rate: float = 0.33,
) -> list[dict]:
    """Compress older conversation turns using LLMLingua-2.

    Keeps system message + most recent `keep_recent` turns verbatim.
    Compresses earlier turns at the given rate (~3x at 0.33).

    Returns the original messages unchanged if compression is unavailable
    or there aren't enough messages to warrant compression.
    """
    if len(messages) <= keep_recent + 1:
        return messages

    compressor = _get_compressor()
    if compressor is None:
        return messages

    # Split: system message (index 0) + compressible + recent
    system_msg = messages[0] if messages and messages[0].get("role") == "system" else None
    start = 1 if system_msg else 0
    split_idx = len(messages) - keep_recent

    if split_idx <= start:
        return messages

    old_messages = messages[start:split_idx]
    recent = messages[split_idx:]

    # Build text block from old messages for compression
    lines: list[str] = []
    for msg in old_messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if content:
            lines.append(f"[{role}] {content}")

    if not lines:
        return messages

    text_block = "\n".join(lines)

    try:
        result = compressor.compress_prompt_llmlingua2(
            [text_block],
            rate=rate,
            force_tokens=["\n", "[", "]"],
        )
        compressed_text = result.get("compressed_prompt", text_block)

        # Reconstruct as a single summary message
        compressed_msg = {
            "role": "user",
            "content": f"[Earlier conversation, compressed]\n{compressed_text}",
        }

        result_messages: list[dict] = []
        if system_msg:
            result_messages.append(system_msg)
        result_messages.append(compressed_msg)
        result_messages.extend(recent)
        return result_messages
    except Exception:
        log.warning("LLMLingua-2 compression failed, keeping original messages", exc_info=True)
        return messages
