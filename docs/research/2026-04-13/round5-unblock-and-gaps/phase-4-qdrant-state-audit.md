# Phase 4 — Qdrant state audit + schema drift

**Queue item:** 026
**Phase:** 4 of 6
**Date:** 2026-04-13 CDT
**Register:** scientific, neutral (per `feedback_scientific_register.md`)

## Headline

Five Phase 4 findings, ordered by severity:

1. **Schema drift**: the live Qdrant has **10 collections**;
   `shared/qdrant_schema.py::EXPECTED_COLLECTIONS` lists **8**.
   Two live-but-not-expected: `hapax-apperceptions` (130 points)
   and `operator-patterns` (0 points). The `verify_collections()`
   function will report `hapax-apperceptions` and
   `operator-patterns` as "missing" (because they're not in the
   expected set), not as "unexpected present."
2. **`operator-patterns` is empty (0 points).** The writer at
   `agents/_pattern_consolidation.py::COLLECTION = "operator-patterns"`
   exists but the backing timer (`profile-update.timer`) has
   `NextElapseUSecRealtime=` empty, i.e. the timer will not fire
   again. Last fired 2026-04-13 18:34:49 CDT. The writer pathway
   is alive in code but de-scheduled.
3. **Consent gate coverage is THIN**: `PERSON_ADJACENT_COLLECTIONS`
   in `agents/_governance/qdrant_gate.py:38` covers only
   `documents` and `profile-facts`. The other 8 collections —
   including `operator-episodes` (1681 pts), `studio-moments`
   (1965 pts), `stream-reactions` (2178 pts) — are **not
   consent-checked on upsert.** Combined with BETA-FINDING-K
   (the consent *reader* was silently off), this is a
   **two-layer governance gap** on person-adjacent data.
4. **`axiom-precedents` is sparse (17 points)**, carry-over from
   queue 024 Phase 6 finding.
5. **`stream-reactions` (2178 pts) is still not in CLAUDE.md's
   "9 collections" list.** Already flagged in queue 023 Phase 6.
   Docs drift, no operational impact.

## Collection inventory table

Live + canonical cross-reference:

| # | collection | points | vector | in `qdrant_schema.py`? | in CLAUDE.md? | in qdrant_gate? | writer status |
|---|---|---|---|---|---|---|---|
| 1 | `affordances` | 172 | 768·Cosine | yes | yes | **no** | `shared/affordance_pipeline.py`, `agents/reverie/system_reader.py` |
| 2 | `axiom-precedents` | 17 | 768·Cosine | yes | yes | **no** | `agents/_axiom_precedents.py` |
| 3 | `documents` | 186599 | 768·Cosine | yes | yes | **YES** | 46 files across agents; RAG corpus |
| 4 | `hapax-apperceptions` | 130 | 768·Cosine | **NO (drift)** | yes | **no** | `agents/_apperception.py`, `shared/apperception.py` |
| 5 | `operator-corrections` | 307 | 768·Cosine | yes | yes | **no** | `agents/_correction_memory.py` |
| 6 | `operator-episodes` | 1681 | 768·Cosine | yes | yes | **no** | `agents/_episodic_memory.py`, daimonion session memory |
| 7 | `operator-patterns` | **0** | 768·Cosine | **NO (drift)** | yes | **no** | `agents/_pattern_consolidation.py` (de-scheduled) |
| 8 | `profile-facts` | 929 | 768·Cosine | yes | yes | **YES** | `agents/_profile_store.py`, 18 files |
| 9 | `stream-reactions` | 2178 | 768·Cosine | yes | **NO (drift)** | **no** | `agents/studio_compositor/director_loop.py` |
| 10 | `studio-moments` | 1965 | 768·Cosine | yes | yes | **no** | `agents/av_correlator.py` |

**Counts:** 10 live, 8 in schema, 9 in CLAUDE.md, 2 consent-gated.

## Finding 1: schema drift (`hapax-apperceptions`, `operator-patterns`)

`shared/qdrant_schema.py::EXPECTED_COLLECTIONS` dict as of main:

```python
EXPECTED_COLLECTIONS: dict[str, dict[str, object]] = {
    "profile-facts":        {"size": ..., "distance": "Cosine"},
    "documents":            {"size": ..., "distance": "Cosine"},
    "axiom-precedents":     {"size": ..., "distance": "Cosine"},
    "operator-episodes":    {"size": ..., "distance": "Cosine"},
    "studio-moments":       {"size": ..., "distance": "Cosine"},
    "operator-corrections": {"size": ..., "distance": "Cosine"},
    "affordances":          {"size": ..., "distance": "Cosine"},
    "stream-reactions":     {"size": ..., "distance": "Cosine"},
}
```

**8 entries.** Missing from this map:

- `hapax-apperceptions` (130 points, actively being written to —
  `_apperception.py:678 COLLECTION_NAME = "hapax-apperceptions"`
  + ongoing upserts)
