"""Daimonion-owned affordance pipeline construction."""

from __future__ import annotations

from pathlib import Path

from agents._affordance_pipeline import AffordancePipeline


def build_daimonion_affordance_pipeline(
    *,
    posterior_path: str | Path | None = None,
) -> AffordancePipeline:
    """Build the daimonion's read-only posterior view."""

    return AffordancePipeline(
        posterior_mode="reader",
        posterior_client_id="hapax_daimonion",
        posterior_path=posterior_path,
    )
