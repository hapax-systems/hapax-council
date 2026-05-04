"""Orchestrator: registry + dispatcher for grant-submission recipes."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from agents.playwright_grant_submission_runner.package import (
    UniversalGrantPackage,
    load_universal_package,
)
from agents.playwright_grant_submission_runner.recipe import (
    Recipe,
    RecipeNotImplementedError,
    RecipeOutcome,
    RecipeStatus,
)

log = logging.getLogger(__name__)

DEFAULT_OUTPUT_ROOT: Path = Path.home() / ".local/state/hapax/playwright-grant-submission-runner"

# Constitutional-disclosure invariant — every operator-authored
# package must contain at minimum these tokens in its
# constitutional_disclosure section. Recipes verify the rendered
# preview includes them before clicking submit.
_DISCLOSURE_REQUIRED_SUBSTRINGS: tuple[str, ...] = (
    "Hapax",  # the project name token; appears in every disclosure
)


def constitutional_disclosure_present(
    rendered_preview: str, package: UniversalGrantPackage
) -> bool:
    """Return True iff the rendered submission preview contains the disclosure.

    Two-stage check:

    1. The package's own ``constitutional_disclosure`` text appears
       (substring match — the rendered preview may have been wrapped /
       reformatted, so a fuzzy substring is more robust than equality).
    2. Every required token from :data:`_DISCLOSURE_REQUIRED_SUBSTRINGS`
       is present somewhere in the preview.

    A False return triggers ``RecipeStatus.DISCLOSURE_MISSING`` and
    refuses submission — the operator's constitutional V5 attribution
    must be on every public-archive deposit.
    """

    if not rendered_preview:
        return False
    # Check the package's own disclosure substring. We use a 64-char
    # head + 64-char tail probe rather than equality so portal-side
    # whitespace normalisation (Airtable in particular) doesn't break
    # the match.
    disclosure = package.constitutional_disclosure.strip()
    if not disclosure:
        return False
    head = disclosure[:64].strip()
    tail = disclosure[-64:].strip()
    if head not in rendered_preview and tail not in rendered_preview:
        return False
    return all(token in rendered_preview for token in _DISCLOSURE_REQUIRED_SUBSTRINGS)


class GrantSubmissionRunner:
    """Recipe registry + batch dispatcher.

    Construction takes a recipe registry (maps recipe name → Recipe
    instance) and an optional output root for receipt + screenshot
    captures. Tests inject an in-memory output root.
    """

    def __init__(
        self,
        recipes: Mapping[str, Recipe],
        *,
        output_root: Path | None = None,
        package: UniversalGrantPackage | None = None,
    ) -> None:
        self._recipes = dict(recipes)
        self._output_root = output_root or DEFAULT_OUTPUT_ROOT
        self._package = package

    @property
    def recipes(self) -> Mapping[str, Recipe]:
        return self._recipes

    def list_recipes(self) -> list[str]:
        """Return the registered recipe names sorted alphabetically."""

        return sorted(self._recipes.keys())

    def schema_only_recipes(self) -> list[str]:
        """Return recipe names that ship schema-only (no Playwright yet)."""

        return sorted(name for name, recipe in self._recipes.items() if recipe.schema_only)

    def _resolve_package(self) -> UniversalGrantPackage:
        if self._package is not None:
            return self._package
        return load_universal_package()

    def _output_dir(self, *, now: datetime | None = None) -> Path:
        ts = now if now is not None else datetime.now(UTC)
        target = self._output_root / ts.strftime("%Y-%m-%dT%H-%M-%SZ")
        target.mkdir(parents=True, exist_ok=True)
        return target

    def run_target(
        self,
        target: str,
        *,
        dry_run: bool = False,
        now: datetime | None = None,
    ) -> RecipeOutcome:
        """Dispatch a single recipe by name."""

        recipe = self._recipes.get(target)
        if recipe is None:
            return RecipeOutcome(
                recipe_name=target,
                status=RecipeStatus.PORTAL_ERROR,
                portal_url="",
                error_detail=f"unknown recipe {target!r}; known: {self.list_recipes()}",
            )
        package = self._resolve_package()
        try:
            outcome = recipe.execute_playwright(package, dry_run=dry_run)
        except RecipeNotImplementedError as exc:
            log.info("recipe %s schema-only stub — %s", target, exc)
            outcome = RecipeOutcome(
                recipe_name=recipe.name,
                status=RecipeStatus.NOT_IMPLEMENTED,
                portal_url=recipe.portal_url,
                error_detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover — defensive
            log.exception("recipe %s execute_playwright raised", target)
            outcome = RecipeOutcome(
                recipe_name=recipe.name,
                status=RecipeStatus.PORTAL_ERROR,
                portal_url=recipe.portal_url,
                error_detail=f"{type(exc).__name__}: {exc}",
            )
        self._record_outcome(outcome, now=now)
        return outcome

    def run_batch(
        self,
        recipe_names: list[str],
        *,
        dry_run: bool = False,
        now: datetime | None = None,
    ) -> list[RecipeOutcome]:
        """Sequential dispatch across a list of recipe names."""

        return [self.run_target(name, dry_run=dry_run, now=now) for name in recipe_names]

    def _record_outcome(self, outcome: RecipeOutcome, *, now: datetime | None) -> None:
        """Append the outcome as a JSONL line in the output dir."""

        try:
            target = self._output_dir(now=now) / "outcomes.jsonl"
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(outcome), default=str) + "\n")
        except Exception:
            log.warning(
                "recipe outcome JSONL write failed for %s", outcome.recipe_name, exc_info=True
            )


__all__ = [
    "DEFAULT_OUTPUT_ROOT",
    "GrantSubmissionRunner",
    "constitutional_disclosure_present",
]
