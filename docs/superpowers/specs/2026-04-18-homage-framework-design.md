# HOMAGE Framework — Design Specification

**Status:** Draft, operator-directed 2026-04-18.
**Authors:** alpha (Claude Opus 4.7).
**Governing condition (target):** `cond-phase-a-homage-active-001` (to be declared before activation).
**Axiom anchors:** `single_user`, `executive_function`, `management_governance`, `interpersonal_transparency` (+ `it-irreversible-broadcast`), `corporate_boundary`.

## 1. Problem Statement

The compositor's current overlay aesthetic is a category error. Sans-serif on dark, grid-aligned rectangles, Grafana-era visual language reads as "someone is debugging a service" to every viewer. The content — hip-hop production, autonomous agent phenomenology, IR perception, Bayesian posteriors, Bachelardian materials — is in the wrong register. The surface miscasts the work.

The remediation is not a re-skin. It is a FRAMEWORK whose implementations (HOMAGE packages) transform the livestream surface's visual grammar as a whole, couple bidirectionally with the video composite pipeline, and enforce that nothing is ever "plopped or pasted" — every ward rotates, emerges, trades places, recedes, swaps, expands, cycles, disappears.

First member: BitchX. Future members anticipated (demoscene, ANSI BBS, VT100 glitch, Brutalist print, HyperCard, CGA/EGA splash). HOMAGE is the named slot; the package is the value.

## 2. Scope

### 2.1 In scope

- A `HomagePackage` abstraction with typography, palette, transition vocabulary, coupling rules, and signature conventions.
- A `BitchXHomage` package as the first concrete member, adhering to the authenticity grammar catalogued in §5.
- A transition FSM applied to every Cairo source — entry, hold, exit, swap — replacing paint-and-hold rendering.
- A choreographer layer preventing simultaneous-entry/exit cacophony.
- New `IntentFamily` members: `homage.rotation`, `homage.emergence`, `homage.swap`, `homage.cycle`, `homage.recede`, `homage.expand`.
- Bidirectional ward↔effect coupling: Cairo ward state exposed to WGSL shaders via `uniforms.custom[4]`; shader state influencing ward behaviour via existing stimmung + color-resonance path.
- A voice register enum (`announcing`, `conversing`, `textmode`) wired into CPAL as a first-class input, settable by HOMAGE package.
- `StructuralIntent.homage_rotation_mode` — the structural director gains an explicit job.
- `PerceptualField.homage: HomageField` so the narrative director can cite homage state in `grounding_provenance`.
- Research-condition declaration `cond-phase-a-homage-active-001` before activation.
- Rehearsal gate before live egress.

### 2.2 Out of scope

- Additional homage packages beyond BitchX (future work, same framework).
- Per-viewer customisation (single_user axiom).
- Chat message body / author rendering (interpersonal_transparency axiom — see §4.3).
- Retirement of pre-HOMAGE code paths prior to the full package being shipped and rehearsed.

## 3. Governance

### 3.1 Research condition

HOMAGE is a deliberate research parameter change, not a bug fix. Per `docs/superpowers/specs/2026-04-15-lrr-phase-1-research-registry-design.md:145-169`, this is a **new condition**, not a DEVIATION.

- **Condition ID:** `cond-phase-a-homage-active-001`.
- **Parent:** `cond-phase-a-volitional-director-001`.
- **Substrate unchanged:** Qwen3.5-9B-exl3-5.00bpw on TabbyAPI, LiteLLM routes `local-fast|coding|reasoning`.
- **Frozen files:** inherit from parent; additionally freeze `shared/homage_package.py`, `agents/studio_compositor/homage/*` once the framework lands.
- **Deliverable manifest:** every PR in the HOMAGE epic carries `condition_id: cond-phase-a-homage-active-001` in its directives_manifest entry.

### 3.2 Axiom compliance

