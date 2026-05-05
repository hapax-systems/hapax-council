# Adapter Tranche Selection Memo

Machine dispatch table: `config/adapter-tranche-selection-memo.json`

Schema: `schemas/adapter-tranche-selection-memo.schema.json`

## Decision

First-wave adapter implementation is capped at five tasks:

1. `caption-substrate-adapter`
2. `cuepoint-substrate-adapter`
3. `chat-ambient-keyword-substrate-adapter`
4. `overlay-research-marker-substrate-adapter`
5. `music-request-provenance-substrate-adapter`

This replaces the broad `substrate-adapter-buildout-tranche-1` implementation
umbrella with a dispatch table. Selection does not make any adapter public-live,
viewer-visible, monetizable, or safe to publish. Each selected adapter remains
private, dry-run, dormant, or blocked until its own producer freshness, render
target, rights/consent, public-claim, health, and evidence checks pass.

## Selection Rationale

The selected tranche maximizes substrate diversity without overloading one
surface family:

| Selected adapter | Why now |
| --- | --- |
| `caption-substrate-adapter` | Captions are a high-value linguistic carrier and consume the existing public-event caption shape. |
| `cuepoint-substrate-adapter` | Programme boundaries and chapters convert research state into replay/navigation evidence. |
| `chat-ambient-keyword-substrate-adapter` | Aggregate-only chat texture adds social substrate value without author persistence. |
| `overlay-research-marker-substrate-adapter` | Research markers make the stream visibly multi-spectacle while staying evidence-gated. |
| `music-request-provenance-substrate-adapter` | Music requests/provenance unlock listening, CBIP, and monetization-safety evidence before player smoke. |

`music-request-provenance-substrate-adapter` is chosen over
`youtube-player-substrate-smoke` for this tranche because the current audio and
Daimonion containment posture makes live/player smoke a higher-risk follow-on.
Music request/provenance can build the structured input and provenance contract
without mutating live audio routing.

## Candidate Matrix

| Candidate | Status | Gate |
| --- | --- | --- |
| Captions | select tranche 1 | Caption bridge freshness, redaction, public-event mapping, egress policy. |
| Cuepoints / chapters | select tranche 1 | Programme boundary event input, duplicate suppression, chapter fallback. |
| Chat ambient / keyword | select tranche 1 | Aggregate-only policy, no author persistence, health state. |
| Overlay / research marker | select tranche 1 | Overlay producer state, marker provenance, render target evidence. |
| Music request / provenance | select tranche 1 | Structured request input, provenance token, public/monetization risk policy. |
| Local visual pool | defer behind named gate | Asset rights/provenance rows and egress manifest consumption. |
| CBIP | defer behind named gate | Music provenance and signal-density metadata. |
| Re-Splay M8 | block | Operator hardware smoke and capture policy. |
| YouTube player smoke | defer behind named gate | Real-content ducker smoke, audio-safe proof, and no private leak evidence. |
| Refusal publication | defer behind named gate | Public-event publication artifact shape and refusal fanout/footer policy. |
| Mobile substream | defer behind named gate | 9:16 producer, smart crop, salience routing, legibility smoke. |
| Lore wards | block | Redaction and chat-authority gates. |
| Autonomous narrative | block | Audio, egress, public-claim, and quality feedback gates. |
| LRR archive | block | Operator consent, retention, redaction, and storage decision. |
| CDN assets | defer behind named gate | Asset publisher recovery plus rights/provenance-bearing dependency shape. |

## Selected Adapter Contracts

Every selected adapter must name:

- event input
- producer freshness
- render target
- rights and consent posture
- public-claim policy
- health signal
- dry-run explanation
- tests
- verification artifact

The dispatch table is the source of truth for those fields. The adapter notes
that follow this memo should copy the contract row rather than reinterpret the
umbrella.

## 2026-05-05 Buildout Handoff Status

`substrate-adapter-buildout-tranche-1` is closed by dispatching the first wave
into concrete child packets. The umbrella remains architecture only and must not
receive adapter implementation changes.

| Selected adapter | Packet state | Owner boundary |
| --- | --- | --- |
| `caption-substrate-adapter` | closed via PR #2288 | `shared/caption_substrate_adapter.py`, `tests/shared/test_caption_substrate_adapter.py` |
| `cuepoint-substrate-adapter` | closed via PR #2290 | `shared/cuepoint_substrate_adapter.py`, `tests/shared/test_cuepoint_substrate_adapter.py` |
| `chat-ambient-keyword-substrate-adapter` | offered child packet | `shared/chat_ambient_keyword_substrate_adapter.py`, `tests/shared/test_chat_ambient_keyword_substrate_adapter.py` |
| `overlay-research-marker-substrate-adapter` | offered child packet | `shared/overlay_research_marker_substrate_adapter.py`, `tests/shared/test_overlay_research_marker_substrate_adapter.py` |
| `music-request-provenance-substrate-adapter` | offered child packet | `shared/music_request_provenance_substrate_adapter.py`, `tests/shared/test_music_request_provenance_substrate_adapter.py` |

The three offered packets inherit the dispatch-table contract row verbatim:
event input, producer freshness, render target, rights/consent posture,
public-claim policy, health signal, dry-run explanation, tests, and verification
artifact. None grants public-live state, viewer visibility, publication, audio
routing, or monetization authority.

## Ownership Preservation

Existing anchors remain authoritative:

- YouTube production wiring owns captions.
- Programme boundary cuepoints own cuepoint/chapter event attempts.
- Overlay zones owns overlay producer state.
- Music request/provenance anchors own request and provenance truth.
- Local visual pool, CBIP, Re-Splay, YouTube player, refusal publication,
  mobile, lore, autonomous narrative, LRR archive, and CDN asset rows are kept
  as future work with named gates.

No selected adapter may duplicate Re-Splay hardware work, visual pool ingestion,
YouTube write ownership, provenance/egress gates, audio routing, mobile
substream ownership, or public fanout policy.

## Umbrella Supersession

`substrate-adapter-buildout-tranche-1` should not be dispatched as an
implementation task. Its role is superseded by this memo and dispatch table:
workers should receive only the selected child adapter packets, each with a
disjoint write scope and fail-closed public/live semantics.
