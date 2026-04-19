# Role Derivation Template

**Status:** template artifact
**Companion to:** `docs/research/role-derivation-methodology.md`
**Usage:** copy this file to a new location, replace every `[FILL: ...]` placeholder, then discard this header. The resulting document is a per-system (or per-research-question) role derivation record.

The template mirrors the five-step method from the methodology document. Each section maps to one step; do not skip or reorder. If a step is non-applicable to the system under derivation, note the rationale rather than omitting the section.

---

## Frontmatter

- **System under derivation:** `[FILL: name of the system or subsystem whose roles are being derived]`
- **Research question:** `[FILL: single-sentence declarative research question]`
- **Date:** `[FILL: YYYY-MM-DD]`
- **Analyst:** `[FILL: name or handle]`
- **Version:** `[FILL: 1.0 for initial derivation; increment on re-derivation]`
- **Supersedes:** `[FILL: prior derivation path if re-deriving; otherwise: "none"]`

---

## 1. Research question (Step 1)

State the research question as a declarative sentence.

> `[FILL: research question]`

Expansion notes (clarify terms, scope, exclusions):

- `[FILL: term A — what it names, why it is narrow enough]`
- `[FILL: term B — what it names, why it is narrow enough]`
- `[FILL: axiom anchors or constraints that pin the question to this scope]`
- `[FILL: conditions under which the question would need to be replaced rather than refined]`

**Step 1 validation checklist:**

- [ ] Research question is a declarative sentence, not a title.
- [ ] Research question admits empirical study.
- [ ] Research question is not trivially decomposable into disjoint sub-questions.
- [ ] Research question does not presuppose a role taxonomy.

If any check fails, pause derivation and refine the question before continuing.

---

## 2. Actant enumeration (Step 2)

Enumerate every entity that acts on or is acted upon by the research question. Include non-human actants (hardware, software, institutions, documents, spaces).

| Actant | Class (human / software / hardware / institution / document / space / other) | Notes |
|---|---|---|
| `[FILL]` | `[FILL]` | `[FILL: why it matters to the research question]` |
| `[FILL]` | `[FILL]` | `[FILL]` |
| `[FILL]` | `[FILL]` | `[FILL]` |

Add rows as needed. A minimum of five actants is typical for any non-trivial system; fewer suggests under-enumeration.

**Step 2 validation checklist:**

- [ ] Every named actant can be pointed at (grep target, documentation, locator).
- [ ] The list is heterogeneous (contains multiple classes, not only humans).
- [ ] No entry names an activity rather than an entity (activities go in `answers_for`, not here).

---

## 3. Candidate position table (Step 3)

For the actant-of-interest (typically the one the taxonomy is being authored *for*), enumerate thick positions. Each candidate has the form:

> In relation to [other actant or network], this actant *answers-for* [enumerable commitments] and is accountable at [specific cadence or condition].

| Candidate position id | whom-to | answers-for (enumerate) | amendment-gating (axiom / registry / posture) |
|---|---|---|---|
| `[FILL]` | `[FILL]` | `[FILL: comma-separated commitments]` | `[FILL]` |
| `[FILL]` | `[FILL]` | `[FILL]` | `[FILL]` |
| `[FILL]` | `[FILL]` | `[FILL]` | `[FILL]` |

Include candidates that seem borderline or that you expect to collapse — Step 5's collapse test is the legitimate mechanism for removing them. Do not pre-filter candidates at this step based on intuition.

**Step 3 validation checklist:**

- [ ] Every candidate has a non-empty `whom-to`.
- [ ] Every candidate has an enumerable `answers-for` list (not a single abstract noun).
- [ ] No candidate is phrased as a disposition, attitude, or feeling.

---

## 4. Persona / posture / role classification (Step 4)

Classify every item from Step 3 — plus any items that surfaced during Steps 1–3 but did not fit the candidate position table — into exactly one of persona, posture, or role.

| Item | Category (persona / posture / role / reject) | Rationale |
|---|---|---|
| `[FILL]` | `[FILL]` | `[FILL: why this category]` |
| `[FILL]` | `[FILL]` | `[FILL]` |
| `[FILL]` | `[FILL]` | `[FILL]` |

Guidance:

- **Persona** items describe what the actant *is* at the substrate level — architectural invariants, species-type claims. They are not roles; they are the ontological ground.
- **Posture** items are named consequences of architectural state — emergent, per-context, observability-oriented. Not roles.
- **Role** items are thick positions with whom-to and answers-for, relative to the research question.
- **Reject** items are candidates that failed Step 3 validation on re-examination (e.g., activities disguised as positions, feelings asserted as roles).

**Step 4 validation checklist:**

