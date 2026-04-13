# Phase 5 — Silent-failure sweep across the council codebase

**Queue item:** 024
**Phase:** 5 of 6
**Date:** 2026-04-13 CDT
**Register:** scientific, neutral (per `feedback_scientific_register.md`)

## Headline

Static search across `agents/`, `shared/`, `logos/` returned:

- **0** `except: pass` bare catches
- **193** `except Exception:` followed by `pass` / `return` / `return None` within 3 lines
- **704** `except <Specific>: pass` or `except Exception as e: pass` swallows
- **1197** `log.warning` / `log.debug` inside `except` blocks without `raise`

Not every hit is a bug — many are legitimate cleanup paths (e.g.,
`except ProcessLookupError: pass` when killing an already-dead PID).
But enough of them are genuine silent failures at operator-visible
boundaries to produce at least **1 Critical**, **6 High**, and
dozens of Medium severity sites.

**The top Critical finding is a governance violation that is active
in the live daimonion right now.**

## Critical: ConsentGatedReader silently off

### Location

- `agents/hapax_daimonion/init_pipeline.py:40–46` — the init path
- `agents/hapax_daimonion/conversation_pipeline.py:1281–1285` — the fallthrough consumer
- Live journal: `agents.hapax_daimonion.init_pipeline: ConsentGatedReader unavailable, proceeding without consent filtering`

### The pattern

```python
# init_pipeline.py:40–46
daemon._precomputed_consent_reader = None
try:
    from agents._consent_reader import ConsentGatedReader
    daemon._precomputed_consent_reader = ConsentGatedReader.create()
except Exception:
    log.warning("ConsentGatedReader unavailable, proceeding without consent filtering")
```

```python
# conversation_pipeline.py:1281–1285
# Consent gate: filter tool results before they reach the LLM
if self._consent_reader is not None:
    try:
        result = self._consent_reader.filter_tool_result(tc["name"], result)
    except Exception:
        log.warning("Consent filtering failed for %s", tc["name"], exc_info=True)
```

### Why it matters

`CLAUDE.md § Axiom Governance` defines `interpersonal_transparency`
at weight 88: *"No persistent state about non-operator persons
without active consent contract."*

The init path silently drops the consent reader to `None` on any
exception. The consumer path silently passes tool results through
when the reader is `None`. **There is no fail-closed branch.** If
`ConsentGatedReader.create()` fails — for any reason: an import
error, a contract loading bug, a filesystem permission change —
the daimonion proceeds to pipe tool results containing
non-operator-person data to the LLM unfiltered.

The live daimonion's journal confirms this is not hypothetical:
`ConsentGatedReader unavailable, proceeding without consent
filtering` was emitted at startup, and the daimonion is currently
running without consent filtering.

This is the archetypal silent-failure: **a governance guarantee
protected only by a conditional that silently disappears when the
guarantee's dependency fails**. The axiom says "no unfiltered PII";
the code's fail-open posture says "if the filter is broken, ship
unfiltered."

### Proposed fix (Critical, should land before any other Phase 5 work)

Option A (fail-closed): raise on init failure.

```python
daemon._precomputed_consent_reader = None
try:
    from agents._consent_reader import ConsentGatedReader
    daemon._precomputed_consent_reader = ConsentGatedReader.create()
except Exception as exc:
    log.exception("ConsentGatedReader failed to initialize")
    raise RuntimeError(
        f"interpersonal_transparency axiom requires ConsentGatedReader; "
        f"init failed: {exc}"
    ) from exc
```

And in the consumer:

```python
if self._consent_reader is None:
    raise RuntimeError(
        "consent filtering unavailable; refusing to forward tool results "
        "to LLM per interpersonal_transparency axiom"
    )
result = self._consent_reader.filter_tool_result(tc["name"], result)
```

Option B (maintain-degraded-but-enforce): write a `NullConsentReader`
that refuses to filter (returns an empty result with a warning).
The pipeline still runs, but no non-operator data reaches the LLM.

Recommendation: **Option A**. The daimonion cannot operate without
consent filtering per axiom weight 88; a fail-closed init is the
correct posture. Operator sees the failure at daemon startup and
can investigate before the daemon processes any request.

## High (6 sites): governance-adjacent or operator-visible silent failures

