"""Playwright grant-submission runner — universal recipe dispatcher.

Cc-task ``playwright-grant-submission-runner`` (WSJF 10.0). Reduces
operator-active time per grant submission from ~30 minutes to ~5
minutes (review captured screenshots) by dispatching universal-package
form-fills across portal-specific recipes.

Composes:

* ``shared.preprint_artifact.PreprintArtifact`` — the universal package
  shape (already used by ``zenodo_publisher`` + ``philarchive_adapter``).
* ``agents.zenodo_publisher.publish_artifact`` — mints a concept-DOI
  per submission for citation-graph completeness.
* The existing Playwright session-daemon pattern (PhilArchive adapter
  reads ``HAPAX_PHILARCHIVE_SESSION_COOKIE`` + ``HAPAX_PHILARCHIVE_AUTHOR_ID``;
  per-recipe env vars follow the same shape — see each recipe's
  module docstring).

Per the cc-task's ethical/public-claim commitment: **the runner
submits ONLY operator-authored content**. The universal package is
authored by the operator in the vault file
``~/Documents/Personal/20-projects/hapax-cc-tasks/active/grant-application-package-q2-2026.md``;
the runner reads it, maps it to portal-specific form fields, verifies
the constitutional-disclosure paragraph appears in the submission
preview, and clicks submit. The runner does NOT generate application
content beyond field mapping.

CLI surface (see ``__main__.py``):

* ``--target <portal>`` — single submission via the named recipe.
* ``--batch <name>`` — sequential dispatch across the named batch
  (e.g., ``q2-2026`` runs all 8 recipes back-to-back).
* ``--dry-run`` — fill forms, capture preview screenshots, but do NOT
  click submit. Used by tests + cassette fixtures.

Recipe registry — all 8 recipes are registered in
``recipes/__init__.py``; some ship as full implementations (NLnet,
Manifund per the JR currentness packet's recommendation), others as
schema-only stubs for follow-up cc-tasks.
"""

from __future__ import annotations

from agents.playwright_grant_submission_runner.package import (
    UniversalGrantPackage,
    load_universal_package,
)
from agents.playwright_grant_submission_runner.recipe import (
    Recipe,
    RecipeOutcome,
    RecipeStatus,
)
from agents.playwright_grant_submission_runner.runner import (
    GrantSubmissionRunner,
    constitutional_disclosure_present,
)

__all__ = [
    "GrantSubmissionRunner",
    "Recipe",
    "RecipeOutcome",
    "RecipeStatus",
    "UniversalGrantPackage",
    "constitutional_disclosure_present",
    "load_universal_package",
]
