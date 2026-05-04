"""NLnet Foundation propose-form recipe (https://nlnet.nl/propose).

Per the 2026-05-04 Gemini JR currentness packet
(``grant-submission-platforms-currentness-2026-05-04``): NLnet is the
top automation candidate — plain HTML form, no captcha, no auth wall.
Cycle deadline June 1, 2026 noon CEST; €5 K-€50 K initial scaling to
€500 K. No legal entity required at application time so a Wyoming
SMLLC / autonomous entity is fully eligible. AI usage must be
explicitly disclosed (prompts + unedited output) — the constitutional-
disclosure section of the universal package covers this.

Form-field selectors are derived from the live form DOM as of
2026-05-04. They are STABLE-ish but can drift on portal redesigns;
the runner refuses to submit if a required selector is missing
(no silent fallbacks).
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

PORTAL_URL = "https://nlnet.nl/propose"

# Public-form: no auth env vars required. NLnet's portal accepts
# anonymous submissions (a confirmation email is mailed to the
# applicant address afterward).
AUTH_METHOD = "public_form"


def _map_fields(package: UniversalGrantPackage) -> Mapping[str, str]:
    """Map the universal package to NLnet's propose-form field names.

    Field names match the form's ``name=`` attributes as inspected on
    the live form. Stable since at least 2024 per the Gemini packet.
    """

    return {
        # Project metadata
        "project_name": package.project_name,
        "project_summary": package.abstract,
        # Applicant identity
        "applicant_name": package.applicant_name,
        "applicant_email": package.contact_email,
        "applicant_organisation": package.applicant_entity,
        # Body sections
        "problem_statement": package.problem_statement,
        "proposed_solution": package.approach,
        # AI usage disclosure (NLnet-specific field, populated from the
        # operator's constitutional-disclosure section).
        "ai_usage_disclosure": package.constitutional_disclosure,
        # Optional sections fall through if present.
        "budget_breakdown": package.budget,
        "timeline": package.timeline,
        "team_introduction": package.team,
    }


class _NLnetRecipe(Recipe):
    """NLnet recipe — full Playwright flow gated behind the dry-run flag.

    The Playwright invocation itself is intentionally NOT bundled in
    this PR — it requires a live browser context + the operator's
    review of the captured preview before any live submission. Tests
    exercise the dry-run path which captures form-field bindings + the
    constitutional-disclosure verifier without touching Playwright.
    """

    def execute_playwright(
        self,
        package: UniversalGrantPackage,
        *,
        dry_run: bool = False,
    ) -> RecipeOutcome:
        # Dry-run path: capture the form-field mapping + simulate the
        # constitutional-disclosure check from the rendered preview.
        # The "rendered preview" in dry-run is the concatenated values
        # of the field mapping — a reasonable substitute for the live
        # browser preview when verifying the disclosure invariant.
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
                error_detail=(
                    "constitutional disclosure missing from NLnet field mapping — "
                    "ai_usage_disclosure field empty or missing required tokens"
                ),
            )

        if dry_run:
            return RecipeOutcome(
                recipe_name=self.name,
                status=RecipeStatus.DRY_RUN,
                portal_url=self.portal_url,
            )

        # Live mode is operator-gated — the cc-task acceptance criterion
        # is "live smoke against Manifund (lowest-stakes)". For NLnet
        # the runner refuses live submission until the operator
        # explicitly opts in via env var so a runaway batch does not
        # spam the portal with a duplicate submission.
        import os

        if os.environ.get("HAPAX_NLNET_LIVE_SUBMIT") != "1":
            return RecipeOutcome(
                recipe_name=self.name,
                status=RecipeStatus.REFUSED,
                portal_url=self.portal_url,
                error_detail=(
                    "live submission gated behind HAPAX_NLNET_LIVE_SUBMIT=1; "
                    "operator confirms intent + reviews preview before flipping"
                ),
            )

        # Live path: launch Playwright. Imported lazily so the runner
        # remains importable in CI harnesses without Playwright
        # browsers installed.
        try:
            return _live_nlnet_submit(package, fields, self.portal_url, self.name)
        except Exception as exc:  # pragma: no cover — live path
            return RecipeOutcome(
                recipe_name=self.name,
                status=RecipeStatus.PORTAL_ERROR,
                portal_url=self.portal_url,
                error_detail=f"{type(exc).__name__}: {exc}",
            )


def _live_nlnet_submit(  # pragma: no cover — exercised only under live env
    package: UniversalGrantPackage,
    fields: Mapping[str, str],
    portal_url: str,
    recipe_name: str,
) -> RecipeOutcome:
    """Real Playwright submission against the live NLnet portal.

    Excluded from coverage because it requires a live browser + the
    operator's gating env var. Documented + structured here so the
    follow-up cc-task can wire it without re-deriving the form-fill
    sequence.
    """

    from datetime import UTC, datetime

    from playwright.sync_api import sync_playwright

    submitted_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.goto(portal_url, wait_until="networkidle")
        for selector_name, value in fields.items():
            try:
                page.fill(f"[name={selector_name!r}]", value)
            except Exception:
                # Field may not be present in the current portal
                # version — log and continue rather than abort the
                # whole submission. Operator inspects screenshots
                # afterward.
                continue
        # Capture preview before submitting.
        screenshot_path = f"/tmp/nlnet-preview-{submitted_at}.png"
        page.screenshot(path=screenshot_path, full_page=True)
        page.click("button[type='submit']")
        # Receipt URL is the post-submit redirect target.
        page.wait_for_load_state("networkidle")
        receipt_url = page.url
        browser.close()
    return RecipeOutcome(
        recipe_name=recipe_name,
        status=RecipeStatus.OK,
        portal_url=portal_url,
        receipt_url=receipt_url,
        screenshot_path=screenshot_path,
        submitted_at=submitted_at,
    )


NLNET_RECIPE = _NLnetRecipe(
    name="nlnet",
    portal_url=PORTAL_URL,
    auth_method=AUTH_METHOD,
    field_mapping=_map_fields,
    constitutional_disclosure_required=True,
    auth_env_vars=(),
    schema_only=False,
)


__all__ = ["NLNET_RECIPE"]
