# RIFTS harness checkpoint resume — empirical test

**Date:** 2026-04-15
**Author:** beta (queue #232, identity verified via `hapax-whoami`)
**Scope:** empirical validation of the #231 static audit finding that `run_rifts_benchmark.py` cannot resume mid-run. Run a small subset, restart with the same output path, verify the truncation behavior.
**Branch:** `beta-phase-4-bootstrap`

---

## 0. Summary

**Verdict: NOT RESUMABLE (confirmed empirically).** Plus three additional findings not in the #231 static audit:

1. ✅ **Restart truncates existing output** (confirmed in §2) — matches #231 §3.1 prediction
2. 🔴 **`prompt_id` is UNSTABLE across runs** — the RIFTS dataset has no stable ID column, so the harness falls back to `hash(row)` at `_extract_prompt_fields` line 224. Python hash is seeded per-process (PYTHONHASHSEED), so **the same row gets a different prompt_id on every invocation**. A future `--resume` implementation CANNOT deduplicate by prompt_id.
3. 🟡 **Harness processes ALL splits (test + train + val = 1740 rows)**, not just the held-out test split (578 rows). The paper's 23.23%/96.09%/2.22% frontier baselines are presumably computed on the test split only. The queue #210 run's results will NOT be apples-to-apples comparable to the paper without a post-run filter to `split == "test"`.
4. 🟡 **Only 25.2% of rows are `label=="ambiguous"`** (439/1740). The other 75% are `addressing`/`advancing`/`none`, which the harness currently maps to `ambiguous=False` per `_extract_prompt_fields` lines 234-251. This collapses a 4-way classification into a 2-way binary and may underrepresent the true grounding signal.

**Severity:** MEDIUM for the resume finding + the prompt_id instability (compounds the #231 §7.1 recommendation — any `--resume` fix MUST use stable keying, not prompt_id). LOW for the split + label findings (analysis-time concerns, not harness bugs).

## 1. Test procedure + environment

**Environment:**
- Branch `beta-phase-4-bootstrap`, commit `8bb9802e7` (pre-test)
- Running queue #210 RIFTS process: **left untouched** throughout this test
- TabbyAPI shared across the test + #210 run (no additional instance)
- Test output path: `/tmp/rifts-resume-test-pass1.jsonl` (side-channel, does not interfere with `research/benchmarks/rifts/results-local-fast-qwen-20260415.jsonl`)

**Commands:**

```bash
# Pass 1: small 5-prompt subset
LITELLM_MASTER_KEY=... uv run --with pandas --with pyarrow python \
    scripts/run_rifts_benchmark.py \
    --model local-fast \
    --dataset-path research/benchmarks/rifts/microsoft_rifts \
    --output /tmp/rifts-resume-test-pass1.jsonl \
    --limit 5

# Backup for comparison
cp /tmp/rifts-resume-test-pass1.jsonl /tmp/rifts-resume-test-before-restart.jsonl

# Pass 2: restart with SAME --output path, smaller --limit 3
LITELLM_MASTER_KEY=... uv run --with pandas --with pyarrow python \
    scripts/run_rifts_benchmark.py \
    --model local-fast \
    --dataset-path research/benchmarks/rifts/microsoft_rifts \
    --output /tmp/rifts-resume-test-pass1.jsonl \
    --limit 3
```

## 2. Result: restart TRUNCATES

```
# Pass 1 output (5 rows)
$ wc -l /tmp/rifts-resume-test-before-restart.jsonl
5 /tmp/rifts-resume-test-before-restart.jsonl

# Pass 2 output — same path, should APPEND if resumable
$ wc -l /tmp/rifts-resume-test-pass1.jsonl
3 /tmp/rifts-resume-test-pass1.jsonl

# File is now EXACTLY 3 rows, not 5+3=8
```

**The second run clobbered the first.** The file after pass 2 contains only the 3 rows pass 2 wrote — pass 1's 5 rows are gone. This matches #231 §3.1's prediction (`output_path.open("w")` at line 349 truncates on open).

No resume, no append, no skip. The static audit was correct: **a SIGINT or crash mid-run, followed by a re-invocation with the same `--output` path, silently destroys all completed work.**

## 3. New finding: `prompt_id` is UNSTABLE

While validating the truncation, I also compared the prompt content between the two runs to verify both runs see the same first row:

### 3.1 Pass 1 prompt IDs + text

```
rifts-740758f9  'I have two photos containing one woman in each photo. I want'
rifts-46fa739b  'prove me that Forex trading is Haram by islamic concepts and'
rifts-e816af5a  'how i use adclony with kotlin and xml sdk 4.8.0 allcode plz'
rifts-daa2c17d  'make a questionnaire survey about PE Benefits exercise 3 que'
rifts-d92103fa  'write a javascript code that will return all the js paths of'
```

### 3.2 Pass 2 prompt IDs + text

```
rifts-e78a0f0f  'I have two photos containing one woman in each photo. I want'
rifts-fd060894  'prove me that Forex trading is Haram by islamic concepts and'
rifts-9ba3b5b7  'how i use adclony with kotlin and xml sdk 4.8.0 allcode plz'
```

**Same rows in the same order, but DIFFERENT `prompt_id` values.** The test prompts match byte-for-byte on `prompt_text`, but every `prompt_id` differs between the two runs.

### 3.3 Root cause

`_extract_prompt_fields()` at `scripts/run_rifts_benchmark.py:220-225`:

```python
prompt_id = str(
    raw.get("id")
    or raw.get("prompt_id")
    or raw.get("example_id")
    or f"rifts-{hash(json.dumps(raw, sort_keys=True, default=str)) & 0xFFFFFFFF:08x}"
)
```

The dataset inspection confirms:

```
$ uv run ... python3 -c "import pandas; df = pandas.read_parquet('.../test.parquet'); print(list(df.columns))"
columns: ['instruction', 'split', 'label', 'logits']
```

**No `id`, `prompt_id`, or `example_id` column exists in the RIFTS dataset.** The harness always falls back to the `hash(...)` branch. Python's `hash()` is seeded per-process by `PYTHONHASHSEED` which defaults to random, so the same input produces different output across process invocations.

### 3.4 Impact on future `--resume` work

Queue #235 (proposed in #231 §7.1) suggested implementing `--resume` via "read existing JSONL, build set of seen prompt_ids, skip rows already seen". **This approach will NOT work** because:

- Run 1 writes rows with IDs {A, B, C}
- Run 2 starts, reads the JSONL, sees {A, B, C}
- Run 2 computes the IDs for the dataset rows — gets {A', B', C', D, E, ...}
- `A` ≠ `A'`, so Run 2 does not skip any rows — it restarts from prompt 1

**Corrected resume strategy for #235:**

**Option A (preferred):** Use **row index** (the `count_total` counter the harness already tracks) as the stable key. Store `{"row_index": N}` in each JSONL row + implement resume by counting existing JSONL rows and `itertools.islice(dataset, existing_count, None)` to skip.

**Option B:** Hash `prompt_text` with a deterministic hash function (e.g., `hashlib.sha256`) instead of Python's built-in `hash()`. This gives stable IDs across runs but loses the current "one random ID per row" collision resistance guarantee (sha256 is stronger, so this is fine).

**Option C (safest):** Both — store `row_index` AND a sha256-based stable ID. Index gives O(1) resume position; stable ID gives content-based deduplication for the "re-run only errored prompts" flag.

**#235 spec needs an update** to reference this finding + specify Option A or C. The prompt_id column in the current JSONL output is not a valid dedup key.

## 4. New finding: dataset schema and split coverage

### 4.1 All splits bundled together

```
$ uv run ... python3 -c "
import pandas as pd
from pathlib import Path
total = 0
for pq in sorted(Path('research/benchmarks/rifts/microsoft_rifts').rglob('*.parquet')):
    df = pd.read_parquet(pq)
    total += len(df)
    print(f'{pq.name:20s} rows={len(df)}  labels={df[\"label\"].value_counts().to_dict()}')
print(f'TOTAL: {total}')
"
test.parquet         rows=578  labels={'advancing': 148, 'ambiguous': 146, 'addressing': 145, 'none': 139}
train.parquet        rows=583  labels={'advancing': 147, 'none': 146, 'ambiguous': 146, 'addressing': 144}
val.parquet          rows=579  labels={'none': 147, 'ambiguous': 147, 'addressing': 143, 'advancing': 142}
TOTAL: 1740
```

**The 1740 total matches the queue #210 description, but comes from test + train + val combined.** `_load_dataset()` at line 187 uses `path.rglob("*.parquet")` which returns all three files, and the harness iterates all of them without a split filter.

### 4.2 Paper comparability concern

The Shaikh et al. ACL 2025 paper presumably computes the 23.23% frontier average on the **test split only** (578 rows), consistent with standard benchmark practice. The #210 run processes all 1740 rows.

**Implications for the findings template (`docs/research/2026-04-15-rifts-qwen3.5-9b-baseline.md`):**

- §2.1 "per-split response counts" should add a `split` dimension (test/train/val) alongside the existing `ambiguous`/`non-ambiguous` dimension
- §0 executive summary should clarify whether the Qwen baseline number is computed on all 1740 or just the 578 test rows
- §2.3 harness limitation disclosure should note that paper-comparable scores require both (a) running the RIFTS labeler AND (b) filtering to `split == "test"`

**Proposed update to queue #227 findings template:** I'll patch the template in a follow-up edit to account for the split dimension. Or this could be a post-run edit when #210 completes.

### 4.3 Label mapping

The harness's `_extract_prompt_fields()` binarizes the 4-way label into `ambiguous: bool`:

```python
# lines 234-251
label = raw.get("label")
if isinstance(label, str) and label.lower() == "ambiguous":
    ambiguous = True
else:
    ...  # fallbacks
    ambiguous = False
```

Current run mapping:
- `label == "ambiguous"` → `ambiguous=True` (25.2% of rows, 439/1740)
- `label in {"addressing", "advancing", "none"}` → `ambiguous=False` (75% of rows)

**The 4-way RIFTS taxonomy:**

- `ambiguous` — prompt requires clarification; model should ask
- `addressing` — model performs a grounding act (asks clarification, restates assumption, etc.) — this is "the right thing"
- `advancing` — model proceeds without grounding — "assume-and-proceed"
- `none` — no grounding act category applies

The harness's binary mapping is the queue #210 spec's simplification (`ambiguous vs non-ambiguous`) and matches the paper's headline split, but it discards the grounding-act classification entirely. A future pass with the RIFTS labeler could reconstruct the 4-way classification against the captured outputs.

**Non-drift, analysis-time concern only.** The binarization is documented + intentional per queue #210 spec.

## 5. Updated resume-implementation recommendation for #235

Given the prompt_id instability, #235's implementation must use one of:

### 5.1 Row-index based resume

```python
# sketch for _real_run()
if args.resume and output_path.exists():
    with output_path.open("r") as f:
        skip_count = sum(1 for _ in f)
    mode = "a"  # append
    log.info(f"resume: skipping first {skip_count} rows")
else:
    skip_count = 0
    mode = "w"

with httpx.Client() as client, output_path.open(mode) as out_f:
    for raw in _load_dataset(args.dataset_path):
        if count_total < skip_count:
            count_total += 1
            continue
        # ... rest unchanged
```

**Pros:** simple, uses existing counter, no schema change needed
**Cons:** fragile if the dataset file order changes mid-run (shouldn't happen in practice)

### 5.2 Content-hash based resume

```python
import hashlib
# in _extract_prompt_fields
stable_id = hashlib.sha256(prompt_text.encode()).hexdigest()[:16]

# in _real_run with --resume
seen = set()
if args.resume and output_path.exists():
    with output_path.open("r") as f:
        for line in f:
            d = json.loads(line)
            seen.add(d.get("stable_id") or d["prompt_text"][:64])
    # ...
for raw in _load_dataset(args.dataset_path):
    ...
    if stable_id in seen:
        continue
```

**Pros:** robust against dataset file ordering changes
**Cons:** requires a new `stable_id` field in the JSONL schema (or a fallback to `prompt_text` hashing post-hoc)

### 5.3 Recommended

**Both.** Write `stable_id` (sha256-16 of `prompt_text`) + `row_index` to every row. Resume skips by `row_index` for speed; `--retry-errors` dedupes by `stable_id` for correctness under partial re-runs.

## 6. Impact on the in-flight queue #210 run

**None immediate.** The queue #210 run is healthy at 1340/1740 (77%) as of 21:03Z, ETA ~21:44Z. The findings in this drop apply to:

1. **Hypothetical restart scenarios** — if #210 crashes, the operator MUST rename the output file before re-running (per #231 §6 recipe)
2. **Post-run analysis** — the findings template needs to distinguish test/train/val split + filter to test for paper comparison
3. **prompt_id attribution** — any post-run merge step that depends on prompt_id as a stable key will be wrong; merges must use row_index or prompt_text-based keys

**Will NOT impact the run's numeric output.** The 1740 prompts are being processed correctly; the data is being written; errors are recorded. The findings are about interpretation + resume capability, not correctness of the raw capture.

## 7. Follow-up queue items (revised from #231)

### 7.1 #235 (revised) — `--resume` with stable keying

**Revision from #231 §7.1:** implementation MUST use row_index or content-hash (not prompt_id). See §5 above for the sketch. Add `stable_id` field to JSONL schema.

### 7.2 #239 — Harness split filter + row_index output field

```yaml
id: "239"
title: "RIFTS harness: add --split filter + row_index output field"
assigned_to: beta
status: offered
depends_on: []
priority: low
description: |
  Queue #232 empirical test found the harness iterates ALL parquet
  files (test + train + val = 1740 rows) without a split filter.
  Standard benchmark practice is to measure on test split only
  (578 rows).
  
  Actions:
  1. Add --split {test,train,val,all} flag (default: all for
     backward compat with the current #210 run)
  2. Filter _load_dataset() output to the selected split
  3. Add row_index field to RunResult dataclass + JSONL schema
  4. Add stable_id field (sha256-16 of prompt_text)
  5. Regression test: run --split test --limit 10 and verify
     - all 10 rows have split='test'
     - row_index increments 0..9
     - stable_id is deterministic across invocations
size_estimate: "~60 min implementation + test"
```

### 7.3 Queue #227 findings template — post-run patch

The findings template at `docs/research/2026-04-15-rifts-qwen3.5-9b-baseline.md` (commit `4967d7bdf`) needs a small update to account for the split dimension + prompt_id instability. **I'll do this as a template patch commit next** — the template was designed as a placeholder that gets filled in; adding a split-breakdown row is consistent with its purpose.

## 8. Non-drift observations

- **Every pass-1 row completed OK in 5s each.** TabbyAPI is healthy; the test did not disrupt the in-flight #210 run.
- **The test used `/tmp` for output** to avoid colliding with the #210 output path at `research/benchmarks/rifts/results-local-fast-qwen-20260415.jsonl`. No risk to the live run.
- **Python's `hash()` being seeded is well-documented behavior** (see PEP 456 and `PYTHONHASHSEED` docs) — this is not a bug in Python, it's a bug in the harness's fallback strategy which should use `hashlib` instead.
- **The dataset has no `id` column** — this is a microsoft/rifts design choice, not a download corruption. The queue #227 findings template should reference rows by `prompt_text` prefix or `row_index`, not by the unstable `prompt_id`.

## 9. Cross-references

- Queue spec: `queue/232-beta-rifts-checkpoint-resume-test.yaml`
- Predecessor audit: `docs/research/2026-04-15-rifts-harness-error-recovery-verify.md` (queue #231, commit `8bb9802e7`)
- Harness source: `scripts/run_rifts_benchmark.py` (409 LOC, commit `a52dafc87` for the microsoft/rifts schema fix)
- Test outputs (temporary, in `/tmp`):
  - `/tmp/rifts-resume-test-before-restart.jsonl` (5-row pass 1 backup)
  - `/tmp/rifts-resume-test-pass1.jsonl` (3-row post-restart file, proving truncation)
- Queue #227 findings template (to be patched): `docs/research/2026-04-15-rifts-qwen3.5-9b-baseline.md` (commit `4967d7bdf`)
- RIFTS README: `research/benchmarks/rifts/README.md` (known-limitations section)
- Paper: Shaikh et al. ACL 2025, arXiv [2503.13975](https://arxiv.org/abs/2503.13975)
- Python hash randomization: PEP 456 + `PYTHONHASHSEED` docs

— beta, 2026-04-15T21:10Z (identity: `hapax-whoami` → `beta`)
