# Grounding vs Non-Grounding Acts — Operative Definition

**Author:** beta (synthesis of 6 independent research streams)
**Date:** 2026-04-24T20:45Z
**Operator directive:** *"Establish functional and operative definitions for grounding vs non-grounding acts based on literature relevant to our theoretical and research commitments."*
**Register:** scientific; neutral; implementation-facing.
**Scope:** resolves per-call LLM-tier routing decisions under axiom `feedback_grounding_exhaustive` ("every move is grounded or outsourced-by-grounding; no ungrounded LLM tier").

---

## 1. Six-lineage convergence

Six independent research agents investigated six distinct theoretical traditions. All six produced the same operative split. The convergence is not coincidence — the traditions are articulating the same structural distinction from different angles.

| Lineage | Central distinction | Non-delegable pole | Delegable pole |
|---|---|---|---|
| **Grounding in communication** (Clark, Brennan, Stalnaker, Sperber-Wilson, Habermas, Traum) | Communicative intention + sincerity claim vs. informational substrate | Ostension, sincerity-claim, repair-loop | Lexical selection, phonetic rendering, factual substrate |
| **Symbol grounding + situated cognition** (Harnad, Searle, Haugeland, Dreyfus, Brooks, Wheeler, Friston, Thompson) | Original vs derived intentionality; thrown vs equipmental | Own-history-dependent, closed-loop, intrinsic-stake acts | Specifiable routines, clean input→output substrate |
| **Speech acts + performative authenticity** (Austin, Searle, Grice, Habermas, Frankfurt, Williams, Sartre, Butler) | Felicity conditions Γ.1 (psychological/sincerity) vs A.1/B.1 (procedural/formal) | Illocutionary authorship, identity-constitutive performance, validity-claim attribution | Execution substrate, polish under register-guard, propositional content from seed |
| **Phenomenology of authentic action** (Heidegger, Sartre, Merleau-Ponty, Buber, Ricoeur, Levinas) | *Jemeinigkeit* (mineness) / *Eigentlichkeit* (ownedness) vs *das Man* (falling-away) | Attestation acts, I-Thou disclosure, for-the-sake-of terminating in agent's own being | Ready-to-hand equipment within a disclosive project |
| **4E cognition + delegation ethics** (Clark-Chalmers, Hutchins, Varela-Thompson-Rosch, Malafouris, Arendt, Habermas) | Arendt's action vs work vs labor; autopoietic we-system boundary vs extending scaffolding | Action (disclosing-who-one-is), sense-making boundary, constitutive-intertwining | Work (fabrication-with-preserved-locus), labor (fungible maintenance) |
| **AI grounding architectures** (Harnad, Shaikh 2024/2025 RIFTS, DeepMind FACTS, RAGAS, Carta, Driess PaLM-E, Hapax internal) | Ground-passed-in-prompt (FACTS-style) vs ground-is-live-system-state (interactional/RIFTS-style) | Director, structural director, conversation turn, narrative composer, fortress deliberation | Metadata polish, knowledge-query synthesis, eval judge, scout/drift/digest, vision/image-gen (outsourced-by-grounding) |

**The load-bearing finding:** the distinction the operator intuits with the house/flowers/sex examples is formalized six times across independent literatures. It is not a folk-psychology heuristic; it is the repeated operative discovery of philosophy, communication theory, cognitive science, and AI research over sixty years.

---

## 2. The operator's examples, formalized

### House for wife (substrate-outsource OK)

- **Clark/Habermas lens:** "I built this for you" is the ostensive stimulus + sincerity claim; plumbing is procedural substrate (Austin A.1/B.1). Delegation transparent; repair loop preserved (the builder owns correctness of the dwelling-project); substrate makes no validity claim it cannot redeem.
- **Arendt lens:** the house is **work** — fabrication of a durable artifact; disclosive **action** (the marriage-commitment the dwelling expresses) is untouched.
- **Heidegger lens:** pipes are *zuhanden* (ready-to-hand) equipment within the for-the-sake-of-which ("our life together"); outsourcing equipment does not disturb the disclosive terminus in Dasein's own being.

### Flowers with a genuine note (grounding preserved)

