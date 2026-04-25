---
type: research-drop
date: 2026-04-25
title: GitHub Repos Forward Under Constitutional Norms — Operational + Aesthetic
agent_ids: [a84908f6592f50189, a53bcbfd8a4cb45fa]
status: shaping-in-progress
note: Two parallel research dispatches converged on similar verdict; this doc consolidates both.
---

# GitHub Repos Forward Under Constitutional Norms

## Verdict (consolidated)

The single highest-leverage move is to **publish a `ryanklee/.github` org-repo profile-README that functions as the constitutional preamble**, then attach **three machine-readable metadata layers per repo (CITATION.cff + codemeta.json + .zenodo.json) plus DataCite RelatedIdentifier graph linking the seven first-party repos as a connected graph node**. This forces GitHub from "social platform" into "research-archive surface" while the refusal stance lives inline in the README as an anti-marketing artifact. Repos become research artifacts, not products.

## Operational checklist (file × repo × priority)

| File | hapax-council | hapax-constitution | hapax-officium | hapax-watch | hapax-phone | hapax-mcp | hapax-assets | tabbyAPI (fork) | atlas-voice (fork) | Pri |
|---|---|---|---|---|---|---|---|---|---|---|
| CITATION.cff (v1.2.0) | yes | yes (anchor) | yes | yes | yes | yes | yes | NO upstream | NO upstream | P0 |
| codemeta.json (v3.0 JSON-LD) | yes | yes (anchor) | yes | yes | yes | yes | yes | NO | NO | P0 |
| .zenodo.json (DOI minting) | yes | yes | yes | yes | yes | yes | skip CDN | NO | NO | P0 |
| LICENSE PolyForm Strict 1.0.0 (runtime) / CC BY-NC-ND 4.0 (spec/docs) | yes | yes | yes | yes | yes | yes | yes (existing CC-BY-SA-4.0/BSD-3) | upstream | upstream | P0 |
| NOTICE.md (constitutional disclosure) | yes | yes | yes | yes | yes | yes | yes | yes (gitignored via `.git/info/exclude`) | yes (same) | P0 |
| SECURITY.md (Sigstore-signed disclosure path, not email) | yes | yes | yes | yes | yes | yes | yes | NO | NO | P1 |
| CONTRIBUTING.md (refuse-and-redirect) | yes | yes | yes | yes | yes | yes | yes | NO | NO | P0 |
| GOVERNANCE.md → axiom registry | yes | yes (canonical) | yes | yes | yes | yes | yes | NO | NO | P1 |
| CODEOWNERS (`* @ryanklee` + axioms/ protect) | exists, expand | yes | yes | yes | yes | yes | yes | NO | NO | P0 |
| .github/FUNDING.yml | DELETE + uncheck Sponsorships | same | same | same | same | same | same | n/a | n/a | P0 |
| .github/ISSUE_TEMPLATE/config.yml (`blank_issues_enabled: false` + redirect) | yes | yes | yes | yes | yes | yes | yes | NO | NO | P1 |
| Repo Settings: Issues OFF, Discussions OFF, Wiki OFF (except hapax-constitution as axiom registry), Sponsorships OFF, PR auto-close action | all 7 first-party | | | | | | | | | P0 |
| .github/workflows/release-attest.yml (sigstore + actions/attest-sbom on tag) | yes | yes | yes | yes | yes | yes | skip | NO | NO | P1 |
| GitHub topics (sparse, schema.org-aligned: `research-software`, `single-operator`, `philosophy-of-science`, `governance`, `infrastructure-as-argument`) — AVOID `ai`/`agents`/`framework`/`tool`/`library`/`awesome` | yes | yes | yes | yes | yes | yes | yes | inherit | inherit | P0 |
| GitHub description (≤350 chars, schema.org-aligned, refusal-stance opener) | yes | yes | yes | yes | yes | yes | yes | upstream | upstream | P0 |
| Zenodo-GitHub integration (DOI mints on release) | enable | enable | enable | enable | enable | enable | skip | skip | skip | P1 |

