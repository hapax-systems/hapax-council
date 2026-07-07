<!-- hapax-sdlc:preamble:begin -->

# hapax-council

`hapax-council` is a constituent of the Hapax operating environment. It is research or boundary infrastructure published as an artifact, not a staffed product or community project.

## Reader promise

Primary live Hapax estate and research artifact for readers auditing how governance, perception, coordination, public egress, and refusal operate under one single-operator system.

## Claim ceiling

Research/runtime apparatus only; not a reusable platform, harness, product, support surface, or open-source project.

## License and rights

Source-visible strict research/runtime artifact; not open source, not a framework, not a supported distribution.

Rendered summary: PolyForm Strict 1.0.0 (source-available, non-distribution, non-modification). See `LICENSE`, `NOTICE.md`, `CITATION.cff`, and `.zenodo.json` for the authority surfaces.

## Public boundary

- Issues are redirect-only; no discussions, no pull requests accepted; see `CONTRIBUTING.md` and `SUPPORT.md`
- Public copy must use `hapax-systems` organization links for first-party Hapax repositories.
- Publication, weblog, RSS, social, DOI/archive, and other public fanout paths must route through the governed publication bus or a documented guarded legacy surface.
- Support Hapax research routes through the no-perk public page at https://hapax.weblog.lol/support.
- Governance reference: https://github.com/hapax-systems/hapax-constitution

## Portfolio position

Primary research/runtime artifact. Carries governance, coordination, evidence, refusal, and publication-bus surfaces. Consumes the constitution via the hapax-sdlc package.

<!-- hapax-sdlc:preamble:end -->

# hapax-council

[![CI](https://github.com/hapax-systems/hapax-council/actions/workflows/ci.yml/badge.svg)](https://github.com/hapax-systems/hapax-council/actions/workflows/ci.yml)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20113515.svg)](https://doi.org/10.5281/zenodo.20113515)
[![License: PolyForm Strict](https://img.shields.io/badge/license-PolyForm%20Strict%201.0.0-blue)](LICENSE)

`hapax-council` is the source-visible research/runtime artifact behind Hapax
Systems.

It is published so technical readers can inspect how a real single-operator
agent estate handles governance, coordination, evidence, refusal, and public
egress under continuous development pressure. It is not an adoption package,
not a supported framework, and not the commercial product front door.

## Reader Map

| Reader Need | Start Here |
|---|---|
| Portable governance hooks | [agentgov](https://github.com/hapax-systems/agentgov) |
| Product cockpit and command preview | [reins](https://github.com/hapax-systems/reins) |
| Governance specification and repo metadata authority | [hapax-constitution](https://github.com/hapax-systems/hapax-constitution) |
| Research/runtime inspection | this repository |
| Public-safe evidence ledger | [hapax-research-ledger](https://github.com/hapax-systems/hapax-research-ledger) |

## What This Repository Shows

- A governed task and lane system with explicit authority, route metadata,
  evidence, and closeout records.
- Runtime and review machinery for claim checking, public-surface gating,
  refusal records, and publication-bus fanout.
- Research apparatus for studying governed AI-agent work as it happens,
  including source-visible failures, blocked claims, and redaction paths.
- Integration points consumed by source-available or adoption-surface repos,
  including Reins and agentgov.

## What Not To Infer

- The repository is not open source. It is published under PolyForm Strict
  1.0.0 unless a subpackage or asset declares a narrower local posture.
- GitHub Issues are redirect-only. There is no public support queue, community
  governance process, or contributor onboarding path.
- Public material may describe shipped read paths, dispatch mechanisms,
  evidence ledgers, and publication-bus controls. It must not claim autonomous
  write authority, unrestricted portability, or general framework status.
- Direct public egress is not a reader-facing affordance. Weblog, RSS, social,
  DOI/archive, and other public channels are governed publication-bus surfaces.

## Public Surfaces

| Surface | Role |
|---|---|
| `agents/publication_bus/` | Source-visible publication-bus registry and publisher implementations. |
| `docs/publication-drafts/` | Draft public copy. Drafts are not publishable unless their frontmatter says so and current claim review passes. |
| `docs/published-artifacts/` | Public artifact ledger and archive metadata. |
| `START_HERE.md` | Reader guide for navigating the research artifact. |
| `SUPPORT.md` / `CONTRIBUTING.md` | Redirect and refusal boundaries. |

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
