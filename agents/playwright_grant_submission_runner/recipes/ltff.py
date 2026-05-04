"""Long-Term Future Fund (EA Funds) — schema-only stub."""

from __future__ import annotations

from agents.playwright_grant_submission_runner.recipes._stub_factory import (
    make_stub_recipe,
)

LTFF_RECIPE = make_stub_recipe(
    name="ltff",
    portal_url="https://funds.effectivealtruism.org/funds/far-future/apply",
    auth_method="public_form",
    field_schema={
        "applicant_name": "applicant.applicant_name",
        "applicant_email": "applicant.contact_email",
        "project_summary": "package.abstract",
        "project_description": "package.approach",
        "expected_impact": "package.problem_statement",
        "funding_amount": "extra_metadata.funding_target_usd",
        "constitutional_disclosure": "package.constitutional_disclosure",
    },
)


__all__ = ["LTFF_RECIPE"]
