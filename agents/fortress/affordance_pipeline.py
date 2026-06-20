"""Fortress-owned affordance pipeline construction."""

from __future__ import annotations

from pathlib import Path

from agents._affordance import CapabilityRecord
from agents._affordance_pipeline import AffordancePipeline
from agents.fortress.capability import FORTRESS_DESCRIPTION


def build_fortress_affordance_pipeline(
    *,
    posterior_path: str | Path | None = None,
    index_capabilities: bool = True,
) -> AffordancePipeline:
    """Build the fortress read-only posterior view and optional runtime index."""

    pipeline = AffordancePipeline(
        posterior_mode="reader",
        posterior_client_id="fortress",
        posterior_path=posterior_path,
    )
    if index_capabilities:
        pipeline.index_capability(
            CapabilityRecord(
                name="fortress_governance",
                description=FORTRESS_DESCRIPTION,
                daemon="fortress",
            )
        )
        pipeline.register_interrupt("population_critical", "fortress_governance", "fortress")
    return pipeline