| Axiom | Compliance approach |
|---|---|
| `single_user` | No per-spectator customisation. HOMAGE renders one surface. |
| `executive_function` | HOMAGE packages ship pre-configured; operator does not tune per-session. |
| `management_governance` | HOMAGE never generates feedback language about named persons. Signature artefacts (see §5.4) carry only agent-authored content. |
| `interpersonal_transparency` | Chat backscroll renders **tier counts + unique-author counts only** — never names, never message bodies. The BitchX grammar is simulated from `ChatField` aggregates, not from the real chat stream. `it-irreversible-broadcast` gate: HOMAGE is disabled in `consent-safe` layout. |
| `corporate_boundary` | HOMAGE does not surface work data. |

### 3.3 Six decision gates

The LRR audit surfaced six gates every downstream PR must honour. They are resolved here so implementation need not re-litigate:

1. **Recruited vs. always-on?** Package is always-on (substrate-like). Transitions within the package are recruited via `homage.*` IntentFamily entries.
2. **New condition vs. DEVIATION?** New condition. See §3.1.
3. **Chat data surface?** Aggregates only. No names, no bodies. BitchX grammar is simulated from counts.
4. **Consent-safe persistence?** HOMAGE **off** when consent-safe layout active. The consent gate wins.
5. **`PerceptualField` inclusion?** Yes — `homage: HomageField` with `package_name`, `active_transitions`, `rotation_phase`, `signature_of_current_artefact`. The director cites these unambiguously in `grounding_provenance`.
6. **Voice register coupling?** Yes — a first-class `VoiceRegister` enum is introduced and CPAL reads it. This is a persona change tied to the new condition, not an ad-hoc hack.

### 3.4 Spec amendments

Eight existing specs are amended as part of this epic (referenced, not re-authored, by the HOMAGE spec):

- `docs/superpowers/specs/2026-04-02-unified-semantic-recruitment-design.md` — HOMAGE package is a substrate; homage.* families are recruited.
- `docs/superpowers/specs/2026-04-17-volitional-grounded-director-design.md` §3.2 — `PerceptualField.homage` added.
- `docs/superpowers/specs/2026-04-15-lrr-phase-1-research-registry-design.md` §6 — new condition on the risk table.
- `axioms/persona/hapax-description-of-being.prompt.md` — register-is-register-selection already stated; HOMAGE's register enum formalises the mechanism.
- `shared/perceptual_field.py::ChatField` docstring — reaffirm no names, no bodies; BitchX format applies to aggregates only.
- `config/compositor-layouts/consent-safe.json` — HOMAGE explicitly disabled.
- `docs/logos-design-language.md` §11 — HOMAGE is a governed surface, distinct from Logos desktop UI.
- `shared/director_observability.py` — `hapax_homage_transition_total{package,transition}`, `hapax_homage_package_active{package}` counters added.

## 4. Architecture

### 4.1 HomagePackage abstraction

File: `shared/homage_package.py`.

```python
class HomagePackage(BaseModel):
    """A named aesthetic framework bundle.

    A package is a DATA description of the grammar, typography, palette,
    transitions, coupling rules, and signature artefacts that collectively
    render as an authentic homage to some aesthetic lineage.

    Packages are immutable at runtime. One package is active at a time.
    Package swap (which IS allowed) is a structural-director move.
    """

    name: str                           # "bitchx"
    version: str                        # "1.0.0"
    grammar: GrammarRules               # §4.2
    typography: TypographyStack         # §4.3
    palette: HomagePalette              # §4.4
    transition_vocabulary: TransitionVocab  # §4.5
    coupling_rules: CouplingRules       # §4.6
    signature_conventions: SignatureRules  # §4.7
    voice_register_default: VoiceRegister   # §4.8
    signature_artefacts: list[SignatureArtefact]  # rotating authored content
```

Registry: `agents/studio_compositor/homage/__init__.py` registers available packages. `get_active_package()` resolves via `/dev/shm/hapax-compositor/homage-active.json` (written by structural director, falls back to `bitchx` default).

### 4.2 GrammarRules

Load-bearing visual rules enforced by every ward when the package is active:

