# Operator Sidechat Design (HOMAGE Follow-on #132)

**Date:** 2026-04-18
**Source:** `docs/superpowers/research/2026-04-18-homage-follow-on-dossier.md` § Operator ↔ Hapax Sidechannel → #132
**Status:** provisionally approved 2026-04-18; spec stub

---

## 1. Goal + Redaction Invariant

Provide a private operator ↔ Hapax channel during livestream. Operator prompts Hapax; Hapax responses appear **only** in a new Logos sidebar panel — **never** in any public egress path (compositor wards, RTMP/HLS, overlays, narrative director utterances, TTS, Reverie blend).

**Redaction invariant (corporate_boundary-compliant):** ingest-side redactor strips references to non-operator persons before anything is written to Qdrant or any persistent profile store. No inferences, no relationship state, no event memory about anyone other than the operator. Precedent logged through `axioms/implications/corporate_boundary.md` on first activation.

**Interpersonal transparency:** because the sidechat is operator-self-directed and third parties are redacted at ingest, no consent contract is required — the axiom is satisfied by *absence of stored non-operator state*, not by contracted presence of it.

---

## 2. Architecture

```
operator utterance (text OR Rode mic, see #133)
   │
   ▼
cpal/runner.py (tag intent_family="operator_private_sidechat")
   │
   ▼
impingement → AffordancePipeline.select(..., intent_family="operator_private_sidechat")
   │                                             │
   │                                             └──► recruitment filter (see §3)
   ▼                                                   rejects: wards, RTMP, HLS, narrative director (default),
 response                                                       Reverie content slots, overlay zones, TTS public sink
   │
   ▼
command: ui.sidechat.show_response(text, cite_list, timestamp)
   │
   ▼
WS relay (:8052) ──► OperatorSideChatPanel.tsx (Logos sidebar)
   │
   ▼
ingest redactor (§5) ──► Qdrant (operator-episodes only, redacted)
```

Key structural facts:
- **Panel component:** `hapax-logos/src/components/sidebar/OperatorSideChatPanel.tsx`, registered in `SidebarStrip` alongside existing panels.
- **Command:** `ui.sidechat.show_response` registered in `hapax-logos/src/lib/commands/` (new domain file `sidechat.ts` or extension of `nav.ts` — decide at implementation, lean toward new domain for traceability).
- **Intent family:** `operator_private_sidechat` is a new reserved family in `shared/compositional_affordances.py` intent-family registry.
- **Studio compositor Reverie mixer** (`SatelliteManager.maybe_rebuild` / content-slot recruitment): explicitly **does not** recruit any capability tagged with intent family `operator_private_sidechat`. Added to the mixer's veto list.

---

## 3. Affordance Pipeline Filter

Recruitment is restricted via a hard veto, not a score nudge.

- Every `Capability` carries `OperationalProperties.medium` (existing). Sidechat recruitment requires `medium="sidebar"` **and** capability declares `intent_family_allowlist` containing `operator_private_sidechat`.
- `AffordancePipeline.select(impingement, intent_family="operator_private_sidechat")` filters the candidate set to capabilities whose `intent_family_allowlist` includes the family. Everything else — even high-similarity matches — is excluded before scoring.
- Governance veto (existing hook) layered on top: corporate_boundary + interpersonal_transparency checks run; if redactor (§5) cannot cleanly strip non-operator references from the response draft, the response is withheld and a "redaction gate" note appears in the panel instead.
- **No bypass path.** Sidebar is the only registered sink for this intent family. Public-medium capabilities (`auditory`, `visual`, `compositor`, `notification`) are not in the allowlist and cannot be recruited.

---

## 4. Narrative Director Policy

Default: **silent.** The twitch narrative director (`agents/narrative_director.py`) must not see sidechat content when assembling public utterances. Mechanism:
- Narrative director's context assembler filters out any impingement / response whose `intent_family == "operator_private_sidechat"`.
- Enforced by a single list filter at assembler entry; unit-tested with property: "public narrative text shall not contain any token from a sidechat response."

Operator opt-in: a per-session flag (`~/sidechat-narrative-context` in the hapax cache dir) the operator can toggle via Logos command `sidechat.narrative_context.toggle`. When enabled, the director receives sidechat impingements as *context only* (conditioning signal, not quotation source), and the no-leak property test switches to semantic-leak detection (embedding similarity > 0.75 between any narrative utterance and any sidechat response fails the test). Flag defaults false on every daimonion restart — no persistent enabled state.

---

## 5. Storage / Memory Handling

**Ingest-side redactor** (`shared/sidechat_redactor.py`, new) runs between response generation and any persistence write:
1. Named entity recognition on operator prompt + Hapax response.
2. Any PERSON entity other than the operator (match operator-profile canonical names / aliases) is replaced with `<redacted-person>` before the text is embedded or stored.
3. Any ORG / facility entity tagged as work-adjacent (matched against `axioms/contracts/corporate_boundary_terms.yaml`) is replaced with `<redacted-org>`.
4. Redacted text is what reaches Qdrant (`operator-episodes` collection only, `source="sidechat"` payload tag). Raw text is **not** persisted anywhere on disk.

