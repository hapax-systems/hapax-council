# Citable Nexus Front-Door Site — Phase 0 Bootstrap Status

**Status:** Phase 0 (renderer + content-generator) ships in this PR.
The full cc-task `citable-nexus-front-door-static-site` (WSJF 11.5)
is multi-phase; Phase 0 establishes the static-HTML rendering
substrate that the eventual external repo (`ryanklee/hapax-research`,
deployed at `hapax.research`) will serve. **No external repo is
created in this PR.** The renderer ships in `agents/citable_nexus/`
and the build CLI ships at `scripts/build_citable_nexus.py`; both
are runnable today against the in-repo signals.
**Driver task:** `citable-nexus-front-door-static-site` (cc-task,
WSJF 11.5; braid-score 7.5).
**Parent plan:** `docs/superpowers/plans/2026-04-30-auto-gtm-strengthening-plan.md`.

---

## 1. What Phase 0 ships (this PR)

### 1.1 Renderer

`agents/citable_nexus/renderer.py` (~280 LOC) — framework-free static
HTML renderer. No Astro / Eleventy / Hugo dependency; pure stdlib +
filesystem reads from `agents/publication_bus/surface_registry` and
`shared/attribution_block`. The output is portable across any static
host.

**Page renderers shipped:**

- `render_landing_page()` → `/` — V5 byline + page index +
  long-form non-engagement clause.
- `render_cite_page()` → `/cite` — canonical citation block (BibTeX,
  RIS, plaintext) plus a `CITATION.cff` pointer to the hapax-council
  source repo.
- `render_refuse_page()` → `/refuse` — Tier-3 REFUSED-surface catalog,
  rendered from `refused_surfaces()` with refusal-link suffixes when
  available.
- `render_surfaces_page()` → `/surfaces` — full publication-bus
  registry rendered as three tiers (FULL_AUTO / CONDITIONAL_ENGAGE /
  REFUSED) with API-style and scope-note annotations.

**Site-level renderer:**

- `render_site()` → `RenderedSite(pages: dict[path → html])` for
  programmatic use; the build CLI consumes this.

**Constitutional invariants enforced lexically:**

- **No operator legal name in body text** — V5 byline (`Hapax /
  Oudepode / OTO`) is the only authorship surface; tests pin the
  byline form on every page.
- **No "Subscribe" / "Contact" / "Demo" CTAs** —
  `TestNoCtaCopy.FORBIDDEN_PHRASES` is an 8-phrase exclusion list
  that fires on every rendered page (see
  `tests/agents/citable_nexus/test_renderer.py`).
- **Non-engagement clause on every page footer** — long form on
  `/` and `/refuse`, short form elsewhere; tests pin presence of one
  or the other on every page.
- **Open Graph + Twitter Card meta tags on every page** — Bluesky
  uses Open Graph; the explicit declaration covers all three
  platforms with one block.

### 1.2 Build CLI

`scripts/build_citable_nexus.py` — operator-runnable thin shell over
the renderer. Two output modes:

- **`--format html-tree`** (default) — emits `<out>/index.html`,
  `<out>/cite/index.html`, etc. as a static-host-ready directory
  tree. Suitable for `git push → GitHub Pages` or `rsync → omg.lol
  weblog` deploy paths.
- **`--format json`** — emits a single `<out>` JSON file keyed by
  URL path → rendered HTML. Suitable for piping into a deploy
  pipeline that does its own filesystem layout.

### 1.3 Tests

`tests/agents/citable_nexus/test_renderer.py` (26 tests):

- Phase-0 path-set contract (`PAGE_PATHS == ('/', '/cite', '/refuse',
  '/surfaces')`).
- Per-page metadata + body content sanity.
- Site-level invariants: doctype, V5 byline, non-engagement clause,
  canonical link, Open Graph meta on every page.
- Constitutional invariants: no CTA copy anywhere; polysemic-register
  attribution present.
- Surface registry tier-count parity: `/surfaces` page shows the
  same FULL_AUTO / CONDITIONAL_ENGAGE / REFUSED counts as the live
  registry.

---

## 2. What Phase 0 does NOT ship

### 2.1 External repo + DNS

The cc-task scope names `ryanklee/hapax-research` as the source repo
and `hapax.research` as the deployment URL. **Neither is created in
this PR.** Repo creation + DNS configuration is operator-action; the
sequence is documented in §3 below.

### 2.2 Vault-content pages

- `/manifesto` — Manifesto v0 lives in the operator vault
  (`~/Documents/Personal/30-areas/hapax/manifesto.md`). A
  vault-sync ingest step is needed before the renderer can pull the
  content into Phase 1; deferred.
- `/refusal-brief` — same vault-sync requirement as Manifesto.

### 2.3 DataCite / citation-graph pages