- `punctuation_colour_role: str` — "muted" (grey in BitchX); all brackets, colons, pipes, parens rendered via this role.
- `identity_colour_role: str` — "bright" (accent hue); all nick-equivalent, channel-equivalent, stance-equivalent tokens rendered via this role.
- `content_colour_role: str` — "terminal-default"; the message body equivalent renders via this role.
- `line_start_marker: str` — `»»»` in BitchX; prepended to every ward update row.
- `container_shape: Literal["angle-bracket", "square-bracket", "curly", "bare"]` — BitchX uses angle-bracket.
- `raster_cell_required: bool` — True for BitchX (CP437 monospace); gates font stack selection.
- `transition_frame_count: int` — 0 for BitchX (zero-frame instant-cut). Other packages may specify soft fades.
- `event_rhythm_as_texture: bool` — True for BitchX; join/part-style churn is part of the aesthetic, not noise.
- `signed_artefacts_required: bool` — True for BitchX; every generated artefact carries authorship.

### 4.3 TypographyStack

BitchX-compliant stack:
- Primary: `Px437 IBM VGA 8x16` (CP437 raster) — shipped as a font file under `assets/fonts/homage/bitchx/`.
- Fallback: `Terminus`, `Unscii`, `DejaVu Sans Mono` (existing stack, last resort).
- Size classes: `compact` (10px), `normal` (14px), `large` (18px), `banner` (24px) — no intermediates; discrete steps maintain raster integrity.
- Weight: single weight only (BitchX is single-weight authentic — bold is a colour role in the palette, not a typographic weight).

The typography stack is loaded via `text_render.py` Pango font-description construction, package-aware.

### 4.4 HomagePalette

Semantic role → RGBA mapping. BitchX example:

```python
BITCHX_PALETTE = HomagePalette(
    muted         = (0.39, 0.39, 0.39, 1.00),   # grey punctuation skeleton
    bright        = (0.90, 0.90, 0.90, 1.00),   # bright identity (white)
    accent_cyan   = (0.00, 0.78, 0.78, 1.00),   # mIRC 11 (bright cyan)
    accent_magenta= (0.78, 0.00, 0.78, 1.00),   # mIRC 6 (magenta — own-message)
    accent_green  = (0.20, 0.78, 0.20, 1.00),   # mIRC 9 (bright green — op indicator)
    accent_yellow = (0.90, 0.90, 0.00, 1.00),   # mIRC 8 (highlight/warning)
    accent_red    = (0.78, 0.00, 0.00, 1.00),   # mIRC 4 (bright red — critical)
    accent_blue   = (0.20, 0.20, 0.78, 1.00),   # mIRC 2 (status bar ground)
    terminal_default = (0.80, 0.80, 0.80, 1.00),  # content body
    background    = (0.04, 0.04, 0.04, 0.90),   # near-black, alpha for composite
)
```

Mode-aware: `research` vs `rnd` working-mode remap the accent roles per the existing working-mode palette contract (`logos-design-language.md` §3).

### 4.5 TransitionVocab

An enumerated set of named transitions each ward uses for entry/hold/exit/swap. BitchX-authentic set:

- `zero-cut-in` — appear atomically at target alpha, no fade.
- `zero-cut-out` — disappear atomically, no fade.
- `join-message` — text scrolls upward with a `* <ward_id> has joined` prefix line, zero-frame cut at final position.
- `part-message` — text scrolls upward with a `* <ward_id> has left (<reason>)` prefix line, zero-frame cut to absent.
- `topic-change` — flash inverse-video for 200ms, then zero-cut to new content.
- `netsplit-burst` — simultaneous multi-ward part, later simultaneous re-join; choreographer-synchronised.
- `mode-change` — `* Mode <ward_id> [+H homage.rotation.<name>]` flash then cut.
- `ticker-scroll-in` — scroll in from right edge, zero-frame cut when settled.
- `ticker-scroll-out` — scroll out to left edge, zero-frame cut at boundary.

Future packages redefine these; the vocabulary name is stable, the realisation is package-specific.

### 4.6 CouplingRules

Bidirectional ward↔effect contract. BitchX instance:

- **Ward → shader:** Each active homage transition writes a 4-float summary into `uniforms.custom[4]`:
  - `.x = active_transition_energy` (0..1; ramp during scroll, 1.0 during flash, 0 otherwise)
  - `.y = homage_palette_accent_hue_deg` (0..360; drives shader warmth modulation)
  - `.z = signature_artefact_intensity` (0..1; pulses on signature-artefact emit)
  - `.w = rotation_phase` (0..1; where we are in the current homage cycle)
  - Written by the choreographer on every tick; read by WGSL shaders that opt in.

- **Shader → ward:** existing `signal.color_warmth` + `signal.stance` uniforms already flow Python → GPU. HOMAGE adds a *reverse* channel: the WGSL compiler emits a `uniforms.shader_energy: f32` derived from the current pipeline's dominant activity (noise amplitude, rd feed rate, feedback strength). Python reads this from `/dev/shm/hapax-imagination/shader-feedback.json` (new writer) and modulates ward cadence + accent selection.

### 4.7 SignatureRules

Every artefact the package emits carries authorship — the BitchX lineage demands signed work.

- **Quit/join message templates** carry `by Hapax` or `by Hapax × <package_name>`.
- **Rotating banner artefacts** (homage equivalent of BitchX `art.c` logos) include an inline attribution line (e.g., `..H a p a x..` lettering signed `by Hapax/<package>@<condition_id>`).
- **Signature artefact rotation:** `SignatureArtefact` records rotate through on structural-director cadence. Each has a `content: str`, `form: Literal["quit-quip", "join-banner", "motd-block", "kick-reason"]`, `author_tag: str`.
- **Constraint:** signature artefacts are **generated content**, not captured chat. No axiom surfaces touched.

### 4.8 VoiceRegister

New enum in `shared/voice_register.py`:

```python
class VoiceRegister(str, Enum):
    ANNOUNCING  = "announcing"   # broadcast, no turn closes
    CONVERSING  = "conversing"   # turn-taking, repair, grounding
    TEXTMODE    = "textmode"     # clipped, IRC-style, bridge-short
```

CPAL reads from `/dev/shm/hapax-daimonion/voice-register.json` (written by HOMAGE package on activation; falls back to `ANNOUNCING` under `stream_mode == public_research`, `CONVERSING` otherwise). The `TEXTMODE` register is set by the BitchX package default.

Register influences CPAL prompt construction (partner block + tonality directives) and TTS parameters (Kokoro phoneme pacing). It does NOT change the axiom layer. Register is register selection, not personality — existing persona doctrine.

### 4.9 Choreographer

New module: `agents/studio_compositor/homage/choreographer.py`.

Runs at the compositor tick rate. Responsibilities:

1. Read active package from registry.
2. Read pending transitions from `/dev/shm/hapax-compositor/homage-pending-transitions.json` (written by `dispatch_homage_*`).
3. Reconcile against concurrency rules:
   - **Max simultaneous entries per tick:** 2 (package-configurable).
   - **Max simultaneous exits per tick:** 2.
   - **Netsplit-burst** may override, but only every `N` seconds (package-configurable, default 120s).
4. Emit the ordered transition plan to `ward-animation-state.json` using the existing `animation_engine.append_transitions` API.
5. Publish the 4-float `uniforms.custom[4]` payload for shader coupling.
6. Emit observability: `hapax_homage_transition_total{package, transition_name}`, `hapax_homage_choreographer_rejection_total{reason}`.

The choreographer is the arbiter of "nothing plopped or pasted" — any ward draw call whose corresponding transition was not emitted by the choreographer logs a violation and the draw proceeds only if `HAPAX_HOMAGE_STRICT=0`.

### 4.10 Ward integration

Every `CairoSource` subclass gains, through a shared base-class mixin (`HomageTransitionalSource`):

- `transition_state: Literal["entering", "hold", "exiting", "absent"]`.
- `pending_transition: TransitionName | None`.
- `last_transition_applied_ts: float | None`.
- Hook points `on_entry_start()`, `on_entry_complete()`, `on_exit_start()`, `on_exit_complete()`.
- Rendering during `absent` is a no-op (transparent).
- Rendering during `entering`/`exiting` applies package-specific entry/exit pixel effects (e.g. scroll for BitchX `ticker-scroll-in`).
- Rendering during `hold` applies the package grammar rules (colour roles, line-start marker, container shape).

