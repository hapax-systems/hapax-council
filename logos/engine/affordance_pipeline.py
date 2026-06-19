"""Logos-owned affordance pipeline construction."""

from __future__ import annotations

from pathlib import Path

from logos._affordance_pipeline import AffordancePipeline


def build_logos_affordance_pipeline(
    *,
    posterior_path: str | Path | None = None,
) -> AffordancePipeline:
    """Build the Logos engine's read-only posterior view."""

    return AffordancePipeline(
        posterior_mode="reader",
        posterior_client_id="logos_engine",
        posterior_path=posterior_path,
    )
