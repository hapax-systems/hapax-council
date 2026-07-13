# Public Copy Rewrite Matrix Plan

Date: 2026-07-08

Status: planning artifact. This document captures public-copy rewrite research
and the required control shape before new public-facing copy is written. It is
not itself public copy, publication authority, feature evidence, legal advice,
or a claim grant.

## Throughline

The frontmatter rewrite is not a prose polish pass. It has to become a governed
copy system:

`value proposition -> technical evidence -> audience -> claim ceiling -> surface -> freshness witness`

Copy should compete on like-for-like buyer questions: can the system route
agents, preserve context, review work, gate writes, show current state, and
produce evidence? The Hapax difference is that authority and evidence are the
surface. Public copy should make visible what an agent estate can do, what it is
allowed to do, and what evidence would be required before a stronger claim or
write is permitted.

Claim ceilings are part of the value proposition. They should not be buried as
apologetic disclaimers.

## Non-Negotiable Rules

- Use `hapax-systems` for first-party GitHub organization links. Do not seed new
  copy from stale `ryanklee` repository paths.
- Do not describe the portfolio as open source. Say repo-specific public,
  source-available, source-visible, or permissive surfaces.
- Do not use `MIT` except for `agentgov` and `hapax-mcp`, unless a repo-local
  license authority says otherwise.
- Do not describe `hapax-constitution` as blanket Apache. It has a split
  posture: specification/publication metadata versus runnable `hapax-sdlc`
  tooling.
- Do not imply Reins, hapax-spine, hapax-council, Officium, phone, watch, or
  coord rights/support from `agentgov` adoption copy.
- Do not claim autonomous write authority, full lifecycle generality,
  unrestricted portability, comparative superiority, or staffed support unless
  release gates and fresh evidence support the claim.
- Keep internal acronyms out of top-level copy when there is a public name:
  prefer Claim Verification Council over CCTV, Capability Frontier over harness
  inventory, and Reins cockpit over generic command center.
- Treat public egress, weblog, RSS, social, DOI/archive, support pages, and
  omg.lol surfaces as publication-bus channels with receipts, not as side
  channels.

## Copy Surfaces

Priority key:

- P0: rewrite or quarantine before public convergence copy.
- P1: rewrite during convergence before wider visibility or reuse.
- P2: support cleanup after P0/P1 controls exist.

