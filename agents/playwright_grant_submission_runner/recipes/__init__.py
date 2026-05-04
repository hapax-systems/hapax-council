"""Recipe registry for the grant-submission runner.

Each module in this package registers one recipe. The registry is
constructed at import time and consumed by :class:`GrantSubmissionRunner`.

Per the cc-task incremental ship plan: NLnet (June 1 deadline) and
Manifund (low-stakes smoke) ship as full recipes; the remaining six
ship as schema-only stubs (URL + auth method + form-field schema, no
Playwright invocation) and land their Playwright flows in the follow-
up cc-task ``playwright-grant-submission-runner-q3-batch-recipes``.
"""

from __future__ import annotations

from agents.playwright_grant_submission_runner.recipe import Recipe
from agents.playwright_grant_submission_runner.recipes.anthropic_cco import (
    ANTHROPIC_CCO_RECIPE,
)
from agents.playwright_grant_submission_runner.recipes.cooperative_ai_foundation import (
    COOPERATIVE_AI_RECIPE,
)
from agents.playwright_grant_submission_runner.recipes.emergent_ventures import (
    EMERGENT_VENTURES_RECIPE,
)
from agents.playwright_grant_submission_runner.recipes.ltff import LTFF_RECIPE
from agents.playwright_grant_submission_runner.recipes.manifund import MANIFUND_RECIPE
from agents.playwright_grant_submission_runner.recipes.nlnet import NLNET_RECIPE
from agents.playwright_grant_submission_runner.recipes.openai_safety_airtable import (
    OPENAI_SAFETY_RECIPE,
)
from agents.playwright_grant_submission_runner.recipes.schmidt_sciences import (
    SCHMIDT_SCIENCES_RECIPE,
)


def default_recipes() -> dict[str, Recipe]:
    """Build the canonical recipe registry."""

    return {
        recipe.name: recipe
        for recipe in (
            NLNET_RECIPE,
            MANIFUND_RECIPE,
            EMERGENT_VENTURES_RECIPE,
            LTFF_RECIPE,
            COOPERATIVE_AI_RECIPE,
            OPENAI_SAFETY_RECIPE,
            ANTHROPIC_CCO_RECIPE,
            SCHMIDT_SCIENCES_RECIPE,
        )
    }


# Q2 2026 batch: all 8 recipes per the cc-task scope.
BATCH_Q2_2026: tuple[str, ...] = (
    "nlnet",
    "manifund",
    "emergent_ventures",
    "ltff",
    "cooperative_ai_foundation",
    "openai_safety_airtable",
    "anthropic_cco",
    "schmidt_sciences",
)


__all__ = [
    "BATCH_Q2_2026",
    "default_recipes",
]
