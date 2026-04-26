# Security Architecture

This document describes the security posture of `hapax-council`. It
prioritises honesty over assurance theatre — the constitutional
substrate is single-operator, the threat model is local, and "no
defence-in-depth" is a deliberate scope-control.

## Security model overview

This is a **single-operator personal tool**. The `single_user`
constitutional axiom (weight: 100) explicitly prohibits authentication,
authorisation, multi-user features, role management, and administrative
interfaces. These are not missing features — they are T0 violations
that must not be built (`axioms/registry.yaml`,
`axioms/implications/single-user.yaml`).

The security model relies entirely on:

- Localhost-only network binding (no service exposed beyond 127.0.0.1
  except the operator-owned Tailnet at 100.64.0.0/10 for the operator's
  watch + phone)
- OS-level access control (only the operator has access to the
  workstation)
- GPG-encrypted secret storage (`pass`)
- Hardware watchdog + greetd autologin for 24/7 recovery (see
  `systemd/README.md`)

If an attacker has local console access to the workstation, they have
full access to all data and services. There is no credential gating
against that scenario; the constitutional substrate does not pretend
otherwise.

## Network boundary

All Docker containers (LiteLLM, Qdrant, PostgreSQL, Langfuse,
Prometheus, Grafana, Redis, ClickHouse, MinIO, n8n, ntfy, OpenWebUI,
Loki) bind to `127.0.0.1` only. The Logos API on `:8051` listens on
loopback + the Tailnet IP `100.117.1.83` so the operator's Wear OS
watch and Android phone can stream sensor data.

The studio compositor publishes to a local MediaMTX relay at
`127.0.0.1:1935`; only the upstream YouTube RTMP push reaches the
public network, and that flow carries livestream output (operator-
authored content) only.

No service exposes a write API beyond the operator's own devices on
the Tailnet.

## Secrets management

Secrets live in `pass` (GPG-encrypted, file-based). They reach service
processes via `direnv` (`.envrc` is gitignored) or `EnvironmentFile=`
clauses in systemd units. Per-publisher pass-keys are catalogued in
`agents/publication_bus/wire_status.py`; the `--check-creds` CLI mode
reports live presence without exposing values:

```bash
uv run python -m agents.publication_bus --check-creds
```

No `.env` files are committed. No secrets are passed via command-line
arguments. The `axiom-commit-scan.sh` pre-commit hook catches secret-
shaped strings before they enter git history.

## Refusal-as-data substrate

A constitutional posture, not a security control: every refused-by-
design surface (Stripe payment links, ML-based inbox classifiers,
unverified webhook receivers, etc.) emits a structured refusal-event
into `/dev/shm/hapax-refusals/log.jsonl`. The refusal-brief library at
`docs/refusal-briefs/` documents the architectural reasoning per
surface; the substrate at `agents/refused_lifecycle/` re-evaluates
each refusal on the appropriate cadence (weekly HTTP probe,
inotify-driven on axiom change, or cc-task close-event).

This means: when this document says "we don't do X", the assertion is
backed by code that prevents X from being added without an explicit
constitutional amendment, not just by the absence of code today.

## What this system is NOT

- **Not multi-tenant.** The `single_user` axiom prohibits it.
- **Not designed for network exposure.** If the Logos API binding
  drifts off `127.0.0.1` and the Tailnet IP, the entire model breaks.
- **Not audited.** No external security review. The audit substrate is
  the operator's own absence-bug epic (`docs/research/2026-04-26-*`)
  catching shipped-but-unwired surfaces.
- **Not compliant with any framework.** SOC 2, ISO 27001, GDPR — none
  apply. This is a personal workstation tool.

## Known limitations

- **No TLS between local services.** Plaintext HTTP over loopback or
  the Tailnet. A compromised container could sniff inter-service
  traffic; nothing leaves the machine + Tailnet.
- **No authentication on the Logos API.** Port `8051` serves 60+ REST
  endpoints with no auth, protected only by the loopback + Tailnet
  binding.
- **No encryption at rest.** Qdrant, PostgreSQL, ClickHouse, MinIO
  store data unencrypted on Docker volumes. Full-disk encryption (if
  enabled at the OS level) is the only protection.
- **No rate limiting.** Any localhost process can flood any service.
- **LLM API egress.** Refusal events, prompts, and responses transit
  Anthropic / Google APIs via LiteLLM. Cloud-provider data-retention
  policies apply to that flow; the operator accepts the trade-off.
- **Cross-worktree contamination risk.** Multiple Claude sessions
  operate concurrent worktrees; branch-pollution between worktrees has
  caused incidents (see gamma's worktree-allocation-crisis inflection
  2026-04-26T19:15Z). Hooks under `hooks/scripts/` enforce branch
  discipline but the system is layered, not absolute.

## Responsible disclosure

This is a personal project. There is no bug-bounty programme and no
security team. The disclosure path uses **Sigstore-signed artefacts**
posted to the operator's `omg.lol` weblog, NOT email. Email-based
disclosure assumes a person to receive + act, which is constitutionally
incompatible with full-automation; Sigstore provides a cryptographic
disclosure surface that the operator can verify on receipt.

To disclose a security finding:

1. Compose a plaintext disclosure document. Include the affected
   commit SHA, reproduction steps, and impact.
2. Sign the document with `cosign` (Sigstore keyless via OIDC
   identity is acceptable):

   ```bash
   cosign sign-blob --output-signature disclosure.sig \
     --output-certificate disclosure.pem disclosure.txt
   ```

3. Post the disclosure + signature + certificate to either:
   - The operator's `omg.lol` weblog (`hapax.weblog.lol`)
   - `ryanklee/.github` Discussions (note: GitHub Issues are
     intentionally OFF on every council-published repo per the
     `repo-pres-issues-redirect-walls` constitutional posture; use
     Discussions only)

4. The operator monitors both surfaces; the cosign signature
   establishes that the report is bound to a verifiable identity (or
   to a valid OIDC session at sign-time).

No GPG email path. No HackerOne / Bugcrowd. No tip-line. The
substrate's only intake is the cryptographically-anchored public log.

## Cross-references

- `axioms/registry.yaml` — constitutional axioms governing the
  security posture
- `agents/refusal_brief/writer.py` — canonical refusal-event log
- `docs/refusal-briefs/` — per-surface architectural-refusal library
- `systemd/README.md` — boot, recovery, and 24/7 watchdog chain
- `hooks/scripts/` — pre-commit + pre-push CI guards (axiom scan,
  secrets scan, branch discipline)