| Priority | Surface | Current issue | Required source of truth |
|---|---|---|---|
| P0 | `hapax-constitution--metadata-owner/sdlc/render/repos.yaml` and renderers | Central repo copy is close, but still repo-level; it lacks feature-level value propositions, audience weights, and claim freshness triggers. | Merged public-copy registry projection plus renderer checks. |
| P0 | `hapax-systems--github/profile/README.md` | Main org front door is improved but should be regenerated after naming, license, and value matrix convergence. | Constitution renderer plus public-copy registry. |
| P0 | Live GitHub repo descriptions, topics, license detection, issue settings, community profile | Several descriptions are stale/null/cheesy, license detection can disagree with intended posture, and public settings need live readback. | `scripts/github-public-surface-reconcile.py` plus repo registry. |
| P0 | `ryanklee-profile/README.md` | Still routes Hapax readers through stale personal-profile framing. | Either quarantine or rewrite as pointer to `hapax-systems`. |
| P0 | `agentgov` README, package metadata, docs | Adoption commons wedge; must be practical, narrow, MIT-only, and avoid broader Hapax rights/support claims. | Package source, hook registry, CLI tests, adoption guide. |
| P0 | `reins` README, docs, release metadata | Product front door; must be rewritten around read/preview ceiling, BSL posture, Reins layout taxonomy, and non-cheesy commercial value. | Reins layout-boundary plan, smoke tests, release artifacts, BSL authority. |
| P0 | `hapax-council` README, `START_HERE.md`, citation/archive/package metadata, `.github` metadata, public drafts | Needs ground-up rewrite; current copy has stale claims, absolute language, support/intake drift, and unresolved package/license boundaries. | Council public-copy registry, claim/audience validation, live runtime freshness receipts. |
| P0 | `hapax-constitution` README/docs/metadata | Authority repo; split license posture must be precise before downstream copy trusts it. | Current metadata-owner renderer and registry. |
| P0 | weblog, omg.lol, RSS, social, DOI/archive, publication-bus channels | Local weblog receipts are stale and landing/support/public fanout copy can bypass current claim controls if not bound to source/freshness. | Publication bus registry, omg source reconcile, publication freshness envelopes. |
| P1 | `hapax-spine` | Commercial core/private now; rewrite before public exposure with BSL and mechanism-not-platform boundary. | BSL license, spine API/ledger/policy evidence. |
| P1 | `hapax-officium` | Internal apparatus visible publicly; copy must avoid HR SaaS, advice engine, or management-product claims. | Officium boundary tests and registry posture. |
| P1 | `hapax-assets` and Pages asset mirror | Per-asset rights can be flattened accidentally. | `_manifest.yaml`, `_NOTICES.md`, asset approval and publication bus records. |
| P1 | `hapax-research-ledger` | Must preserve numeric-only, caveated evidence posture. | Ledger schemas, latest data, review gates. |
| P1 | Historical repo-pres scaffolds and wiki/profile templates | Old `ryanklee` scaffolding can contaminate new copy. | Quarantine or regenerate from current registry. |
| P2 | `hapax-mcp` | Supporting bridge; avoid general MCP framework positioning. | Tool contract/API tests and authority boundary docs. |
| P2 | `hapax-phone`, `hapax-watch` | Device sources need strict privacy/non-health posture and license reconciliation. | Device payload schemas, permission lists, stale/degrade tests, license authority. |
| P2 | `hapax-coord` | Private coordination surface; needs public-readiness cleanup before exposure. | Coord source labels, receipt-producing control boundary. |

## Hapax Council Ground-Up Scope

Council needs a rewrite, not a preamble polish.

Primary surfaces:

- `README.md`
- `START_HERE.md`
- `CITATION.cff`
- `codemeta.json`
- `.zenodo.json`
- `pyproject.toml`
- `NOTICE.md`
- `CONTRIBUTING.md`
- `SUPPORT.md`
- `SECURITY.md`
- `.github/FUNDING.yml`
- `.github/ISSUE_TEMPLATE/config.yml`
- `.github/pull_request_template.md`
- `.github/CODEOWNERS`

Secondary surfaces:

- `config/obsidian-publish/Home.md`
- `docs/repo-pres/dot-github-scaffold/**`
- `docs/publication-drafts/**`
- `docs/applications/**`
- `docs/audience/**`
- `docs/published-artifacts/**`
- `packages/agentgov/**`
- `packages/hapax-axioms/**`
- `packages/hapax-refusals/**`
- `packages/hapax-swarm/**`
- `packages/hapax-velocity-meter/**`
- `vscode/package.json`
- `hapax-logos/package.json`
- `obsidian-hapax/package.json`

Council copy must stop using absolute or hype-coded claims such as "cannot
lie", "structurally impossible", "proves what happens", or product-negation
formulas that become a pitch by inversion. The safer frame is: source-visible
research/runtime apparatus for inspecting claim authority, refusal, governed
public egress, route evidence, and coordination under operational pressure.

## Audience Weights

