# Imagination Bus — Continuous DMN Content Production

## Summary

An independent imagination loop that runs alongside the DMN, producing structured `ImaginationFragment` objects on a variable cadence. Fragments carry content references (pointers to renderable things from any source) and dimensional coloring (the 9 expressive dimensions). Published to a shm bus for surface consumption. High-salience fragments escalate back to the cascade as impingements.

This is sub-project 1 of 3. It covers the imagination loop, fragment model, bus, and escalation path. It does NOT cover surface consumption (sub-projects 2 and 3).

## Motivation

The DMN runs continuously (sensory 5s, evaluative 30s, consolidation 180s), observing and assessing. But its output is purely evaluative — situation fragments and threshold-based impingements. It has no generative output channel.

Human imagination is a continuous byproduct of DMN activity. It produces internal imagery — memories, projections, associations, novel connections — as a natural consequence of ongoing observation. Most of this is ambient (background mind-wandering). Occasionally, imagination produces something salient enough to compel action ("oh wait, I should tell someone about this").

The imagination loop externalizes this process. It reads the DMN's observations and sensor state, produces structured content fragments via a higher-tier LLM, and publishes them for any output surface to render. The visual surface shows them as composited imagery. The vocal chain (future) could be influenced by them during conversation. The imagination loop is itself a source of impingements — when a fragment is sufficiently salient, it feeds back into the cascade, potentially triggering escalation.

## Architecture

### Process Identity

The imagination loop runs as an independent async task inside the voice daemon process. It shares memory access to the DMN's observation buffer (no IPC needed) but has its own tick cadence and its own LLM calls. It is not part of the DMN — it reads the DMN's output.

### Model

qwen3.5:27b via LiteLLM gateway at `:4000`. Higher tier than the DMN's qwen3:4b because imagination requires synthesis and novel connection, not just situation description.

### Cadence

Variable, driven by the imagination's own output:

- **Base cadence:** 12 seconds between ticks
- **Accelerated cadence:** 4 seconds, activated when the previous fragment had `continuation=true` AND `salience > 0.3`
- **Deceleration:** Returns to base cadence after 3 consecutive non-continuation fragments
- **TPN suppression:** When deliberative TPN is active (conversation in progress), cadence doubles (24s base, 8s accelerated) — same anti-correlation pattern as the DMN

This mirrors the phenomenology of mind-wandering: long stretches of idle drift punctuated by accelerating trains of thought that develop and then settle.

### Input Context

Each tick assembles a context window for the LLM:

- Last 5 DMN sensory observations (situation fragments from the observation buffer)
- Current stimmung state (stance + all dimension values)
- Last 3 imagination fragments (for continuity — what have I been thinking about?)
- Current sensor snapshot: perception state, biometrics (HR, HRV), weather, time of day, working mode
- Current working context: active goals, recent agent outputs, drift report summary

The context is assembled from shm files and in-memory state. No Qdrant queries at assembly time — the LLM itself can reference Qdrant collections in its output (as content references that surfaces resolve later).

### Output: ImaginationFragment

```python
class ContentReference(BaseModel, frozen=True):
    """Pointer to renderable content. Surfaces resolve these."""
    kind: str          # "qdrant_query", "camera_frame", "text", "url", "file", "audio_clip"
    source: str        # collection name, camera ID, URL, file path, or literal text
    query: str | None  # for qdrant_query: the search text
    salience: float    # how central this reference is to the fragment (0.0-1.0)

class ImaginationFragment(BaseModel, frozen=True):
    id: str                                      # UUID
    timestamp: float                             # epoch seconds
    content_references: list[ContentReference]   # what the imagination is "about"
    dimensions: dict[str, float]                 # 9 expressive dimensions (0.0-1.0)
    salience: float                              # self-assessed importance (0.0-1.0)
    continuation: bool                           # follows from previous fragment
    narrative: str                               # 1-2 sentence natural language (logging, not rendering)
    parent_id: str | None                        # if continuation, which fragment this follows
```

The `dimensions` dict uses medium-agnostic keys: `intensity`, `tension`, `diffusion`, `degradation`, `depth`, `pitch_displacement`, `temporal_distortion`, `spectral_color`, `coherence`. When a surface consumes the fragment, it maps these to its own chain's namespace (e.g., `visual_chain.intensity`).

`ContentReference.kind` is deliberately open-ended. Surfaces handle the kinds they understand and ignore the rest. Initial kinds:

| Kind | Source field contains | Resolved by |
|------|----------------------|-------------|
| `text` | Literal text to display | Visual: rasterize. Vocal: context injection. |
| `camera_frame` | Camera role name (e.g., "overhead", "hero") | Visual: fetch JPEG from `/dev/shm/hapax-compositor/{role}.jpg` |
| `qdrant_query` | Collection name. `query` field has search text. | Visual: resolve to text, rasterize. Vocal: context. |
| `url` | URL to fetch (image, page) | Visual: fetch + decode image bytes. |
| `file` | Filesystem path | Visual: read + decode. |
| `audio_clip` | Audio file path or identifier | Vocal: playback or prosody reference. |

### Bus: Filesystem-as-Bus

The imagination loop publishes via atomic shm writes. Surfaces subscribe by polling.

**Publisher writes:**
- `/dev/shm/hapax-imagination/current.json` — latest fragment (atomic tmp+rename)
- `/dev/shm/hapax-imagination/stream.jsonl` — rolling append, capped at 50 lines (for surfaces that want recent history)

**Subscriber reads:**
- Any surface polls `current.json` at its own cadence
- No registration, no coupling
- Surfaces that are down don't cause backpressure
- Surfaces that start up late see the current state immediately

### Escalation: Fragment → Impingement

When a fragment's `salience > 0.6`, the imagination loop creates an `Impingement` and writes it to `/dev/shm/hapax-dmn/impingements.jsonl`:

```python
Impingement(
    id=fragment.id,
    timestamp=fragment.timestamp,
    source="imagination",
    type=ImpingementType.SALIENCE_INTEGRATION,
    strength=fragment.salience,
    content={
        "narrative": fragment.narrative,
        "content_references": [ref.model_dump() for ref in fragment.content_references],
        "continuation": fragment.continuation,
    },
    context={"dimensions": fragment.dimensions},
    interrupt_token=None,
    embedding=None,  # generated by affordance pipeline on demand
)
```

The cascade consumer picks this up on its next drain. The affordance pipeline can recruit any capability — visual chain, vocal chain, or higher-level action. The DMN's evaluative tick also sees these impingements and can factor them into trajectory assessment.

## LLM Prompt Structure

The imagination tick sends a structured prompt to the LLM with `output_type=ImaginationFragment`:

```
You are the imagination process of a personal computing system. You observe
the system's current state and produce spontaneous associations, memories,
projections, and novel connections — the way a human mind wanders during
idle moments.

Your output is a structured fragment describing what you're currently
"imagining." This is not evaluation or analysis — it is free association
grounded in what you observe.

## Current Observations (from DMN)
{last_5_observations}

## System State
Stance: {stimmung_stance}
Stress: {operator_stress}, HR: {heart_rate} bpm
Weather: {weather_condition}, {temperature}
Time: {time_of_day}, Mode: {working_mode}
Activity: {perception_activity}, Flow: {flow_score}

## Recent Imagination (what you've been thinking about)
{last_3_fragments}

## Content Sources Available
You can reference these in content_references:
- camera_frame: overhead, hero, left, right (live camera feeds)
- qdrant_query: profile-facts, documents, operator-episodes, studio-moments
- text: any text you want to display
- url: any image URL
- file: any file path

## Instructions
Produce one ImaginationFragment. Be specific in content_references —
point to real things. Set dimensional coloring to match the emotional
tone of what you're imagining. Assess salience honestly — most fragments
are low salience (0.1-0.3). Only mark high salience (>0.6) for genuine
insights or concerns worth escalating.

If your previous fragment had continuation=true, you may continue that
train of thought or let it go. Don't force continuation.
```

## File Layout

| File | Responsibility |
|------|---------------|
| `agents/imagination.py` | `ImaginationFragment`, `ContentReference` models, `ImaginationLoop` class |
| `tests/test_imagination.py` | Unit tests for fragment model, cadence logic, escalation, shm output |

## Integration Points

- **Reads from:** DMN observation buffer (in-memory), `/dev/shm/hapax-stimmung/state.json`, `/dev/shm/hapax-voice/perception-state.json`, `/dev/shm/hapax-sensors/*.json`
- **Writes to:** `/dev/shm/hapax-imagination/current.json`, `/dev/shm/hapax-imagination/stream.jsonl`
- **Escalates to:** `/dev/shm/hapax-dmn/impingements.jsonl`
- **Launched by:** Voice daemon main loop (alongside DMN pulse)

## Testing

- Fragment model: construction, serialization, dimension key validation
- Cadence logic: base rate, acceleration on continuation+salience, deceleration after 3 non-continuations, TPN suppression
- Escalation threshold: fragments above 0.6 produce impingements, below do not
- Shm output: atomic write to current.json, rolling append to stream.jsonl with 50-line cap
- Context assembly: correct fields from shm sources, graceful handling of missing files
- LLM integration: mock LLM returns valid fragment, loop processes and publishes (marked `llm` for test exclusion)
