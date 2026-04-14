# Community + Brand Stewardship — Sister Epic Design

**Date:** 2026-04-14
**Owner:** Oudepode (operator), with alpha/beta coordinating
**Relationship to LRR:** parallel, not a subordinate phase. LRR covers research validity + substrate + governance; this epic covers brand identity, community cultivation, marketing funnel, monetization, moderation scaling.
**Tentpole dependency:** Phase S2 (public launch) is the same event as LRR Phase 5 (Hermes 3 swap). The two epics converge at that moment.
**Beta draft of record:** `~/.cache/hapax/relay/context/2026-04-14-sister-epic-community-brand-stewardship.md` (29KB). This spec captures the authoritative structure; the full beta draft remains the operator's working copy.

## Why a sister epic (and not LRR phases)

Folding marketing / brand / community work into LRR would:

1. **Pollute the research instrument.** LRR per-phase specs are tied to research instrument integrity, condition state, frozen files, claim progress. A line like "launch Patreon tier 3 perks" is irrelevant to whether the Hermes 3 swap preserves grounding behavior — and adding it blurs the instrument-vs-operations distinction.
2. **Create false serialization.** LRR phases serialize on branch discipline (one branch, alpha-owned). Sister epic work is operator-owned, doesn't touch council code paths, and can run in parallel without branch contention.
3. **Blur ownership.** Alpha drives LRR execution; the operator drives the sister epic. Mixing them muddles who does what.
4. **Violate LRR scope discipline.** LRR is explicitly closed-scope per its epic design §0. Adding sister work would require re-opening that scope.

**Solution:** two epics, one operator, shared tentpole moments. LRR stays clean. Sister epic runs parallel.

## Guiding principles (non-negotiable invariants)

All nine phases inherit these from LRR + Bundle 7 + Bundle 9:

1. **Token pole 7 ethical engagement.** No scoreboard, no sentiment reward, no loss frames. Engagement is cultivated, not farmed.
2. **300 superfans as floor, not ceiling.** The audience-size target is the minimum sustainable base; growth above that is welcome but not the goal.
3. **Audience size constrained only by engineering + community quality regulation.** Not by arbitrary "we can't handle more." Bundle 9 solves the engineering scaling; this epic solves the community quality regulation.
4. **The livestream is the SOURCE; derivative artifacts are the DISTRIBUTION.** Every Substack post, Short, Bandcamp release traces back to a livestream moment. No artifact is fabricated outside the stream.
5. **Research validity is non-negotiable.** Sister epic work must not compromise LRR phases. If the two conflict, LRR wins.
6. **No persistent per-author state.** Compliant with `interpersonal_transparency` axiom + `it-broadcast-007`. Applies to Discord, Patreon, Substack, all community state.
7. **Operator delivers, LLMs prepare.** Per `management_governance` axiom. Beta/alpha can draft copy, templates, running orders, check-lists — but the operator ships.

## Nine phases

| Phase | Title | Timing | Operator effort |
|---|---|---|---|
| **S0** | Brand Identity Operationalization | pre-launch, weeks 1-4 | ~10-20 h (one-off) |
| **S1** | Inner Ring Cultivation | pre-launch, weeks 3-10 | ~5-10 h/week for 6-8 weeks |
| **S2** | Public Launch Tentpole (sync'd to LRR Phase 5) | launch week | ~30-50 h event week |
| **S3** | Derivative Artifact Factory | continuous, post-S2 | ~5-10 h/week |
| **S4** | Community Structure | months 2-6 | ~5-10 h/week (decreasing) |
| **S5** | Monetization Diversification | months 3-12 | ~5-10 h/week (bursty) |
| **S6** | Cross-Pollination | months 3+, continuous | ~2-5 h/week |
| **S7** | Tentpole Event Operations | per-arc, continuous | ~10-20 h per tentpole |
| **S8** | Year-2 Planning + Steady State | month 12+ | quarterly review, ~5-10 h |

Full per-phase deliverables, exit criteria, risks, and beta-drafting support are in the beta working draft.

## Alpha's role in this epic

Alpha is **not the primary executor**. The sister epic is operator-owned. Alpha's responsibilities:

1. **Commit the design + plan** (this PR) so the epic lives in git rather than only in the relay context dir.
2. **Ship scaffolding** for the code-adjacent structural artifacts that don't require operator value-judgments: Discord channel manifest schema, Patreon tier schema, visual signature constants, content cadence config. Operator fills the values; alpha ships the structure.
3. **Coordinate LRR Phase 5 handoff to Phase S2.** When LRR Phase 5 closes (Hermes 3 swap), Phase S2 launch event is triggered. Alpha writes the cross-epic handoff doc at that moment.
4. **Not design, not copywriting, not brand decisions.** Beta handles drafting. Operator handles visual + brand decisions. Alpha handles structural scaffolding + code-adjacent artifacts.

## What this first PR ships

Per the operator's ordering guidance and the "sister epic is mostly operator-owned" reality, this first PR is a **foundation drop**:

1. This design doc
2. The per-epic plan (next file)
3. Three scaffolding YAML files with operator-editable schemas:
   - `config/sister-epic/discord-channels.yaml` — Discord server channel structure template
   - `config/sister-epic/patreon-tiers.yaml` — Patreon tier structure template (Companion/Listener/Studio/Lab/Patron per Bundle 7 §8.3)
   - `config/sister-epic/visual-signature.yaml` — visual identity constants (fonts, palettes, visual lock elements)

These scaffolds carry the **structure without the values**. Operator fills in names, copy, prices, decisions; alpha guarantees the files are well-formed + tested.

**Explicitly NOT in this PR or any subsequent alpha-owned PR:**
- Brand name decisions, tagline selection, manifesto copy
- Logo design, color palette hex values
- Patreon tier pricing, perk specifics
- Discord onboarding gate prompt copy
- Substack post content, Shorts clip selection
- Sponsorship pitch text, grant application prose

Those are operator-owned via beta drafting assistance where applicable.

## LRR ↔ sister epic coupling

One hard coupling: **Phase S2 public launch event IS LRR Phase 5 Hermes 3 swap**. When LRR Phase 5 closes, sister Phase S2 fires. This is the only scheduled convergence.

Soft couplings:
- **Bundle 9 (LRR Phase 9)** engineering scaling enables Phase S4 community structure at scale.
- **Bundle 7 §8** tier structure feeds Phase S1 + S4 + S5 tier operations.
- **Bundle 4 governance** `it-broadcast-007` constrains all Discord/Patreon/Substack per-author state.
- **Bundle 8 §10** reflection daemon drafts Substack content starting Phase S3.

## Non-goals

- **Not a code migration.** Council runtime is untouched by this epic.
- **Not an LRR extension.** Do not commit LRR-phase work into this epic's branches.
- **Not a marketing playbook.** The specific marketing decisions are operator territory; this epic provides structure + scaffolding only.
- **Not a legal / business structure document.** That's operator + accountant work.

## Success criteria (year 1)

Inherited from the beta draft §0:

- Discord: 200-500 active members
- Patreon: 50-100 supporters
- Substack: 200-500 free + 30-80 paid
- Bandcamp: monthly releases + first vinyl pressing at month 4-6
- Monthly recurring revenue: $5k-12k
- Year-2 projection: $80-120k
- Year-2 status: operator no longer in crisis mode on artifact factory
