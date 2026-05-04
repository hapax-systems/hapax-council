"""Cooperative AI Foundation research-grant form — schema-only stub."""

from __future__ import annotations

from agents.playwright_grant_submission_runner.recipes._stub_factory import (
    make_stub_recipe,
)

COOPERATIVE_AI_RECIPE = make_stub_recipe(
    name="cooperative_ai_foundation",
    portal_url="https://www.cooperativeai.com/grants",
    auth_method="public_form",
    field_schema={
        "applicant_name": "applicant.applicant_name",
        "applicant_email": "applicant.contact_email",
        "applicant_organisation": "applicant.applicant_entity",
        "project_title": "package.project_name",
        "project_abstract": "package.abstract",
        "research_question": "package.problem_statement",
        "methodology": "package.approach",
        "expected_outputs": "extra_sections.expected_outputs",
        "constitutional_disclosure": "package.constitutional_disclosure",
    },
)


__all__ = ["COOPERATIVE_AI_RECIPE"]
