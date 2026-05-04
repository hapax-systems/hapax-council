"""OpenAI Safety Fellowship Airtable form — schema-only stub."""

from __future__ import annotations

from agents.playwright_grant_submission_runner.recipes._stub_factory import (
    make_stub_recipe,
)

OPENAI_SAFETY_RECIPE = make_stub_recipe(
    name="openai_safety_airtable",
    portal_url="https://airtable.com/openai-safety-fellowship",
    auth_method="airtable_form",
    field_schema={
        "name": "applicant.applicant_name",
        "email": "applicant.contact_email",
        "project_title": "package.project_name",
        "what_are_you_working_on": "package.abstract",
        "research_problem": "package.problem_statement",
        "approach": "package.approach",
        "constitutional_disclosure": "package.constitutional_disclosure",
    },
)


__all__ = ["OPENAI_SAFETY_RECIPE"]