The 22 existing Cairo sources (`token_pole`, `album_overlay`, `sierpinski_renderer`, `activity_header`, `stance_indicator`, `chat_keyword_legend`, `grounding_provenance_ticker`, `captions_source`, `impingement_cascade`, `recruitment_candidate_panel`, `thinking_indicator`, `pressure_gauge`, `activity_variety_log`, `whos_here`, `research_marker_overlay`, `stream_overlay`) all migrate to `HomageTransitionalSource`. Non-transitional draw calls are prohibited post-migration.

### 4.11 IntentFamily extensions

New `IntentFamily` members (backward-compatible additions to `shared/director_intent.py::IntentFamily`):

- `homage.rotation` — rotate to a new signature artefact.
- `homage.emergence` — bring a dormant ward out of `absent` (entry transition).
- `homage.swap` — two wards exchange positions (simultaneous exit+entry choreographed).
- `homage.cycle` — an ordered sweep through wards in a set.
- `homage.recede` — move a ward from `hold` to `absent` via exit transition.
- `homage.expand` — increase a ward's scale + alpha via the package's expansion transition.

Each maps to a dispatcher in `compositional_consumer.py` that writes the specific transition into `homage-pending-transitions.json`; the choreographer reconciles.

### 4.12 Director prompt

`director_loop.py` prompt gains a section:

```
## Homage Composition

The active homage package is <package_name>. Every tick, think about whether
a homage move fits what you are doing:

- homage.rotation: cycle to a new signature artefact (default cadence: every ~90s)
- homage.emergence: bring a dormant ward into view because the moment calls it
- homage.swap: trade a ward for another when context shifts
- homage.cycle: sweep through a family (legibility wards, hothouse wards, etc.)
- homage.recede: quiet a ward back to absent
- homage.expand: emphasise a ward that is about to carry a payload

NEVER paste. Every ward appearance is a transition. Signature artefacts are
authored (by you), not captured. Idle is the cardinal sin — compositional
pressure is compatible with calm pacing; it is incompatible with stasis.
```

### 4.13 StructuralIntent extension

`shared/structural_intent.py::StructuralIntent` gains:

```python
homage_rotation_mode: Literal["steady", "deliberate", "rapid", "burst"] | None = None
```

- `steady` — default; rotate signature artefacts at ~90s.
- `deliberate` — slow (~180s) with emphasis on each.
- `rapid` — fast (~30s) for high-energy passages.
- `burst` — netsplit-style mass exit + re-join cycle, rare (every 120s+), triggered structurally.

## 5. BitchX Package Authenticity

Per the authenticity research (sources catalogued in the same PR as this spec), the following elements are LOAD-BEARING for BitchX authenticity and carried into the package data:

### 5.1 Grammar
- Grey-punctuation skeleton.
- Bright-identity colouring at `[`, `]`, `<`, `>` and nick-equivalents.
- Angle-bracket message container `<id>content`.
- Monospaced CP437-capable raster.
- Bracketed-pipe status format `[field|field|field]`.
- Three-chevron line-start marker `»»»`.
- Zero-frame transitions (instant cut).
- Event-rhythm as texture (join/part-style churn tolerated and shaped, not suppressed).

### 5.2 Typography
- Px437 IBM VGA 8x16 or equivalent CP437 bitmap font.
- Half-block `▀▄` and shade `░▒▓` glyph vocabulary for logo art.
- Double-line `═║╔╗╚╝` and single-line `─│┌┐└┘` box-drawing for framed regions only.
- ASCII-7 `----` / `====` for inline dividers (NEVER box-draw inline).

### 5.3 Palette
- mIRC 16-colour reduction with BitchX role assignments (see §4.4).
- Bright-bookend spelling convention for package name display (e.g., `%WH%napa%WX%n` maps to bright-default-bright).

### 5.4 Signature artefacts (rotating corpus)

A seed set of ~40 signature artefacts ships with the package. Each is ONE of:

