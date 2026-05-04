"""Schmidt Sciences 2026 Trustworthy AI portal — schema-only stub."""

from __future__ import annotations

from agents.playwright_grant_submission_runner.recipes._stub_factory import (
    make_stub_recipe,
)

SCHMIDT_SCIENCES_RECIPE = make_stub_recipe(
    name="schmidt_sciences",
    portal_url="https://www.schmidtsciences.org/programs/trustworthy-ai",
    auth_method="oauth",
    auth_env_vars=("HAPAX_SCHMIDT_SCIENCES_SESSION_TOKEN",),
    field_schema={
        "applicant_name": "applicant.applicant_name",
        "applicant_email": "applicant.contact_email",
        "applicant_organisation": "applicant.applicant_entity",
        "project_title": "package.project_name",
        "abstract": "package.abstract",
        "research_problem": "package.problem_statement",
        "approach": "package.approach",
        "budget_breakdown": "package.budget",
        "team": "package.team",
        "constitutional_disclosure": "package.constitutional_disclosure",
    },
)


__all__ = ["SCHMIDT_SCIENCES_RECIPE"]
