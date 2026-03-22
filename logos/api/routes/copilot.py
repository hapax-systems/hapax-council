"""Copilot observation endpoint — context-aware message from CopilotEngine."""

from __future__ import annotations

from datetime import UTC

from fastapi import APIRouter

from logos.api.cache import cache
from logos.copilot import CopilotContext, CopilotEngine

router = APIRouter(prefix="/api", tags=["copilot"])

_engine = CopilotEngine()


@router.get("/copilot")
async def get_copilot_observation():
    """Get the current copilot observation based on system state."""
    ctx = CopilotContext()

    # Populate from cache
    if cache.health:
        ctx.health_status = cache.health.overall_status
        ctx.healthy_count = cache.health.healthy
        ctx.total_checks = cache.health.total_checks
        ctx.failed_checks = [c for c in cache.health.failed_checks]

    if cache.gpu:
        ctx.vram_pct = cache.gpu.usage_pct
        ctx.loaded_model = cache.gpu.loaded_models[0] if cache.gpu.loaded_models else ""

    if cache.briefing:
        from datetime import datetime

        try:
            gen = datetime.fromisoformat(cache.briefing.generated_at)
            now = datetime.now(UTC)
            ctx.briefing_age_h = (now - gen).total_seconds() / 3600
        except (ValueError, TypeError):
            pass
        ctx.action_item_count = len(getattr(cache.briefing, "action_items", []))

    if cache.drift:
        ctx.drift_count = (
            cache.drift.total_items
            if hasattr(cache.drift, "total_items")
            else len(getattr(cache.drift, "items", []))
        )

    if cache.readiness:
        ctx.readiness_level = cache.readiness.level
        ctx.readiness_top_gap = cache.readiness.top_gap
        ctx.readiness_gaps = cache.readiness.gaps
        ctx.interview_conducted = cache.readiness.interview_conducted

    if cache.accommodations:
        ctx.accommodations = cache.accommodations

    message = _engine.evaluate(ctx)
    return {"message": message}