| Weight | Audience | Primary trigger | Evidence required | Tone constraint |
|---:|---|---|---|---|
| 100 | HN/frontpage technical readers | Mechanical governance for AI coding agents that has shipped real work. | Installable hooks, receipts, PR-window audit, public package/repo links, current caveats. | Skeptical, concrete, numbers with caveats. |
| 95 | Directors/technical leaders at mid-sized orgs | Reduce AI-agent delivery risk without banning agents. | Reins demo/read-preview, agentgov pilot guide, evidence packet examples. | Operational and sober; pilot language over platform promise. |
| 92 | Enterprise/compliance/security buyers | Map agent controls to security, supply-chain, and review processes. | SBOM/provenance/security scans, hook limits, support/license boundary. | Procurement-clean; no certification or warranty claims. |
| 90 | OSS adopters | Installable MIT governance hooks without adopting the Hapax estate. | `agentgov` quickstart, examples, tests, package metadata. | Narrow and practical. |
| 88 | Harness/agent-system builders | Governed orchestration, append-only ledgers, capability routing, receipts. | Reins, spine, dispatch/read APIs, route receipts. | Inspectable mechanism, not generic framework. |
| 85 | Fundamental researchers | Case study, formal surfaces, evidence ledgers, claim/refusal data. | SCED ledger, CVC/CCTV records, limitations, no-user-study disclosure. | Precise, caveated, n=1 honest. |
| 82 | Privacy/AI-safety auditors | Bounded claims, refusals, public egress, AIR/default-deny redaction. | Refusal records, source reconcile, AIR tests/screenshots. | No "impossible to leak" or truth-oracle claims. |
| 70 | MCP/tool integrators | Bounded bridge to Hapax APIs. | Tool list, timeout/error behavior, authority boundary tests. | Integration-focused; not general MCP framework. |
| 65 | Funders/grant/research-support readers | Research infrastructure with receipts and DOI/archive paths. | DOI/CITATION, research-ledger schema, publication receipts. | No perks, access, deliverables, or patron-control framing. |
| 40 | Management-domain reviewers | Safe management-context preparation without people evaluation. | Officium boundaries and tests. | No HR SaaS, employee scoring, or advice engine claims. |

## Value Propositions

| Value proposition | Consumer benefit | Evidence and maturity | Claim ceiling |
|---|---|---|---|
| Evidence-bound portfolio | Readers can see what is shipped, reserved, and evidence-gated. | Org profile, publication hardening, repo registry. Implemented copy policy. | Do not imply full system validity or open-source portfolio. |
| Reins cockpit | Operators can inspect estate state and command previews before granting authority. | Reins read paths, cell grammar, smoke tests. Live read/preview; writes planned. | Read/preview cockpit, not mutating lifecycle system. |
| hapax-spine | Reconstruct and govern delivery state from append-only events and policy evaluators. | Event log, dispatcher policy, route metadata. Alpha package. | Mechanism, not full portable kernel. |
| agentgov | Teams can pilot AI coding-agent hooks without adopting the estate. | Hook registry, CLI, docs. Public alpha. | MIT hook toolkit, not certification or support. |
| hapax-council | Researchers/auditors can inspect real claim authority, refusal, egress, and coordination mechanisms. | Council source, citations, public bus, receipts. Implemented internal apparatus. | Research/runtime artifact, not product/framework. |
| hapax-constitution / hapax-sdlc | Governance and repo metadata become inspectable and renderable. | Axioms, implications, renderers, tests. Implemented spec/tooling. | Spec and gates, not runtime proof. |
| Claim Verification Council | Claims and requests can be decomposed, checked, and refused before action. | Rubrics, intake gate design, request gate. Operational plus designed. | Evidence layer, not truth oracle. |
| Capability Frontier | Routing can be based on measured capability, quota, and authority ceilings. | Capability registry, receipts, route schema. Implemented metadata/receipts. | No universal benchmark or leaderboard. |
| HKP | Knowledge projections can support context without authorizing mutation. | Bundle schema, non-authority rules, exporter. Implemented support path. | Read-only support projection; no source-of-truth claim. |
| Publication bus | Public claims and public egress can be routed, refused, and reconciled. | Surface registry, allowlist, public event witness, published artifacts. Implemented gates. | Events do not themselves publish; surface credentials and receipts matter. |
| Research ledger | Early observations, nulls, and caveats remain inspectable. | Ledger README, schema, data. Public evidence artifact. | Observations only, not adjudicated results. |
| MCP bridge | MCP clients can reach Hapax APIs without becoming the authority source. | hapax-mcp README and API tests. Implemented bridge. | Hapax Logos MCP Bridge only. |
| Phone/watch context sources | Context and biometric ingestion can be inspected with explicit exclusions. | Payload schemas, permission boundaries. Implemented device surfaces. | Not health products; no diagnosis/efficacy claims. |
| Officium | Management context can be prepared without people evaluation claims. | Officium README, codemeta, boundary docs. Source-visible internal artifact. | Not HR SaaS, advice engine, or adoption surface. |
| Assets mirror | Public pages can reuse approved assets with stable URLs and notices. | Manifest, notices, Pages mirror. Public mirror. | Per-asset rights only. |
| Coord dashboard | Operators can inspect readiness and receipts without treating UI as authority. | Coord README and source labels. Private/V0. | UI state is not authority. |
| System dynamics/lenses | Projections can explain system state without claiming completeness. | Dynamics docs, Reins lens, read API. Partial/read projection. | Projection, not proof the system is complete. |
| Labrack/RDLC | Research custody/disposition can become explicit. | Reins honest-dark notes, constitution package notes. Planned/partial. | Planned unless receipts/model layer land. |
| Visual/audio/AIR posture | Public or reviewable surfaces can be gated through AVSDLC and redaction evidence. | AVSDLC docs, Reins AIR, council multimodal paths. Mixed. | Requires fresh witness evidence; no broad privacy guarantee. |

