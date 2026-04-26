# Refusal Brief: CODE_OF_CONDUCT.md

**Slug:** `repo-pres-code-of-conduct-REFUSED`
**Axiom tag:** `single_user`
**Refusal classification:** Refuse-by-omission — CoC presumes a community to govern; Hapax is single-operator.
**Status:** REFUSED — no `CODE_OF_CONDUCT.md` in any first-party Hapax repo.
**Date:** 2026-04-26
**Related cc-task:** `repo-pres-code-of-conduct-REFUSED`
**Related work:** drop-4 §5 (refusal-shaped repo presentation)

## What was refused

`CODE_OF_CONDUCT.md` files in any of the first-party Hapax repos:

- `ryanklee/hapax-council`
- `ryanklee/hapax-officium`
- `ryanklee/hapax-constitution`
- `ryanklee/hapax-mcp`
- `ryanklee/hapax-watch`
- `ryanklee/hapax-phone`
- `ryanklee/hapax-assets` (when bootstrapped)
- `ryanklee/dotfiles`
- `ryanklee/hapax-private` (governance / non-public)

The Contributor Covenant template, the Microsoft Open Source CoC,
the Mozilla CPG, and similar CoC templates are all REFUSED — not
because of any specific concern with their content, but because
each presumes a multi-contributor community. Hapax has no such
community.

## Why this is refused

### Single-operator axiom

The single-operator axiom is constitutional (`single_user`, weight
100). It states explicitly that Hapax is one operator on one
workstation; there is no multi-tenant collaboration model. CoC
templates assume the opposite: multiple contributors with diverse
backgrounds, conduct disputes that require third-party arbitration,
report-and-investigate workflows.

These presumptions cannot hold for Hapax. There is no contributor
diversity to protect; there is no third-party arbitrator; there are
no conduct disputes that don't reduce to "operator self-correcting"
(which is not a CoC matter).

### Refuse-by-omission

Per drop-4 §5: refusing CoC across all repos is the constitutionally-
correct posture. The absence is itself the artefact:

- An external observer reading the repo sees no CODE_OF_CONDUCT.md
- This signals: Hapax is not soliciting contributions
- Contribution surfaces are walled per `repo-pres-issues-redirect-walls`
  + `leverage-REFUSED-github-discussions-enabled`
- The constitutive position is documented in the operator-referent
  policy + axiom registry

Adopting a CoC would falsely signal a community-governance posture
that contradicts the constitutional reality. Refusal by omission is
honest; CoC adoption would be performative.

## Daemon-tractable boundary

There is no daemon-tractable boundary for CoC refusal. CoC absence
is a static property of the repo tree; the absence itself is
self-enforcing (no daemon needs to actively maintain the refusal).

The companion enforcers do daemon-tractable work:
- `repo-pres-issues-redirect-walls` — Issues template + GitHub
  Discussions disabled
- `leverage-REFUSED-github-discussions-enabled` — refusal-brief
  for the Discussions surface (already shipped in #1567)

## Refused implementation

- NO `CODE_OF_CONDUCT.md` in any first-party Hapax repo
- NO `.github/CODE_OF_CONDUCT.md` in any first-party org template
- NO references to CoC adoption in CONTRIBUTING.md (since
  CONTRIBUTING.md itself is also refusal-adjacent — contributions
  are not solicited)
- NO CI guard required (the absence is self-enforcing; adding a
  CoC would be a deliberate operator action)

## Lift conditions

This refusal lifts only if the `single_user` axiom is amended at
`hapax-constitution`. Such an amendment would constitute a
fundamental constitutional change — single_user is one of the
3 constitutional axioms (vs the 2 domain axioms).

The `refused-lifecycle-constitutional-watcher` daemon (when shipped)
will check the axiom registry per its cadence policy. Probe path:
`~/projects/hapax-constitution/axioms/registry.yaml`. Lift keyword:
absence of the `single_user` axiom.

## Cross-references

- cc-task vault note: `repo-pres-code-of-conduct-REFUSED.md`
- Sibling refusal: `leverage-REFUSED-github-discussions-enabled`
  (refused for the same single-operator-axiom reason)
- Companion enforcer: `repo-pres-issues-redirect-walls` (Issues
  surface disposition)
- Constitutional anchor: `hapax-constitution/axioms/registry.yaml`
  (`single_user` axiom)
- Source research: drop-4 §5 (refusal-shaped repo presentation)