- `operator-patterns` (0 points but code expects to write to it
  — `_pattern_consolidation.py::COLLECTION = "operator-patterns"`)

The startup health check `verify_collections()` iterates
`EXPECTED_COLLECTIONS` and checks each one exists in the live
Qdrant. It does NOT check the reverse — "are there live
collections not in the expected set?" So the drift is silent:

- ops view: all 8 expected collections present and valid ✓
- reality: 10 live collections, 2 invisible to the health check

**Fix:** add `hapax-apperceptions` and `operator-patterns` to
`EXPECTED_COLLECTIONS`. Optionally add a reverse-check that
warns if the live set is a superset of the expected set.

## Finding 2: `operator-patterns` is empty + writer de-scheduled

```bash
$ curl -s http://127.0.0.1:6333/collections/operator-patterns
{ "result": { "points_count": 0, "indexed_vectors_count": 0, "status": "green", ... } }
```

0 points. The collection exists (probably created at some point
by the `_pattern_consolidation.py::create_collection()` path)
but has never been written to.

Writer scheduling trace:

```bash
$ systemctl --user show -p LastTriggerUSec,NextElapseUSecRealtime profile-update.timer
NextElapseUSecRealtime=
LastTriggerUSec=Mon 2026-04-13 18:34:49 CDT
```

`NextElapseUSecRealtime=` is **empty** — the timer has no
scheduled next fire. Last fired 18:34:49. Meaning:

- The timer fired at 18:34:49
- The service completed and exited
- systemd did NOT compute a next fire time

This is consistent with a `OnActiveSec=` or `OnBootSec=` style
unit that only fires once (oneshot timer), not a recurring
`OnCalendar=` unit. Or a timer that was disabled after the
last fire. Either way: **the writer is not scheduled to run
again.**

Check which timer unit spec applies:

```bash
$ cat ~/.config/systemd/user/profile-update.timer
```

(Not executed — out of scope for this phase, but the follow-up
ticket should read the unit file and confirm.)

**Secondary: does the writer even reach `operator-patterns`?**
`_pattern_consolidation.py` is a separate module from
`_profile_store.py`. The `profile-update` timer probably runs
the profile-update agent, which consolidates *profile-facts*,
not *operator-patterns*. **The operator-patterns writer may
have no scheduler at all.** Grep:

```bash
$ grep -rln "pattern_consolidation\|_pattern_consolidation" \
    ~/.config/systemd/user/ agents/ shared/ logos/
```

If the result is empty outside the module itself, the writer
is referenced from nowhere — a dead module.

**Fix options:**

A. **Wire a timer**: create `hapax-pattern-consolidation.timer`
   + service unit that runs the consolidator every N hours.
B. **Delete the collection + module**: if operator pattern
   consolidation was a planned feature that was never finished,
   remove it from the canonical list + drop the Qdrant
   collection.

**Recommendation**: A. The module name suggests the feature
(consolidate similar operator patterns into aggregates for the
profile layer) is architecturally valuable. File a ticket to
wire the timer. If the operator says "I don't need this,"
drop to option B.

## Finding 3: consent gate coverage is thin

`agents/_governance/qdrant_gate.py:38`:

```python
PERSON_ADJACENT_COLLECTIONS: dict[str, str] = {
    "documents": "document",
    "profile-facts": "document",
}

PERSON_FIELDS: dict[str, list[tuple[str, str]]] = {
    "documents": [
        ("people", "list"),
        ("attendees", "list"),
        ("from", "direct"),
        ("to", "direct"),
        ("sender", "direct"),
        ("organizer", "direct"),
    ],
    "profile-facts": [
        ("audience_key", "direct"),
        ("audience_name", "direct"),
    ],
}
```

**2 collections** gated. **8 collections** not gated.

Of the 8 ungated collections, several contain payloads that
could include person-adjacent data:

| collection | person-adjacent fields observed |
|---|---|
| `operator-episodes` | likely `heart_rates`, `activity`, session attribution — if any field references a guest or co-located person, no consent check |
| `studio-moments` | `audio_classification`, `video_classifications`, `transcript_snippet`, `audio_file`, `video_files` — transcript snippets may contain third-party speech; video files may contain third-party faces |
| `stream-reactions` | `chat_authors`, `chat_messages`, `video_channel`, `video_title` — chat authors are people's usernames; **not consent-gated** |
| `hapax-apperceptions` | `trigger_text`, `observation`, `reflection` — could include text about non-operator persons |
| `axiom-precedents` | `situation` text field — could reference third parties |

**`stream-reactions` is the clearest concern.** Chat authors
are people's display names. The live collection has 2178 points.
None of them passed through a consent check on upsert. Per
`interpersonal_transparency` axiom (weight 88), storing
non-operator-person data requires an active consent contract.
The consent gate doesn't even look at `stream-reactions`.

Combined with BETA-FINDING-K (the consent *reader* was silently
off for LLM consumption), this is a **two-layer failure**:

