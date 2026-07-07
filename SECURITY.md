# Security policy

A single individual (Oudepode The Operator) operates this repository. It runs in a single-operator deployment with no external users, no auth surface, and no third-party data residency.

## Disclosure path

Submit security disclosures via the Sigstore-signed disclosure channel at:

  https://hapax.weblog.lol/contact

Repository surfaces do not publish email by constitutional choice. The Sigstore path verifies disclosure authorship via OpenID Connect, eliminating the need for PGP key exchange or private email correspondence.

## Scope

Security reports about deployment hardening, architectural choices, or features absent from a single-operator system (multi-tenancy, RBAC, federated identity) are out of scope; the single-operator axiom forecloses these.

## Response time

Best-effort, single-operator basis; no SLA. The next maintenance window handles critical disclosures such as remote code execution or secret leaks in published commits.

## Past advisories

None to date.

---

This file is rendered from `hapax-constitution/sdlc/render/`. Edits are overwritten on next render.
