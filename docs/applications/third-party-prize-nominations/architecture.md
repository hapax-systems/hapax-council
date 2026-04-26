# Third-Party Prize Nominations — Architecture

**cc-task:** `leverage-vector-third-party-prize-nominations` (WSJF 4.0)
**Composed:** 2026-04-26

## Premise

Third-party prizes (VinFuture, PROSE, AAAS, Sloan, Mellon, Templeton, etc.) require nomination by an external party — not self-submission. The daemon-tractable surface for Hapax is therefore not "submit a nomination" but "make the citation graph dense enough that nominators have evidence to cite". The substrate for this is already in place via the publication-bus (Zenodo deposits + DataCite RelatedIdentifier graph + ORCID verifier); this architecture identifies the per-prize cite-able-evidence shape and the shipping order.

## Candidate prizes (substrate-fit ranking)

| Prize | Sponsor | Substrate fit | Nominator pool likely to cite |
|---|---|---|---|
| **VinFuture Prize** | VinFuture Foundation | Innovation-with-public-good; fits the "single-operator infrastructure for distributed cognition" framing | Anthropic, OpenAI, DeepMind public-policy researchers |
| **PROSE Awards** | Association of American Publishers | Best-of category for scholarly publications; fits if the constitution + research drops cluster gets formally published | Academic publishers in HCI / governance categories |
| **AAAS Newcomb Cleveland Prize** | AAAS | Best paper in Science | Conditional on a Science publication landing — unlikely without endorser path |
| **Sloan Research Fellowship** | Sloan Foundation | Early-career; nominator must be department chair | Not applicable — Hapax is independent |
| **Mellon Foundation grants** | Mellon | Humanities-and-emerging-tech intersection; refusal-as-data has direct fit | Humanities-research institutions |
| **Templeton Foundation prize cycles** | Templeton | Spiritual / philosophical computing; constitutional-LLM work + Oudepode framing fits the "big questions" rubric | Philosophy-of-mind / theology-of-tech researchers |

The substrate-fit-ranked candidates are **VinFuture, PROSE, Mellon, Templeton** — all four have nomination paths that could be triggered by citation-graph density in the relevant academic neighborhoods (HCI for VinFuture/PROSE, humanities-tech for Mellon, philosophy-of-mind for Templeton).

The Sloan Fellowship is structurally inapplicable (requires department-chair nomination). AAAS is conditional on a Science publication landing (out of scope for this lifetime).

## Daemon-tractable substrate

For each viable prize, the work splits into:

1. **Cite-able-evidence layer** — what artifact does a nominator point to?
   - For VinFuture: the Hapax velocity findings + refusal-as-data Zenodo deposits (PR #1677 + the architecture in PR #1663)
   - For PROSE: the formal hapax-constitution publication + accompanying research-drop corpus
   - For Mellon: the refusal-brief corpus + the operator-referent policy + the constitutional-axiom hierarchy
   - For Templeton: the Hapax-Oudepode constitutional substrate + the agency-disambiguation work

2. **Nominator-discovery layer** — who would plausibly nominate?
   - Endorser-discovery infra from the arxiv-velocity-preprint architecture (PR #1663) is the direct fit — same `agents/cold_contact/endorser_discovery.py` module identifies prize-relevant nominators by audience-vector
   - Per-prize nominator pool: enumerate via ORCID + DataCite Commons GraphQL queries scoped to the prize's relevant subject category

3. **Citation-graph touch layer** — how does Hapax-presence reach the nominator?
   - Same RelatedIdentifier-edge mechanism the arxiv path uses: Zenodo deposits with `References` edges to the nominator's prior work
   - Subject to the existing `graph_touch_policy` caps (≤5/deposit, ≤3/year/candidate)

4. **Refusal-on-rejection** — explicit refusal brief if the prize cycle closes without nomination, per `feedback_full_automation_or_no_engagement`. The refusal brief itself is an additional citation-graph node — non-engagement becomes data.

## What this PR ships

This architecture doc only. The components in §2 layers above already exist (endorser-discovery is in `cold-contact/`, RelatedIdentifier graph is shipped, refusal-brief publisher is shipped, ORCID verifier is shipped). No new code is needed for the cite-able-evidence + citation-graph paths — the existing infrastructure handles them once configured per-prize.

## Per-prize follow-up cc-tasks

| Prize | Follow-up cc-task | Effort |
|---|---|---|
| VinFuture | `leverage-prize-vinfuture-config` | 30 min config + 2-3h citation-graph density review |
| PROSE | `leverage-prize-prose-config` | 30 min config (depends on hapax-constitution formal-publication routing first) |
| Mellon | `leverage-prize-mellon-config` | 30 min config (depends on refusal-brief Zenodo deposit cadence stabilising) |
| Templeton | `leverage-prize-templeton-config` | 30 min config |

Each follow-up is YAML config + nominator-discovery query + per-prize attribution-edge composition. None require new daemon code.

## Constitutional posture

- `feedback_full_automation_or_no_engagement`: the cite-able-evidence + citation-graph layers are entirely daemon-tractable. The nomination itself is third-party action by definition; Hapax does not nominate itself.
- `interpersonal_transparency`: nominator candidates are public ORCID + DataCite records; no private-state about the nominator is persisted (only the touch log per `graph_touch_policy`).
- Refusal-as-data: prize cycles closing without nomination publish refusal briefs; the refusal corpus density itself becomes part of the substrate that future nominators see.

## Cross-references

- Endorser-discovery (substrate reuse): `docs/research/2026-04-26-arxiv-velocity-preprint-architecture.md` (PR #1663)
- Velocity findings (cite-able evidence): PR #1677 + `docs/research/2026-04-25-velocity-comparison.md`
- License matrix: PR #1679
- Cold-contact graph-touch policy: `agents/cold_contact/graph_touch_policy.py`
- Refusal-brief publisher: `agents/publication_bus/refusal_brief_publisher.py`
- Operator-referent policy + CI guard: PR #1661

— alpha