## Feature-To-Benefit Schema

Every feature-level copy item should carry:

- `technical_item`
- `value_proposition_id`
- `tangible_benefit`
- `audience_ids`
- `priority_weight`
- `implementation_maturity`
- `claim_ceiling_ref`
- `proof_artifact_refs`
- `freshness_source`
- `freshness_ttl_s`
- `stale_behavior`
- `target_surfaces`

Placement rule:

- Org profile gets portfolio-level value and ceilings.
- Repo README gets the one concrete reader benefit and the claim ceiling.
- Docs hold mechanics and proof details.
- Weblog carries witnessed cases only.
- Release notes mention newly shipped behavior only with evidence.

## Competitive Positioning

| Comparator | Like-for-like parity | Hapax differentiator | Copy risk |
|---|---|---|---|
| Autonomous coding agents | Issue/PR loop, review, branch/CI, context retrieval. | Govern task authority, route evidence, review gates, and receipts. | Do not claim developer replacement or benchmark dominance. |
| Agent orchestration frameworks | State machines, workflows, shared state, observability. | Governed dispatch with quality floors, mutation gates, quota freshness, and holds/refusals. | Do not reduce Hapax to generic workflow diagrams. |
| SDLC automation/policy-as-code | Pipeline stages, audit trails, checks. | Constitutional gates, disconfirmation, visible blockers, no false green. | Avoid compliance theater. |
| Model councils | Multi-model verdicts and scoring. | Claim checks bind to local sources, route receipts, and evidence adequacy. | CVC is not a truth oracle. |
| Google OKF / knowledge frameworks | Concept files, generated indexes, resource pointers, permissive consumers. | HKP as non-authorizing projection/context. | Do not claim universal knowledge format or mutation authority. |
| Reins-like dashboards | Estate view, tasks, sessions, readiness, command preview. | Honest-dark projection cockpit with authority outside the UI. | Do not imitate glossy command-center/fake-action language. |
| Harness engineering lists | Capability descriptors, adapters, routes, costs. | Measured authority and capability ceilings, not inventory breadth. | Do not become another monotonic harness catalog. |

## License Posture

Use four buckets:

- Adoption commons: `agentgov` under MIT, and only for portable hooks.
- Integration bridge: `hapax-mcp` under MIT, only as a Hapax Logos MCP bridge.
- Commercial core: `reins` and `hapax-spine` under BSL 1.1, source-available,
  self-hosted evaluation/non-competing use invited, hosted-service rights
  reserved until change license/date.
- Source-visible strict artifacts: council, Officium, phone, watch, coord. These
  are inspection/audit artifacts, not open source, support, or community intake
  surfaces.

