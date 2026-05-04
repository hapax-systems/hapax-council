"""Anthropic Claude for Open Source portal — schema-only stub."""

from __future__ import annotations

from agents.playwright_grant_submission_runner.recipes._stub_factory import (
    make_stub_recipe,
)

ANTHROPIC_CCO_RECIPE = make_stub_recipe(
    name="anthropic_cco",
    portal_url="https://www.anthropic.com/claude-for-open-source",
    auth_method="public_form",
    field_schema={
        "applicant_name": "applicant.applicant_name",
        "applicant_email": "applicant.contact_email",
        "github_handle": "extra_metadata.github_handle",
        "project_repository": "extra_metadata.project_repository",
        "project_description": "package.abstract",
        "claude_usage_plan": "package.approach",
        "constitutional_disclosure": "package.constitutional_disclosure",
    },
)


__all__ = ["ANTHROPIC_CCO_RECIPE"]
