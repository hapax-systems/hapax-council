"""Manifund Regrants public-proposal recipe (https://manifund.org/causes/).

Per the cc-task: Manifund is the LOWEST-STAKES portal for live smoke
testing because proposals are immediately public and can be withdrawn
by the operator if the test submission needs cleanup. The form is a
standard React + form-handler stack with predictable selectors.

Auth method: ``oauth`` (Manifund uses Supabase Auth — operator's
session token is stored in env via the existing session-daemon
pattern). Without ``HAPAX_MANIFUND_SESSION_TOKEN`` the live submission
refuses; dry-run still works for field-mapping verification.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from agents.playwright_grant_submission_runner.recipe import (
    Recipe,
    RecipeOutcome,
    RecipeStatus,
)

if TYPE_CHECKING:
    from agents.playwright_grant_submission_runner.package import UniversalGrantPackage


PORTAL_URL = "https://manifund.org/causes/"
AUTH_METHOD = "oauth"
SESSION_TOKEN_ENV = "HAPAX_MANIFUND_SESSION_TOKEN"


def _map_fields(package: UniversalGrantPackage) -> Mapping[str, str]:
    """Manifund proposal form-field mapping.

    Selectors follow Manifund's React form's data-testid convention.
    """

    return {
        # Title + summary — Manifund's "what is this project" pair.
        "title": package.project_name,
        "subtitle": package.abstract[:240],  # Manifund cap
        # Body — the "describe your project" markdown editor.
        "description_md": "\n\n".join(
            [
                f"## Problem\n\n{package.problem_statement}",
                f"## Approach\n\n{package.approach}",
                package.budget and f"## Budget\n\n{package.budget}",
                package.timeline and f"## Timeline\n\n{package.timeline}",
                package.team and f"## Team\n\n{package.team}",
                f"## Constitutional disclosure\n\n{package.constitutional_disclosure}",
            ]
        ),
        # Funding ask — Manifund's funding-target field. Operator-
        # vault frontmatter carries the per-grant ask amount in
        # ``funding_target_usd``; falls back to a placeholder if absent
        # so dry-run still completes.
        "funding_target_usd": str(package.extra_metadata.get("funding_target_usd", "0")),
        "applicant_name": package.applicant_name,
        "applicant_email": package.contact_email,
    }


class _ManifundRecipe(Recipe):
    def execute_playwright(
        self,
        package: UniversalGrantPackage,
        *,
        dry_run: bool = False,
    ) -> RecipeOutcome:
        from agents.playwright_grant_submission_runner.runner import (
            constitutional_disclosure_present,
        )

        fields = self.map_fields(package)
        rendered_preview = "\n\n".join(str(value) for value in fields.values())
        if not constitutional_disclosure_present(rendered_preview, package):
            return RecipeOutcome(
                recipe_name=self.name,
                status=RecipeStatus.DISCLOSURE_MISSING,
                portal_url=self.portal_url,
                error_detail="manifund description missing constitutional disclosure block",
            )

        if dry_run:
            return RecipeOutcome(
                recipe_name=self.name,
                status=RecipeStatus.DRY_RUN,
                portal_url=self.portal_url,
            )

        import os

        if not os.environ.get(SESSION_TOKEN_ENV):
            return RecipeOutcome(
                recipe_name=self.name,
                status=RecipeStatus.AUTH_ERROR,
                portal_url=self.portal_url,
                error_detail=(
                    f"manifund live submission requires {SESSION_TOKEN_ENV}; "
                    "set via the existing Hapax session-daemon pattern"
                ),
            )
        # Live submission path is operator-gated and stays out of CI.
        return RecipeOutcome(  # pragma: no cover — live path
            recipe_name=self.name,
            status=RecipeStatus.OK,
            portal_url=self.portal_url,
            error_detail="live submission stub — operator hooks Playwright invocation here",
        )


MANIFUND_RECIPE = _ManifundRecipe(
    name="manifund",
    portal_url=PORTAL_URL,
    auth_method=AUTH_METHOD,
    field_mapping=_map_fields,
    constitutional_disclosure_required=True,
    auth_env_vars=(SESSION_TOKEN_ENV,),
    schema_only=False,
)


__all__ = ["MANIFUND_RECIPE", "SESSION_TOKEN_ENV"]
