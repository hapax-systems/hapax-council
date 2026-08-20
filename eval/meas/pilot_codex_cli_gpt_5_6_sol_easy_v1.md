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

## Historical measurement boundary

Each cell used an isolated shallow checkout at the authoritative PR parent. Codex
edited through the historical `--full-auto` invocation, which selected the
workspace-write sandbox; both surfaces were removed from the shipped v7 driver.
User config, MCP, and web search were disabled. The harness captured JSONL
stdout/stderr and the post-exec diff, then installed merge-version tests and ran the
deterministic predicate. The proprietary model's weight hash and serving quantization
are not published; those λ fields say `provider-managed` rather than pretending a
weights digest exists.

This result predates the v7 external agent-read boundary, clean scoring checkout,
isolated predicate, pytest/xdist-origin checks, and controller/worker separation.
It is retained as an explicitly historical v1 measurement, not represented as a
measurement of the shipped v7 driver. The adjacent witness contains the redacted
19-cell evidence, task and commit contracts, λ, result seals, and artifact seal.

## Recheck

`uv run python eval/meas/driver_codex_cli.py --verify-result eval/meas/pilot_codex_cli_gpt_5_6_sol_easy_v1.witness.json`
