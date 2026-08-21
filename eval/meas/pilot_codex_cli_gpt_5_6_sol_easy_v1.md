# MEAS Tier-0 Codex CLI pilot

- Completed: 2026-08-20T07:14:45.778500Z
- Arm: `gpt-5.6-sol` through `codex-cli-agentic`
- Historical driver: `driver_codex_cli/v1`
- Result: **11/19 (57.9%)**
- Direct-API 35B single-shot baseline: **0/19 (0.0%)**
- λ: `e403ed3d4909` (the full configuration is embedded in every JSON cell)

## Finding

The Codex CLI agentic harness passed 11 of 19 easy cells, versus 0 of 19 for
the 35B direct-API single-shot baseline. This comparison establishes only the
measured harness/model pair; it does not isolate model quality from harness effects.
The verifier permits that comparison only when difficulty, complete task order, and
the exact task-contract hash match the recorded 19-cell baseline selection.

## Historical measurement boundary

Each cell used an isolated shallow checkout at the authoritative PR parent. Codex
edited through the historical `--full-auto` invocation, which selected the
workspace-write sandbox; both surfaces were removed from the shipped v14 driver.
User config, MCP, and web search were disabled. The harness captured JSONL
stdout/stderr and the post-exec diff, then installed merge-version tests and ran the
deterministic predicate. The proprietary model's weight hash and serving quantization
are not published; those λ fields say `provider-managed` rather than pretending a
weights digest exists.

This result predates the v14 external agent-read boundary, clean scoring checkout,
isolated predicate, pytest/xdist-origin checks, and controller/worker separation.
It is retained as an explicitly historical v1 measurement, not represented as a
measurement of the shipped v14 driver. The adjacent witness contains the redacted
19-cell evidence, task and commit contracts, λ, result seals, and artifact seal.

No provider-backed 19-cell pass rate has been measured for v14. That measurement is
deferred to a separately authorized provider-spend follow-up tranche; the v1 rate
must not be used as a v14 performance claim. The provider-backed v14 measurement
remains explicit acceptance work for that separately authorized follow-up tranche.

## Shipped-driver validation

The provider-free v14 validation ran on `hapax-appendix` (Linux 6.18.32,
Bubblewrap 0.11.2, Codex CLI 0.148.0). Both optional integration prerequisites were
present: `uv run pytest -q tests/eval` reported **87 passed, 0 skipped**, and
`--self-check` passed the real read-only Bubblewrap predicate and isolated-worker
path. This validates the shipped control path; it does not measure a provider-backed
v14 pass rate. On other hosts, the `requires_bubblewrap` and `requires_codex` markers
skip their integration tests when either named prerequisite is unavailable, so the
pass/skip count will differ visibly.

## Recheck

`uv run python eval/meas/driver_codex_cli.py --verify-result eval/meas/pilot_codex_cli_gpt_5_6_sol_easy_v1.witness.json`

That command verifies the committed witness's seals and internal consistency; it
does not re-execute or reproduce the historical v1 provider run. To exercise the
shipped v14 clean-checkout, read-only predicate, sealed call-capture chain,
worker-integrity guard,
merge-test installation, isolated-worker, and trusted-controller path without
provider spend, run:

`uv run python eval/meas/driver_codex_cli.py --self-check`