**Cross-repo container**: `ryanklee/.github` org-level repo with `profile/README.md` = constitutional preamble (renders at github.com/ryanklee); `.github/workflows/` carries shared workflows callable as `ryanklee/.github/.github/workflows/<x>.yml@main` from each repo. NOTE: there is conflicting research output on whether to use `ryanklee/ryanklee/README.md` (user-account profile README) vs `ryanklee/.github/profile/README.md` (org-level). The `.github/profile/README.md` pattern works only if `ryanklee` is treated as an org; for user-accounts, `ryanklee/ryanklee/README.md` is the correct surface. Verify before implementation.

## Aesthetic checklist — README structural template

```
# <repo-name>

This repository is a constituent of the Hapax operating environment. It is
not a product, not a service, and not seeking contributors. It is research
infrastructure published as artifact.

Authorship is indeterminate by design: this codebase is co-produced by
Hapax (the system itself), Claude Code, and the operator (Oudepode / The
Operator / OTO). Per the Hapax Manifesto, unsettled contribution is a
feature of the work, not a concealment.

## What this is, not what it does
<2-4 sentences: ontological, not functional>

## Constitutional position
- Single-operator system; no auth, no roles, no contributor onboarding (axiom: single_user)
- No issues, no discussions, no PRs accepted; refusal is the artifact (see /refusal-brief)
- License: PolyForm Strict 1.0.0 — source-available, non-distribution, non-modification
- Citation: see CITATION.cff; archival DOI: <Zenodo concept DOI>

## Linked artifacts
- Manifesto: hapax.weblog.lol/hapax-manifesto-v0
- Refusal Brief: hapax.weblog.lol/refusal-brief
- Cohort Disparity Disclosure: hapax.weblog.lol/cohort-disparity-disclosure
- Constitution: github.com/ryanklee/hapax-constitution

## Inter-repo position
<one sentence locating this repo in the dependency graph>
```

Hard rules: monospace voice, ASCII-only structural elements, NO emojis, NO shields.io badges, NO screenshots, NO "Quick Start", NO "Roadmap", NO "Star history", NO "we" (HARDM anti-anthropomorphization), present-tense scientific register only.

## Five anti-marketing case studies