- [ ] Every item is in exactly one category.
- [ ] No item asserts inner life the architecture does not produce.
- [ ] Activities are demoted to "activities a role carries out" and noted in the relevant role's `answers_for`.

---

## 5. Collapse test (Step 5)

For each item classified as *role* in Step 4, apply the collapse test.

> Test: If this role were removed from the taxonomy, would the research question still be fully characterized with respect to the actant?

| Candidate role | Collapse outcome (survives / collapses-into-X / rejects) | Unique contribution (if survives) | Rationale |
|---|---|---|---|
| `[FILL]` | `[FILL]` | `[FILL: what this role uniquely contributes to the research question's characterization]` | `[FILL]` |
| `[FILL]` | `[FILL]` | `[FILL]` | `[FILL]` |
| `[FILL]` | `[FILL]` | `[FILL]` | `[FILL]` |

**Step 5 validation checklist:**

- [ ] Each surviving role has a documented unique contribution.
- [ ] No two surviving roles share the same `whom_to` + `answers_for` pair.
- [ ] Every collapsed role has a named absorbing role.
- [ ] Every rejected role has a named rejection reason (activity, posture, disposition, etc.).

---

## 6. Final taxonomy

The output of Step 5 is the taxonomy. Produce the list of surviving positions with full field population, including the `is_not:` enumeration derived from collapsed and rejected candidates.

For each surviving role:

### Role: `[FILL: role id]`

- **Layer:** `[FILL: structural / institutional / relational]`
- **Axiom anchors:** `[FILL: axiom ids or "none"]`
- **whom_to:** `[FILL]`
- **answers_for:**
  - `[FILL: commitment 1]`
  - `[FILL: commitment 2]`
  - `[FILL: ...]`
- **is_not:**
  - `[FILL: pattern the role explicitly rejects — derived from Step 4 rejects and Step 5 collapsed candidates]`
  - `[FILL: ...]`
- **amendment_gated:** `[FILL: true / false]`
- **Instances inferred from:** `[FILL: runtime signals or state paths — relational roles only]`
- **Description:** `[FILL: 2–4 sentences — what the role is, what stabilizes it, how it relates to adjacent roles]`

Repeat for every surviving role.

---

## 7. Registry YAML proposal

Produce a ready-to-merge YAML block for the governance registry (or equivalent persistence layer in the target system).

```yaml
# [FILL: target registry file path]
version: [FILL]
schema_version: "[FILL]"

roles:
  - id: [FILL]
    layer: [FILL]
    axiom_anchors: [FILL]
    whom_to: [FILL]
    answers_for:
      - [FILL]
      - [FILL]
    is_not:
      - [FILL]
      - [FILL]
    amendment_gated: [FILL]
    description: >
      [FILL: prose description]

  # repeat for every surviving role
```

---

## 8. Known adjustments for the target system

List any system-specific constraints that materially affected the derivation. These are not part of the general method; they document the adjustments this particular derivation made because of the target system's architecture, axioms, or history.

- `[FILL: constraint A — e.g., axiom-anchored scale, continuity-of-study, no-authentication-surface]`
- `[FILL: constraint B]`
- `[FILL: constraint C]`

For Hapax as a worked example, typical adjustments include:

- `single_user` axiom forbids any multi-operator role decomposition.
- Livestream-as-research-instrument forecloses Goffman back-stage / front-stage separation.
- Affordance pipeline means every expression is recruited, not dispatched from a fixed repertoire; role `answers_for` items are realized through recruitment, not scripts.
- Continuous DMN + CPAL loops make posture emergent; roles do not prescribe posture.

Other systems will have different adjustments. Enumerate them honestly; do not elide them to make the taxonomy look cleaner than the system actually is.

---

## 9. Open questions and deferred decisions

Some derivations leave decisions unresolved. Document them here for future re-derivation attention.

- `[FILL: question A]`
- `[FILL: question B]`

An open question does not block the taxonomy's use; it flags where the next derivation cycle should look first.

---

## 10. Post-derivation actions

After the derivation is complete, the following downstream actions are expected:

- [ ] Update the target registry (YAML or equivalent) with the Step 7 proposal.
- [ ] Update the persona document (if applicable) to cross-reference the new or changed roles.
- [ ] Update any `is_not:`-consuming linter configuration to pick up new constraints.
- [ ] Archive the prior derivation (if this is a re-derivation) with a link from the new one.
- [ ] Run the target system's role-registry tests to confirm the new taxonomy parses and lints.

---

## References

- `docs/research/role-derivation-methodology.md` — the authoring method this template implements
- `[FILL: target system's persona document, if applicable]`
- `[FILL: target system's posture vocabulary, if applicable]`
- `[FILL: target system's axiom registry, if applicable]`
- `[FILL: relevant literature — ANT sources, grounding theory, stage-management craft, etc.]`