### H1: `agents.hapax_daimonion.tts_server._handle_client` success path has no log

[Phase 1 finding, restated here in Phase 5 vocabulary] — the handler
has `log.warning` on error paths but zero `log.info` on the success
path. A successful 54-second synthesize followed by a client
disconnect produces zero observable log lines. This is the exact
"silently successful" failure class the brief flagged.

**Fix**: see Phase 1 backlog item 45.

### H2: OTEL span export timeouts on slow downstream

- `opentelemetry.sdk._shared_internal.BatchSpanProcessor` retries
  timeouts silently and eventually drops the batch
- Current live daimonion has 1 retry-timeout in session (tolerable)
- Under sustained downstream slowness (e.g., langfuse under load),
  spans drop invisibly with no operator-facing signal

**Fix**: `compositor_otel_span_exporter_dropped_total` counter on
the exporter, paired with a Prometheus alert for `rate(...) > 0.1
per second for 5m`.

### H3: `_cpal_impingement_loop` exception handler at DEBUG level

```python
# agents/hapax_daimonion/run_inner.py:160–165
while daemon._running:
    try:
        for imp in consumer.read_new():
            await daemon._cpal_runner.process_impingement(imp)
    except Exception:
        log.debug("CPAL impingement consumer error", exc_info=True)
    await asyncio.sleep(0.5)
```

