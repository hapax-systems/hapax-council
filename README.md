<!-- hapax-sdlc:preamble:begin -->

# hapax-council

`hapax-council` is a constituent of the Hapax operating environment. It is research or boundary infrastructure published as an artifact, not a staffed product or community project.

## Reader promise

Inspect how AI-agent work is authorized, routed, reviewed, refused, and surfaced publicly inside the Hapax estate.

## Reader value

Lets technical leaders, researchers, and auditors evaluate concrete controls: what may run, what may write, what evidence exists, and where stale or unsupported claims fail closed.

## Claim ceiling

Source-visible research runtime and current case study only. Not a portable platform, adoption package, product front door, support surface, or open-source project.

## License and rights

Source-visible strict research/runtime artifact; not open source, not a framework, not a supported distribution.

Rendered summary: PolyForm Strict 1.0.0 (source-available, non-distribution, non-modification). See `LICENSE`, `NOTICE.md`, `CITATION.cff`, and `.zenodo.json` for the authority surfaces.

## Public boundary

- Issues are redirect-only; no discussions, no pull requests accepted; see `CONTRIBUTING.md` and `SUPPORT.md`
- Public copy must use `hapax-systems` organization links for first-party Hapax repositories.
- README text is orientation, not a freshness witness; current public claims require surface-specific release, reconcile, or publication receipts.
- Publication, weblog, RSS, social, DOI/archive, and other public fanout paths must route through the governed publication bus or a documented guarded legacy surface.
- Governance reference: https://github.com/hapax-systems/hapax-constitution

## Portfolio position

Primary research/runtime estate. Carries task authority, coordination, route evidence, claim and publication gates, refusal records, and public-egress controls. Consumes the constitution via the hapax-sdlc package.

<!-- hapax-sdlc:preamble:end -->

# hapax-council