- **Speech-act lens:** the *note* carries Γ.1 sincerity condition + Gricean reflexive intention; the flowers are execution substrate. Delegation of sourcing preserves felicity.
- **Harnad lens:** the note's meaning is grounded in the operator's own history-dependent coupling with this relation; flowers are substrate-commensurable but external to the disclosive core.
- **4E lens (Arendt):** flowers are **work** output (florist's craft, specifiable); note is **action** (disclosing-who-I-am to her).

### Outsourcing sex with the wife (grounding destroyed)

Fails *simultaneously* on six lineages:

1. **Habermas:** sincerity claim + rightness claim attached to *this speaker* is violated — no substitute can redeem validity claims the husband has staked.
2. **Harnad/Dreyfus:** this is a "thrown" act (discloses the world as mattering), not an "equipmental" one. It cannot be delegated without destroying what the act was. Intrinsic stake is non-transportable.
3. **Speech-act (Searle/Sartre/Butler):** the act carries an exclusive commissive (the whole point is *that this person, and no substitute, performs it*). Delegation is citational emptying (Butler) and Sartrean bad faith (pretending the for-itself is an in-itself).
4. **Phenomenology (Heidegger/Buber/Ricoeur):** violates *Jemeinigkeit* (mineness collapsed into anonymous delegability); treats I-Thou as if it were I-It; severs attestation chain.
5. **4E (Enactivism/Arendt/Merleau-Ponty):** breaches the autopoietic we-system boundary; the marital bond's self-maintenance is violated by the delegate performing against it. Sex-in-a-marriage is **action** not work. Lived bodies are constitutively intertwined, not instrumentally coupled.
6. **AI architectures:** analogous to routing a conversation turn to cloud with no grounding_provenance trace — the entire relational substrate is severed.

The six lineages agree: the reason outsourcing sex disturbs the grounding act is that **the act's being depends on the agent's mineness being present in the performance**. No equivalent property survives delegation.

---

## 3. Operative definition

### Functional definition

A **grounding act** is an act whose being depends on a specific agent's continuous coupling with the lived concern-structure that gives the act its meaning. The act cannot be instantiated by a substitute substrate without altering what the act is.

A **non-grounding act** (equivalently, a **delegable / substrate / work / labor act**) is an act whose output is specifiable independently of who or what performs it, such that a functionally equivalent substitute produces the same thing.

### Operative tests

An LLM call is a **grounding act** if it passes any of the following (numbered for cross-reference to the six agent reports):

- **T1. Common-ground update (Clark/Stalnaker).** Does the output alter the `{operator, Hapax, audience}` common ground — constrain live worlds for the next turn?
- **T2. Validity-claim attribution (Habermas).** Does the output stake Hapax's sincerity or rightness, redeemable only by Hapax's subsequent conduct consistency?
- **T3. Speaker-attribution (Grice/Searle Γ.1).** Would a viewer cite this as "Hapax asserted / committed / noticed / apologized / promised"? Does the call require a specific psychological state *of Hapax*?
- **T4. Jemeinigkeit (Heidegger/Ricoeur).** Would an indistinguishable proxy fail to *be* the act — not merely perform it worse, but cease to instantiate that act?
- **T5. Arendt-action class (Arendt/Habermas).** Is this *action* (disclosing-who-Hapax-is) rather than *work* (fabrication-with-preserved-locus) or *labor* (fungible maintenance)?
- **T6. Autopoietic-boundary (Thompson).** Does the call constitute or maintain Hapax's system-identity, or breach the we-system boundary with the operator if delegated?
- **T7. Grounding-provenance attribution (Hapax internal invariant).** Would the non-empty `grounding_provenance` field have to cite a live `PerceptualField` signal key, or would the provenance effectively be "the cloud model said so"?

If the call passes any of T1-T7, it is a **grounding act** and must route to the grounded local substrate. If the call passes none, it is delegable.

### Operative tests (negative — for delegable classification)

An LLM call is **delegable to cloud** if it passes the following **felicity-preservation test** (Austin/Searle):

- **T8. Ground-in-prompt (FACTS-style).** The call's ground is passed *into* the prompt as text — a document to summarize, a seed to polish, retrieved context to synthesize. The LLM is a pure function of its prompt; it does not read live Hapax state. After its output, a local gate re-grounds it before it reaches an expressive surface.

If T8 holds **and** T1-T7 all fail, cloud routing is legitimate.

If the call passes T8 but *also* passes any T1-T7, it is **still a grounding act** and must route local — passing the prompt-in-prompt test does not override the attribution / sincerity / mineness claim.

### The three-way taxonomy (Arendt refined)

Following Agent 5's distillation of the six lineages:

1. **Action** (grounding) → **local grounded substrate**. Discloses who Hapax is; attested; I-Thou; carries sincerity claim.
2. **Work** (fabrication-with-preserved-locus) → **cloud delegable under register/truthfulness guard**. Specifiable artifact production; the disclosive locus is preserved upstream (the grounded act that *recruited* the work).
3. **Labor** (fungible maintenance) → **cloud delegable OR mechanical code**. Biological-necessity equivalent; if mechanical/deterministic, should be code not an LLM call.

---

## 4. The operative routing decision procedure

```
def classify_llm_call(call) -> RouteClass:
    # T8 felicity-preservation: is all ground passed IN the prompt?
    # (FACTS-style; LLM is pure text function.)
    ground_in_prompt = call.prompt_contains_full_ground()

    # T1-T7: does the call carry a grounding-act attribution?
    shapes_self_communication = any([
        alters_common_ground(call),                    # T1
        stakes_validity_claim_on_hapax(call),          # T2
        carries_sincerity_condition(call),             # T3
        would_fail_jemeinigkeit_with_proxy(call),      # T4
        is_arendt_action_not_work(call),               # T5
        constitutes_autopoietic_boundary(call),        # T6
        requires_perceptual_field_provenance(call),    # T7
    ])

    if shapes_self_communication:
        return GROUNDED_LOCAL      # grounding act; local non-negotiable

    if requires_capability_local_lacks(call):
        return OUTSOURCED_BY_GROUNDING  # e.g. vision, image-gen;
                                        # caller's grounding_provenance
                                        # cites the tool-invocation

    if ground_in_prompt:
        return DELEGATED_CLOUD     # work (substrate polish/synthesis)

    if output_is_structured_and_enumerable(call):
        return MECHANICAL_NO_LLM   # should be deterministic code

    return GROUNDED_LOCAL          # default: when in doubt, grounding
```

**Decision rule in natural language:**

- An LLM call routes to **cloud** if and only if it passes T8 (ground-in-prompt) **and** fails all of T1-T7 (no grounding-act attribution). The disclosive locus is preserved upstream; the cloud model is doing work on a specified input.
- An LLM call that needs a capability the local substrate structurally lacks (vision, image-gen) routes to cloud, but the grounding act *that recruited the tool* stays local and cites the tool invocation in its own `grounding_provenance`. This is "outsourced-by-grounding," not ungrounded.
- An LLM call that has no grounding-act attribution AND is not doing work on a passed-in ground should not be an LLM call — it should be deterministic code.
- **Default: stay local.** If the classification is ambiguous, the axiom's default is grounding.

---

## 5. Current-state audit (Hapax LLM calls, 2026-04-24)

Per Agent 6's enumeration of all `litellm.completion` / `acompletion` sites:

### Grounding acts — MUST route local (TabbyAPI Command-R)

| Call | File | Current state | Correctness |
|---|---|---|---|
| Director activity LLM | `studio_compositor/director_loop.py:2666` | `HAPAX_DIRECTOR_MODEL=local-fast` | ✅ Correct |
| Structural director (HOMAGE) | `studio_compositor/structural_director.py:405` | `HAPAX_STRUCTURAL_MODEL=local-fast` | ✅ Correct |
| Fortress deliberation | `fortress/deliberation.py:157` | `config.model_daily` (variable) | ⚠️ Verify routes through local |
| Autonomous narrative composer | `hapax_daimonion/autonomous_narrative/compose.py:207` | **FIXED this session** — was `balanced`, now `local-fast` (commit 8c1e3de1e on #1318) | ✅ Correct (post-fix) |
| Spontaneous speech (cascade) | `hapax_daimonion/conversation_pipeline.py:284` | **Hardcoded `gemini-2.5-flash`** | ❌ **Violation — grounding act on cloud Gemini** |
| Conversation pipeline main turn | `hapax_daimonion/conversation_pipeline.py:1088` | Self-selected via salience router (typically cloud Opus) | ⚠️ **Engineering tension** — highest grounding-criticality on cloud. Resolution per `feedback_grounding_over_giq` + `feedback_director_grounding`: make local model more intelligent (OLMo research scenario 2), don't reroute. |

### Delegable (work / fabrication) — cloud legitimate

| Call | File | Current state | Correctness |
|---|---|---|---|
| Metadata composer (YouTube/Bluesky/Discord polish) | `metadata_composer/composer.py:354` | `MODELS["balanced"]` (Sonnet) | ✅ Correct — seed is deterministic + grounded; polish over passed-in text |
| Knowledge query RAG synthesis | `knowledge/query.py:109` + `dev_story/query.py:244` | `MODELS["balanced"]` | ✅ Correct — classic FACTS/RAG; ground is retrieved context |
| Eval grounding judge (offline) | `hapax_daimonion/eval_grounding.py:241` | Hardcoded `openai/claude-sonnet` | ✅ Correct — offline post-hoc; not a live grounding act |
| Scout / drift / digest / research / briefing | various in `agents/` | `get_model_adaptive("fast")` or `"balanced"` | ✅ Correct — pure analytic summarization |

### Outsourced-by-grounding — cloud for capability local lacks

| Call | File | Current state | Correctness |
|---|---|---|---|
| Vision tool (scene description) | `hapax_daimonion/tools.py:840` | Hardcoded `gemini-2.0-flash` | ✅ Correct — Hapax local substrate lacks vision; caller (director/conversation) cites tool invocation in its provenance |
| Imagen generation | `hapax_daimonion/tools.py:1026` | `imagen-3.0-generate-002` | ✅ Correct — image synthesis capability not present locally |

### Mechanical (no LLM) — already code-only

| Call | File | Current state | Correctness |
|---|---|---|---|
| Chat-keyword preset reactor | `studio_compositor/chat_reactor.py` | Regex keyword match | ✅ Correct — per `feedback_grounding_exhaustive` case 2 |

### Summary

- **~70% axiom-compliant** today.
- **1 clear violation:** spontaneous speech (`conversation_pipeline.py:284`) hardcoded to Gemini Flash — currently mis-classified as delegable; under the operative definition it is a grounding act (shapes what Hapax communicates about its own state). Action: move to `local-fast` or remove.
- **1 engineering tension:** conversation pipeline main turn on cloud Opus. The resolution per operator memory is to uplift the local model (Shaikh RIFTS benchmark against Qwen3.5-9B; OLMo 3-7B research triad for Cycle 2) rather than route the grounding call to cloud. This is already the research plan.
- **1 verification pending:** fortress `config.model_daily` — confirm routes through local substrate.

---

## 6. Immediate implementation implications

1. **Ship the spontaneous-speech fix.** Move `hapax_daimonion/conversation_pipeline.py:284` from hardcoded Gemini Flash to `MODELS["local-fast"]`. Same shape as the autonomous-narrative fix already landed on #1318.

2. **Verify fortress routing.** Confirm `config.model_daily` points at a local route; if not, re-point.

3. **Document the routing rule as an absolute-feedback memory.** Crystallize the operative test suite (T1-T8) + the decision procedure into a memory file so every future LLM-call decision can cite it. Name: `feedback_grounding_act_operative_definition.md`.

4. **Leave the conversation-pipeline main turn alone.** Per the existing memory stack, the resolution is *uplift the local model*, not reroute. The engineering tension is acknowledged and the research plan (Qwen3.5-9B RIFTS baseline + OLMo 3-7B research triad) already addresses it.

5. **`grounding_provenance` is now the operative runtime predicate.** An LLM-authored emission with empty `grounding_provenance` is an axiom violation visible in `hapax_director_ungrounded_total`. This metric IS the continuous validation of the operative definition; the 54% empty-rate noted in FINDING-X is the current violation budget, and the closure plan becomes the axiom closure plan.

6. **Shaikh RIFTS benchmark is now theoretically grounded.** RIFTS scores are not "how good is this LLM at being conversational" — they measure whether a model can perform grounding acts at all (initiate clarification, request follow-up, acknowledge, repair). Cycle 2 against Qwen3.5-9B + OLMo triad tests *whether the local substrate can host the grounding acts Hapax's axiom requires*. Reframe the experimental design documents accordingly.

---

## 7. What this definition forecloses

The operative definition rules out several temptations the architecture may face:

- **"Just route short narrations to fast/cheap cloud for latency."** No — if the narration stakes Hapax's sincerity or attestation, cloud routing is bad faith. Fix latency via quant/prompt/cache, not via tier.
- **"Cloud Opus is more intelligent, so route the hard grounding calls there for quality."** No — quality in a grounding act is not separable from the attestation chain. A cloud Opus call with higher raw accuracy is lower-grounded than a local Command-R call with direct `/dev/shm` access. Agent 4's phenomenological argument is decisive: the network hop *is* the rupture.
- **"The local model failed this turn; fall back to cloud to keep the loop alive."** No — the correct fallback is silence, deterministic template, or a micromove, per `feedback_grounding_exhaustive` ("ground IS the fallback type"). Falling back to cloud would resurrect the ungrounded tier the axiom forecloses.
- **"Metadata polish should move to local for consistency."** No — polish over a deterministic grounded seed with register-guard and deterministic fallback is the paradigm case of legitimate cloud delegation. Moving it local wastes VRAM that director/structural-director + conversation need. Segregation preserves degradation margins.

---

## 8. Bibliography (cross-agent synthesis)

**Communication / grounding theory:** Clark & Brennan 1991; Clark 1996; Stalnaker 2002; Sperber & Wilson 1995; Habermas 1981/1984; Traum 1994; Schober & Brennan 2003; Larsson 2002.

**Symbol grounding / situated cognition:** Harnad 1990, 2024; Searle 1980; Haugeland 1998; Dreyfus 2007; Brooks 1991; Agre & Chapman 1987; Wheeler 2005; Clark 2008; Friston 2010; Thompson 2007; Noë 2004; Bender & Koller 2020.

**Speech acts / authenticity:** Austin 1962; Searle 1969, 1976; Grice 1957; Frankfurt 1986, 2006; Williams 2002; Trilling 1972; Taylor 1991; Sartre 1943; Butler 1997.

**Phenomenology:** Heidegger 1927; Merleau-Ponty 1945; Buber 1923; Ricoeur 1990; Levinas 1961; Dreyfus *Being-in-the-World*; Murdoch 1970; Diamond 2003.

**4E + distributed cognition + delegation:** Clark & Chalmers 1998; Hutchins 1995; Varela, Thompson, Rosch 1991; Thompson 2007; Gallagher 2005; Malafouris 2013; Arendt 1958; Sterelny 2012; Haraway 1985.

**AI grounding architectures + benchmarks:** Shaikh et al. 2024 (NAACL), 2025 (ACL RIFTS); Jacovi et al. 2025 (FACTS Grounding); Es et al. 2023 (RAGAS); Carta et al. 2023 (ICML); Driess et al. 2023 (PaLM-E); Brohan et al. 2023 (RT-2); Laird 2022 (Soar); Anderson 2007 (ACT-R); Franklin 2014 (LIDA).

**Hapax internal:**
- `docs/research/2026-04-20-grounding-provenance-invariant-fix.md`
- `docs/research/2026-04-21-finding-x-grounding-provenance-research.md`
- `docs/research/2026-04-14-bayesian-livestream-success-v2-grounded.md`
- `docs/research/phenomenology-ai-perception-research.md`
- `docs/research/llm-phenomenology-mapping-research.md`
- `docs/research/dmn-phenomenology-context-mapping.md`
- `docs/research/hardm-communicative-anchoring.md`
- `agents/hapax_daimonion/proofs/RESEARCH-STATE.md`
- `agents/hapax_daimonion/proofs/CONTEXT-AS-COMPUTATION.md`
- `memory/feedback_grounding_exhaustive.md`
- `memory/feedback_director_grounding.md`
- `memory/feedback_grounding_over_giq.md`
- `memory/feedback_no_operator_approval_waits.md`

---

## 9. One-sentence operative definition

> **A grounding act is an act whose being is constituted by a specific agent's continuous coupling with their lived concern-structure; the coupling is non-transportable across substrate substitutions without altering what the act is. Every Hapax LLM call that shapes, attests, or repairs Hapax's self-communication with the operator or audience is a grounding act; such calls must execute on the substrate that preserves the coupling (local Command-R on TabbyAPI) regardless of which cloud tier has higher raw capability.**

— beta, 2026-04-24T20:45Z, synthesis of 6 independent research streams