- **Quit-quip** — Hapax-authored analog to BitchX `BitchX.quit`. E.g. `Hapax: research instrument and the thing studying itself`, `Connection reset by Bachelard`, `Read error: 20Hz (Excessive cognitive tick rate)`. Rotation-driven emission as a status-bar or caption flash.
- **Join-banner** — CP437 block-art logo with `by Hapax/<package>` attribution.
- **MOTD block** — a longer framed banner, rotated by structural director at ~150s.
- **Kick-reason** — short `[TAG]` bracketed aphorism used as transition chrome (e.g., `[STANCE SHIFT]`, `[GROUNDING LOST]`, `[CONSENT GATE]`).

The corpus is **generated by Hapax under the operator's supervision** before activation. Governance: the corpus is human-reviewed and committed to `assets/homage/bitchx/artefacts.yaml` at condition-open time.

### 5.5 Anti-patterns (hard refusals)

The package MUST refuse:
- Emoji in any rendered content.
- Anti-aliased text.
- Proportional fonts.
- Modern flat-UI chrome.
- ISO-8601 timestamps.
- Rounded corners on framed regions.
- Right-aligned timestamps inside messages.
- Fade/dissolve transitions (zero-frame only).
- Swiss-grid MOTD or MOTD without signature.
- Box-drawing characters used for inline horizontal rules.

Violations log to `hapax_homage_violation_total{kind}` and draw proceeds only under `HAPAX_HOMAGE_STRICT=0`.

## 6. Observability

New Prometheus counters in `shared/director_observability.py`:

```python
_homage_package_active = Gauge(
    "hapax_homage_package_active",
    "1 if the named package is currently active.",
    ("package",),
)
_homage_transition_total = Counter(
    "hapax_homage_transition_total",
    "Homage transitions applied, labelled by package + transition kind.",
    ("package", "transition_name"),
)
_homage_choreographer_rejection_total = Counter(
    "hapax_homage_choreographer_rejection_total",
    "Pending transitions the choreographer rejected, by reason.",
    ("reason",),
)
_homage_violation_total = Counter(
    "hapax_homage_violation_total",
    "Paste / anti-pattern violations detected at render time.",
    ("package", "kind"),
)
_homage_signature_artefact_emitted_total = Counter(
    "hapax_homage_signature_artefact_emitted_total",
    "Signature artefacts emitted, labelled by package + form.",
    ("package", "form"),
)
```

Grafana dashboard addition: `Homage — Transitions & Violations` panel under the existing director dashboard. Per-condition slicing via the established `condition_id` label on director intent metrics.

## 7. Research-Condition Declaration

Before activation:

1. `scripts/research-registry.py open cond-phase-a-homage-active-001 --parent cond-phase-a-volitional-director-001`.
2. Commit the condition YAML declaring frozen-files extension + directives manifest referencing this spec.
3. Run the rehearsal (§8).
4. Inspect the audit-report template filled in.
5. Only after audit passes: wire the package as default, restart services, confirm deploy.

## 8. Rehearsal Requirements

Before live egress under the new condition:

- 30-minute private-mode rehearsal via `scripts/rehearsal-capture.sh`.
- `grounding_provenance` signal distribution compared to baseline — no new signals should appear that weren't in `PerceptualField.homage` schema.
- Director activity distribution within 2σ of baseline (same activities at same rates).
- Stimmung dimensions (especially `operator_stress`, `operator_energy`) unchanged beyond noise band.
- Prometheus cardinality bounded: label combinations finite and enumerated.
- No `hapax_homage_violation_total` increments during rehearsal.
- Visual-contrast audit: overlay text readable against all 9 shader dimensions × colour-warmth range.

## 9. Testing Strategy

- **Unit:** Every transition vocabulary entry pinned by a deterministic-frame-buffer test in `tests/studio_compositor/homage/`.
- **Property:** `tests/studio_compositor/homage/test_choreographer_invariants.py` — no more than `max_simultaneous_entries` per tick; no ward draw without a choreographer-emitted transition.
- **Integration:** `tests/studio_compositor/homage/test_bitchx_package_authenticity.py` — palette role assignments match mIRC contract; typography loads CP437 font; anti-pattern detector fires on a known-bad configuration.
- **Visual regression:** Golden-image comparison per ward in `entering`, `hold`, `exiting` states under the BitchX package. Images live in `tests/studio_compositor/homage/golden/`.
- **Axiom conformance:** `tests/studio_compositor/homage/test_homage_axiom_conformance.py` — chat rendering contains no author names or message bodies; consent-safe layout disables the package; research-condition declaration required for activation.

