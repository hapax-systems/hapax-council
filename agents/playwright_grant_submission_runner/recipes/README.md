# Grant-submission recipes

Each module in this package registers one portal recipe. See the
parent module's docstring for the orchestrator surface.

| Recipe | Status | Portal | Auth | Deadline / cycle |
|---|---|---|---|---|
| `nlnet` | **live** | https://nlnet.nl/propose | public form | June 1, 2026 12:00 CEST (next: Aug 1) |
| `manifund` | **live** | https://manifund.org/causes/ | OAuth (`HAPAX_MANIFUND_SESSION_TOKEN`) | rolling |
| `emergent_ventures` | stub | https://www.mercatus.org/emergent-ventures/apply | public form | rolling |
| `ltff` | stub | https://funds.effectivealtruism.org/funds/far-future/apply | public form | quarterly |
| `cooperative_ai_foundation` | stub | https://www.cooperativeai.com/grants | public form | varies |
| `openai_safety_airtable` | stub | https://airtable.com/openai-safety-fellowship | Airtable form | rolling |
| `anthropic_cco` | stub | https://www.anthropic.com/claude-for-open-source | public form | rolling |
| `schmidt_sciences` | stub | https://www.schmidtsciences.org/programs/trustworthy-ai | OAuth (`HAPAX_SCHMIDT_SCIENCES_SESSION_TOKEN`) | program-specific |

Status:

- **live** — Playwright form-fill flow shipped; live submission gated
  behind a per-recipe env var (e.g. `HAPAX_NLNET_LIVE_SUBMIT=1`) so
  dry-run is the safe default.
- **stub** — schema-only: URL + auth method + form-field schema
  documented; the orchestrator returns
  `RecipeStatus.NOT_IMPLEMENTED` for `execute_playwright`. Implementation
  lands in cc-task `playwright-grant-submission-runner-q3-batch-recipes`.

## Dropped from automation (per JR currentness packet 2026-05-04)

- **Alfred P. Sloan Foundation** — initial LOI is email-based
  (`technology@sloan.org`). Route through an SMTP/email-generation
  task, not Playwright.
- **NSF SBIR Phase I** — Research.gov requires Login.gov 2FA which
  aggressively blocks headless browsers. Operator-only.
- **EU Horizon Europe** — requires consortium of ≥3 entities from
  ≥3 EU member states. Standalone Wyoming SMLLC ineligible to apply
  alone.
- **GitHub Sponsors** — Stripe Connect KYC requires a human
  "Significant Controller". Use the GraphQL API + human steward
  instead of Playwright.

## Adding a recipe

1. Create `agents/playwright_grant_submission_runner/recipes/<name>.py`
   exporting a `Recipe` instance named `<NAME>_RECIPE`.
2. For schema-only stubs, build via
   `_stub_factory.make_stub_recipe(...)`.
3. For full Playwright recipes, subclass `Recipe` and override
   `execute_playwright`. Gate the live submission path behind a
   per-recipe env var so dry-run is the safe default.
4. Register the new recipe in `recipes/__init__.py`'s
   `default_recipes()` and (if appropriate) the `BATCH_Q2_2026` tuple.
5. Add a row to this README's table.
6. Add tests under `tests/playwright_grant_submission_runner/`.
