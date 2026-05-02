"""WCS-gated temporal prompt blocks.

Temporal prompt text is useful orientation for LLMs, but it must not become
unverified temporal authority. This module renders prompt blocks only from
``WorldSurfaceHealthRecord`` rows produced by the temporal/perceptual WCS
health adapter. Raw temporal XML or prose can be evidence behind a WCS row; it
is not injected directly here.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from shared.world_surface_health import (
    FreshnessState,
    HealthStatus,
    SurfaceFamily,
    WorldSurfaceHealthRecord,
)
from shared.world_surface_temporal_perceptual_health import (
    project_temporal_perceptual_health_records,
)

TEMPORAL_PROMPT_BLOCK_HEADER = "## Temporal/Perceptual WCS Prompt Gate"
TEMPORAL_PROMPT_AUTHORITY_FENCE = (
    "Orientation only: static temporal hints do not authorize current, public, live, "
    "available, or grounded state. Use WCS claim gates before making claims."
)

_CLAIM_AUTHORITY_DENIAL: Literal[False] = False
_TEMPORAL_BAND_PREFIX = "temporal_band:"
_OBSERVATION_CATEGORY_PREFIX = "observation_category:"
_FALSE_GROUNDING_PREFIX = "false_grounding_risk:"
_UNSET = "unset"


class TemporalPromptState(StrEnum):
    """Prompt-row state after WCS health gating."""

    ORIENTING = "orienting"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class TemporalPromptRow:
    """One WCS health row rendered into the temporal prompt block."""

    surface_id: str
    observation_category: str
    temporal_band: str
    prompt_state: TemporalPromptState
    status: str
    freshness: str
    checked_at: str
    ttl_s: int | None
    authority_ceiling: str
    evidence_refs: tuple[str, ...]
    blocker_reason: str
    source_ref: str
    authorizes_current_public_live_available_grounded: Literal[False] = _CLAIM_AUTHORITY_DENIAL


@dataclass(frozen=True, slots=True)
class TemporalPromptBlock:
    """Rendered prompt-gate read model for temporal/perceptual WCS rows."""

    block_state: TemporalPromptState
    rows: tuple[TemporalPromptRow, ...]
    blocker_reasons: tuple[str, ...]
    authorizes_current_public_live_available_grounded: Literal[False] = _CLAIM_AUTHORITY_DENIAL


def load_default_temporal_prompt_records() -> list[WorldSurfaceHealthRecord]:
    """Load temporal/perceptual WCS health rows for prompt rendering."""

    return project_temporal_perceptual_health_records()


def build_temporal_prompt_block(
    records: Iterable[WorldSurfaceHealthRecord],
) -> TemporalPromptBlock:
    """Project WCS temporal/perceptual rows into a prompt-safe read model."""

    prompt_rows = tuple(
        _prompt_row(record) for record in records if _is_temporal_perceptual_prompt_record(record)
    )
    if not prompt_rows:
        return TemporalPromptBlock(
            block_state=TemporalPromptState.BLOCKED,
            rows=(),
            blocker_reasons=("temporal_perceptual_wcs_rows_missing",),
        )

    blockers = tuple(
        dict.fromkeys(
            reason for row in prompt_rows for reason in _row_blocker_reasons(row) if reason
        )
    )
    return TemporalPromptBlock(
        block_state=_block_state(prompt_rows),
        rows=prompt_rows,
        blocker_reasons=blockers,
    )


def render_temporal_prompt_block(records: Iterable[WorldSurfaceHealthRecord]) -> str:
    """Render a WCS-gated temporal prompt block.

    The block may orient a model, or it may tell the model that temporal state
    is blocked/degraded. It never grants public/current/live/action/grounded
    authority.
    """

    return render_temporal_prompt_read_model(build_temporal_prompt_block(records))


def render_director_temporal_prompt_block(
    records: Iterable[WorldSurfaceHealthRecord],
) -> str:
    """Render the director-facing temporal block from WCS rows only."""

    return render_temporal_prompt_block(records)


def render_temporal_prompt_read_model(block: TemporalPromptBlock) -> str:
    """Render an already-built temporal prompt read model."""

    lines = [
        TEMPORAL_PROMPT_BLOCK_HEADER,
        TEMPORAL_PROMPT_AUTHORITY_FENCE,
        f"block_state: {block.block_state.value}",
        "authorizes_current_public_live_available_grounded: false",
    ]
    if block.blocker_reasons:
        lines.append("blocker_reasons: " + ", ".join(block.blocker_reasons))

    if not block.rows:
        lines.append("- state=blocked temporal_band=unknown category=temporal_band")
        lines.append(
            "  checked_at=unknown ttl_s=unknown authority_ceiling=no_claim "
            "evidence_refs=none blocker_reason=temporal_perceptual_wcs_rows_missing"
        )
        return "\n".join(lines)

    lines.append("rows:")
    for row in block.rows:
        ttl = str(row.ttl_s) if row.ttl_s is not None else "unknown"
        evidence = ", ".join(row.evidence_refs) if row.evidence_refs else "none"
        lines.append(
            f"- state={row.prompt_state.value} temporal_band={row.temporal_band} "
            f"category={row.observation_category} surface={row.surface_id}"
        )
        lines.append(
            f"  checked_at={row.checked_at} ttl_s={ttl} freshness={row.freshness} "
            f"status={row.status} authority_ceiling={row.authority_ceiling}"
        )
        lines.append(f"  evidence_refs={evidence}")
        lines.append(f"  source_ref={row.source_ref}")
        lines.append(
            "  authorizes_current_public_live_available_grounded=false "
            f"blocker_reason={row.blocker_reason}"
        )
    return "\n".join(lines)


def render_default_temporal_prompt_block() -> str:
    """Render the default temporal prompt block from WCS health rows."""

    return render_temporal_prompt_block(load_default_temporal_prompt_records())


def render_default_director_temporal_prompt_block() -> str:
    """Render the default director temporal block from WCS rows only."""

    return render_director_temporal_prompt_block(load_default_temporal_prompt_records())


def _is_temporal_perceptual_prompt_record(record: WorldSurfaceHealthRecord) -> bool:
    if record.surface_family is not SurfaceFamily.PERCEPTION_OBSERVATION:
        return False
    return any(ref.startswith(_TEMPORAL_BAND_PREFIX) for ref in record.capability_refs)


def _prompt_row(record: WorldSurfaceHealthRecord) -> TemporalPromptRow:
    return TemporalPromptRow(
        surface_id=record.surface_id,
        observation_category=_capability_suffix(
            record.capability_refs, _OBSERVATION_CATEGORY_PREFIX
        ),
        temporal_band=_capability_suffix(record.capability_refs, _TEMPORAL_BAND_PREFIX),
        prompt_state=_row_state(record),
        status=record.status.value,
        freshness=record.freshness.state.value,
        checked_at=record.checked_at,
        ttl_s=record.freshness.ttl_s,
        authority_ceiling=record.authority_ceiling.value,
        evidence_refs=tuple(record.evidence_envelope_refs),
        blocker_reason=_blocker_reason(record),
        source_ref=record.freshness.source_ref or _UNSET,
    )


def _row_state(record: WorldSurfaceHealthRecord) -> TemporalPromptState:
    if record.freshness.state is not FreshnessState.FRESH:
        return TemporalPromptState.BLOCKED
    if record.status is HealthStatus.HEALTHY:
        return TemporalPromptState.ORIENTING
    if record.status is HealthStatus.DEGRADED:
        return TemporalPromptState.DEGRADED
    return TemporalPromptState.BLOCKED


def _block_state(rows: tuple[TemporalPromptRow, ...]) -> TemporalPromptState:
    if any(row.prompt_state is TemporalPromptState.BLOCKED for row in rows):
        return TemporalPromptState.BLOCKED
    if any(row.prompt_state is TemporalPromptState.DEGRADED for row in rows):
        return TemporalPromptState.DEGRADED
    return TemporalPromptState.ORIENTING


def _blocker_reason(record: WorldSurfaceHealthRecord) -> str:
    reasons = list(record.blocking_reasons)
    if record.freshness.state is not FreshnessState.FRESH:
        reasons.append(f"freshness:{record.freshness.state.value}")
    if record.status is not HealthStatus.HEALTHY:
        reasons.append(f"status:{record.status.value}")
    if record.public_claim_allowed:
        reasons.append("unexpected_public_claim_allowed")
    if record.claimable_health:
        reasons.append("unexpected_claimable_health")
    if not reasons:
        return "none"
    return "|".join(dict.fromkeys(reasons))


def _row_blocker_reasons(row: TemporalPromptRow) -> tuple[str, ...]:
    if row.blocker_reason == "none":
        return ()
    return tuple(part for part in row.blocker_reason.split("|") if part)


def _capability_suffix(capability_refs: list[str], prefix: str) -> str:
    for ref in capability_refs:
        if ref.startswith(prefix):
            return ref.removeprefix(prefix)
    return _UNSET


def false_grounding_risk_causes(row: TemporalPromptRow) -> tuple[str, ...]:
    """Return false-grounding risk causes exposed on a prompt row."""

    return tuple(
        reason.removeprefix(_FALSE_GROUNDING_PREFIX)
        for reason in row.blocker_reason.split("|")
        if reason.startswith(_FALSE_GROUNDING_PREFIX)
    )


__all__ = [
    "TEMPORAL_PROMPT_AUTHORITY_FENCE",
    "TEMPORAL_PROMPT_BLOCK_HEADER",
    "TemporalPromptBlock",
    "TemporalPromptRow",
    "TemporalPromptState",
    "build_temporal_prompt_block",
    "false_grounding_risk_causes",
    "load_default_temporal_prompt_records",
    "render_default_director_temporal_prompt_block",
    "render_default_temporal_prompt_block",
    "render_director_temporal_prompt_block",
    "render_temporal_prompt_block",
    "render_temporal_prompt_read_model",
]
