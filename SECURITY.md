# Security policy

This repository is published by Hapax Research Lab. Public repository surfaces are not a multi-tenant product, customer-data processor, or public auth service. That boundary is a scope statement, not a warranty about every internal integration.

## Disclosure path

Send security disclosures to hrl-han@hapaxresearch.com, the address on the lab's contact page. Attach Sigstore-signed disclosure artifacts when applicable. The commitment that covers this address is on that page:

  https://hapaxresearch.com/about/#contact

Sigstore's keyless signing associates each signature with an OpenID Connect identity through a short-lived certificate, and logs the signing event in Rekor, a signature transparency log.

Address check (fails if the contact page no longer carries its contact anchor or this address):

```bash
curl -fsSL https://hapaxresearch.com/about/ | grep -qF 'id="contact"' && curl -fsSL https://hapaxresearch.com/about/ | grep -qF 'hrl-han@hapaxresearch.com'
```

## Scope

In scope: exposure of secrets or private material in public commits/artifacts, public-egress bypasses, supply-chain or workflow weaknesses, and concrete remotely exploitable defects. Out of scope: feature requests for multi-tenancy, RBAC, federated identity, general hardening consultations, or integration support.

## Response time

Best effort; no SLA. Messages sent to this address fall under the commitment stated on the contact page: "The network commits to receipt, retention and published correction. It promises no response time." The page also says: "Today one person inside the network is the first reader of incoming mail, so a correction request currently reaches the network through that person." Critical disclosures, such as remote code execution or leaked secrets in published commits, are triaged out of band as soon as they are read, not deferred to a maintenance window. Other reports wait for one.

## Advisory record

This rendered policy does not maintain a complete dated advisory ledger. Current advisories, if any, belong in release notes, security notices, or publication-bus records with their own dates and receipts.

---

This file is rendered from `hapax-constitution/sdlc/render/`. Edits are overwritten on next render.