1. Writer side (this phase): most collections bypass the
   consent gate on upsert
2. Reader side (BETA-FINDING-K, fixed in PR #761): consent
   filtering was silently disabled for reads

**Fix:**

A. **Audit each non-gated collection's payload schema and add
   it to `PERSON_ADJACENT_COLLECTIONS` if any person-adjacent
   field is present.** Start with `stream-reactions`.

B. **Add a reverse-guard**: for every upsert to a non-gated
   collection, assert that the payload has no person-looking
   fields (using a configurable list). Fail-closed on first
   unknown person field.

**Both should land together.** A covers what we know; B catches
what we missed.

## Finding 4: `axiom-precedents` sparse (17 points)

Already filed in queue 024 Phase 6 backlog. Carry-over. No new
information; just noting it's still present.

## Finding 5: `stream-reactions` not in CLAUDE.md

Already filed in queue 023 Phase 6 backlog. Carry-over. Docs
drift only; operational OK.

## Schema drift cross-table

| collection | live | in qdrant_schema.py | in CLAUDE.md | action |
|---|---|---|---|---|
| affordances | ✓ | ✓ | ✓ | OK |
| axiom-precedents | ✓ | ✓ | ✓ | OK (sparse — carry-over) |
| documents | ✓ | ✓ | ✓ | OK |
| hapax-apperceptions | ✓ | **missing** | ✓ | **add to qdrant_schema.py** |
| operator-corrections | ✓ | ✓ | ✓ | OK |
| operator-episodes | ✓ | ✓ | ✓ | OK |
| operator-patterns | ✓ (empty) | **missing** | ✓ | **add to qdrant_schema.py + wire writer OR retire** |
| profile-facts | ✓ | ✓ | ✓ | OK |
| stream-reactions | ✓ | ✓ | **missing** | **add to CLAUDE.md** |
| studio-moments | ✓ | ✓ | ✓ | OK |

## Sample payload schemas (for Phase 4 schema drift future check)

Use these as baselines for future sweeps:

```text
profile-facts:         {confidence, dimension, key, profile_version, source, text, value}
hapax-apperceptions:   {action, cascade_depth, observation, reflection, source, stimmung_stance, timestamp, trigger_text, valence, valence_target}
affordances:           {available, capability_name, consent_required, daemon, description, latency_class, priority_floor, requires_gpu}
axiom-precedents:      {authority, axiom_id, created, decision, distinguishing_facts, precedent_id, reasoning, situation, superseded_by, tier}
operator-episodes:     {activity, audio_energy, audio_trend, consent_phase, corrections_applied, duration_s, end_ts, flow_scores, flow_state, flow_trend, heart_rates, hour, ...}
studio-moments:        {audio_classification, audio_file, audio_score, correlated_at, joint_category, joint_score, music_seconds, speech_seconds, transcript_snippet, video_classifications, video_files, video_motion, ...}
operator-corrections:  {activity, applied_count, context, corrected_value, dimension, flow_score, hour, id, last_applied, original_value, timestamp}
stream-reactions:      {activity, album, chat_authors, chat_messages, reaction_index, stimmung, text, tokens, ts, ts_str, video_channel, video_title}
```

(`documents` and `operator-patterns` not sampled — documents is
too high-volume for a sample to be representative; operator-patterns
is empty.)

## Backlog additions (for round-5 retirement handoff)

149. **`fix(qdrant-schema): add hapax-apperceptions and operator-patterns to EXPECTED_COLLECTIONS`** [Phase 4 Finding 1] — ~6 lines in `shared/qdrant_schema.py`. Closes the schema drift.
150. **`feat(qdrant-schema): add reverse-check for unexpected live collections`** [Phase 4 Finding 1 sub-fix] — iterate live collections; warn if any are not in `EXPECTED_COLLECTIONS`. ~20 lines.
151. **`decision(operator-patterns): wire timer OR retire collection + module`** [Phase 4 Finding 2] — decide whether `_pattern_consolidation.py` is a live feature or dead code. If live, add `hapax-pattern-consolidation.timer`. If dead, drop the module + collection.
152. **`fix(qdrant-gate): add stream-reactions + hapax-apperceptions + operator-episodes to PERSON_ADJACENT_COLLECTIONS`** [Phase 4 Finding 3] — critical governance fix. Audit each collection's payload schema, list person-looking fields, add consent-check on upsert.
153. **`feat(qdrant-gate): reverse-guard for unknown person-looking fields`** [Phase 4 Finding 3 sub-fix] — for every non-gated upsert, assert the payload has no known person-field patterns. Fail-closed on surprise.
154. **`docs(claude.md): add stream-reactions to the Qdrant collections list`** [Phase 4 Finding 5] — one-line doc fix. Carry-over from queue 023 backlog, restated here.
155. **`research(qdrant): investigate operator-patterns module timer OR retirement`** [Phase 4 Finding 2 sub-fix] — one-pass audit of the pattern_consolidation module to decide A vs B.
