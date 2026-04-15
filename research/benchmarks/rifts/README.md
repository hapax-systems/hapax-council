# RIFTS benchmark harness

**RIFTS** — "Navigating Rifts in Human-LLM Grounding: Study and Benchmark"
Shaikh, Mozannar, Bansal, Fourney, Horvitz (ACL 2025)
arXiv: <https://arxiv.org/abs/2503.13975>
Dataset: <https://huggingface.co/datasets/microsoft/rifts>
Code: <https://github.com/microsoft/rifts>

## Why hapax cares

Per beta's 2026-04-15 substrate research drop
(`docs/research/2026-04-15-substrate-reeval-post-hermes.md` §4), RIFTS is the
cleanest published grounding benchmark for the Shaikh framework. Frontier
models average **23.23% accuracy** on the benchmark with a stark asymmetry:

- **96.09%** success when no clarification is needed
- **2.22%** success when clarification IS needed (on the "requires grounding" split)

This is the empirical signal that drives the hapax research program's interest
in SFT-vs-DPO-vs-RL effects on conversational grounding. Running RIFTS directly
against hapax's current local substrate (`local-fast` → Qwen3.5-9B) and
candidate alternatives gives hapax **direct empirical data** on its exact
substrate choices rather than predicting from post-training recipe.

## This directory

- `run_rifts_benchmark.py` — the harness (this file's sibling; Python 3.12+, uses httpx)
- `README.md` — this file
- `results-<model>-<timestamp>.jsonl` — per-run output (appended per run; git-ignored)
- `results-summary-<model>-<timestamp>.md` — human-readable summary (git-ignored)

## Delta's Item #10 scope

Per delta's nightly queue inflection at 07:55Z:

> **Item #10 — RIFTS benchmark preparation (Phase 1 — download + harness only, no runs)**
> - Download the RIFTS benchmark to `research/benchmarks/rifts/`
> - Write an eval harness that invokes a model via LiteLLM
> - Do NOT run the benchmark yet — that's item #11
> - `--dry-run` mode produces a report of what would be benchmarked

## Phase 1 status (beta 2026-04-15T09:00Z)

- ✅ Harness exists at `scripts/run_rifts_benchmark.py`
- ✅ `--dry-run` mode works without the dataset on disk (uses inline fixture of 5 example prompts from the ACL 2025 paper)
- ⚠️ **Dataset not downloaded.** Beta deferred the ~50 MB HuggingFace dataset download per the item #12 convention ("check for a 'don't pull large weights' signal before starting"). Dataset download is scoped to Item #11 (operator-triggered real run).
- ✅ LiteLLM reachability verified at 2026-04-15T08:57Z (`POST /v1/chat/completions` with `model=local-fast` returns valid response)
- ✅ Harness uses `httpx` (existing dependency); no new packages required

## Usage

### Dry run (fixture-only; no external downloads, no inference calls)

```bash
python scripts/run_rifts_benchmark.py --dry-run --model local-fast
```

Output: report of what WOULD be benchmarked (fixture prompts + target route +
output path planning). No `/v1/chat/completions` calls. No dataset download.

### Real run (Item #11 — operator trigger)

Prerequisite: RIFTS dataset downloaded to one of:
- `research/benchmarks/rifts/microsoft_rifts/` (local copy via `huggingface-cli download microsoft/rifts --repo-type dataset --local-dir ./microsoft_rifts`)
- OR `HF_DATASETS_CACHE` pointing at a cached location

```bash
# Step 1: download dataset (~50 MB, operator-triggered)
cd research/benchmarks/rifts
huggingface-cli download microsoft/rifts --repo-type dataset --local-dir ./microsoft_rifts

# Step 2: run harness
python scripts/run_rifts_benchmark.py \
    --model local-fast \
    --dataset-path research/benchmarks/rifts/microsoft_rifts \
    --output research/benchmarks/rifts/results-local-fast-$(date +%Y%m%d-%H%M%S).jsonl
```

Output: JSONL file with one line per prompt:
```json
{"prompt_id": "...", "ambiguous": true, "prompt_text": "...", "model": "local-fast", "response": "...", "latency_ms": 234, "tokens_in": 42, "tokens_out": 67, "error": null, "timestamp": "2026-04-15T...Z"}
```

Plus a summary markdown file with aggregate stats (mean latency, token counts,
total prompts processed, error count). **The harness does NOT compute the
RIFTS accuracy score** — that requires the RIFTS labeler (a separate trained
classifier that annotates grounding acts). Scoring is deferred to a follow-up
step that runs the labeler against the captured model outputs.

## Known limitations

1. **No scoring.** The harness captures outputs but does not compute the RIFTS
   accuracy score. To get comparable numbers to the paper's 23.23% frontier
   average, the captured JSONL must be fed through the RIFTS labeler
   (`microsoft/rifts/labeler/`). Labeler integration is a follow-up task.
2. **Dataset format assumption.** The harness assumes the RIFTS dataset is a
   HuggingFace dataset with fields `{id, prompt, ambiguous: bool}` or similar.
   If the actual dataset has a different schema, the `--dataset-path` loader
   in the harness must be updated to match.
3. **Concurrency.** The harness sends prompts one at a time (sequential). For
   1740 prompts at ~1 s latency per call, total time is ~30 minutes. To
   parallelize, add `--parallel N` later (not in this Phase 1 scope).
4. **No retry on transient errors.** If LiteLLM or TabbyAPI hiccups during a
   run, the affected prompts are marked `{error: "..."}` in the JSONL and
   skipped. A follow-up run can re-process just the errored prompts.

## Cross-references

- beta's substrate research drop `bb2fb27ca` (`docs/research/2026-04-15-substrate-reeval-post-hermes.md`) §9 recommendation to run RIFTS
- delta's nightly queue inflection `20260415-075500-delta-beta-nightly-rolling-queue-16-items.md` §Item #10, §Item #11, §Item #13
- Shaikh et al. ACL 2025 paper (arXiv 2503.13975) — the canonical framework
- Mohapatra et al. LREC-COLING 2024 — the SFT-vs-DPO grounding-agreement finding
