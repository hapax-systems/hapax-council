# Cheap/local-model SDLC lane (Aider + TabbyAPI)

Cost-offload Tier-1 (REQ-CAND-3, ISAP `S5-CAPACITY-ROUTING-COST-OFFLOAD-TIER1`, under `CASE-CAPACITY-ROUTING-001`). Routes bounded, offloadable SDLC slices (lint-fixes, boilerplate scaffolds, mechanical edits) to a **local open-weight model** instead of spending frontier-Claude tokens — at held quality, behind the normal cc-task review/merge gate.

## Harness: Aider, not OpenCode (research-corrected)

The program originally specified **OpenCode**. On-device testing refuted it: OpenCode v1.17.4 `run`/`serve` **hangs** when headlessly driving a local OpenAI-compatible endpoint (no model call; upstream #5674, also #6396/#8832 deny-permission bugs). **Aider** — built on LiteLLM — drives the same local TabbyAPI model reliably and produces reviewable diffs, so it is the lane harness. (TabbyAPI itself was never the problem; a direct chat returns fine.)

## What runs where

- **Host:** appendix (the dev/SDLC rig) — never podium (no-dev-on-podium).
- **Model:** local TabbyAPI `:5000` (`command-r-08-2024-exl3-4.0bpw` / `Qwen3.5-9B-exl3-5.00bpw`) — `local_compute` only, **no provider spend** (S5 scope).
- **Driver:** `scripts/hapax-aider-lane` wraps Aider with the local-model config.

## Usage

```sh
# on appendix, inside a cc-claim'd worktree slot:
scripts/hapax-aider-lane <model_id> "<task message>" [file ...]
# e.g.
scripts/hapax-aider-lane command-r-08-2024-exl3-4.0bpw \
  "Add a typed, documented add(a, b) helper; keep it ruff-clean." mathx.py
```

The wrapper sets `OPENAI_API_BASE=http://127.0.0.1:5000/v1` (override with `HAPAX_TABBY_URL`), `--no-auto-commit` (the diff stays unstaged for review), `--yes-always` (headless), and `--with audioop-lts` (Python 3.13 dropped the stdlib `audioop` that aider→pydub needs).

## Governance

The lane produces an ordinary git diff; **existing council governance applies at review/merge** — the work runs under a `cc-claim`'d task in a `/data/cache/hapax/scratch/<slug>` worktree, and the diff must pass the same gate any lane does (`ruff check`, `ruff format --check`, `pytest -q` on touched modules) before it is committed/PR'd. A local-model diff that fails those checks fails closed.

## Validation (2026-06-13, appendix)

Two end-to-end runs on the local Command-R, $0 Anthropic spend, each producing a diff that passed `ruff check` unmodified:
- `add(a: int, b: int) -> int` with docstring → ruff clean.
- `shout(s: str) -> str` via the wrapper script → ruff clean.

Verified: local provider resolves, model round-trips (`Tokens: ~680 sent`), diff applies, gate passes.
