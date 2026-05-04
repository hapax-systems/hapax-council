"""Schema-only recipe factory.

Per the cc-task incremental ship plan, six of the eight recipes ship
as schema-only stubs in this PR — URL + auth method + form-field
schema documented, but no Playwright invocation. The follow-up cc-task
``playwright-grant-submission-runner-q3-batch-recipes`` lands the
implementations.

The factory below builds a :class:`Recipe` whose ``execute_playwright``
call raises ``RecipeNotImplementedError`` — the orchestrator catches
this and surfaces ``RecipeStatus.NOT_IMPLEMENTED`` so the operator
sees clearly which recipes are live and which need follow-up work.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from agents.playwright_grant_submission_runner.recipe import Recipe

if TYPE_CHECKING:
    from agents.playwright_grant_submission_runner.package import UniversalGrantPackage


def make_stub_recipe(
    *,
    name: str,
    portal_url: str,
    auth_method: str,
    auth_env_vars: tuple[str, ...] = (),
    field_schema: Mapping[str, str],
) -> Recipe:
    """Construct a schema-only recipe.

    ``field_schema`` is the documented field-name → meaning mapping for
    the portal; the field_mapping function returns it directly so the
    runner's dry-run output shows what the live submission *would*
    contain once the follow-up Playwright wiring lands.
    """

    def _map(package: UniversalGrantPackage) -> Mapping[str, str]:
        del package
        return dict(field_schema)

    return Recipe(
        name=name,
        portal_url=portal_url,
        auth_method=auth_method,
        field_mapping=_map,
        auth_env_vars=auth_env_vars,
        schema_only=True,
    )


__all__ = ["make_stub_recipe"]