[![CI](https://github.com/hapax-systems/hapax-council/actions/workflows/ci.yml/badge.svg)](https://github.com/hapax-systems/hapax-council/actions/workflows/ci.yml)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20113515.svg)](https://doi.org/10.5281/zenodo.20113515)
[![License: PolyForm Strict](https://img.shields.io/badge/license-PolyForm%20Strict%201.0.0-blue)](LICENSE)

`hapax-council` is the source-visible live research/runtime behind Hapax
Systems. It is where task authority, route evidence, claim review, refusal,
coordination, and public-egress controls are implemented against a real
single-operator AI-agent estate.

The practical question is not whether an agent can complete an isolated task.
It is whether agent work carries enough authority, evidence, and freshness to
be trusted, reviewed, refused, or published. The UI, the model, and the README
are not the source of truth.

## Reader Map

| Reader | What to inspect | Tangible value |
|---|---|---|
| Technical leaders | `scripts/hapax-methodology-dispatch`, `scripts/cc-claim`, route receipts, PR gates | See how AI-agent work can be bounded by task authority, route capability, and evidence before write access matters. |
| Harness and agent-system builders | capability registry, review routes, lane state, Reins integrations | Compare orchestration mechanics against a system that treats admission, refusals, and stale evidence as first-class concerns. |
| Researchers | claim gates, refusal records, publication bus, research ledgers | Study agentic claim authority and correction behavior in a live, privacy-constrained environment. |
| Security and privacy reviewers | public-surface gates, redaction paths, publication freshness checks | Audit where public claims and public egress fail closed instead of relying on policy prose. |
| OSS adopters | [agentgov](https://github.com/hapax-systems/agentgov) | Pilot the portable MIT hook boundary without adopting this stricter research/runtime estate. |
| Product evaluators | [reins](https://github.com/hapax-systems/reins) | Inspect the cockpit/read-preview layer that shows state and proposed writes before authority is granted. |

## What This Repository Makes Legible

| Technical item | Reader benefit | Current claim ceiling |
|---|---|---|
| cc-task and methodology dispatch | Work is attached to an authority case, parent spec, lane, and declared mutation surface. | Shows the live Hapax control pattern; not a packaged enterprise workflow product. |
| Capability and route receipts | Model, tool, quota, and route choices can be reviewed as evidence rather than inferred from logs. | Evidence-bound routing surface; not a universal benchmark or provider certification. |
| Review and merge gates | PRs can carry tests, review dossiers, stale-state blockers, and queue/readback evidence. | Current SDLC apparatus; not a guarantee that every historical PR is complete or exemplary. |
| Claim and public-surface gates | Public statements are checked against source, freshness, and publication eligibility. | Claim discipline mechanism; not proof of truth by itself. |
| Publication bus | Weblog, RSS, archive, support, and other public fanout paths are treated as governed egress surfaces. | Egress control and receipts; events do not themselves prove a claim is publishable. |
| Refusal and boundary records | Unsupported, unsafe, stale, or out-of-scope requests can become explicit refusal artifacts. | Research material and operational control; not a general moral authority system. |
| Reins coupling | The cockpit can read estate state and preview commands without making the UI the authority source. | Read/preview and selected control paths only; mutating claims need current Reins receipts. |
| Extracted packages | Some reusable pieces are separated into narrower repos or packages. | Repo-local license and support boundaries apply; this repository does not grant broader rights. |

## Portfolio Boundaries

| Need | Correct surface | Boundary |
|---|---|---|
| Portable governance hooks | [agentgov](https://github.com/hapax-systems/agentgov) | MIT adoption commons; narrow hook toolkit only. |
| Cockpit/read-preview product surface | [reins](https://github.com/hapax-systems/reins) | Source-available commercial core; read/preview ceiling unless fresh receipts say more. |
| Metadata, licenses, support posture, claim ceilings | [hapax-constitution](https://github.com/hapax-systems/hapax-constitution) | Governance spec plus `hapax-sdlc` render tooling; not the runtime. |
| Numeric observations and caveated evidence | [hapax-research-ledger](https://github.com/hapax-systems/hapax-research-ledger) | Evidence artifact; not adjudicated results. |
| This research runtime | `hapax-council` | Source-visible strict research/runtime; not open source, not a support surface, not a framework. |

## Public-Current Standard

This README is orientation, not a freshness witness. Treat a claim as
public-current only when the relevant source has a fresh receipt:

- live GitHub public-surface reconciliation for repository metadata,
- release or PR gate output for shipped behavior,
- publication-bus receipts for weblog/RSS/archive/social fanout,
- Reins or council runtime witness for current operational state,
- package-local tests and metadata for extracted packages.

If the receipt is missing, stale, or outside the named surface, the safe reading
is "inspectable mechanism or plan," not "current shipped capability."

## What Not To Infer

- This repository is not open source. It is published under PolyForm Strict
  1.0.0 unless a subpackage declares a narrower local posture.
- GitHub Issues are redirect-only. There is no public support queue, community
  governance process, or contributor onboarding path.
- The system does not claim unrestricted autonomous write authority, general
  portability, model superiority, or staffed commercial support.
- Public channels are not side channels. Weblog, RSS, social, DOI/archive,
  support, and related surfaces must pass through governed publication controls
  or a documented guarded legacy path.

## Public Surfaces

| Surface | Role |
|---|---|
| [`START_HERE.md`](START_HERE.md) | Short reviewer dossier and reading order. |
| `agents/publication_bus/` | Source-visible publication registry, publishers, fanout, and refusal controls. |
| `shared/github_public_claim_gate.py` and `scripts/check-public-surface-claims.py` | Public-claim and public-file gate logic. |
| `docs/repo-pres/` | Public-surface reconciliation, rewrite matrices, and repository-presentation plans. |
| `docs/publication-drafts/` | Draft copy that is not publishable without current claim and publication review. |
| `docs/published-artifacts/` | Citation, archive, and public artifact records. |
| [Support Hapax research](https://hapax.weblog.lol/support) | No-perk support boundary; payment creates no rights, SLA, access, or product commitment. |
| `SUPPORT.md` / `CONTRIBUTING.md` / `SECURITY.md` | Redirect, refusal, and disclosure boundaries. |

## Verification Contract

CI typecheck uses the fast path:

```bash
uv run --no-project --with pyrefly==0.64.1 pyrefly check
```

The weekly typecheck safety net runs Pyright:

```bash
uv run pyright
```

## License

PolyForm Strict 1.0.0. See [LICENSE](LICENSE), [NOTICE.md](NOTICE.md), and
[CITATION.cff](CITATION.cff).
