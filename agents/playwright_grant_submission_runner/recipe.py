"""Recipe protocol for the grant-submission runner.

Every portal-specific recipe is a subclass of :class:`Recipe`. The
orchestrator (``runner.GrantSubmissionRunner``) walks the recipe's
form-field mapping, fills via Playwright, captures the submission
preview, verifies the constitutional disclosure, and either submits
(live mode) or returns the captured preview (dry-run).

A recipe declares:

* ``name`` — the CLI ``--target`` slug.
* ``portal_url`` — the public URL of the submission form.
* ``auth_method`` — one of ``"session_cookie"``, ``"oauth"``,
  ``"airtable_form"``, ``"public_form"``. Drives which env vars the
  runner looks up before dispatch.
* ``constitutional_disclosure_required`` — whether the runner must
  verify the disclosure paragraph appears in the submission preview.
  Default True; set False only for portals where the disclosure cannot
  be embedded (e.g., a 200-character Airtable field).
* ``field_mapping`` — a callable that takes a
  :class:`UniversalGrantPackage` and returns a ``dict[str, str]`` of
  ``form-selector → value`` entries.

Recipes that are schema-only stubs (per the cc-task's incremental
ship plan) raise ``RecipeNotImplementedError`` from
``execute_playwright`` until the follow-up cc-task lands. The CLI
surfaces this as a clear error so the operator sees which recipes are
live.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from agents.playwright_grant_submission_runner.package import UniversalGrantPackage

log = logging.getLogger(__name__)


class RecipeStatus(StrEnum):
    """Per-submission outcome enum."""

    OK = "ok"
    DRY_RUN = "dry_run"
    AUTH_ERROR = "auth_error"
    DISCLOSURE_MISSING = "disclosure_missing"
    PORTAL_ERROR = "portal_error"
    NOT_IMPLEMENTED = "not_implemented"
    REFUSED = "refused"


@dataclass(frozen=True)
class RecipeOutcome:
    """One submission's captured outcome.

    The orchestrator collects these into a JSONL log under
    ``~/.local/state/hapax/playwright-grant-submission-runner/<iso-date>/``
    so the operator can review what happened across a batch.
    """

    recipe_name: str
    status: RecipeStatus
    portal_url: str
    receipt_url: str | None = None
    screenshot_path: str | None = None
    zenodo_concept_doi: str | None = None
    error_detail: str | None = None
    submitted_at: str | None = None  # ISO-8601 UTC


class RecipeNotImplementedError(NotImplementedError):
    """Raised by stub recipes that ship schema-only without Playwright."""


class FieldMapper(Protocol):
    """Maps a universal package to portal-specific form fields."""

    def __call__(self, package: UniversalGrantPackage) -> Mapping[str, str]: ...


@dataclass
class Recipe:
    """A grant-submission recipe.

    Subclasses override :meth:`execute_playwright` to invoke the
    portal-specific Playwright flow. The base class handles the
    schema-only stub path — calling ``execute_playwright`` on a stub
    raises :class:`RecipeNotImplementedError` so the CLI surfaces the
    gap clearly.
    """

    name: str
    portal_url: str
    auth_method: str
    field_mapping: FieldMapper
    constitutional_disclosure_required: bool = True
    auth_env_vars: tuple[str, ...] = field(default_factory=tuple)
    schema_only: bool = False

    def map_fields(self, package: UniversalGrantPackage) -> Mapping[str, str]:
        """Materialise the form-field mapping from the universal package."""

        return self.field_mapping(package)

    def execute_playwright(
        self,
        package: UniversalGrantPackage,
        *,
        dry_run: bool = False,
    ) -> RecipeOutcome:
        """Run the Playwright flow for this recipe.

        Default implementation raises ``RecipeNotImplementedError`` —
        schema-only stubs inherit this so the CLI surfaces the gap.
        Concrete recipes override this method.
        """

        del package, dry_run  # unused in the stub path
        raise RecipeNotImplementedError(
            f"recipe {self.name!r}: schema-only — Playwright flow lands in a follow-up cc-task"
        )


__all__ = [
    "FieldMapper",
    "Recipe",
    "RecipeNotImplementedError",
    "RecipeOutcome",
    "RecipeStatus",
]
