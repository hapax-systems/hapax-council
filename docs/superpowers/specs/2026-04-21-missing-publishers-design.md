# FINDING-V — Missing Publishers Design Spec

**Author:** Delta (FINDING-V research → spec → plan chain)
**Date:** 2026-04-21 (research) / 2026-04-24 (spec — status-audited against live system)
**Task:** `finding-v-publishers-research-spec-plan` (vault cc-task)
**Parent:** `docs/research/2026-04-21-missing-publishers-research.md`
**Handoff:** `~/.cache/hapax/relay/alpha-to-delta-2026-04-21-finding-v-producers.md`

---

## Executive Summary

The FINDING-V audit (docs/research/2026-04-20-wiring-audit-findings.md §650–688) identified six SHM files referenced by consumer wards with no producer anywhere in the repo. Between 2026-04-19 and 2026-04-24, **three of the six publishers shipped** and **three resolved as false-missings** — the wards read from an alternate path that already has an upstream. The remaining work is a single systemd-timer unit file that exists in live runtime but is missing from the repo (drift), plus explicit retirement of the three false-missing entries from the FINDING-V tracker.

This spec formalises the per-publisher architecture decisions (already shipped or not shipped), the retirement rationale for the three false-missings, and the single remaining gap.

## Status Audit as of 2026-04-24T21:45Z

| Publisher | Audit verdict | Shipped state | Remaining work |
|---|---|---|---|
| `recent-impingements.json` | IMPLEMENT | LIVE — `hapax-recent-impingements.service` active; file present in `/dev/shm/hapax-compositor/` | None |
| `chat-keyword-aggregate.json` | IMPLEMENT | **False-missing** — consumer (`chat_ambient_ward.py:243`) reads `/dev/shm/hapax-chat-signals.json` directly; the audit mis-named the input path | Retire from FINDING-V tracker |
| `chat-tier-aggregates.json` | IMPLEMENT | **False-missing** — same upstream as above; same ward; one-file/two-field-groups reality collapses the two rows | Retire from FINDING-V tracker |
| `youtube-viewer-count.txt` | IMPLEMENT | LIVE — `hapax-youtube-viewer-count.service` active; file present | Timer unit file missing from repo (drift) |
| `grounding-provenance.jsonl` | RETIRE | **False-missing** — consumer tails `~/hapax-state/stream-experiment/director-intent.jsonl` directly via `legibility_sources.py::_read_latest_intent()` (lines 62–64, 690–691); no separate file needed | Retire from FINDING-V tracker |
| `chat-state.json` (production) | IMPLEMENT | LIVE — `chat-monitor.service` (`scripts/chat-monitor.py:46`) + `ChatSignals.publish_chat_state_sidecar()` (`agents/studio_compositor/chat_signals.py:312`) | None |

Three publishers shipped. Three resolve as false-missings (no publisher required; consumer already has working upstream). One drift artefact remains.

## Per-Publisher Design (shipped)

### Publisher 1 — `recent-impingements.json`

- **Producer:** `agents/recent_impingements_producer/` (dedicated agent)
- **Unit:** `systemd/units/hapax-recent-impingements.service` (always-on daemon)
- **Input:** `/dev/shm/hapax-dmn/impingements.jsonl` (daimonion writes)
- **Output:** `/dev/shm/hapax-compositor/recent-impingements.json`
- **Cadence:** 500 ms tail-read, top-N by salience
- **Atomic write:** tmp + `Path.replace()` pattern
- **Failure posture:** stale file → consumer falls back to `_active_perceptual_signals()` walk in `hothouse_sources.py`

### Publisher 4 — `youtube-viewer-count.txt`

- **Producer:** `scripts/youtube-viewer-count-producer.py`
- **Service:** `systemd/units/hapax-youtube-viewer-count.service`
- **Timer:** present in `~/.config/systemd/user/hapax-youtube-viewer-count.timer` (live) but **absent from repo** — drift
- **Input:** YouTube Data API v3 (`videos.list` → `concurrentViewers`)
- **Output:** `/dev/shm/hapax-compositor/youtube-viewer-count.txt` (plain integer, no newline)
- **Cadence:** 90 s (timer-driven)
- **Quota:** ~960 units/day (feasible under default 10k/day; operator has cc-task `ytb-OG3` open to request quota extension for other usage)
- **Failure posture:** write `0` on offline broadcast; consumer already tolerates missing file

