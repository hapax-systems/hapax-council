# One-Segment Iteration Review Protocol

Status: implemented as deterministic review gate.

## Purpose

Before the final nine segments are generated, the first generated segment is treated as a canary. The gate reviews exactly one manifest-accepted prepared artifact and emits a JSON receipt. It is a blocking review receipt for the next-nine batch: the CLI exits nonzero until the automated gates and bound team receipts pass. It never calls a model, never swaps or unloads the resident model, and never treats prepared layout metadata as broadcast authority.

## Steps

1. Generate only one segment into an isolated prep directory.
2. Load artifacts through `load_prepped_programmes`, so manifest, hash, provenance, actionability, and layout projection gates have already run.
3. Run `scripts/review_one_segment_iteration.py --prep-dir <isolated-prep-dir> --receipt-out <receipt.json>`.
4. If automated gates pass, collect team critique receipts for:
   - `script_quality`
   - `actionability_layout`
   - `layout_responsibility`
5. Re-run the review with `--team-receipts <team-receipts.json>`.
6. Generate the next nine only when `ready_for_next_nine` is true.

## Automated Pass Criteria

- Exactly one manifest-accepted artifact is present.
- The review separates loader acceptance metadata from the saved raw artifact. `load_prepped_programmes` enriches accepted objects with runtime validation and projected contract fields; the reviewer uses that enrichment only as acceptance/path metadata, then rereads the saved JSON artifact for hash, prior, actionability, and proposal-only layout checks.
- The artifact and every LLM call receipt use `command-r-08-2024-exl3-5.0bpw`.
- Artifact authority remains `prior_only`.
- `artifact_sha256` and `source_provenance_sha256` verify.
- `prepared_script` is one-to-one with `segment_beats`.
- The recomputed script-quality score is non-generic, has no thin beats, clears the automated floor, and meets per-dimension floors for premise, tension, arc, specificity, pacing, stakes, callbacks, audience address, source fidelity, ending, actionability, and layout responsibility. Team critique still decides whether it is actually excellent.
- Source fidelity is checked separately: sources must appear as grounded arguments, and source hashes, prompt hash, seed hash, and LLM call receipts must bind to the same prior.
- Actionability recomputation finds no unsupported action claims.
- Multiple supported spoken action kinds are required, so the canary cannot pass as a one-note effect demo.
- Every concrete spoken action claim must bind to a layout need, source affordance, and evidence ref.
- Stored beat action/layout receipts match deterministic recomputation.
- Layout metadata remains responsible, proposal-only, pending runtime readback, with `layout_success=false`, no layout decision receipts, and `may_command_layout=false`.
- The reviewer replays `validate_prepared_segment_artifact` against the saved raw artifact before any next-nine release. Responsible artifacts also fail if prepared layout metadata advertises forbidden `bounded_vocabulary` values such as `camera_subject` or `spoken_only_fallback`.
- Prepared metadata contains no concrete layout command, cue, static-default success claim, camera subject/affordance, spoken-only fallback, or public/broadcast bypass.

## Team Critique Receipts

Team receipts are explicit JSON objects. Each must include:

```json
{
  "role": "script_quality",
  "verdict": "approved",
  "reviewer": "cx-gold",
  "checked_at": "2026-05-06T04:00:00Z",
  "receipt_id": "script-quality-pass",
  "artifact_sha256": "artifact hash from the canary review receipt",
  "programme_id": "prog-canary",
  "iteration_id": "segment-prep-canary-session",
  "notes": "Concrete critique explaining why this artifact passes the role."
}
```

Accepted roles are `script_quality`, `actionability_layout`, and `layout_responsibility`. Passing verdicts are `approved`, `pass`, or `passed`. Receipts must bind to the current `artifact_sha256`, `programme_id`, and `iteration_id`, and notes must be substantive rather than reusable one-word approvals. Missing, malformed, stale, pending, revise, or block receipts keep `ready_for_next_nine=false`.

## Residency And Authority

The review path does not call Command-R; it only verifies that the prepared artifact was produced by the resident Command-R route. It contains no Qwen fallback, no LiteLLM fallback, and no model load/unload/restart behavior. Runtime layout authority remains with the canonical broadcast/runtime readback path; prepared artifacts only propose typed needs.
