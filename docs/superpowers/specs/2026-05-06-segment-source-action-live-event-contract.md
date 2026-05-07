# Segment Source-Action Live-Event Contract

**Status:** current_authority
**Checked at:** 2026-05-06
**Scope:** prepared segment artifacts, candidate review, and runtime pool eligibility.

## Rule

An eligible segment artifact is not a script. It is a source/action/live-event contract with a script attached.

The contract must show:

- which source packet grounds each substantive claim;
- what the source changes if it is present or absent;
- what visible or doable counterpart the spoken beat creates;
- what layout need is proposed without commanding runtime;
- what readback must happen before layout success can count;
- why the segment is a live event rather than a compliant essay.

Deterministic validators replay these fields for freshness. They do not replace them.

## Artifact Fields

- `segment_prep_contract_version`
- `segment_prep_contract`
- `segment_prep_contract_report`
- `segment_prep_contract_sha256`
- `segment_live_event_rubric_version`
- `segment_live_event_plan`
- `segment_live_event_report`
- `segment_live_event_report_sha256`

`source_hashes.segment_prep_contract_sha256` binds the source/action contract to the prior. If the contract changes, source provenance changes.

## Release Boundary

`manifest.json` means eligible candidate. It does not mean runtime pool content.

`selected-release-manifest.json` is the pool boundary. Runtime loading defaults to `require_selected=true`, so no eligible artifact is exposed to the programme loop or Qdrant recruitment until candidate-set review selects it.

## Failure Modes

- Missing source packets: recruit sources before composing.
- Source labels without consequence: rewrite or quarantine.
- Spoken-only responsible beat: repair or quarantine.
- Action tokens without temporal coupling: live-event failure.
- Chat prompt without bounded audience job: live-event failure.
- Default/static layout as success: invalid.
- Framework vocabulary in public prose: invalid.
- First eligible artifacts selected without review receipts: selected-release failure.
