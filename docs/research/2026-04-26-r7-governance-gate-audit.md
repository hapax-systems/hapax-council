# R-7 audit: governance-gate wire status

**Authored:** 2026-04-26 by alpha
**Audit row:** `governance-gate-wire-audit` (WSJF 14.0)
**Posture:** audit-before-fix per absence-bug epic
**Source synthesis:** `~/.cache/hapax/relay/research/2026-04-26-absence-bugs-synthesis-for-beta.md`

## TL;DR

Audit confirms R-7's structural finding: 4 governance-gate primitives
are defined and are not invoked in production. **But the consent
risk is theoretical, not actual** at this point in time, because the
artefacts the gate protects (transcripts under `events-*.jsonl`,
`recordings/`, and `impingements.jsonl`) currently contain only
metadata — no transcript text reaches them. The gate is a preventive
firewall for future code that adds transcript content. Recommendation:
wire the gate at the existing read sites (1 prod call site) so the
firewall closes the moment transcripts land.

## Functions inventory

| Function | Defined at | Prod call sites (excl. tests/duplicates) | Test coverage |
|---|---|---:|---:|
| `read_transcript_gate` | `shared/transcript_read_gate.py:88` | 0 (1 string mention in `scripts/scan-transcript-firewall-bypasses.py`) | 6 tests |
| `is_protected_transcript_path` | `shared/transcript_read_gate.py:55` | 0 | 13 tests |
| `guard_content` | `shared/transcript_read_gate.py:123` | 0 | 6 tests |
| `TemporalConsent` | `agents/_governance/temporal.py:128` *and* `shared/governance/temporal.py:129` (vendored duplicate; R-18) | 0 | 8 tests |

The earlier 2026-04-26T18:40Z correction inflection (`alpha-r17-r7-audit-corrections.md`) over-counted: the `TemporalConsent` "1 prod call" was a sibling class definition (R-18 vendored duplicate), and the `read_transcript_gate` "1 prod call" was a string mention in a scanner's remediation message. **R-7's structural claim stands.**

## Protected-path inventory (per `is_protected_transcript_path` predicate)

1. `events-*.jsonl` anywhere under `~/.local/share/hapax-daimonion/`
2. anything under `~/.local/share/hapax-daimonion/recordings/`
3. `/dev/shm/hapax-dmn/impingements.jsonl` (exact match)

## Read-site inventory (where the gate WOULD apply if wired)

The audit grepped for actual `read_text() / open()` reads of the protected paths.

| Site | Path read | Read content | Gate applicable? |
|---|---|---|---|
| `agents/context_restore.py:391` `collect_voice_events_summary` | `events-{today}.jsonl` | `presence_transition` events (metadata only — counts + last presence flag) | **YES** (would close the firewall on future transcript fields) |
| (no other prod call sites read protected paths directly) | — | — | — |

`agents/hapax_daimonion/event_log.py:_get_file` opens the event file in append mode (write only); `cleanup` walks for deletion (no read). Other producers (apperception, vinyl_pet_detector, content_id_watcher, inflection_to_impingement, director_loop) only WRITE to `impingements.jsonl`, not read.

## Content-risk inventory (does anything write transcript text into the protected paths?)

Audit grepped for `event_log.emit(...)` calls passing `text|transcript|partial|stt|utterance` fields. **Zero hits across all callers.**

Confirmed-safe writers (per `agents/hapax_daimonion/{run_loops,session_events,workspace_monitor,consent_session,consent_session_runner,consent_state,context_gate}.py`):

- session_lifecycle, perception_tier_changed, face_result, analysis_failed, actuation, consent_*, subprocess_failed, etc. — all metadata fields (action, latency_ms, tier names, count, error strings).

The recordings subtree is BYTES (audio blobs). `read_transcript_gate` returns those as `bytes` when stream is private, redacts when public — also gate-applicable.

## Risk assessment

- **Today (no transcript content in protected paths):** the firewall would silently pass-through everything; wiring is a no-op for current code paths.
- **First future commit that adds transcript text to event log fields:** without the gate wired, public-stream reads of those events leak transcript content. With the gate wired, they redact automatically.

R-7's "consent risk" framing is correct as a forward-looking concern. The risk is dormant today and activated by any commit that emits transcript text via the event log.

## Recommendation (audit-only PR — defers wire-up)

This document is the audit deliverable. The wire-up itself is a separate ~1h PR:

1. `agents/context_restore.collect_voice_events_summary` — wrap the `events_file.read_text()` call in `read_transcript_gate(events_file)`. Gracefully handle the `TranscriptRedacted` return path (return early with `transitions=0, present=True` and a redacted-flag in the result dict).
2. Add a regression test pinning that the wired call short-circuits when `is_public_stream_visible()` returns True.
3. Optional: add a `unittest`-level smoke test asserting `event_log.emit()` callers do NOT pass transcript-shaped fields (a static-text-scan over the call sites).

`TemporalConsent` is a related but orthogonal concern (interval-arithmetic on `ConsentContract` expiry); its 0 prod calls are best addressed by the `ConsentRegistry` consumers when interval-bounded contracts are introduced. Filing as separate cc-task `temporal-consent-wire`.

## Cross-references

- Synthesis source row R-7: `~/.cache/hapax/relay/research/2026-04-26-absence-bugs-synthesis-for-beta.md`
- Audit-of-synthesis (the 10 corrections): `~/.cache/hapax/relay/research/2026-04-26-absence-bugs-synthesis-audit.md`
- R-18 (vendored-duplicate cleanup) is a prerequisite for unambiguous `TemporalConsent` references — `agents/_governance/temporal.py` should be deleted once `shared/governance/temporal.py` is canonical.

— alpha
