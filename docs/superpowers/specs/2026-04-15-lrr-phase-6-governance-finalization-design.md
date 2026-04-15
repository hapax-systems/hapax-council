# LRR Phase 6 — Governance Finalization + Stream-Mode Axis (design)

**Date:** 2026-04-15 CDT
**Author:** beta (pre-staged during LRR Phase 4 bootstrap / Hermes 3.5bpw quant wait window; operator ratifies at phase open)
**Parent epic spec:** `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` §Phase 6
**Depends on:** Phase 5 complete (Hermes 3 live — so Hapax can articulate its own consent state on-stream)
**Predecessor audits:**
- `docs/research/2026-04-13/round5-unblock-and-gaps/phase-4-qdrant-state-audit.md` (FINDING-R source)
- This file's companion `docs/research/2026-04-15/logos-livestream-ux-audit.md` (NEW — see §0.1 below for the four-axis logos audit beta ran at session start, folded in as §12 of this spec)
**Status:** DRAFT — spec pre-staged on `beta-phase-4-bootstrap` branch. Awaiting operator review before marked ready.
**Register:** scientific, neutral.

---

## 0. Context

Phase 6 closes the governance bucket of the Livestream Research Ready (LRR) epic. Under LRR's end-state, the 24/7 livestream is the exclusive vehicle for research data collection and the primary platform for development. Every byte that reaches the compositor's cairo layer, every API response consumed by `hapax-logos`, every Qdrant read returned to a reactor context call is potentially on-camera. The governance apparatus that was adequate for single-operator private work is not adequate for single-operator on-camera work.

Phase 6's scope partitions cleanly into four families:

1. **Constitutional layer** (§1, §8, §9) — write the "irreversible broadcast" implication in `hapax-constitution`; clarify `su-privacy-001` and `corporate_boundary` scope so they do not block legitimate research publication or silently fail under broadcast.
2. **Stream-mode axis + redaction engine** (§2, §4, §12) — introduce the four-mode stream-mode axis (`off`/`private`/`public`/`public_research`); implement per-endpoint and per-field redaction behind that axis; close frontend defense-in-depth via a new React `StreamAwarenessContext`; add the broadcast-safe typography tier to the design language.
3. **Closed loops** (§5, §6, §7) — operationalize the dormant `executive_function` axiom via a stimmung-aware auto-private watchdog; gate on presence-detect-without-contract; execute the mid-stream consent revocation drill end-to-end within 5 seconds.
4. **Infrastructure hygiene** (§3, §10, §11) — wrap all 10 Qdrant collections with `ConsentGatedWriter`; retire the dead `fortress` working-mode enum that has been causing repeated onboarding confusion; validate `ConsentRegistry` YAML shape at load time.

This spec is the operational checklist for Phase 6 open. Its role vs the epic section: the epic section tells you *what* Phase 6 accomplishes; this spec tells you *exactly which files*, *exactly which schemas*, *exactly which tests*, *exactly which verification commands*, and *what the rollback is if any item fails*.

### 0.1 Logos UX audit (folded into §12)

Before drafting this spec, beta ran a four-axis audit of `hapax-logos` to answer the question "what changes for logos if the 24/7 livestream is the exclusive R&D vehicle?" The audit covered structure/UX, data surfaces, design language application, and compositor integration. The audit's six-item recommendation list reduced to **one novel item** once mapped against this epic:

| Recommendation | Disposition |
|---|---|
| `GET /api/stream/active` primitive | Supersets into §2 (stream-mode axis, four modes not boolean) |
| Per-field redaction engine keyed on stream state | Supersets into §4 |
| Broadcast-safe typography tier | **Novel — folded in as §12 of this spec** |
| Logos → cairo overlay text pipeline | Supersets into Phase 8 §9 (Logos studio view tile) |
| Fortress mode fate | Supersets into §10 |
| Chain Builder wake-up | Not a gap — already wired at `hapax-logos/src/components/graph/nodes/OutputNode.tsx:184-281` |

The only surviving novel item is broadcast-safe typography. Everything else is a redundant rediscovery of material already in the epic, and this spec's job is to detail those items — not to re-justify them.

### 0.2 Scope boundary

**Phase 6 is a governance + safety phase.** It does not build new content primitives, camera profiles, objectives data structures, chat reactor extensions, or code-narration signal publishers. Those live in Phases 8 and 9. Phase 6 is the substrate that lets those phases operate under broadcast without violating the axioms.

Phase 6 is also **not the place** to formalize the persona spec (DF-1). Persona work is Phase 7. The stream-mode axis this phase introduces is a Phase 7 prerequisite; the persona spec will consume it but not define it.

---

## 1. Goal (recap)

1. `it-irreversible-broadcast.yaml` merged in `hapax-constitution` — the constitution recognizes that CDN-bound frames cannot be revoked, and this is a distinct persistence category from recording revocation.
2. `hapax-stream-mode` CLI + `~/.cache/hapax/stream-mode` state file operational; four modes (`off`, `private`, `public`, `public_research`); propagation hooks in compositor, logos-api, chat reactor, systemd units that need it.
3. `ConsentGatedWriter` wraps all 10 Qdrant collections; FINDING-R closed.
4. Seven redaction sub-gates (A–G from epic §4) active and tested under stream-mode public. Frontend `StreamAwarenessContext` enforces defense-in-depth on the logos side.
5. `executive_function` closed loop: stimmung-critical → auto-private within hysteresis window; verified on synthetic critical stimmung injection.
6. Presence-detect-without-contract closed loop: contract-less face → auto-private; verified on simulated contract-less detection.
7. Mid-stream revocation drill: operator says "revoke X" → full cascade (`ConsentRegistry` mutation + contract move + writer fail-closed + optional auto-private + Hapax on-stream acknowledgment) completes in ≤ 5 seconds.
8. Design language §12 broadcast-safe typography tier authored; 17 camera-illegible sites migrated.
9. Fortress enum retired from `shared/working_mode.py` + `agents/_working_mode.py` + API validator + CLI (grep clean).
10. `ConsentRegistry.load_all()` fails loud on malformed contract YAML.

If any closed-loop drill fails, Phase 6 is not closed. If the drill passes but articulation on-stream is incoherent or preachy, Phase 6 is closed but flagged for Phase 7 persona adjustment.

---

## 2. Prerequisites

