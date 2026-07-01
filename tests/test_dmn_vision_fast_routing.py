"""jr-gemini-3-flash-vision-router-update — vision-fast route + media_resolution.

cc-task `jr-gemini-3-flash-vision-router-update`. Per-tick DMN vision should
route through Gemini 3 Flash with `media_resolution="low"` (280 tokens, ~
$0.00014/frame) for the price-performance leader on 10fps vision.

Pinned invariants:
  * `MODELS["vision-fast"]` resolves to `gemini-flash` (LiteLLM route name).
  * The DMN multimodal call site uses `model=MODELS["vision-fast"]`.
  * The DMN multimodal call site passes BOTH `budget_tokens: 0` AND
    `media_resolution: "low"` in `extra_body`. Removing either breaks the
    cost-efficient vision contract.
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, patch

import pytest

from shared.config import MODELS
from shared.fix_capabilities.background_admission import BackgroundCapabilityAdmission


def test_vision_fast_alias_resolves_to_gemini_flash() -> None:
    """Pin: vision-fast uses the gemini-flash LiteLLM route (which maps
    to gemini-3-flash-preview under the hood)."""
    assert MODELS["vision-fast"] == "gemini-flash"


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


@pytest.mark.asyncio
async def test_dmn_multimodal_refuses_provider_without_admission() -> None:
    """DMN vision spend must be admitted before constructing a provider client."""
    from agents.dmn import ollama as ollama_mod

    denied = BackgroundCapabilityAdmission(
        capability_name="dmn.multimodal_vision.llm",
        route_id="api.headless.provider_gateway",
        model_alias="gemini-flash",
        admitted=False,
        denied_reason="provider_model_descriptor_mismatch",
        reason_codes=("provider_model_descriptor_mismatch",),
        mutation_surface="provider_spend",
        quality_floor="frontier_required",
    )
    with (
        patch("agents.dmn.ollama.admit_background_capability", return_value=denied),
        patch(
            "agents.dmn.ollama._tabby_think", new_callable=AsyncMock, return_value="fallback"
        ) as mock_fallback,
        patch("openai.AsyncOpenAI") as mock_client_cls,
    ):
        result = await ollama_mod._gemini_multimodal("prompt", "system", "ZmFrZQ==")

    assert result == "fallback"
    mock_fallback.assert_awaited_once_with("prompt", "system")
    mock_client_cls.assert_not_called()
