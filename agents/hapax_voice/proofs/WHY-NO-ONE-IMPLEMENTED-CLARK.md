# Why No Commercial System Implements Clark & Brennan (1991): The 32-Year Gap

**Date:** 2026-03-21
**Source:** Deep research agent, 42 web searches, 30+ citations

## The Three Categories

### Real Obstacles (we will face these)

1. **Authoring cost / domain specificity** — TRAINS, RavenClaw, Collagen ALL required manual specification of task models and grounding policies per domain. Open-domain conversation seemed intractable. *Our mitigation: LLM-as-grounding-act-recognizer eliminates the manual taxonomy problem. The model classifies grounding acts; we track state mechanically.*

2. **Slot-filling was good enough** — For command-and-control voice assistants (Siri, Alexa, Google), intent + slots + confirmation prompts handle 90% of cases. No discourse-level machinery needed. *Our case is different: sustained relational interaction, not command-and-control.*

3. **No empirical business case** — No one has demonstrated measurable ROI from grounding in production. *This is what our experiment IS. If we show measurable improvement, we make the case.*

### Misconceptions We Can Challenge

1. **"LLMs are smart enough to ground implicitly"** — Shaikh et al. (2024 NAACL) proved they're not. RLHF specifically reduces grounding acts. Larger models + more preference optimization = WORSE grounding.

2. **"Grounding is computationally intractable"** — Only if you track full recursive mutual beliefs. Traum's DU state machine is computationally trivial (regular grammar, microsecond transitions). The hard part is grounding act recognition — which LLMs are well-suited for.

3. **"RAG/context engineering solves the same problem"** — It solves knowledge access, not mutual understanding. Knowing what to inject ≠ knowing whether both parties understood it.

4. **"Users just rephrase and move on"** — Some do. Many abandon entirely. In high-stakes domains (medical, legal, educational), undetected misunderstanding is catastrophic.

### Historical Accidents

1. **Academic-industry gap never bridged** — NAACL 2007 workshop explicitly named this problem ("Bridging the Gap"). Research and commercial dialogue systems evolved on parallel tracks.

2. **Deep learning revolution skipped discourse** — Neural approaches (2012-2020) focused on perception (ASR, NLU), not discourse management. End-to-end training was the paradigm; explicit state machines were "retrograde."

3. **RLHF's anti-grounding bias** — The most impactful training methodology actively suppresses grounding. Human raters prefer confident, comprehensive answers over clarification-seeking answers. The reward model learns that grounding acts are "unhelpful." No one designed this deliberately; no one is fixing it.

## The Most Devastating Finding

**OpenAI's model spec (2025) explicitly instructs models NOT to ask clarifying questions** — instead to "cover all plausible user intents with both breadth and depth." This is the anti-grounding strategy codified as product policy. The industry's answer to "what if the user's intent is ambiguous?" is not "ask" but "guess comprehensively."

## Who Is Currently Working on Clark + LLMs

1. **Cassell, Mohapatra, Traum** — ESSLLI 2024 workshop. Annotation framework published. No implementation.
2. **Shaikh, Horvitz et al. (Microsoft Research)** — Rifts benchmark. Diagnosis, not treatment.
3. **Jokinen (2024)** — Position paper. No implementation.
4. **Traum (USC ICT)** — Continuing multimodal grounding research. Editor of Dialogue & Discourse.
5. **AIST Japan** — LLM comprehension of grounding. No implementation.

**Everyone is studying the phenomenon. No one is building a system.**

## What This Means for Us

We are not just the first to attempt Clark in a production voice system. We are attempting it in an environment where:
- The dominant training methodology actively opposes grounding
- The industry leader's product spec explicitly forbids the core grounding act (asking for clarification)
- The academic community has identified the gap but not closed it
- 32 years of theory have produced zero production implementations

Our advantage: we don't need to solve the authoring cost problem (LLMs classify grounding acts). We don't need slot-filling (open-domain, single operator). We don't need to convince a product team (we ARE the operator). The obstacles that stopped everyone else don't apply to us.

The obstacle that DOES apply: RLHF fighting our grounding constraints. This is the Cycle 3 question — whether prompted Opus suffices or whether we need a fine-tuned model.

## Key Citations

- Shaikh et al. (2024, NAACL): "Grounding Gaps in Language Model Generations"
- Shaikh et al. (2025, ACL): "Navigating Rifts in Human-LLM Grounding"
- OpenAI Model Spec (2025): anti-clarification policy
- Bohus & Rudnicky: RavenClaw authoring cost acknowledgment
- Koschmann & LeBaron (2003): "common ground is a place with no place"
- NAACL 2007 Workshop: "Bridging the Gap: Academic and Industrial Research in Dialog Technologies"
- ESSLLI 2024 Workshop: "Conversational Grounding in the Age of Large Language Models"