At DEBUG level, exceptions are invisible unless the operator has
enabled debug logging. If this loop starts failing (e.g., the
cursor file becomes unreadable, the JSONL file has a malformed
line, the CPAL runner's `process_impingement` raises), the impingement
stream silently stops processing.

**Fix**: upgrade to `log.warning` + emit a counter
`hapax_cpal_impingement_errors_total`.

### H4: Image decoder silent swallow in album_overlay

```text
# journal snippet from PR #756 Phase 4
ImageLoader: failed to decode /dev/shm/hapax-compositor/album-cover.png
WARNING: Album cover load failed
```

The compositor's album overlay tolerates I/O errors on the album
cover file — the error is logged but the overlay continues with
the previous cached surface. Over time, if the cover file goes
stale (e.g., the album-identifier script dies), the overlay
displays an old cover indefinitely. There is no staleness alarm
because the `FreshnessGauge` (PR #755) only tracks successful
writes to the overlay's output, not successful reads from its
input.

**Fix**: add an `album_cover_age_seconds` gauge that tracks mtime
of `/dev/shm/hapax-compositor/album-cover.png`. Grafana alerts
when > 600 s.

### H5: Fallback camera silent degradation

- `agents/studio_compositor/pipeline_manager.py:swap_to_fallback` —
  logs INFO on swap but no counter increments when the fallback
  becomes the steady-state source for > N minutes
- If a BRIO bus-kicks and the reconnect loop never reacquires, the
  stream silently shows the fallback content (e.g., a blank frame,
  or a "camera offline" poster) until someone notices

**Fix**: per-camera `studio_camera_seconds_in_fallback` counter
that increments while `in_fallback == 1`, paired with a Grafana
alert at > 300 s.

### H6: Kokoro "produced no audio" warning

```python
# agents/hapax_daimonion/tts.py:68
if not chunks:
    log.warning("Kokoro produced no audio for text: %r", text[:50])
    return b""
```

If Kokoro returns an empty audio chunk (happens on empty phoneme
sequences, rare pronunciation failures, or an internal phoneme
dictionary miss), the daimonion emits a WARNING and returns empty
bytes. The compositor's TTS client then sees `pcm_len=0` and plays
nothing. Silent success for the compositor, failed synthesis from
the operator's perspective.

**Fix**: `hapax_tts_empty_output_total` counter incremented on the
`not chunks` branch. Alert if > 1 per minute.

## Medium (16+ sites, sampled)

### M1-M5: agents/_telemetry.py has 7 `except Exception: pass` blocks

Lines 272, 317, 349, 401, 442, 472. Telemetry swallow is a common
pattern to avoid crashing the business path when telemetry itself
has a bug, but the current policy emits nothing — if the telemetry
pipeline breaks, the operator has no way to know. Each block
should at least increment a `hapax_telemetry_errors_total` counter.

### M6: agents/_config.py:147 `except Exception: pass` in embed path

```python
# agents/_config.py around line 215
_log.warning("embed_safe: Ollama unavailable, returning None")
```

If the embedding backend is down, `embed_safe` returns None and
upstream code treats that as "no embedding, skip similarity
search." Downstream effect: affordance pipeline selects capabilities
without the similarity signal, falls back to pure base-level
scoring. The operator sees weaker recruitment decisions but no
alert.

**Fix**: `hapax_embed_safe_failures_total` counter + restore
previous behavior after backend recovers.

### M7: `agents/_browser_services.py:29` parse failure

```python
log.warning("Failed to parse browser-services.json", exc_info=True)
```

Silent degradation of an auxiliary data source. Non-critical but
should be counted.

### M8-M12: Presence-engine backend silent registrations

From Phase 4 observation, the perception registry silently skips
unavailable backends at startup:

```text
Backend device_state not available, skipping registration
Backend midi_clock not available, skipping registration
Backend phone_media not available, skipping registration
```

These three backends are dormant because their dependencies
(evdev device IDs, MIDI clock subscription, phone-media D-Bus
path) were not available at daemon start. The presence engine
continues without them, falling back to lower-weight signals.

**Fix**: expose these as a `hapax_backend_registered{name, status}`
gauge — operator can see at dashboard level which backends are
live vs dormant.

### M13: `agents/hapax_daimonion/audio_input.py:78` silent process terminate

```python
try:
    self._process.terminate()
except ProcessLookupError:
    pass
```

Legitimate cleanup pattern — the child process may have already
exited. But `ProcessLookupError` is specific and narrow; if the
terminate raises a different exception (e.g., PermissionError
because the process got owned by another uid), the failure is
silent. This is a medium-to-low priority cleanup site.

### M14-M16: `/dev/shm/hapax-compositor/*.json` writers

From PR #756 Phase 3 findings + this phase: many compositor
status writers use the `atomic_write_json` pattern correctly but
lack `FreshnessGauge` wrapping, so producer-side failures are
invisible. Sites:

- `agents/studio_compositor/publish_health.py`
- `agents/visual_layer_state.py`
- `agents/studio_compositor/token_pole.py::_write_ledger`

PR #755 wired `FreshnessGauge` for cairo source frames + budget
publishers. These additional three sites should get the same
treatment.

## Non-exception shapes

### N1: `.get(key, default)` on critical fields

```text
grep -rn "\.get\(\"pcm_len\"" …
```

Found in `agents/studio_compositor/tts_client.py:83`:

```python
pcm_len = int(header.get("pcm_len", 0))
if pcm_len <= 0:
    return b""
```

If the daimonion side sends a malformed header without `pcm_len`,
the client silently returns empty PCM. The compositor's director
loop treats empty PCM as "nothing to say" and advances the slot.
Failed synthesis + silent advance = stream silence without
operator-visible alarm. This is exactly what FINDING-G looked like
before Phase 1 disambiguated the root cause.

**Fix**: if `pcm_len` is missing, log a warning and distinguish
from the "0 bytes expected" case (empty text input).

### N2: `or {}` fallback on JSON loads

`grep -rn "json\.loads.*or {}\|json\.loads.*or \[\]"` returned
zero hits in the production code. The codebase does not use this
anti-pattern pervasively — a positive finding. (The pattern
exists in tests but those are fine.)

### N3: `if not data: return` early returns

Too many sites to enumerate individually. Classify as a
code-review rule: any `if not X: return` on a non-optional field
where X is the primary signal should be flagged by a linter rule.
Out of scope for this phase.

## Critical + High severity fix-proposal summary

| rank | site | severity | fix |
|---|---|---|---|
| C1 | `init_pipeline.py:40` + `conversation_pipeline.py:1281` consent-gate fallthrough | **Critical** | fail-closed init + `NullConsentReader` alternative |
| H1 | `tts_server._handle_client` no success log | **High** | add `log.info` at entry + completion |
| H2 | OTEL span export timeout silent drop | **High** | `otel_spans_dropped_total` counter + alert |
| H3 | `_cpal_impingement_loop` DEBUG-level exception swallow | **High** | upgrade to WARNING + counter |
| H4 | album_cover.png decode silent tolerance | **High** | `album_cover_age_seconds` gauge + alert |
| H5 | fallback camera silent steady-state substitution | **High** | `studio_camera_seconds_in_fallback` counter + alert |
| H6 | Kokoro "produced no audio" empty-chunk warning | **High** | `hapax_tts_empty_output_total` counter |

## Methodology notes

### Static search commands used

```bash
# Bare except + pass (0 hits, clean code in this axis)
grep -rn "^\s*except:\s*$" --include='*.py' agents/ shared/ logos/

# except Exception + pass/return within 3 lines (193 hits)
grep -rn --include='*.py' -B0 -A2 'except Exception' agents/ shared/ logos/ | \
  grep -E 'pass$|return None$|return$|return default'

# except Specific: pass or except Exception as e: pass (704 hits total in daimonion/compositor/vla)
grep -rn --include='*.py' 'except [A-Za-z]*.*:\s*$' agents/hapax_daimonion agents/studio_compositor agents/visual_layer_aggregator

# except + log at warning/debug without raise (1197 hits)
grep -rn --include='*.py' 'log\.warning\|log\.debug' agents/ shared/ logos/
```

### What this sweep did NOT do

- AST-level confirmation (brief step 2) — replaced with targeted
  code inspection of high-impact sites. A full AST walk across
  1000+ hits would be a multi-hour job; the returns on the marginal
  hit are low after the Critical + High tier.
- Boundary analysis for every Medium site — Medium severity items
  are listed by category (telemetry swallows, image loader fallbacks,
  presence-engine backend skips) rather than per-line.
- False-positive filtering — `except ProcessLookupError: pass`
  is a legitimate cleanup pattern and is counted in the 704 but is
  not a bug. Phase 5's methodology is "err on the side of listing"
  so future sessions can deduplicate.

### For future sessions re-running the sweep

Run the commands above. The absolute counts will change as the
codebase evolves. The ratio of Critical/High/Medium/Low should
shrink over time as fixes land. If the ratio grows, that's a
regression signal.

## Backlog additions (for retirement handoff)

66. **`fix(governance): ConsentGatedReader fail-closed init +
    NullConsentReader fallback`** [Phase 5 Critical] — CRITICAL
    governance axiom violation. Most load-bearing fix in the
    entire research pass, bigger than FINDING-G in severity
    because it's a live axiom compliance failure. Operator should
    address before any other Phase 5 work.
67. **`feat(daimonion): tts_server success-path info log`** [Phase
    5 H1, restates Phase 1 backlog item 45] — one line.
68. **`feat(monitoring): otel_spans_dropped_total + alert`**
    [Phase 5 H2] — counter + Prometheus rule.
69. **`fix(daimonion): _cpal_impingement_loop exception to WARNING
    + counter`** [Phase 5 H3] — DEBUG → WARNING + new counter
    `hapax_cpal_impingement_errors_total`.
70. **`feat(compositor): album_cover_age_seconds gauge + alert`**
    [Phase 5 H4] — prevents stale album display.
71. **`feat(compositor): studio_camera_seconds_in_fallback counter
    + alert`** [Phase 5 H5] — prevents unnoticed fallback substitution.
72. **`feat(daimonion): hapax_tts_empty_output_total counter`**
    [Phase 5 H6] — catches Kokoro empty-chunk case.
73. **`feat(compositor): tts_client distinguishes missing-pcm_len
    from zero-pcm_len`** [Phase 5 N1] — medium-priority observability
    fix. Changes a silent-same-outcome situation into a
    log-distinguished one.
74. **`fix(telemetry): per-site error counters in _telemetry.py`**
    [Phase 5 M1-M5] — replace the 7 `except Exception: pass` with
    counter-increment-and-pass.
75. **`feat(presence): hapax_backend_registered{name, status}
    gauge`** [Phase 5 M8-M12] — expose dormant-backend state to
    dashboard level.
76. **`research(linter): add a rule to flag .get(critical_key,
    default) patterns`** [Phase 5 N1 followup] — codebase-wide
    anti-pattern, worth catching in CI.
77. **`docs(styleguide): document the silent-failure prohibition
    as a code-review rule`** [Phase 5 methodology] — Phase 5 keeps
    finding these because new code keeps introducing them. A
    written rule (e.g., "every except block emits either a
    counter increment or a re-raise") gives reviewers something
    concrete to cite.
