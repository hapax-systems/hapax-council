# chatbind — Featherless + Verboo builder binding (source only)

Task `chatbind-featherless-verboo-proxy-build-and-probes-20261004`. Design:
`30-areas/hapax/frame/second-source-family-20261003/CHAT-BINDING.md` §6 (accepted by the seat).

A narrowly-scoped LiteLLM instance that lets **Featherless** (prepaid, top-up off) and
**Verboo** (flat) models act as builders behind the hooked harness, reached via
`ANTHROPIC_BASE_URL=http://127.0.0.1:4100`. **Never PAYG.** It reuses the estate's existing
LiteLLM image and the `secret_env_from_filestore.py` credential pattern — it is **not** a new
proxy, and it does not touch `~/llm-stack` or its `.env`.

## Files
- `chatbind-config.yaml` — the LiteLLM config. The whole configuration surface; every line is a
  guard invariant (`tests/test_chatbind_config_guard.py`): exactly two model pins, no
  fallbacks/aliases/wildcards, no database/cache/master-key/callbacks/budgets/virtual-keys,
  `drop_params` on, `modify_params` off, `num_retries` 0, Featherless non-default UA, Verboo
  concurrency 2. The per-call JSONL ledger is the only state.
- `docker-compose.chatbind.yml` — the container (reuses `ghcr.io/berriai/litellm`, pin by digest
  at build), loopback `127.0.0.1:4100`, exactly the two FileStore secrets passed through, no
  backing services.
- `ledger/` — per-call JSONL ledger mount (created at start).

## The two model pins are a SEAT choice
`chatbind-config.yaml` carries candidate defaults (measured live 2026-10-03) marked `SEAT PIN`.
The seat sets the final Featherless and Verboo pins per routing-table §B2/§B3 before admission;
this build does not choose them and changes no routing-table row.

## Secrets
At start, `scripts/secret_env_from_filestore.py` (reins `k0` FileStore, file backend) resolves
**exactly two** names into the process env — `FEATHERLESS_API_KEY`, `VERBOO_API_KEY` — which the
compose passes through. No key value is committed, and `~/llm-stack/.env` is never read.

## Runtime is the seat's, not this build's
Container start/stop and probes **P1–P5** (client-passthrough, hook parity, wire identity,
failure-class mapping, a bounded builder smoke) are runtime acts. Each comes to the seat with a
fresh-context `claude -p --model claude-opus-5-5` challenge whose served `message.model` is recorded
in the ISAM line, **before** it happens. §9's vendor-posture note (Anthropic does not support
routing Claude Code to non-Claude models through a gateway; Verboo terminal-vs-pipeline terms;
the Featherless data ruling) is recorded for the seat before P5.

## Prior art (CAPABILITY-PRIOR-ART-ANCHORS-20260925, via CHAT-BINDING.md §8)
- §1 capability-shape onboarding — **align** (the binding names its whole surface: model × harness
  × config × credential location).
- §2 demand differentiation — **align** (pins are seat demand-shape choices, not frontier rank).
- §3 containerization (`LOCAL-CAPABILITY-CONTAINERIZATION-20260912`) — **align** (the container
  constrains the declared binding; it does not mint admission authority — that stays the seat's).
- `gemini-payg-leak-via-litellm-fast-tier-20260928` — **invert**: that leak was an unpinned
  `fast`-tier alias reaching PAYG; chatbind has no alias/fallback/wildcard and can reach only the
  two prepaid/flat upstreams.
- PR #5020 (review plane) — **extend, not duplicate**: this is the builder plane, inheriting its
  verified failure classes and vendor findings.