### Publisher 6 — `chat-state.json`

- **Producer:** `scripts/chat-monitor.py` (primary, `active (running)` as `chat-monitor.service`); secondary writer `ChatSignals.publish_chat_state_sidecar()` in `agents/studio_compositor/chat_signals.py:312`
- **Input:** YouTube IRC (`chat-downloader` library) via `chat-monitor.py`; aggregation via `ChatSignalsAggregator`
- **Output:** `/dev/shm/hapax-compositor/chat-state.json` (2-field schema: `total_messages`, `unique_authors`)
- **Cadence:** per-message + periodic flush; file stays fresh while `chat-monitor.service` is up
- **Failure posture:** chat-monitor bails cleanly on no-broadcast (empty chat); consumer renders `[CHAT|idle]`

## Retirement Rationale (false-missings)

The audit identified three "missing" files whose consumer wards already render against a different upstream. None require a new publisher:

### `chat-keyword-aggregate.json` + `chat-tier-aggregates.json` → RETIRE

The consumer is `agents/studio_compositor/chat_ambient_ward.py`. Its canonical input (line 243 docstring) is `shared/hapax-chat-signals.json` (i.e. `/dev/shm/hapax-chat-signals.json`). That file is written every ~30 s by `ChatSignalsAggregator` (`agents/studio_compositor/chat_signals.py:56, DEFAULT_CHAT_SIGNALS_PATH`) and contains all four fields the ward needs (`t5_rate_per_min`, `t6_rate_per_min`, `unique_t4_plus_authors_60s`, `t4_plus_rate_per_min`, plus `audience_engagement` + `message_rate_per_min`). The two audit file names were aspirational labels that never matched the shipped consumer code. No rename, alias, or new producer is required.

**Action:** Mark both entries RETIRED in the FINDING-V tracker. No code changes.

### `grounding-provenance.jsonl` → RETIRE

The consumer is `GroundingProvenanceTickerCairoSource` in `agents/studio_compositor/legibility_sources.py`. Its read path is `_read_latest_intent()` (lines 62–64, 690–691) which tails `~/hapax-state/stream-experiment/director-intent.jsonl` and extracts `.get("grounding_provenance")` from the most recent entry. Director INTENT JSONL already contains the provenance array on every intent emission. A separate `grounding-provenance.jsonl` would duplicate data and add staleness without any benefit the ward could use.

**Action:** Mark RETIRED in the FINDING-V tracker. No code changes.

## Remaining Gap — youtube-viewer-count.timer drift

The timer unit file exists in live user-systemd state (`~/.config/systemd/user/hapax-youtube-viewer-count.timer`) but is **absent from the repo** (`systemd/units/`). `systemctl --user status` reports:

```
hapax-youtube-viewer-count.timer
  Loaded: not-found (Reason: Unit hapax-youtube-viewer-count.timer not found.)
  Active: active (running) since Wed 2026-04-22 14:48:34 CDT
```

The daemon is running from cached systemd state; the unit file itself disappeared. This is a quiet drift bug — the next `systemctl --user daemon-reload` or rebuild step that re-materialises the unit directory could remove the timer entirely.

**Required:**
1. Copy the live unit file from `~/.config/systemd/user/hapax-youtube-viewer-count.timer` into `systemd/units/hapax-youtube-viewer-count.timer` (repo).
2. Ensure the installer (`systemd/README.md` install step) deploys both `.service` and `.timer`.
3. Add a regression pin in `tests/systemd/` matching the existing unit-file parity test pattern.

**Failure posture:** if the timer unit is lost before this spec lands, the service would stop being triggered at 90 s cadence. The file would freeze at its last-written value. Consumer would render a stale viewer count until `chat-monitor.service` output (which is unrelated) flushes.

## Test Strategy

