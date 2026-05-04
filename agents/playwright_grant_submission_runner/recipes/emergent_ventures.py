"""Tyler Cowen Emergent Ventures (Mercatus) — schema-only stub."""

from __future__ import annotations

from agents.playwright_grant_submission_runner.recipes._stub_factory import (
    make_stub_recipe,
)

EMERGENT_VENTURES_RECIPE = make_stub_recipe(
    name="emergent_ventures",
    portal_url="https://www.mercatus.org/emergent-ventures/apply",
    auth_method="public_form",
    field_schema={
        "name": "applicant.applicant_name",
        "email": "applicant.contact_email",
        "project_title": "package.project_name",
        "summary": "package.abstract",
        "amount_requested": "extra_metadata.funding_target_usd",
        "what_will_you_do": "package.approach",
        "why_does_it_matter": "package.problem_statement",
        "constitutional_disclosure": "package.constitutional_disclosure",
    },
)


__all__ = ["EMERGENT_VENTURES_RECIPE"]
