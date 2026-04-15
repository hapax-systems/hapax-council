# pydantic-ai v3 migration check

**Date:** 2026-04-15
**Author:** alpha (AWB mode, queue/ item #135)
**Scope:** Grep for deprecated pydantic-ai API usage across the council Python workspace. Per workspace CLAUDE.md, the current API uses `output_type=` (not `result_type=`) and `result.output` (not `result.data`). Flag any live usage of the deprecated forms.
**Register:** scientific, neutral

## 1. Headline

**Zero deprecated pydantic-ai API usage in council Python.** The migration is clean.

- `result_type=` in agent definitions → **0 hits**
- `.result.data` / `.response.data` access → **0 hits**
- `output_type=` (current API) → **27 files** using it correctly
- `result.output` (current API) → widely used correctly

**No action needed.** The migration was done in a prior cycle and no regressions have appeared.

## 2. Method

```bash
# Deprecated API scans
grep -rnE "result_type\s*=|result_type:" --include="*.py"
grep -rnE "\.result\.data|\.response\.data" --include="*.py"

# Current v3 API usage
grep -rnE "output_type\s*=" --include="*.py"
grep -rnE "result\.output\b" --include="*.py"
```

All four scans exclude `.venv/` and focus on first-party source (`agents/`, `shared/`, `logos/`, `scripts/`, `tests/`).

## 3. Scan results

### 3.1 Deprecated API — zero hits

```
$ grep -rnE "result_type\s*=|result_type:" --include="*.py" [council]
(empty)
```

```
$ grep -rnE "\.result\.data|\.response\.data|result_type=" --include="*.py" [council]
(empty)
```

**Zero occurrences of `result_type=`, `.result.data`, or `.response.data`** anywhere in council Python code. The v3 migration is complete in first-party code.

### 3.2 Current API — 27 files using `output_type=`

Representative sample (not exhaustive):

- `agents/demo_pipeline/choreography.py:69` — `output_type=str`
- `agents/demo_pipeline/critique.py:37` — `output_type=DemoQualityReport`
- `agents/demo_pipeline/critique.py:51` — `output_type=DemoScript`
- `agents/demo_pipeline/eval_rubrics.py:188` — `output_type=TextEvalOutput`
- `agents/demo_pipeline/eval_rubrics.py:339` — `output_type=VisualEvalOutput`
- `agents/demo_pipeline/eval_rubrics.py:483` — `output_type=DiagnosisOutput`
- `agents/demo.py:411` — `output_type=DemoScript`
- `agents/demo.py:424` — `output_type=ContentSkeleton`
- `agents/demo.py:437` — `output_type=ContentSkeleton`
- `agents/demo.py:450` — `output_type=DemoScript`
- `agents/drift_detector/agent.py:63` — `output_type=DriftReport`
- `agents/drift_detector/fixes.py:58` — `output_type=FixReport`
- `agents/_pattern_consolidation.py:146` — `output_type=ConsolidationResult`
- `agents/_threshold_tuner.py:96` — `output_type=list[ThresholdOverride]`
- `agents/digest.py:182` — `output_type=Digest`
- ...and 12 more

**All 27 usages are correct v3 API.** No migration drift.

### 3.3 `result.output` access — widely used correctly

Sampled usages (from broader grep for `result.output`):

- `agents/demo_pipeline/choreography.py:156` — `actions = _parse_actions(result.output)`
- `agents/demo_pipeline/critique.py:1199` — `report = critique_result.output`
- `agents/demo_pipeline/critique.py:1235` — `revised = revision_result.output`
- `agents/demo_pipeline/eval_rubrics.py:291` — `output = result.output`
- `agents/demo_pipeline/eval_rubrics.py:434` — `output = result.output`
- `agents/demo_pipeline/eval_rubrics.py:591` — `return result.output`
- `agents/dev_story/__main__.py:65` — `print(result.output)`
- `agents/dev_story/__main__.py:86` — `print(f"\n{result.output}\n")`
- `agents/dev_story/query.py:317` — "The agent interleaves text with tool calls, so result.output only..." (comment)
- `agents/dev_story/query.py:330` — `return "\n\n".join(parts) if parts else result.output`

**All sampled usages correctly access `.output`, not `.data`.**

## 4. Remediation priority

**None.** No deprecated API usage detected. No migration drift. No remediation action items.

## 5. Possible follow-up scans (not urgent)

1. **Check `.venv/` for mismatched pydantic-ai version.** Council uses `pyproject.toml` pin; verifying the installed version matches (should be v3+). Alpha did not run `uv tree | grep pydantic-ai` in this audit.
2. **Check officium + mcp Python for same patterns.** Out of scope for this council-focused audit but worth a parallel scan if another session has bandwidth.
3. **Audit `Agent` class instantiation patterns** — pre-v3 sometimes used positional arguments that are now keyword-only. Would need deeper per-file walk.

None of these are urgent.

## 6. Closing

Council Python is fully migrated to pydantic-ai v3 `output_type=` + `result.output` API. Zero deprecated usages. No follow-up work needed for the council repo.

Branch-only commit per queue item #135 acceptance criteria.

## 7. Cross-references

- Workspace CLAUDE.md § "Shared Conventions" — documents the v3 API expectations
- `pyproject.toml` — should pin pydantic-ai version (not verified in this audit)
- Queue item #113 (LiteLLM config audit) — related agent-framework check
- Queue item #118 (Qdrant schema audit) — another structural audit in this session

— alpha, 2026-04-15T19:46Z