1. **suckless.org** — code complexity is the mother of bloated software; READMEs are pure technical declaration; project-as-philosophy. *Transferable*: state the negative-space (deliberately missing) up front.
2. **Hundred Rabbits** (github.com/hundredrabbits) — explicitly demotes GitHub: "we only use github to host js versions, for the C and asm versions see git.sr.ht/~rabbits/". *Transferable*: GitHub is a mirror, not canonical surface.
3. **SerenityOS** — "a system by us, for us, based on the things we like"; explicitly limited interest in non-contributor feature requests. *Transferable*: aesthetic-and-language norms as governance.
4. **Pluralistic.net** (Doctorow's POSSE) — Post Own Site, Syndicate Everywhere; site owns canonical, GitHub is downstream. *Transferable*: weblog.lol is canonical.
5. **9fans/plan9port** — minimal README, no marketing, technical-only documentation, one-line mission. *Transferable*: terse single-paragraph mission; documentation outside README.

## Three "fresh" infrastructure-as-argument patterns

1. **Wiki-as-axiom-registry** (hapax-constitution exclusive). Enable Wiki on hapax-constitution only; mirror `axioms/registry.yaml` rendered as Markdown pages, one axiom per page. Other 6 repos disable Wiki; their `GOVERNANCE.md` redirects there. The asymmetry IS the argument: governance is centralised, not distributed.

2. **Releases-as-DataCite-graph-nodes**. Each repo's tagged release auto-mints a Zenodo DOI; `.zenodo.json` `related_identifiers` declares `IsPartOf` → hapax-constitution concept-DOI, `Requires`/`IsRequiredBy` for the council-officium-mcp triangle, `IsSupplementTo` → relevant weblog.lol post URL. The seven repos form a machine-readable graph in DataCite Commons that academic-spectacle audiences traverse via DOI relations — without ever touching GitHub trending.

3. **`ryanklee/ryanklee/README.md` (or `ryanklee/.github/profile/README.md` if org-shaped) as constitutional preamble**. Single canonical surface for: refusal stance, manifesto link, axioms summary, repo dependency graph (Mermaid), no-contribution declaration. Subsumes "About Us"/"Team" page while categorically refusing both formats.

## Cross-repo consistency mechanism

**`python -m hapax_sdlc.render --repo <id>` script** in `hapax-constitution` (which already publishes the `hapax-sdlc` package) emits canonical CITATION.cff, codemeta.json, .zenodo.json, NOTICE.md, CONTRIBUTING.md, SECURITY.md, GOVERNANCE.md from a single `repos.yaml` keyed by repo-id, gated by axioms. Each repo runs `hapax_sdlc.render` in a scheduled workflow; PRs land via the existing axiom-commit-scan pipeline. Single source of truth, no template injection from elsewhere, governance file generation under CODEOWNERS protection. **Beats** the alternative (`.github`-org-shared-workflows + `default-files-as-templates`) because templates are inherited only when files are absent; we want them positively asserted with constitutional content per-repo.

## Risk / anti-pattern list (looks constitutional, isn't)

- **Empty FUNDING.yml** — does NOT hide the sponsor button; you must disable Sponsorships in Settings > Features per repo.
- **`awesome-` topics or marketing topics** — wrong audience. Use schema.org-aligned, sparse topics.
- **GitHub Pages on gh-pages branches other than hapax-assets** — creates marketing surface demanding maintenance.
- **Citing operator's legal name in NOTICE.md/CONTRIBUTING.md/SECURITY.md** — violates operator-referent policy. Legal name only in CITATION.cff `authors:`, git author, Zenodo `creators` array, ORCID record. Body text uses {The Operator | Oudepode | OTO} sticky-per-document.
- **MIT/Apache-2.0 LICENSE** — communicates "use freely, build a community". For constitutional refusal, PolyForm Strict 1.0.0 is correct shape. AGPL-3 is wrong-shape (assumes downstream contributors). The two upstream forks keep their licenses; only NOTICE.md (gitignored from upstream) marks integration.
- **SECURITY.md listing email** — surface-area violation. Use Sigstore-signed disclosure path.
- **Auto-merging Dependabot PRs** — implies multi-actor maintenance norm; instead, dependabot in security-only mode + attest each release.
- **README screenshots/demo GIFs** — violates HARDM anti-anthropomorphization (livestream is the demo surface).
- **Calling codebase "framework" or "platform"** — invites build-with-X reading. Use "research-instrument", "operating-environment", "constituent".
- **CODE_OF_CONDUCT.md** — assumes a community to govern. Refuse by omission.
- **Pinned repositories on profile** — implies hierarchy/promotion. Use Mermaid graph instead.
- **README.md differing from codemeta.json description** — two sources of truth violates scientific register. Render README description from codemeta.

## Sources

- Citation File Format spec (citation-file-format.github.io)
- GitHub: About CITATION files
- CodeMeta terms / schema.org mapping
- FAIR4RS principles (Nature Scientific Data 2022)
- ReSA blog: Software Citation Infrastructure 2026-04-21
- Zenodo GitHub integration; .zenodo.json reference
- DataCite Metadata Schema 4.5 / 4.7 RelatedIdentifier
- SLSA distributing-provenance spec
- actions/attest-build-provenance + actions/attest-sbom
- GitHub blog: SLSA 3 with GitHub Actions and Sigstore
- Sonatype 2026 Software Supply Chain Report
- GitHub org profile README docs
- GitHub disabling issues/discussions/sponsor docs
- GitHub reusable workflows docs
- PolyForm Strict 1.0.0 / Project Licenses
- Open Source Licenses 2026 Guide
- suckless philosophy; Hundred Rabbits org; SerenityOS README; Pluralistic POSSE; 9fans/plan9port
- OSSF maintainer-guide.md (vulnerability disclosure)
- github/automatic-contrib-prs; roots/issue-closer-action
