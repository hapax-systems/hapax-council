from __future__ import annotations

from typing import Any


def litellm_no_fallback_model_settings() -> dict[str, Any]:
    return {"extra_body": {"disable_fallbacks": True}}