Known license/copy blockers:

- `hapax-watch` live root has Apache 2.0 `LICENSE` while README/NOTICE/metadata
  say PolyForm Strict.
- `hapax-phone` live root README links `LICENSE`, but the live root checkout is
  missing it; metadata-owner has the PolyForm file.
- `hapax-constitution` main-copy drift can imply blanket Apache despite split
  spec/tooling posture.
- `hapax-coord` root has only README while metadata-owner carries PolyForm and
  generated boundaries.

2026-07-08 follow-up readback:

- `hapax-constitution` is the remaining true license-authority blocker: remote
  main still has an Apache-2.0 root `LICENSE` while rendered public metadata
  declares a split CC BY-NC-ND specification/publication posture plus
  Apache-2.0 tooling. Do not treat downstream generated license copy as final
  until the split-license authority is implemented, not merely described.
- The watch, phone, and coord license/copy mismatches were confirmed in stale
  local worktrees, while current default branches carry the generated PolyForm
  metadata. Treat them as rebase/merge-result verification blockers rather
  than new legal decisions unless a PR would regress those files.
- GitHub license detection for PolyForm and BSL repos may report `NOASSERTION`;
  public-surface gates should prove the repo authority files and set expected
  detection behavior rather than claiming GitHub's detected license aligns.

2026-07-08 landing-slice readback (multi-agent recon, workflow
wf_49a0482f-006, 61 agents; fixes landed on this branch):

- `public_surface_freshness` is now a member of the `all-green` required
  aggregate and of `hooks/gate-manifest.yaml` ci.jobs, so the registry check
  is merge-blocking. It still validates registry structure only; content
  claim checks and stale predicates remain outside CI (docs-only paths can
  change root `*.md` without a claim scan).
- `check-public-surface-claims.py` carries a hardcoded, non-expiring waiver
  for exactly the constitution Apache-vs-CC-BY-NC-ND drift. Delete the waiver
  as part of the split-license implementation, not before.
- Marker families diverge: the constitution renderer emits
  `hapax-sdlc:preamble` markers while this plan specifies
  `hapax-public:surface=<id>`. Converge on one family before flipping
  `generated_section_required`.
- The reconcile engine required every drift category to appear yet emitted
  findings only on drift, so a healthier estate invalidated the report
  (`contributing_governance` vanished when GOVERNANCE.md landed). Fixed:
  every required category now carries a positive `ok` witness when clean.
- Fresh reconcile (2026-07-08) confirms `reins` license detection is
  `NOASSERTION` against registry `BUSL-1.1`. Needed mechanism: an
  `expected_github_license_detection` field in `repo-registry.yaml` plus an
  authority-file-presence check in `shared/github_public_surface.py`,
  replacing the raw detected-vs-policy comparison.
- Public clip egress attributed content to `hapax.github.io`, which belongs
  to an unrelated third-party GitHub account; re-pointed to
  `https://hapax.weblog.lol` with the sponsors/dead rails replaced by the
  no-perk support page. `agents/citable_nexus/renderer.py` still assumes
  `https://hapax.research` as canonical, and that domain does not resolve —
  settle the canonical domain before publishing citable-nexus pages.
- Live org-profile blockers confirmed: the profile asserts the constitution
  split license (live root LICENSE is Apache-2.0) and calls private
  `hapax-spine` source-available. Regenerate the profile after the
  split-license landing and spine posture decision.
- `ryanklee/ryanklee` profile README carries now-false claims (hapax-mcp,
  watch, and phone described as private; retired Gemini-CLI coordination
  claims). P0 remediation independent of this branch.
- Renderer wording fixes are global but only council and spine are
  re-rendered here; constitution main, agentgov, and the org profile still
  serve superseded copy (including "Past advisories: None to date").
  Schedule a re-render wave across the remaining targets after this lands.