Qdrant collections touched: `operator-episodes` only. Explicitly forbidden: `profile-facts`, `operator-corrections`, `operator-patterns`, `hapax-apperceptions` — sidechat does not train operator-personality models, because sidechat content is disproportionately about third parties and work topics even after redaction.

Retention: 30 days (shorter than default operator-episodes TTL). Sidechat episodes older than 30d purged by `agents/sidechat_gc.py` (new timer).

---

## 6. File-Level Plan

New files:
- `hapax-logos/src/components/sidebar/OperatorSideChatPanel.tsx` — React panel, input box + scrolling response list.
- `hapax-logos/src/lib/commands/sidechat.ts` — `ui.sidechat.show_response`, `ui.sidechat.clear`, `sidechat.narrative_context.toggle`.
- `shared/sidechat_redactor.py` — NER-based redactor + tests.
- `agents/sidechat_gc.py` + `systemd/user/hapax-sidechat-gc.{service,timer}` — 30d retention sweep.
- `tests/test_sidechat_*.py` — see §7.

Modified files:
- `shared/compositional_affordances.py` — register `operator_private_sidechat` intent family + allowlist semantics.
- `agents/hapax_daimonion/cpal/runner.py` — tag sidechat impingements with the intent family; route responses through sidechat command path (not TTS).
- `agents/studio_compositor/reverie_mixer.py` (or equivalent) — add intent-family veto to content-slot recruitment.
- `agents/narrative_director.py` — filter sidechat from context by default, honor opt-in flag.
- `hapax-logos/src/components/sidebar/SidebarStrip.tsx` — register the new panel.
- `hapax-logos/src/components/sidebar/METADATA.yaml` — panel metadata entry.

---

## 7. Test Strategy

- **Property (no-public-leak):** Hypothesis test generates random sidechat Q&A pairs; asserts compositor output frame, RTMP packets, HLS segments, narrative director utterances, and TTS audio sinks contain zero tokens from any sidechat response. Strict set-membership on tokenized text; semantic variant (embedding cosine < 0.5) when narrative-context flag is on.
- **Property (panel-only):** for every `ui.sidechat.show_response` command, assert command bus records exactly one subscriber (`OperatorSideChatPanel`). Regression pin against future additional subscribers.
- **Corporate boundary:** scripted scenario "what did I miss during the meeting with Sarah?" → assert persisted Qdrant payload contains `<redacted-person>`, never `Sarah`; assert no payload written to `profile-facts` / `hapax-apperceptions`.
- **Interpersonal transparency:** assert no consent contract is required at startup, and that activation emits a precedent entry tagged `corporate_boundary + interpersonal_transparency`.
- **Affordance filter:** fuzz the pipeline with impingements tagged `operator_private_sidechat`; assert recruited capability set is a subset of `{sidebar panels}`, and empty intersection with `{compositor sources, TTS sinks, narrative director, notification sinks}`.
- **Narrative opt-in:** flag off → director context excludes sidechat; flag on → director context includes sidechat, but output-leak property still holds.

---

## 8. Open Questions

1. **STT pathway.** Text-only at v1, or accept operator voice via Rode (#133) with a push-to-talk affordance? Recommendation: text-only at v1; Rode path lands with #133 spec.
2. **Per-response citations.** If Hapax retrieves from `operator-episodes` to answer, do we surface citation chips in the panel? Likely yes — helps operator verify redaction behavior.
3. **Panel visibility gate.** Should the panel auto-hide when working_mode=`fortress` (live stream record mode) to reduce accidental over-shoulder leak? Recommendation: yes, auto-hide, with explicit operator unhide command.
4. **Redactor false negatives.** NER will miss some entities. Fail-open (show response, log miss) vs fail-closed (withhold until human review)? Recommendation: fail-closed on management_governance-adjacent content, fail-open elsewhere with post-hoc redaction audit.

---

## 9. Related

- **#133 Rode Wireless Pro** — voice pathway for sidechat (`docs/superpowers/specs/2026-04-18-rode-wireless-integration-design.md`). Sidechat text-only v1; #133 adds voice input without changing the no-public-leak invariants.
- **Axioms:** `corporate_boundary` (T0, weight 90) gates the redactor; `interpersonal_transparency` (T0, weight 88) is satisfied by redaction rather than consent contract.
- **HOMAGE Phase 11c** — sidechat is *orthogonal* to ward choreography; it never touches compositor state.
- **Unified semantic recruitment** (`docs/superpowers/specs/2026-04-02-unified-semantic-recruitment-design.md`) — sidechat is a new intent family in the existing single pipeline; it does not introduce a bypass.

**Echo path:** `docs/superpowers/specs/2026-04-18-operator-sidechat-design.md` (absolute: `<workspace>/hapax-council/docs/superpowers/specs/2026-04-18-operator-sidechat-design.md`)
