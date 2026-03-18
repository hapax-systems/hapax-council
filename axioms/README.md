# axioms/ — Constitutional Governance for Agentic Systems

Constitutional governance for LLM-driven agent systems. Axioms are structural invariants — not guidelines, not prompt instructions — enforced at the architecture level via commit hooks, runtime checks, and accumulated case law. The approach draws on ordoliberalism (Worsdorfer 2023): axioms as frame rules (Ordnungspolitik) that constrain what the system can express, not directives that tell agents what to do.

## Formal grounding

| Concept | Source | Application here |
|---------|--------|-----------------|
| Constitutive vs. regulative rules | Searle 1995, Boella & van der Torre 2004 | Constitutive rules classify data ("email from domain X counts as work data"); regulative rules constrain behavior ("work data must not persist on home infrastructure") |
| Defeasible logic | Governatori & Rotolo | General constitutive rules can be defeated by specific conditions (e.g., environmental data is personal if it enables re-identification) |
| NorMAS enforcement tiers | Criado et al. | T0 = regimentation (structurally impossible), T1 = enforcement (blocked with review), T2 = monitoring (advisory), T3 = suggestion (lint) |
| Interpretive canons | Statutory/constitutional law | Textualist, purposivist, absurdity doctrine, omitted-case — the same reasoning courts use to derive specific obligations from general principles |
| Vertical stare decisis | Common law | Precedent authority hierarchy: operator (1.0) > agent (0.7) > derived (0.5) |
| AMELI governor pattern | Esteva et al. 2004 | GovernorWrapper validates inputs/outputs at agent boundaries |

See [`shared/README.md`](../shared/README.md) for the theory-to-code map and algebraic proofs.

## Governance Approach

Traditional software systems govern behavior through access control: enumerate who can do what, check permissions at runtime, log violations. This works when the space of possible actions is known in advance. A web application has endpoints; each endpoint has a permission; the middleware checks it.

LLM agents break this model. An agent tasked with "prepare context for a 1:1 meeting" might, in the course of doing useful work, construct a code path that persists behavioral patterns about a team member, generates suggested coaching language, or infers someone's emotional state from calendar patterns. None of these actions were anticipated in an access control list. The agent didn't circumvent a rule — it found a path through territory where no rules existed.

