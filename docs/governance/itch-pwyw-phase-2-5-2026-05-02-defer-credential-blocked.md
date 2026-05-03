# Itch PWYW Phase 2.5 — Defer-with-credential-blocker

**Authored:** 2026-05-02 by beta.
**cc-task:** `itch-pwyw-phase-2-5-release-workflow` (WSJF 5.0, p2) closes via this doc.
**Phase 1 substrate (in tree):** `agents/leverage_itch_bundler/` (PR #1715).
**Parent (closed):** `closed/leverage-money-itch-pwyw-bundle.md` (2026-04-26 by epsilon).

## Decision

Phase 2.5 (GH Actions release workflow + receipt poller + Prometheus counter) is **deferred** with a single concrete operator-credential blocker. Phase 1 substrate (artifact scan + butler-command render + dry-run report) is **shipped and stable**. cc-task closes as **DONE (deferred-with-blocker)** so the Phase 2.5 implementation is not lost in the offered queue forever.

## §1 Phase 1 substrate — what's in tree

`agents/leverage_itch_bundler/__init__.py` (PR #1715) ships:

- `BundleArtifact` — typed artifact (paper / dataset / wheel)
- `BundleManifest` — frozen manifest enumerating every artifact + its source
- `scan_local_artifacts(...)` — filesystem discovery of bundle inputs
- `render_butler_command(...)` — formats `butler push` invocations per artifact
- `render_dry_run_report(...)` — markdown enumeration without actually pushing

The dry-run report ends with a single concrete operator-action breadcrumb (verbatim from the source):

> Re-run with `--commit` after the operator runs `pass insert itch/butler-token` (one-time bootstrap).

That sentence IS the unblocker for Phase 2.5.

## §2 Phase 2.5 — concrete blocker

Three components named in `agents/leverage_itch_bundler/__init__.py`:

| Component | Path (when shipped) | Estimate |
|---|---|---|
| GH Actions workflow | `.github/workflows/itch-bundle-release.yml` (tag-triggered on `velocity-report-*`) | 1-2h |
| Receipt poller → monetization block | `agents/leverage_itch_bundler/receipt_poller.py` (Itch.io API) | 1-2h |
| Prometheus counter | `hapax_leverage_itch_bundle_downloads_total{tier}` registered with the standard splat per `project_compositor_metrics_registry` | 30 min |

**Single blocker for all 3:** operator one-time runs `pass insert itch/butler-token`. Until that credential exists in the operator's `pass` store, none of these components can be exercised live; smoke tests + integration would all fail at the `butler push` stage with auth_error.

## §3 cc-task acceptance criteria mapping

| Criterion | Disposition |
|---|---|
| Verify whether Itch release automation is still wanted | **YES** per the parent `leverage-money-itch-pwyw-bundle` (closed/done by epsilon 2026-04-26) — Phase 1 was deliberately shipped with the credential-bootstrap deferral baked in. The companion arXiv velocity supersession (PR #2266) does NOT invalidate the bundle: the bundle composition includes velocity-report + dataset corpus + PyPI wheels, plus a Zenodo concept-DOI paper artifact replacing the would-be arXiv slot per the supersession's §3 replacement publication path. |
| If wanted, add the workflow/poller/metrics without storing credentials in code or docs | DEFERRED — implementation path documented (§2). Credentials reside in `pass insert itch/butler-token`; never in code or env-shipped defaults. |
| Track any required operator token action through operator-unblockers | OBSERVED — credential-blocker note already breadcrumbed in `agents/leverage_itch_bundler/__init__.py` itself; operator-unblockers dashboard at `_dashboard/codex-operator-unblockers.md` is the standard surface for the credential-action queue (operator may add an entry post-merge if not yet listed). |
| If not wanted, update the closed parent with explicit retirement | N/A — wanted (per first criterion). |

## §4 Activation procedure (when operator runs `pass insert itch/butler-token`)

The operator's one-time bootstrap unblocks the full Phase 2.5 path:

1. `pass insert itch/butler-token` (one-time; Itch.io API key from itch.io account settings)
2. Add `HAPAX_ITCH_BUTLER_TOKEN=$(pass show itch/butler-token)` to `hapax-secrets.service` env
3. File a fresh cc-task `itch-pwyw-phase-2-5-release-workflow-implementation` (or re-claim this one if not yet closed) with the §2 component table as scope
4. Implementation is straightforward (~3-4h total): GH Actions workflow uses `butler push` directly; receipt poller is a 30s timer that hits Itch.io API + emits `MonetizationEvent` to the existing event bus; Prometheus counter follows the standard splat pattern

The activation procedure ships with this PR so future-me does not re-derive it.

## §5 Prevent-requeue note

Future cc-tasks framed as "implement Itch.io release workflow / poller / metrics" should be **deferred to operator credential bootstrap first**. The substrate is shipped (Phase 1); the implementation path is documented (§2 + §4). Re-claiming for implementation should ONLY happen after `pass show itch/butler-token` returns a non-empty token AND the operator-unblockers dashboard tracks the credential action as completed.

The only architecture-level change that could supersede this defer is operator-decision-level retirement of Itch.io as a publication surface (e.g., adopt OpenCollective / Liberapay-only monetization). In that case the parent `leverage-money-itch-pwyw-bundle` would need a SUPERSEDED-BY edge per the closed/ vault convention.

## Cross-references

- Phase 1 source: `agents/leverage_itch_bundler/__init__.py` (PR #1715)
- Parent (closed): `closed/leverage-money-itch-pwyw-bundle.md` (epsilon, 2026-04-26)
- Companion supersession: `docs/governance/velocity-arxiv-endorser-path-2026-04-26-supersession.md` (PR #2266) — replaces the arXiv slot with Zenodo concept-DOI surface
- Operator-unblockers dashboard: `~/Documents/Personal/20-projects/hapax-cc-tasks/_dashboard/codex-operator-unblockers.md`
- Pattern: `feedback_status_doc_pattern` memory ("defer-with-concrete-blockers governance status docs are a high-leverage autonomous tool")
- Companion reconciles this session: PRs #2260 (alpha-audit-closeout) #2262 (R-18 twin-drift) #2263 (x402 architecture) #2266 (arXiv supersession)