For each publisher — both shipped and retired — at least one regression pin in `tests/` to prevent drift:

| Publisher | Pin type | Path |
|---|---|---|
| `recent-impingements.json` | Source-grep pin: assert `hapax-recent-impingements.service` exists in `systemd/units/` | `tests/systemd/test_publisher_units_present.py` |
| `youtube-viewer-count.txt` | Source-grep pin: assert both `.service` AND `.timer` exist in `systemd/units/` | same file |
| `chat-state.json` | Source-grep pin: assert `chat-monitor.service` exists; assert `ChatSignals.publish_chat_state_sidecar` function exists | `tests/studio_compositor/test_chat_signals_publishers.py` |
| `chat-keyword-aggregate.json` + `chat-tier-aggregates.json` (retired) | Contract pin: assert no code references these filenames (prove the audit labels are dead) | `tests/studio_compositor/test_chat_ambient_ward_canonical_input.py` |
| `grounding-provenance.jsonl` (retired) | Contract pin: assert `_read_latest_intent()` exists and reads `director-intent.jsonl`; assert no code references a separate `grounding-provenance.jsonl` | `tests/studio_compositor/test_grounding_ticker_intent_read.py` |

The two retirement pins are load-bearing: they prevent a future audit from reopening the false-missing entries.

## Schemas (for retirement pins + future drift)

### `recent-impingements.json` (Pydantic model in `shared/`)

```python
class RecentImpingement(BaseModel):
    path: str
    value: float
    family: str

class RecentImpingementsSnapshot(BaseModel):
    generated_at: float  # epoch seconds
    entries: list[RecentImpingement]  # top-N by salience, N ≤ 6
```

### `chat-state.json`

```python
class ChatState(BaseModel):
    generated_at: float
    total_messages: int
    unique_authors: int
```

### `youtube-viewer-count.txt`

Plain integer text, no newline, no JSON. Schema = single `int` in `[0, ∞)`.

## Out of Scope

- **FINDING-V Q4 chat-keywords consumer ward** (ef7b-180) — a different cc-task; research + design for a new ward using chat keyword data. Not part of FINDING-V publisher work.
- **FINDING-V-corollary** (HARDM perception sources) — separate cascade, alpha-owned.
- **Implementation PRs for the remaining timer-drift fix** — see plan doc.
- **FINDING-W** — shipped in PRs #1316 + #1330 (ef7b-179).

## Constraints Applied

All publisher designs respect the memory guardrails:

- `feedback_scientific_register` — neutral prose
- `feedback_cross_reference_audits` — explicit cross-refs to 2026-04-20 wiring audit and 2026-04-21 research doc
- `feedback_hapax_authors_programmes` — no operator hand-input as sole data source
- `feedback_no_expert_system_rules` — no hardcoded cadence/threshold gates
- `feedback_composites_as_sources` — each publisher is independently tappable
- `feedback_show_dont_tell_director` — no publisher narrates compositor/director actions
- `feedback_grounding_exhaustive` — publishers are deterministic code (not LLM calls), so the grounding-acts operative definition does not apply

## References

- `docs/research/2026-04-21-missing-publishers-research.md` (parent research)
- `docs/research/2026-04-20-wiring-audit-findings.md` §FINDING-V (lines 650–688)
- `docs/research/2026-04-20-finding-v-deploy-status.md` (prior deploy status snapshot)
- `~/.cache/hapax/relay/alpha-to-delta-2026-04-21-finding-v-producers.md` (handoff)
- `agents/studio_compositor/chat_signals.py` (ChatSignalsAggregator + chat-state sidecar)
- `agents/studio_compositor/chat_ambient_ward.py:243` (canonical ward input docstring)
- `agents/studio_compositor/legibility_sources.py::_read_latest_intent` (lines 62–64, 690–691)
- `scripts/chat-monitor.py` (production chat-state.json writer)
- `scripts/youtube-viewer-count-producer.py` (viewer count producer)
- `systemd/units/hapax-youtube-viewer-count.service` (shipped)
- `systemd/units/hapax-recent-impingements.service` (shipped)