## 10. Migration

No code path is deleted until the HOMAGE equivalent is live and rehearsed. Order:

1. Framework + BitchX package data (PR-docs, PR-abstraction).
2. Transition FSM on Cairo base class + choreographer (PR-fsm-choreographer).
3. Migrate 4 legibility surfaces (PR-legibility-migration).
4. IntentFamily extensions + dispatchers + director prompt (PR-director-integration).
5. Ward↔shader coupling (PR-shader-coupling).
6. Voice register enum + CPAL wiring (PR-voice-register).
7. `StructuralIntent.homage_rotation_mode` (PR-structural-hint).
8. Research-condition declaration (PR-condition-open).
9. Rehearsal + audit (no PR — runbook execution).
10. Migrate remaining 18 wards (PR-ward-migration-batch-{1..3}).
11. Consent-safe variant (PR-consent-safe).
12. Retirement of pre-HOMAGE paint-and-hold paths (PR-retirement).

Each PR is independently reversible; the package is effectively off (falling back to existing behaviour) until PR-ward-migration-batch-1 lands.

## 11. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Statistical confound for Bayesian posterior mid-condition | New condition declared before activation; parent preserved for comparison. |
| Visual aesthetic confound on IR-based stress signals | Rehearsal measures operator stress drift; deviation > 1σ from baseline triggers rollback. |
| Chat author leak via BitchX backscroll aesthetic | Axiom conformance test; chat format is synthesized from `ChatField` aggregates only. |
| Consent violation on guest detection | `consent-safe` layout disables HOMAGE entirely; tested via `tests/studio_compositor/test_consent_live_egress.py` extension. |
| Legibility loss for operator during production | Visual-contrast audit in rehearsal; operator can force-off via `~/.cache/hapax/homage-enabled` file toggled by a CLI. |
| CP437 font missing on rebuild worktree | Font files committed to `assets/fonts/homage/bitchx/` (not external package); loader errors are fatal at package load time, not at render time. |
| Subsequent packages require framework rework | Framework is designed with named-slot values and abstract base classes; adding a package is adding files under `agents/studio_compositor/homage/<name>/`, never editing the framework. |
| Structural director cadence pollution if rotation too rapid | `homage_rotation_mode` gate; rehearsal measures director-intent rate variance. |

## 12. Open Questions

- **Multi-package layering?** Out of scope v1. Single active package. Future framework extension if warranted.
- **Per-stream-mode variants?** Out of scope v1. Package is either on or off (consent-safe off). Future if warranted.
- **Signature artefact authorship — direct generation vs curated corpus?** v1 ships a curated corpus; live generation during session considered for v2 once the grammar is proven stable.
- **BitchX palette mapping under `research` working-mode?** Solarized equivalent table in §4.4 to be specified before ship; blocked on a single operator review at open-condition time.

## 13. Glossary

- **Homage:** a named aesthetic framework bundle that transforms the compositor's visual grammar as a whole while coupling bidirectionally with the video composite pipeline.
- **Package:** a concrete homage (e.g. BitchX).
- **Transition vocabulary:** the named state-change operations each package defines (entry, exit, rotation, swap).
- **Signature artefact:** a rotating authored content piece (quit-quip, join-banner, MOTD block, kick-reason) that carries authorship inline.
- **Grammar rules:** the load-bearing structural rules every ward enforces when the package is active (colour roles, line-start marker, container shape).
- **Choreographer:** the module that reconciles pending transitions against concurrency rules and emits the ordered transition plan.
- **Coupling rules:** the bidirectional ward↔shader contract specific to the package.
- **Voice register:** the announcing/conversing/textmode tonality enum CPAL reads.

## 14. Changelog

- 2026-04-18 — v0.1 — initial draft, post-research synthesis. alpha.