Next control increments, in dependency order: (1) enum/ref validation for
registry `stale_behavior`/`claim_ceiling_ref` values; (2) registry↔freshness
envelope surface-id join; (3) marker emission in the constitution renderer;
(4) flip `generated_section_required`; (5) registry-driven stale predicates in
the full gate; (6) gate-manifest/release/autoqueue public-copy wiring;
(7) publication-bus frontmatter invariants plus readback receipts.

## Freshness And Accuracy Mechanics

Existing pieces:

- Constitution renderers already generate README preambles, NOTICE, SUPPORT,
  SECURITY, GOVERNANCE, CONTRIBUTING, CITATION, codemeta, and Zenodo metadata.
- Council has GitHub public-surface reconciliation, public-claim gates,
  publication-bus registries, weblog/omg source reconciliation, and publication
  freshness envelopes.
- Obsidian Publish has a wrapper and repo-owned Home page.

Gaps:

- There are parallel registries: workspace `repos.yaml`, constitution
  `sdlc/render/repos.yaml`, and council `docs/repo-pres/repo-registry.yaml`.
- Current GitHub and omg/weblog reports can become stale and should not support
  current/live claims without refresh.
- The checked-in GitHub public-surface reconcile can lag default branches and
  omit repos such as coord/spine; current/live public-copy claims require a
  fresh reconcile that includes every intended public repo.
- Public-copy checks can be skipped by docs-only paths.
- `check-public-surface-claims.py` does not yet discover README/profile/package,
  release, Obsidian, and rendered constitution surfaces from a registry.
- Claim ceilings exist in domain-specific receipts, but not yet as a unified
  per-feature/per-surface mechanism.

Required control shape:

1. Create one public-surface registry/projection with:
   `surface_id`, path globs, owner, audience refs, source registry refs,
   generated-section markers, claim ceiling ref, freshness TTL, live-state
   builder, publication-bus surface, and required gates.
2. Treat workspace identity/URL inventory, council license/value partition, and
   constitution renderer inputs as one merged generated view.
3. Use generated sections for claim-bearing copy:
   `<!-- hapax-public:surface=<id>:begin/end -->`.
4. Promote `ClaimRecord` and `SurfaceContract` into the shared claim-ceiling
   mechanism.
5. Add stale predicates for report `generated_at`, local repo head, GitHub
   default SHA, package README hashes, publication log latest event, RSS/fanout
   receipts, and runtime witness age.
6. Add a non-skippable `public-surface-freshness` PR job for public paths.
7. Wire the public-copy gate into `hooks/gate-manifest.yaml`, release gates, and
   autoqueue admission.
8. For weblog/publication bus sync, require frontmatter fields:
   `surface_id`, `claim_ceiling_ref`, `source_refs`, and
   `publication_gate_context`; after publish, require readback/fanout receipts
   before current/live copy lands.

## Implementation Sequence

1. Finish repository/naming/license convergence before final copy.
2. Land Reins layout-boundary convergence so `:session`, `:sessions`, and
   `:yard` have stable public meanings.
3. Fix or quarantine license blockers for watch, phone, constitution, and coord.
4. Build the public-copy registry/projection and surface-contract schema.
5. Expand claim checks to registry-discovered public surfaces.
6. Add public-copy freshness gates to CI and release/autoqueue paths.
7. Rewrite P0 copy from the registry:
   org profile, live GitHub metadata, agentgov, Reins, council, constitution,
   weblog/omg landing and publication surfaces.
8. Rewrite P1/P2 surfaces after P0 gates prove stable.

## Immediate Open Questions

- Which repo owns the canonical merged public-copy registry: constitution,
  council, or a generated projection from both?
- Should stale `ryanklee-profile` be rewritten as a pointer, archived, or made
  intentionally personal and non-Hapax?
- Which feature claims can be current/live versus archive-only after the next
  GitHub and omg/weblog readback refresh?
- Which commercial surfaces should be public now versus held until BSL/support
  posture and sales/support workflows exist?
- Should package-level READMEs inside council be rewritten as council-internal
  evidence surfaces, split into separate repos, or hidden from public copy
  surfaces until packaging boundaries are stable?
