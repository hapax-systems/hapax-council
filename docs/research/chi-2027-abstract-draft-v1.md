# CHI 2027 Abstract Draft (v1)

**Status:** Draft for operator review
**Target:** CHI 2027 (Late-Breaking Work or full paper track TBD)
**Authority:** CASE-20260509-RESEARCH-PO

## Title

Hapax: An Embodied Stigmergic Cognitive Mesh for Single-Operator AI Systems

## Abstract (300 words)

We present Hapax, a single-operator AI system that coordinates 190+
specialized agents through stigmergic traces on a filesystem-as-bus
architecture rather than explicit message passing. Unlike multi-agent
orchestration frameworks that rely on centralized planners or turn-based
conversation, Hapax agents read and write shared artifacts (YAML, JSON,
markdown) whose presence and modification history serve as the sole
coordination signal. This design eliminates the bottleneck of a
coordinator agent while preserving coherent system behavior across
perception, expression, and governance domains.

The system extends stigmergic coordination with embodied grounding:
six RGB cameras, three infrared sensors, and continuous audio input
close a perception-action loop where the system observes its physical
environment and its own rendered output. A temporal grounding layer
(retention/protention/impression bands) prevents stale perceptual
evidence from grounding current-world truth claims. A clause-level
verifier rejects assertions that exceed the available evidence before
they reach text-to-speech output.

Hapax operates under five constitutional axioms (single-user, executive
function, corporate boundary, interpersonal transparency, management
governance) enforced by a Bayesian claim-tracking engine that maintains
posterior confidence on every factual assertion. A publication bus with
55 surfaces and three governance tiers (full-auto, conditional-engage,
refused) gates all public output against rights, privacy, and
scientific-doctrine constraints.

We report on 52 days of continuous autonomous operation across a live
research livestream, during which the system composed and delivered
narrated content segments, managed its own visual compositor through
shader graph drift, and maintained governance invariants without
operator intervention. We discuss the tradeoffs between stigmergic
coordination and explicit orchestration, the role of temporal grounding
in preventing LLM hallucination about environmental state, and the
architectural consequences of a system perceiving its own rendered
output.

## Keywords

Stigmergic coordination, single-operator AI, embodied cognition,
temporal grounding, constitutional governance, LLM agent systems
