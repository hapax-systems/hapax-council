"""jr-gemini-3-flash-vision-router-update — vision-fast route + media_resolution.

cc-task `jr-gemini-3-flash-vision-router-update`. Per-tick DMN vision should
route through Gemini 3 Flash with `media_resolution="low"` (280 tokens, ~
$0.00014/frame) for the price-performance leader on 10fps vision.

Pinned invariants:
  * `MODELS["vision-fast"]` resolves to `gemini-3-flash-preview`.
  * The DMN multimodal call site uses `model=MODELS["vision-fast"]`.
  * The DMN multimodal call site passes BOTH `budget_tokens: 0` AND
    `media_resolution: "low"` in `extra_body`. Removing either breaks the
    cost-efficient vision contract.
"""

from __future__ import annotations

import inspect

from shared.config import MODELS


def test_vision_fast_alias_resolves_to_gemini_3_flash_preview() -> None:
    """Pin: the vision route lives on Gemini 3 Flash preview, not the
    older Gemini Flash 2.5. Vendor migration must update this constant."""
    assert MODELS["vision-fast"] == "gemini-3-flash-preview"


def test_dmn_multimodal_call_uses_vision_fast_route() -> None:
    """The DMN per-tick vision call site must read its model from
    `MODELS["vision-fast"]` so a single config change retargets all
    vision callers (no scattered hardcoded model strings)."""
    from agents.dmn import ollama as ollama_mod

    src = inspect.getsource(ollama_mod._gemini_multimodal)
    # Resolution via MODELS lookup, not hardcoded string.
    assert 'MODELS["vision-fast"]' in src, (
        "DMN _gemini_multimodal must read its vision model from "
        'MODELS["vision-fast"] so the route is configurable in one place.'
    )


def test_dmn_multimodal_call_passes_media_resolution_low() -> None:
    """Pin both invariants of cost-efficient Gemini vision:
    `budget_tokens: 0` (existing) AND `media_resolution: "low"` (new
    cc-task contract)."""
    from agents.dmn import ollama as ollama_mod

    src = inspect.getsource(ollama_mod._gemini_multimodal)
    assert '"media_resolution": "low"' in src, (
        "DMN _gemini_multimodal must pass media_resolution=low to land in "
        "the 280-token Gemini 3 Flash low-res mode (~$0.00014/frame). "
        "Without this the call uses high-res defaults at 5x the cost."
    )
    # The existing budget_tokens=0 invariant must remain (Gemini Flash
    # 2.5+ requires it for vision; otherwise reasoning tokens starve
    # the completion budget).
    assert "budget_tokens" in src
    assert '"type": "disabled"' in src
