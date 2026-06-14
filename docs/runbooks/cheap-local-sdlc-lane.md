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

## Validation & recheck

The wrapper's logic (arg validation, the local-only endpoint guard, command construction) is covered by a re-runnable test — **no live model needed**:

```sh
bash tests/scripts/test-hapax-aider-lane.sh   # -> ALL PASS
shellcheck scripts/hapax-aider-lane tests/scripts/test-hapax-aider-lane.sh
```

The end-to-end lane (local model → gate-passing diff) is reproduced on the appendix dev host:

```sh
# in a throwaway git repo on appendix:
HAPAX_TABBY_URL=http://127.0.0.1:5000/v1 \
  scripts/hapax-aider-lane command-r-08-2024-exl3-4.0bpw \
  "Add a typed, documented add(a, b) helper; keep it ruff-clean." mathx.py
uv run ruff check mathx.py   # -> All checks passed!
```

The wrapper test is the **durable, CI-able witness** for the lane's logic (arg
handling, the endpoint guard, command construction). The end-to-end model run is
an inherently **manual reproduce** — it needs a loaded local GPU model, so it is
documented above rather than run in CI. First validated 2026-06-13 (appendix,
local Command-R): two edits (`add(a, b) -> int`, `shout(s) -> str`), each a
`ruff check`-clean diff at **$0 Anthropic** (`Tokens: ~680 sent`).

**No-provider-spend enforcement.** The wrapper refuses any `HAPAX_TABBY_URL` whose
*effective host* is not loopback (`127.0.0.1` / `localhost`) or the appendix host
(`192.168.68.50`) — matched anchored, so userinfo smuggling
(`http://127.0.0.1:5000@paid.example/v1`) and host-suffix tricks fail closed
(exit 3, covered by the test). The guarantee is enforced, not just claimed.