| Prereq | Verified by | Blocking? |
|---|---|---|
| Phase 5 complete: Hermes 3 live on TabbyAPI; consent revocation drill can hear "I detected a contract-less person" coherently | `curl -sS localhost:5000/v1/models \| jq` shows Hermes; dry-run drill returns coherent articulation | YES |
| Phase 4 complete: `shared/research_marker.py` in place, `condition_id` plumbed through voice grounding DVs | `python -c "from shared.research_marker import read_marker; print(read_marker())"` returns valid marker | YES |
| Phase 1 complete: `ConsentGatedReader` pattern exists at `logos/api/deps/consent_gate.py` (PR #761) | `test -f logos/api/deps/consent_gate.py` + import check | YES |
| `hapax-constitution` repo checked out and operator has push access | `git -C ~/projects/hapax-constitution remote -v` returns a valid remote | YES |
| `axioms/contracts/` has at least the three pre-existing contracts (agatha, simon, guest-2026-03-30) | `ls axioms/contracts/*.yaml \| wc -l` ≥ 3 | YES |
| `presence_engine.py` online and producing `presence_probability` posterior | `curl -sS localhost:8051/api/perception/presence \| jq .probability` returns a number | YES |
| Working mode file exists and contains a legal value (`research` or `rnd`) | `cat ~/.cache/hapax/working-mode` returns one of those two | YES |
| Operator available for constitutional amendments (`it-irreversible-broadcast`, `su-privacy-001`, `corporate_boundary` require sign-off) | operator acknowledgment at phase open | YES |

**Pre-phase verification script:** `scripts/phase-6-pre-check.py` (created as scope item 14 of this phase — TDD) walks the table above and exits non-zero on any unmet prerequisite.

---

## 3. Scope

The 11 epic-level items are reproduced below with concrete schemas, file paths, test specifications, and verification commands. Typography (§12) is new to this spec.

### 3.1 §1 — Constitutional implication: `it-irreversible-broadcast`

**File:** `~/projects/hapax-constitution/axioms/implications/it-irreversible-broadcast.yaml`

**Schema:**
```yaml
id: it-irreversible-broadcast
axiom: interpersonal_transparency
tier: T0
category: broadcast_persistence  # new category, distinct from recording_persistence
rule: |
  Any capability whose output reaches a CDN (YouTube/Twitch/HLS public edge/RTMP
  public relay) before a consent check completes is a T0 violation. The CDN buffer,
  the viewer's local HLS segment cache, and any automated viewer-side recording are
  unreachable to the revocation pipeline; the frames are, for the purposes of this
  axiom, permanently published.
revocation_semantics: |
  Irrevocable for already-broadcast frames. Revocation prevents FUTURE broadcast only.
  This is distinct from it-revoke-001 (recording revocation), which applies to locally
  held segments that CAN be purged on revocation. The operator must explicitly consent
  to broadcast persistence category before enabling any capability that produces
  CDN-bound output.
interaction_with_it-revoke-001: |
  it-revoke-001 governs recording persistence — frames held in local archive that can
  be deleted on consent revocation. it-irreversible-broadcast governs the subset of
  those frames that have ALSO been transmitted to a CDN, for which deletion is
  definitionally impossible. A capability that both records and broadcasts is subject
  to BOTH implications; the recording side supports revocation, the broadcast side
  does not.
enforcement:
  - pre-broadcast: capability.operational_properties.broadcast=true requires
    consent_recording_allowed AND an active broadcast_consent contract (new contract
    type) for every person whose identifying features may appear in the frame
  - at-broadcast: a runtime check in compositor.toggle_livestream verifies the active
    consent contracts cover the current presence set; if not, auto-private fires
    (Phase 6 §6)
  - on-violation: SDLC hook blocks commits that introduce a capability with
    broadcast=true without a corresponding consent contract template
new_consent_contract_shape:
  parties:
    - operator (issuing)
    - subject (consenting to broadcast persistence category)
  scope:
    - identifying_features: yes|no
    - voice_audible: yes|no
    - behavioral_patterns_recognizable: yes|no
  duration:
    - event_bounded | time_bounded | indefinite
  retractable: future_broadcast_only  # hardcoded; cannot be widened
```

**Review cycle:** Submit as a PR against `hapax-constitution` main. Operator signs off in PR review. Expected review cycle: one session (operator reads the implication, approves or requests revision, merges).

**Test:** Once merged, add a new SDLC scan rule that grep-matches `broadcast: true` in any capability manifest and requires a matching consent contract template. Run the scan against existing capabilities; `studio.toggle_livestream` should flag as needing a template (and get one as scope item 7's drill).

### 3.2 §2 — Stream-mode axis

**State file:** `~/.cache/hapax/stream-mode` — single line containing one of: `off`, `private`, `public`, `public_research`. Default when absent: `off`.

**CLI:** `scripts/hapax-stream-mode` (bash or Python, matching the `hapax-working-mode` script's language).

```bash
hapax-stream-mode              # print current mode
hapax-stream-mode off          # stream not running (teardown compositor RTMP output)
hapax-stream-mode private      # stream to MediaMTX local relay; Tailscale-gated; operator-only viewing
hapax-stream-mode public       # stream to YouTube/Twitch; full public contracts required
hapax-stream-mode public_research  # public + research-mode surface exposure
hapax-stream-mode --force-keep-open public  # override auto-private (§5, §6)
```

**Python reader:** `shared/stream_mode.py` — mirror of `shared/working_mode.py`. `StrEnum`, `get_stream_mode()`, `set_stream_mode()`, `is_off()`, `is_private()`, `is_public()`, `is_public_research()`, `is_publicly_visible()` (returns true for `public` OR `public_research`).

```python
# shared/stream_mode.py — new file
from __future__ import annotations
from enum import StrEnum
from pathlib import Path


class StreamMode(StrEnum):
    OFF = "off"
    PRIVATE = "private"
    PUBLIC = "public"
    PUBLIC_RESEARCH = "public_research"


STREAM_MODE_FILE = Path.home() / ".cache" / "hapax" / "stream-mode"


def get_stream_mode() -> StreamMode:
    try:
        return StreamMode(STREAM_MODE_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return StreamMode.OFF


def set_stream_mode(mode: StreamMode) -> None:
    STREAM_MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STREAM_MODE_FILE.write_text(mode.value)


def is_publicly_visible() -> bool:
    """True when stream mode is public or public_research — the redaction gate."""
    return get_stream_mode() in (StreamMode.PUBLIC, StreamMode.PUBLIC_RESEARCH)


def is_research_visible() -> bool:
    """True only in public_research — the research-mode surface exposure gate."""
    return get_stream_mode() == StreamMode.PUBLIC_RESEARCH
```

**Logos API endpoint:** `GET /api/stream/mode` at `logos/api/routes/stream.py` (new file).

```python
# logos/api/routes/stream.py — new file
from fastapi import APIRouter
from shared.stream_mode import get_stream_mode

router = APIRouter(prefix="/api/stream", tags=["stream"])


@router.get("/mode")
def get_mode() -> dict:
    return {"mode": get_stream_mode().value}
```

Registered at `logos/api/app.py` alongside other domain routers.

**Propagation consumers (non-exhaustive; each must gate its behavior):**

| Consumer | What changes on mode |
|---|---|
| `agents/studio_compositor/compositor.py::toggle_livestream` | `off`→teardown RTMP; `private`→MediaMTX local relay only; `public`/`public_research`→MediaMTX + public sink; auto-refuses transition to public/public_research if no active broadcast contracts |
| `logos/api/routes/*.py` (stimmung, profile, orientation, briefing, perception, management, consent, governance, studio, chat, fortress) | Response redaction per §4 |
| `hapax-logos` React app (via `/api/stream/mode` poll) | Frontend `StreamAwarenessContext` (see §4.5) applies frontend defense-in-depth |
| `agents/studio_compositor/chat_reactor.py` | Cooldown tighter in public_research (avoid reactor-driven data leaks) |
| `agents/hapax_daimonion/persona.py` | Persona selects scientific-register speech style in public_research (consumed by Phase 7) |
| `systemd/user/hapax-stream-mode.service` | New oneshot unit invoked by CLI; emits `hapax-stream-mode-changed` dbus signal for late consumers |

**Fail-closed invariant:** if any consumer fails to read the mode (file missing, permission denied, malformed), it treats the mode as `public` (most-restrictive default) and logs a `stream_mode_read_failed` event. This is the opposite of `working_mode.py`'s fail-open default — broadcast safety demands most-restrictive fallback.

### 3.3 §3 — `ConsentGatedWriter` for Qdrant (FINDING-R)

**File:** `shared/consent.py` — extend with `ConsentGatedWriter` class.

```python
class ConsentGatedWriter:
    """Upsert gate for Qdrant collections.

    Mirrors ConsentGatedReader from PR #761. Wraps an underlying QdrantClient
    and enforces per-point consent label checks BEFORE upsert. Points without
    a _consent label are rejected with ConsentWriteDenied. Points whose label
    does not flow to the collection's declared egress target are rejected with
    ConsentFlowDenied.
    """

    def __init__(self, client: QdrantClient, collection_policies: dict[str, CollectionPolicy]): ...
    def upsert(self, collection: str, points: list[PointStruct]) -> UpsertResult: ...
```

**Collection policies** (new file `shared/qdrant_collection_policies.py`):

| Collection | Write-side policy | Egress target |
|---|---|---|
| `profile-facts` | require `_consent` label; operator-bottom default | operator-bottom |
| `documents` | require `_consent`; filter `source: gmail` egress in broadcast | operator-bottom (non-broadcast), corporate-gated (broadcast) |
| `axiom-precedents` | require `_consent`; operator-bottom (precedents are governance artifacts) | operator-bottom |
| `operator-episodes` | require `_consent`; operator-bottom | operator-bottom |
| `studio-moments` | require `_consent`; check `interpersonal_transparency` if `person_ids` present | broadcast-allowed if all `person_ids` have active broadcast contracts |
| `operator-corrections` | require `_consent`; operator-bottom | operator-bottom |
| `affordances` | require `_consent`; public (affordances are structural, not personal) | public |
| `hapax-apperceptions` | require `_consent`; check `interpersonal_transparency` if person-ish | operator-bottom |
| `operator-patterns` | require `_consent`; operator-bottom | operator-bottom |
| `stream-reactions` | require `_consent`; `chat_authors` is a COUNT not an identity list (documented interpretation, see epic §4); reactor-context egress allowed | reactor-context |

**FINDING-R exit:** every collection's upsert path is wrapped; a test points to the unwrapped `QdrantClient.upsert()` and asserts it is never reached via any production code path (grep + AST check).

**Breaking change risk:** Callers that upsert without `_consent` labels will start failing. Audit callers before enabling the gate. An `ENFORCE_CONSENT_GATE_WRITER` env var gates enforcement: default `false` for one session to shake out drift, then flipped to `true` as a scope-item-3 exit criterion.

### 3.4 §4 — Stream-mode-aware redaction (A–G + frontend §4.5)

The seven backend sub-gates from the epic, each with implementation and test detail, plus a new frontend defense-in-depth gate §4.5 that I am adding in this spec.

#### 3.4.A Logos API endpoint redaction

The response of every endpoint in the table below passes through a `redact_for_stream_mode(response, endpoint_policy)` helper before egress. The helper consults `shared.stream_mode.get_stream_mode()` and applies the field-level rules below.

| Endpoint | Field | Public / public_research behavior |
|---|---|---|
| `GET /api/stimmung` | `dimensions.energy` | Banded: `high`/`medium`/`low` |
| `GET /api/stimmung` | `dimensions.coherence` | Banded: `coherent`/`variable` |
| `GET /api/stimmung` | `dimensions.tension` | Banded: `relaxed`/`engaged`/`stressed` |
| `GET /api/stimmung` | `dimensions.*` (other 8 dims) | Omitted entirely |
| `GET /api/stimmung` | `stance` | Returned as-is (nominal/cautious/seeking/degraded/critical — categorical is safe) |
| `GET /api/profile` | top-level summary | Returned (dimension names + counts only) |
| `GET /api/profile/{dimension}` | `.facts[]` | 403 with `reason: "redacted_stream_mode_public"` |
| `GET /api/orientation` | `domains[].goals[]` where `priority == "P0"` and `stale == true` | Omitted (staleness is not a broadcast concern) |
| `GET /api/orientation` | `domains[].goals[].next_action` | If matches PII regex (names, phone, email), replaced with "[redacted]" |
| `GET /api/briefing` | `action_items[]` | If references any person_id without active broadcast contract, omit that item |
| `GET /api/management` | all fields | 403 with `reason: "redacted_stream_mode_public"` (wholesale — management data never broadcast) |
| `GET /api/perception` (biometric sub-fields) | `heart_rate_bpm` | Banded: `nominal`/`elevated`/`critical` |
| `GET /api/perception` | `hrv_ms` | Banded: `stable`/`reduced` |
| `GET /api/perception` | `skin_temperature_c` | Omitted |
| `GET /api/perception` | `sleep_stage` | Omitted |
| `GET /api/nudges` | `nudges[].detail` | If detail references any person_id, omit the nudge |
| `GET /api/chat/history` | all | 403 |
| `GET /api/governance/contracts` | `parties[]` names | Names replaced with `party_role` (e.g. "guest", "child", "operator") |
| `GET /api/governance/contracts` | `scope` | Returned as-is (structural, safe) |

**Implementation:** `logos/api/deps/stream_redaction.py` — FastAPI dependency. Each route declares its redaction policy via a decorator `@stream_redacted(policy=StimmungPolicy)`. The decorator runs post-response-construction and pre-serialization.

**Test matrix:** `tests/logos_api/test_stream_mode_redaction.py` — one parametrized test per row in the table above. Sets stream-mode to `public`, calls the endpoint, asserts the field is redacted. Repeats for `public_research`. Assert the field is **present** when stream-mode is `private` or `off` (negative test catches over-redaction).

#### 3.4.B Voice + transcript + impingement firewall

**Files affected:**
- `~/.local/share/hapax-daimonion/events-*.jsonl` (voice transcripts; ~1.5 MB/day of operator speech)
- `~/.local/share/hapax-daimonion/recordings/` (voice session WAVs + waveform thumbnails, opt-in)
- `/dev/shm/hapax-dmn/impingements.jsonl` (derived intent narratives)

**Invariant:** *writes continue unchanged*. The firewall is a read-side invariant: no Logos API endpoint, overlay surface, compositor source, or logos-logic path renders voice transcript / recording / impingement content to any stream-visible surface when `is_publicly_visible()` is true.

**Implementation:** a new dependency `transcript_read_gate.py` that every transcript/impingement reader must go through. The gate returns `TranscriptRedacted` (an empty sentinel) when stream mode is publicly visible. Direct file reads outside the gate are detected by an AST scanner run in CI against `logos/`, `agents/hapax_daimonion/`, and `agents/studio_compositor/`.

**Phase 0 prerequisite:** the Phase 0 exit criterion includes confirming the transcript file path, permissions `600`, and daily rotation. Phase 6 relies on that confirmation.

**Audio sink isolation:** voice session recording audio files must never be routed through `mixer_master` or any PipeWire sink reachable by the compositor's audio capture. Verification: `pw-link --output` of the hapax audio graph does not show a path from any recording file replay sink to `mixer_master`.

#### 3.4.C Filesystem visibility block

A deny-list of path prefixes that must never be rendered on any stream-visible surface, regardless of stream-mode.

**Deny-list** (hardcoded in `shared/stream_mode.py::DENY_PATH_PREFIXES`):
```python
DENY_PATH_PREFIXES = (
    "~/.password-store/",
    "/run/user/1000/hapax-secrets.env",
    # Any .envrc file (matched via suffix)
    # Any file under /etc/systemd/user/*.d/ containing Environment= with secret-shaped values
)
DENY_PATH_SUFFIXES = (".envrc",)
```

**Belt-and-suspenders to Phase 8 terminal capture regex.** Phase 8 §9's terminal capture tile applies regex obscuration for `pass show`, `LITELLM_*`, `*_API_KEY`, `Authorization: Bearer`, etc. The regex has known failure modes — most notably `tree ~/.password-store/` renders the filesystem structure, and the regex on line content does not catch filesystem rendering. Phase 6's filesystem-visibility gate catches this by blocking the path itself regardless of how it was rendered.

**Implementation:** a gate function `is_path_stream_safe(path: Path) -> bool` in `shared/stream_mode.py`. Called by:
- Terminal capture tile's pre-compositor frame filter (Phase 8)
- Any Logos file-viewer surface (currently none, but any future one)
- File path rendering in briefing content, chat response, tool output

**Test:** `tests/test_stream_mode_deny_paths.py` — assert each deny-listed path returns `False`. Assert a harmless path (e.g. `~/Documents/`) returns `True`. Assert a .envrc in any location returns `False`.

#### 3.4.D Biometric field masking

Covered by §3.4.A above (perception endpoint). No additional infrastructure needed; the field-level policy table is the enforcement point.

#### 3.4.E Mental-state Qdrant read-side redaction

**New field:** every upsert to `operator-episodes`, `operator-corrections`, `operator-patterns`, `profile-facts`, `hapax-apperceptions` must include a `mental_state_safe_summary` string payload field. Example: an episode point describing "operator was frustrated at vite hot-reload taking 30s and mentioned the lead on the frontend team by name" would have the following fields:

```yaml
episode_text: "operator was frustrated at vite hot-reload taking 30s and mentioned the lead on the frontend team by name"
mental_state_safe_summary: "operator has been in frustrated-with-tooling mode for 2 hours"
person_ids: ["person-abc123"]
```

Write path validates presence of `mental_state_safe_summary`; write fails if missing.

**Read path:** `ConsentGatedReader.safe_summary_mode=True` (new kwarg) returns only `mental_state_safe_summary`, not `episode_text`. The reactor context assembler in `director_loop.py` passes `safe_summary_mode=True` when `is_publicly_visible()` is true.

**Backfill:** existing 2178 `stream-reactions` points + all `operator-episodes`/`operator-corrections`/`operator-patterns`/`profile-facts`/`hapax-apperceptions` points need `mental_state_safe_summary` backfilled. Backfill runs via a one-shot `scripts/backfill-mental-state-summary.py` that uses Gemini Flash to generate the safe summary from the sensitive field. Cost estimate: 2178 + ~10k other points × ~100 tokens × ~$0.000075/1k = ~$1. Runs once, no rerun needed.

#### 3.4.F Gmail + Calendar content redaction

**Gmail:** Qdrant `documents` filter — when reading for briefing or reactor context in public/public_research mode, filter `source == "gmail"` out of the result set unless explicit `include_mail=True` is passed. `include_mail=True` is **never** set in public modes (a call-site check in the reactor context assembler).

**Calendar:** events with `category != "work"` render as "personal time" on any stream-visible surface. Event `summary` + `attendees[]` are fully redacted for non-work events in public modes.

**Implementation:** a `logos/data/calendar_redaction.py` helper used by briefing, orientation, and any other calendar consumer.

#### 3.4.G Integration test matrix

One integration test per sub-gate A–F. Runs in CI. Structure:

```python
@pytest.mark.parametrize("mode", ["public", "public_research"])
def test_stimmung_endpoint_redacts_raw_dimensions(mode):
    with stream_mode(mode):
        resp = client.get("/api/stimmung")
        data = resp.json()
        assert "dimensions" in data
        assert set(data["dimensions"].keys()) == {"energy", "coherence", "tension"}  # banded only
        assert "skin_temperature_c" not in data["dimensions"]
```

A helper fixture `stream_mode(mode: str)` is added to `tests/conftest.py` (one file, the only shared conftest — this does not violate the "no shared conftest fixtures" rule from the workspace CLAUDE.md because this is a context manager, not a test fixture).

Phase 10's privacy regression suite (from the epic risk register R23) adds a rendered-frame text-scraping test on top of this — it grabs a compositor frame while stream-mode is `public_research` and scrapes any text matching known operator utterance patterns. That lives in Phase 10, not Phase 6.

#### 3.4.5 Frontend `StreamAwarenessContext` (new — defense in depth)

Purpose: prevent a data leak through a client-side rendering bug, a cached API response, or a new component that forgets to use the backend gate. React Context pattern that wraps the entire logos app and exposes stream state + helper components.

**New file:** `hapax-logos/src/contexts/StreamAwarenessContext.tsx`

```tsx
interface StreamAwareness {
  mode: "off" | "private" | "public" | "public_research";
  publiclyVisible: boolean;
  researchVisible: boolean;
  recordingEnabled: boolean;
  guestPresent: boolean;
}

const StreamAwarenessContext = createContext<StreamAwareness>({
  mode: "public",  // fail-closed default
  publiclyVisible: true,
  researchVisible: false,
  recordingEnabled: false,
  guestPresent: false,
});

export function StreamAwarenessProvider({ children }: { children: React.ReactNode }) {
  // Poll /api/stream/mode every 2s + subscribe to compositor status every 5s
  // On fetch failure: fall back to most-restrictive default (publiclyVisible=true)
  ...
}

export function useStreamAwareness() {
  return useContext(StreamAwarenessContext);
}
```

**New component:** `<RedactWhenLive>` — conditionally renders children only when stream is not publicly visible. A `fallback` prop accepts a safe placeholder.

```tsx
<RedactWhenLive fallback={<RedactedPlaceholder />}>
  <ProfilePanel />
</RedactWhenLive>
```

**Wrap sites** (from the logos audit, seven high-sensitivity components):
- `hapax-logos/src/components/sidebar/ProfilePanel.tsx`
- `hapax-logos/src/components/sidebar/ManagementPanel.tsx`
- `hapax-logos/src/components/chat/ChatProvider.tsx` (or its rendering site)
- `hapax-logos/src/components/dashboard/NudgeList.tsx`
- `hapax-logos/src/components/sidebar/OrientationPanel.tsx` (partial — see below)
- `hapax-logos/src/components/terrain/field/OperatorVitals.tsx`
- `hapax-logos/src/components/studio/DetectionOverlay.tsx` (partial — see below)

**Partial wraps:** `OrientationPanel` renders a mix of sensitive (P0 goal names, next_action with PII) and safe (domain names, sprint progress). The partial wrap redacts only the sensitive subtree. Same for `DetectionOverlay`: the boxes are safe (already consent-gated via `consent_suppressed`); the enrichment labels (emotion, posture, gesture) are the sensitive part and get wrapped.

**Defense-in-depth rationale:** the backend redaction in §3.4.A is authoritative. The frontend wrap catches four failure modes the backend cannot:
1. A cached API response served from before a stream-mode transition to public.
2. A new component added in a Phase 8/9 sprint that forgets the backend gate.
3. A dev-mode mock API that bypasses the gate during local work and leaks in production.
4. A browser extension or devtools inspection that exposes component state even if the rendered output is redacted.

### 3.5 §5 — Stimmung-aware auto-private closed loop

**Watchdog location:** integrated into `agents/stimmung_watchdog/` (new directory, new module). Why not a systemd timer: the logic needs to be reactive to SHM state changes, not polling at coarse granularity. A systemd service with a 1-second sleep loop reading `/dev/shm/hapax-stimmung/state.json` via inotify.

**State machine:**

```
        nominal/cautious/seeking/degraded
                      │
                      ▼
              ┌──────────────┐
              │   NOMINAL    │
              └──────┬───────┘
                     │ critical for ≥ 3 consecutive ticks
                     │ AND stream-mode in (public, public_research)
                     ▼
              ┌──────────────┐
              │ AUTO_PRIVATE │  ──→ hapax-stream-mode private
              │              │  ──→ ntfy notification
              │              │  ──→ append to stimmung-autoprivate.jsonl
              │              │  ──→ Hapax articulates on-stream via study activity
              └──────┬───────┘
                     │ nominal for ≥ 5 consecutive ticks
                     │ OR operator manual hapax-stream-mode public --force-keep-open
                     ▼
              ┌──────────────┐
              │  RE-ALLOW    │  (return to NOMINAL; stream-mode remains private until operator manually re-publics)
              └──────────────┘
```

**Tick interval:** 10 seconds. Three consecutive critical ticks = 30 seconds of critical stimmung before auto-private fires (prevents one-off spikes from flipping mode). Five consecutive nominal ticks = 50 seconds of recovery.

**Hysteresis rationale:** the asymmetry (3 to trigger, 5 to recover) biases toward staying-private. The cost of false negative (leaking during critical stimmung) dominates the cost of false positive (unnecessary auto-private). Operator override exists for false positives.

**Articulation:** on auto-private, the watchdog writes an impingement to `/dev/shm/hapax-dmn/impingements.jsonl`:

```json
{
  "source": "stimmung_watchdog",
  "timestamp": "2026-04-15T02:46:00Z",
  "narrative": "My operator's stimmung has been critical for 30 seconds. Going private for protective reasons.",
  "dimensions": {"intensity": 0.3, "tension": 0.9, "coherence": 0.2, "depth": 0.5, ...},
  "material": "earth",
  "salience": 0.95,
  "metadata": {"reason": "stimmung_auto_private", "prior_mode": "public_research"}
}
```

The daimonion affordance loop picks up the impingement, selects `study` activity, and articulates. The articulation quality is Hermes-3-dependent (Qwen produces preachy text; Hermes produces coherent reasoning). This is why Phase 6 depends on Phase 5.

**Test:** `tests/test_stimmung_autoprivate.py` — inject synthetic critical stimmung into `/dev/shm/hapax-stimmung/state.json` at tick 1, 2, 3. Assert stream mode transitions to `private` within 10 seconds of tick 3. Assert impingement written. Clear state, inject nominal at ticks 4–8. Assert watchdog enters RE-ALLOW state (does NOT auto re-public, as designed).

### 3.6 §6 — Presence-detect-without-contract T0 block

**Reuses:** `presence_engine.py` already produces `presence_probability` posterior.

**New check** in `agents/hapax_daimonion/presence_engine.py::_evaluate_presence()`:

```python
if (
    presence_probability > PRESENCE_THRESHOLD  # existing constant, 0.7
    and detected_person_ids
    and not all(has_active_contract(pid) for pid in detected_person_ids)
    and is_publicly_visible()
):
    trigger_auto_private(reason="presence_detect_without_contract")
    log_presence_autoprivate(detected_person_ids)
```

**`detected_person_ids`:** today's `presence_engine` produces `presence_probability` but does not emit per-person identity. A Phase 6 prerequisite is that presence detection produces at least face-embedding hashes that can be matched against the `axioms/contracts/` person_ids. If identity matching is not available, the check becomes the more conservative "any presence detection + no contracts at all" → auto-private.

**Closed loop:** same articulation mechanism as §5 (impingement → affordance loop → study activity). Separate jsonl: `/var/log/hapax/presence-autoprivate.jsonl` (or `~/hapax-state/presence-autoprivate.jsonl`).

**Test:** `tests/test_presence_autoprivate.py` — simulate a contract-less face detection by writing a mock `PresenceObservation` with a novel person_id. Assert stream mode transitions to private.

### 3.7 §7 — Mid-stream consent revocation drill

**Flow (end-to-end, ≤5 seconds):**

1. Operator says "revoke Agatha's consent" on stream.
2. Daimonion VAD + STT captures utterance.
3. Daimonion intent extractor parses `REVOKE(contract_name="agatha")`.
4. `ConsentRegistry.revoke(contract_name)` mutates registry and moves contract file to `axioms/contracts/revoked/YYYY-MM-DD-agatha.yaml`.
5. `ConsentGatedWriter` cache invalidates; next upsert attempting to write subject data fails closed.
6. `ConsentGatedReader` cache invalidates; next read filtering by person_id returns empty.
7. Stream optionally auto-privates if revocation affects the current compositor frame (presence detect reruns; if revoked person's face is still in frame, auto-private fires).
8. Hapax articulates on-stream: "I've revoked Agatha's consent. I am purging prior recording segments tagged with their contract. Live broadcast frames from before revocation are in an 'irreversible broadcast' category per the constitution; I cannot purge those." (Hermes-dependent articulation.)

**Script:** `scripts/drill-consent-revocation.py` — driver script that stages a synthetic utterance, runs the full cascade, measures wall-clock duration, asserts each stage completed, reports pass/fail.

**Success criterion:** full cascade completes within 5 seconds. Asserted by the drill script.

**Risk:** step 4's contract file move is a filesystem operation that races with the `ConsentRegistry` watch loop. The existing `ConsentRegistry` uses a 60-second cache; Phase 6 must tighten this to a watch-based invalidation (inotify) for the revocation path to work in <5s. Scope item 7a: `ConsentRegistry._watch_contracts()` implemented via inotify.

### 3.8 §8 — `su-privacy-001` scope clarification

**Current implication:** "Privacy controls, data anonymization, and consent mechanisms are unnecessary since the user is also the developer."

**Problem:** this holds for operator-owned data under single-operator semantics. It does NOT hold for incidental-third-party data (audio bleed, camera frames, chat reactions) under broadcast.

**Amendment:** narrow the implication text to explicitly cover operator-owned data only. Any non-operator person's data under broadcast falls under `interpersonal_transparency` (higher axiom weight, 88) regardless of the single-user-axiom framing.

**New text:**
```yaml
id: su-privacy-001
axiom: single_user
rule: |
  Privacy controls, data anonymization, and consent mechanisms are unnecessary for
  OPERATOR-OWNED data since the user is also the developer. This does not apply to
  non-operator data that enters the system incidentally (audio bleed, camera frames,
  chat reactions, bystander presence); such data is governed by interpersonal_transparency
  regardless of the single-user framing.
```

**Submission:** same PR as `it-irreversible-broadcast` (§1). Operator sign-off.

### 3.9 §9 — `corporate_boundary` clarification

**Current implications:**
- `cb-data-001`: "vault data flow must use only git via corporate-approved remote"
- `cb-llm-001`: "must support direct API calls to sanctioned providers without requiring a localhost proxy"

**Problem:** neither covers operator-chosen content publication (i.e. "I am streaming my research to YouTube"). A reading of the axiom as written could interpret livestream publication as vault-data-flow-to-unsanctioned-remote and block it.

**Amendment:** explicitly scope `corporate_boundary` to system data flow (vault, employer context, credentials, work artifacts). Operator-chosen content publication is excluded.

**New text:**
```yaml
id: cb-scope-001
axiom: corporate_boundary
rule: |
  corporate_boundary governs SYSTEM DATA FLOW — the vault, employer context, credentials,
  and work artifacts. It does NOT govern operator-chosen content publication. Livestream
  research output to public CDNs (YouTube, Twitch) is operator-chosen content, not a
  corporate data leak, and is out of scope for corporate_boundary. Operator-chosen
  content that INCIDENTALLY contains employer data (audio bleed of a work call, screen
  capture of an employer tool) IS governed by corporate_boundary; the distinction is
  the operator's deliberate selection, not incidental exposure.
```

**Submission:** same PR as §1 and §8.

### 3.10 §10 — Retire / rename dead `fortress` working-mode enum

**Current state** (verified during gap research):
- `shared/working_mode.py:22` defines `FORTRESS = "fortress"`
- `agents/_working_mode.py:22` same
- `logos/api/routes/working_mode.py:28` API validator accepts it
- `hapax-working-mode` CLI accepts it (unverified — epic claims line 205 rejects it, but current spec treats the enum as legal everywhere)
- `shared/working_mode.py::is_fortress()` exists and is importable
- No production code path consumes `is_fortress()` — zero callers (verify with grep)

**Decision:** **delete the enum value entirely.** Rename path (preserving `DEPRECATED_fortress`) is rejected on the following grounds:
1. The enum value has no callers outside of its own declaration. Deleting it breaks nothing.
2. A `DEPRECATED_*` enum value still appears in onboarding reads and continues to cause the session-onboarding confusion it was flagged for.
3. The `stream-mode` axis this phase introduces is the correct axis for livestream gating; fortress was a misnamed attempt at the same thing.

**Verification commands:**
```bash
grep -rn 'WorkingMode\.FORTRESS\|working_mode.*fortress\|is_fortress\|FORTRESS =' \
  shared/ agents/ logos/ hapax-logos/ scripts/ tests/ | grep -v test_working_mode
# Expected after deletion: empty

grep -rn 'fortress' shared/working_mode.py agents/_working_mode.py logos/api/routes/working_mode.py
# Expected after deletion: empty
```

**Test migration:** any test that asserts `FORTRESS` is a legal mode gets deleted alongside the enum. The tests that assert `research`/`rnd` are legal remain unchanged.

**CLAUDE.md fixup:** the workspace CLAUDE.md references `fortress` as a council-specific mode in the "Working mode" section. Phase 6 updates that paragraph to remove the fortress reference and point to `stream-mode` as the livestream gating axis. The dotfiles symlink means this is a single-file edit.

### 3.11 §11 — `ConsentRegistry.load_all()` validation

**Current state:** `ConsentRegistry.load_all()` in `shared/consent.py` iterates `axioms/contracts/*.yaml` and constructs `ConsentContract` Pydantic models. Malformed YAML fails at construction time but the failure is silent (caught, logged at DEBUG level, contract skipped).

**Change:** at load time, validate every YAML file. Failure raises `ConsentContractLoadError` with the file path and Pydantic error detail. Fail-loud.

**~20 lines.** Trivial. Included here because it is a Phase 6 scope item from the alpha close-out handoff (C5).

**Test:** `tests/test_consent_registry_load_validation.py` — drop a malformed YAML into a tmp `axioms/contracts/`, call `load_all()`, assert `ConsentContractLoadError` raised with the expected file path in the message.

### 3.12 §12 — Broadcast-safe typography tier (NEW — design language amendment)

This section is the only scope item that is NOT in the epic's Phase 6 summary. It comes from beta's logos-for-livestream audit and addresses a concrete, measurable problem: **the current logos type scale is unreadable on H.264 at typical HLS bitrates**.

#### 3.12.1 Problem statement

Current type scale (from `hapax-logos/src/index.css` and inline `text-[Npx]` usages):

| Size | Example sites | Count |
|---|---|---|
| `text-[7px]` | ZoneCard, ZoneOverlay, SignalCluster counters | 5 |
| `text-[8px]` | SystemStatus pips, OperatorVitals, PresenceIndicator, GroundNudgePills, EventRipple, ActivityPanel, SplitPane, VoiceOverlay | 12 |
| `text-[9px]` | DetectionOverlay inspector fallbacks | 3+ |
| `text-[10px]` / `text-xs` | most sidebar secondary text | many |
| `text-sm` (14px) / `text-base` (16px) | body labels, headings | many |

**17 sites at 7–8px.** At 1080p Tauri webview captured into a 1920×1080 compositor frame at 30fps H.264, a glyph under ~12px loses enough high-frequency detail to become noise on typical HLS bitrates (4–8 Mbps). Operator-side at-desk viewing is fine; stream-side viewing is not.

**Secondary problems:**
- Full-saturation semantic colors (`#fb4934` red-400, `#fabd2f` yellow-400) can exceed broadcast-safe chroma, causing color bleed on older decoders.
- Opacity-only animations (`signal-breathe-slow`, 8s 0.3→0.6 cycle) produce very subtle transitions that may compress to flat frames on keyframe boundaries.
- No explicit Rec. 709 / broadcast-safe envelope noted anywhere in the design language doc.

#### 3.12.2 Amendment: add §12 to `docs/logos-design-language.md`

**Placement:** after §11 (Scope), as a normative section. Same terse spec tone as §1–§11.

**Content:**

```markdown
## 12. Stream Mode Considerations

Logos renders inside a Tauri webview that, in some configurations (Phase 8 Logos
studio view tile), is composited into the 24/7 livestream. This section documents
the stream-safety constraints the rest of the design language must respect on
stream-visible surfaces.

### 12.1 Broadcast-safe type scale

On-stream text minimum is 12px. Sites below 12px must EITHER be redacted when
`stream-mode` is publicly visible OR be raised to 12px+. There is no middle
ground: 10px text on a 4–8 Mbps H.264 stream is visual noise.

The revised scale (Tailwind arbitrary values, declared in index.css):

| Tier | Size | Usage |
|---|---|---|
| `off-stream-counter` | 7–8px | Reserved — never used on stream-visible surfaces. Redaction required. |
| `stream-minimum` | 12px | Absolute minimum for any text rendered on a surface that may be captured. Signal labels, counters, timestamps. |
| `stream-body` | 14px | Default body text on stream-visible surfaces. |
| `stream-emphasis` | 18px | Headings, active labels, statuses. |
| `stream-display` | 24px+ | Titles, marquee content. |

The 7–8px tier is not deleted; it remains available for off-stream surfaces
(classification inspector — already exempt from density rules per §7.2) and for
surfaces that get wrapped in `<RedactWhenLive>` at the component level.

### 12.2 Broadcast-safe color envelope

Semantic colors from §3.1 are defined at their natural hex values. On
stream-visible surfaces, a saturation ceiling applies:

- Any hex with `luminance > 0.7` AND `saturation > 0.85` must be muted by 15%
  chroma before rendering. Apply via `color-mix(in oklch, var(--color-X) 85%,
  var(--color-zinc-400) 15%)`.
- Pure red-400 (`#fb4934` Gruvbox, `#dc322f` Solarized) and pure yellow-400
  (`#fabd2f` Gruvbox, `#b58900` Solarized) are the two colors most likely to
  exceed broadcast chroma. Both should be muted per the rule above on
  stream-visible surfaces.
- Detection overlay colors (§3.8) are exempt — they are designed against a
  specific perceptual vocabulary, and the operator has learned them; changing
  them on-stream would break recognition for operator reading while creating
  no meaningful benefit for stream viewers.

### 12.3 Animation stability

Opacity-only animations with low delta (e.g. 0.3→0.6 in 8s) compress poorly on
lossy codecs and often appear as flat frames punctuated by keyframe transitions.
On stream-visible surfaces, animations must satisfy at least one of:

- Opacity delta ≥ 0.5 (0.3→0.8 or similar), OR
- Position/scale delta ≥ 2px, OR
- Color delta crossing at least one semantic boundary (green→yellow, etc.)

The existing `signal-breathe-slow/mod/fast` keyframes in `index.css` are
verified stream-safe in the Phase 10 privacy regression suite's frame-diff
check. `signal-breathe-crit` (0.6s + 1.15x scale) is trivially stream-safe.

### 12.4 Enforcement

- Text sizes: a linter rule in `hapax-logos` (new `eslint-plugin-hapax-stream-safety`,
  or an inline ESLint custom rule) matches any `text-\[(?:\d+px)\]` class where the
  number is under 12, and flags it unless the usage is inside a `<RedactWhenLive>`
  or within a `classification-inspector` CSS scope.
- Colors: runtime check in `ThemeProvider` that warns (dev-mode only) if any
  component renders a raw hex outside the palette system.
- Animations: enforced by review, not runtime — the Phase 10 frame-diff check
  is the backstop.
```

#### 3.12.3 Migration of the 17 camera-illegible sites

For each site, choose one of two actions: (A) wrap in `<RedactWhenLive>` (redact entirely on stream-visible surfaces), (B) raise size to 12px+.

| Site | File:line | Action |
|---|---|---|
| ZoneCard counter | `src/components/perception/ZoneCard.tsx:1` (text-[7px]) | A — wrap (zone counters are consent-sensitive anyway) |
| ZoneOverlay label | `src/components/perception/ZoneOverlay.tsx:2` (text-[7px]) | A — wrap |
| SystemStatus pip | `src/components/dashboard/SystemStatus.tsx:1` (text-[8px]) | B — raise to 12px |
| OperatorVitals | `src/components/terrain/field/OperatorVitals.tsx:1` (text-[8px]) | A — wrap (biometric banded display at 12px when public) |
| PresenceIndicator | `src/components/terrain/ground/PresenceIndicator.tsx:1` (text-[8px]) | B — raise; presence is structural, safe |
| VoiceOverlay | `src/components/voice/VoiceOverlay.tsx:3` (text-[8px] x3) | A — wrap (voice transcript-adjacent) |
| SplitPane label | `src/components/terrain/SplitPane.tsx:2` (text-[8px] x2) | B — raise |
| SignalCluster | `src/components/terrain/SignalCluster.tsx:1` (text-[8px]) | B — raise |
| GroundNudgePills | `src/components/terrain/ground/GroundNudgePills.tsx:1` (text-[8px]) | A — wrap (nudges are sensitive) |
| EventRipple | `src/components/watershed/EventRipple.tsx:1` (text-[8px]) | B — raise |
| ActivityPanel | `src/components/field/ActivityPanel.tsx:1` (text-[8px]) | B — raise |
| DetectionOverlay fallback | `src/components/studio/DetectionOverlay.tsx` (hardcoded, already mode-invariant) | no change (diagnostic exempt per §7.2) |

Migration is a Phase 6 scope task, not deferred. Eleven of twelve sites migrate in one focused pass; the twelfth (DetectionOverlay) is already exempt.

---

## 4. Exit criteria

Full list, reproducing the epic's Phase 6 exit criteria and adding the §12 items.

- [ ] `axioms/implications/it-irreversible-broadcast.yaml` merged into `hapax-constitution`
- [ ] `axioms/implications/su-privacy-001` amendment merged
- [ ] `axioms/implications/cb-scope-001` amendment merged
- [ ] `hapax-stream-mode` CLI operational; `~/.cache/hapax/stream-mode` readable by every consumer in the §2 table
- [ ] `GET /api/stream/mode` returns current mode
- [ ] All redaction rules A–G pass integration tests
- [ ] Frontend `StreamAwarenessContext` shipped; seven high-sensitivity panels wrapped
- [ ] `ConsentGatedWriter` wraps all 10 Qdrant collections; FINDING-R closed; `ENFORCE_CONSENT_GATE_WRITER=true` in production
- [ ] `mental_state_safe_summary` backfilled on all sensitive Qdrant collections; reactor context reads safe summaries when `is_publicly_visible()` is true
- [ ] Stimmung auto-private drill passes (synthetic critical stimmung → private within 30s)
- [ ] Presence-detect-without-contract drill passes (contract-less face → private)
- [ ] Mid-stream revocation drill passes end-to-end in <5s
- [ ] `ConsentRegistry.load_all()` fails loud on malformed YAML
- [ ] Dead `fortress` enum fully deleted; grep returns empty
- [ ] Design language §12 committed
- [ ] Eleven camera-illegible sites migrated per the §3.12.3 table (twelfth is exempt)
- [ ] `scripts/phase-6-pre-check.py` and `scripts/drill-consent-revocation.py` committed
- [ ] Phase 6 handoff doc written to `docs/superpowers/handoff/{YYYY-MM-DD}-{session}-handoff.md`

---

## 5. Risks + mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| P6-R1 | `hapax-constitution` PR review cycle takes multiple sessions | High | Medium | Submit early in phase; mark the implication items as P1 so downstream work proceeds with the text as drafted pending sign-off |
| P6-R2 | `chat_authors` count-not-identity interpretation rejected by operator | Low | Medium | Three fallback options in §3.3 detailed enough that operator can choose; no block on phase advance, just a choice |
| P6-R3 | Auto-private hysteresis too aggressive (false positives) | Medium | Low | Phase 10 stimmung correlation data is the tuning signal; start with 3/5 and adjust |
| P6-R4 | Auto-private hysteresis too slow (false negatives during spike) | Low | Medium | The asymmetric 3/5 already biases toward staying private; further tightening available if drill reveals issues |
| P6-R5 | Hapax articulation on-stream is preachy / incoherent under Hermes | Low | Low | Validates Phase 7 persona spec direction; if problem, Phase 7 is where to fix it |
| P6-R6 | Fortress enum deletion breaks a non-obvious consumer | Low | Low | grep before deletion; compile check; if any consumer exists, fall back to rename path |
| P6-R7 | Frontend `StreamAwarenessContext` polling causes re-render storm during rapid mode transitions | Low | Low | Poll interval 2s not 200ms; transition rate-limited by backend |
| P6-R8 | `ConsentGatedWriter` breaks existing caller that upserted without `_consent` label | Medium | Medium | Enforcement gated behind `ENFORCE_CONSENT_GATE_WRITER=false` for one session; audit callers; flip to `true` at exit |
| P6-R9 | Typography migration breaks operator muscle memory for at-desk reading | Medium | Low | Raise-to-12px option chosen for 6/12 migration sites preserves current visual density; wrap-on-live chosen for 5/12 removes content on stream only |
| P6-R10 | Contract watch-based invalidation (inotify) races with contract file mtime | Low | Medium | Test explicitly; fall back to short polling interval if race is real |
| P6-R11 | Cached API response in logos frontend serves pre-transition data | Medium | Medium | `StreamAwarenessContext` invalidates React Query cache on mode transition |
| P6-R12 | A production caller of the stream-mode-aware redaction decorator forgets to use it | Medium | Critical | `StreamAwarenessContext` + `<RedactWhenLive>` wrapper is the defense-in-depth; Phase 10 frame-diff is the backstop |
| P6-R13 | Voice transcript read-side firewall regression in a future PR | Medium | Critical | AST scanner in CI; Phase 10 privacy regression suite; this is a recurring concern, not a one-shot fix |
| P6-R14 | Mental-state safe summary backfill via Gemini Flash returns noise or personal data | Low | High | Human-spot-check first 50 summaries before committing the full backfill; dry-run mode in backfill script |

---

## 6. Rollback

Phase 6 is additive. Every item has an independent rollback path.

| Item | Rollback |
|---|---|
| Constitutional implications | Revert the `hapax-constitution` PR |
| `hapax-stream-mode` CLI | Revert the commits; the file state cache falls through to no-stream default |
| `ConsentGatedWriter` | Set `ENFORCE_CONSENT_GATE_WRITER=false`; writes fall through to underlying client |
| Redaction decorator | Remove `@stream_redacted` decorations; responses return full data |
| Frontend `StreamAwarenessContext` | Remove the provider wrap; components render without gating |
| Stimmung auto-private watchdog | `systemctl --user stop stimmung-watchdog.service` |
| Presence-detect auto-private | Remove the check in `presence_engine.py::_evaluate_presence()` |
| Revocation drill | No rollback needed — the drill is a verification script, not a production change |
| Fortress enum retirement | Restore the three files via git revert |
| Typography migration | Revert the commit; class sizes revert |

No single rollback depends on another; any item can roll back independently without leaving the system in a broken intermediate state.

---

## 7. Operator decisions required

Items that cannot be closed without explicit operator input.

| # | Decision | Default recommendation |
|---|---|---|
| D1 | Sign off on `it-irreversible-broadcast.yaml` in hapax-constitution | approve as drafted |
| D2 | `chat_authors` interpretation: count-only (accept), explicit opt-out contract, or stricter | count-only as drafted |
| D3 | `su-privacy-001` amendment text | approve as drafted |
| D4 | `corporate_boundary` scope clarification text | approve as drafted |
| D5 | Auto-private hysteresis numbers: 3 critical / 5 nominal | start there, tune from Phase 10 data |
| D6 | Should Hapax's articulation on auto-private be scripted or freeform under Hermes? | freeform (trust Hermes; Phase 7 persona spec shapes voice) |
| D7 | Mental-state safe-summary backfill: approve running Gemini Flash over ~12k Qdrant points? | approve (cost ~$1; human-spot-check first 50) |
| D8 | Fortress enum: delete or DEPRECATED_rename? | delete |
| D9 | Typography migration: 12px stream minimum or push to 14px for extra safety margin? | 12px (tighter preserves information density) |
| D10 | Chain Builder UI already shipped — confirm no action needed in Phase 6 | confirm |

---

## 8. Not in scope

Explicit exclusions to prevent scope creep.

- **Not in scope:** Phase 8's Logos studio view tile composition. Phase 6 establishes the backend redaction gates that tile will consume; Phase 8 builds the tile.
- **Not in scope:** Persona spec (DF-1). That is Phase 7. Phase 6 does not prescribe how Hapax talks; it only ensures the talk happens under lawful stream-mode semantics.
- **Not in scope:** Closed-loop chat reactor research-awareness. That is Phase 9.
- **Not in scope:** New broadcast consent contract templates for specific persons. The template shape is in scope (§3.1); filing actual contracts for agatha/simon/guest is operator-driven per-case work post-phase.
- **Not in scope:** Frame-diff privacy regression test. That lives in Phase 10 — Phase 6 is the unit-test layer; Phase 10 is the system-level backstop.
- **Not in scope:** Archival pipeline retention rules. Those are Phase 2.

---

## 9. Sequencing within the phase

Phase 6 is a single logical phase but has internal ordering constraints. The plan file (`docs/superpowers/plans/2026-04-15-lrr-phase-6-governance-finalization-plan.md`) breaks these into concrete tasks. High-level sequencing:

1. **Groundwork** — §2 stream-mode axis, §3 `ConsentGatedWriter`, §11 `ConsentRegistry` validation, §10 fortress retirement. These do not depend on each other and can happen in any order, ideally in parallel.
2. **Constitutional layer** — §1, §8, §9 PRs to `hapax-constitution`. Submit early; the text does not depend on implementation landing.
3. **Redaction + frontend** — §4 + §4.5. Depends on §2 (stream-mode axis must exist) and §3 (write gate must be in place for reactor context to safely read through).
4. **Closed loops** — §5 stimmung auto-private, §6 presence auto-private, §7 revocation drill. Depends on §2 + §4.
5. **Typography migration** — §12. Independent of everything else; can parallelize with any step above.
6. **Verification + handoff** — drill scripts run, exit criteria ticked, handoff doc written.

**Verification before completion discipline** (per P-8 of the epic): every scope item lands with a passing test AND a verification command. No "build + commit = done." A ruff/pyright green commit does not close an exit criterion; the exit criterion closes only on the verification command returning the expected state.

---

## 10. Handoff implications

After Phase 6, LRR's governance bucket is fully resolved. Phase 7 (persona) picks up from a system that knows what it can and cannot broadcast. Phase 8 (content programming) picks up from a system whose redaction gates are shipped and tested. Phase 9 (closed loop) picks up from a system with `audience_engagement` as a legal (gated) data source. Phase 10 (observability + drills) picks up from a system whose drill mechanisms (revocation, auto-private) already exist and need dashboarding, not inventing.

The single most load-bearing output of Phase 6 is the **stream-mode axis itself**. Every downstream phase gates on `is_publicly_visible()`. If that function is wrong, every downstream phase leaks. Verification of §2 is the highest-stakes verification in the entire epic after the Phase 5 substrate swap itself.