- `/deposits` — needs `HAPAX_OPERATOR_ORCID` configured (PR #2018
  closed the env-var fallback wire-up gap; the operator's first
  nightly snapshot at `~/hapax-state/datacite-mirror/<iso-date>.json`
  is the prerequisite for this page's content).
- `/citation-graph` — needs a graph-layout engine choice
  (Cytoscape.js / D3 / static SVG); deferred to Phase 2.

### 2.4 GitHub Actions auto-deploy + uptime probe

- `.github/workflows/citable-nexus-deploy.yml` lives in the eventual
  `ryanklee/hapax-research` repo, not in `hapax-council`. Phase 1
  ships a template for that workflow.
- `hapax-citable-nexus-health.timer` (uptime probe per cc-task
  acceptance) ships once the site has a live URL to probe.

---

## 3. Repo Relocation Path (operator-action sequence)

When the operator wants to bootstrap the external repo:

1. **Create the GitHub repo:**
   ```fish
   gh repo create ryanklee/hapax-research \
       --public \
       --description "Citable nexus for Hapax / Oudepode published artifacts" \
       --homepage "https://hapax.research"
   ```

2. **Bootstrap the repo with the rendered Phase-0 site:**
   ```fish
   set tmp (mktemp -d)
   cd ~/projects/hapax-council
   uv run python scripts/build_citable_nexus.py --out $tmp
   git clone https://github.com/ryanklee/hapax-research $tmp/repo
   cp -r $tmp/* $tmp/repo/
   cd $tmp/repo
   git add .
   git commit -m "feat: Phase 0 — renderer-emitted citable-nexus front door"
   git push origin main
   ```

3. **Enable GitHub Pages:**
   - Settings → Pages → Source = `main` branch, `/` (root).

4. **Configure DNS:**
   - Add a CNAME record: `hapax.research` → `ryanklee.github.io`.
   - Add a `CNAME` file at the repo root: `hapax.research`.
   - GitHub will auto-provision a Let's Encrypt certificate.

5. **Add a daily auto-deploy workflow:**
   `.github/workflows/citable-nexus-deploy.yml` runs on cron
   (recommend `30 4 * * *` UTC, just after the DataCite mirror's
   nightly fire) to re-render against current registry state.
   Phase 1 of this cc-task ships the workflow template.

6. **Update upstream pointers:**
   - Refusal Brief footer auto-injection: point at
     `https://hapax.research/refuse` (currently no canonical
     destination).
   - Bluesky / Mastodon bios: link to `https://hapax.research`.
   - `CITATION.cff` `repository-code` field: cross-reference both
     `hapax-council` (source) and `hapax-research` (citable nexus).

---

## 4. What stays unchanged

- `agents/publication_bus/surface_registry.py` — Phase 0 reads it;
  no schema change needed.
- `shared/attribution_block.py` — V5 byline + non-engagement clause
  constants are the source of truth; renderer pulls them.
- `CITATION.cff` (in `hapax-council` repo root) — remains the
  authoritative GitHub-citation-widget surface; the citable-nexus
  `/cite` page references it as the canonical form.

---

## 5. Acceptance map (cc-task → Phase 0 evidence)

| cc-task acceptance | Phase 0 evidence |
|---|---|
| Source repo created | **Deferred** — operator-action per §3.1 |
| DNS configured | **Deferred** — operator-action per §3.4 |
| All 8 named pages rendered | **Partial** — 4 of 8 ship (landing, cite, refuse, surfaces); 4 deferred (manifesto, refusal-brief, deposits, citation-graph) per §2 |
| V5 attribution on every footer | **Done** — pinned by `TestRenderSite::test_every_page_has_v5_byline` |
| Open Graph + meta tags valid | **Done** — pinned by `TestRenderSite::test_every_page_has_open_graph_meta` |
| DataCite citation-graph rendering | **Deferred** to Phase 2 |
| Surface registry rendering | **Done** — `/surfaces` page renders all three tiers with parity tests |
| No CTAs | **Done** — pinned by `TestNoCtaCopy::test_no_cta_copy_anywhere` |
| No legal entity name | **Done** — V5 byline + Oudepode referent only; covered by the existing legal-name leak guards |
| `axiom-scan` passes | Verified via CI lint job |
| Refusal Brief footer points at `/refuse` | **Deferred** — needs the live URL first |
| Bluesky/Mastodon bios updated | **Deferred** — operator-action per §3.6 |
| Site uptime probe | **Deferred** — Phase 2 |

Phase 0 closes ~7 of the 13 acceptance items; the remaining 6 are
either operator-action or deferred to Phase 2.

---

## 6. Phase 1 / 2 follow-up cc-tasks (recommended)

When Phase 0 lands and the external repo is bootstrapped, file:

- **`citable-nexus-vault-content-ingest`** (Phase 1, ~WSJF 6) —
  vault-sync the Manifesto v0 + Refusal Brief into the renderer's
  ingest path so `/manifesto` and `/refusal-brief` render with real
  content.
- **`citable-nexus-deposits-page-from-datacite`** (Phase 1, ~WSJF 5) —
  add `/deposits` rendering from the DataCite mirror's daily
  snapshot ledger.
- **`citable-nexus-deploy-workflow`** (Phase 1, ~WSJF 4) — ship the
  GitHub Actions cron-deploy workflow template + uptime probe
  systemd timer.
- **`citable-nexus-citation-graph`** (Phase 2, ~WSJF 4) — add
  `/citation-graph` with a graph-layout engine (Cytoscape.js
  recommended).
- **`citable-nexus-refusal-brief-footer-injection`** (Phase 1
  follow-on, ~WSJF 3) — update Refusal Brief footer auto-injection
  to point at the live `/refuse` URL.

---

## 7. Public-claim invariant

**No public claim that "hapax.research is live" until §3 is done.**
The renderer ships and is testable today, but the deployed URL
doesn't exist yet. Phase 0 establishes the substrate; the live
canonical destination is operator-action gated.

When the bootstrap sequence completes:

1. Update this status doc → "Status: live as of `<iso-date>`."
2. Open the Phase 1 follow-up cc-tasks per §6.
3. Update the Refusal Brief footer auto-injection.
4. Update Bluesky / Mastodon bios.

Until then, every "citable nexus" reference remains forward-looking.
