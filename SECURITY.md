# Security policy

A single individual operates this repository in a single-operator deployment. Public repository surfaces are not a multi-tenant product, customer-data processor, or public auth service. That boundary is a scope statement, not a warranty about every internal integration.

## Disclosure path

Submit security disclosures through the contact page. Attach Sigstore-signed disclosure artifacts when applicable:

  https://hapax.weblog.lol/contact

Repository surfaces do not publish email by constitutional choice. Sigstore signatures let the operator verify authorship via OpenID Connect without publishing an email address.

Endpoint recheck:

```bash
curl -fsSIL https://hapax.weblog.lol/contact
```

## Scope

In scope: exposure of secrets or private material in public commits/artifacts, public-egress bypasses, supply-chain or workflow weaknesses, and concrete remotely exploitable defects. Out of scope: feature requests for multi-tenancy, RBAC, federated identity, general hardening consultations, or integration support.

## Response time

Best-effort, single-operator basis; no SLA. Critical disclosures such as remote code execution or leaked secrets in published commits are triaged out of band immediately; other reports wait for a maintenance window.

## Advisory record

This rendered policy does not maintain a complete dated advisory ledger. Current advisories, if any, belong in release notes, security notices, or publication-bus records with their own dates and receipts.

---

This file is rendered from `hapax-constitution/sdlc/render/`. Edits are overwritten on next render.
