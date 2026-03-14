# Level 6: How to Talk About This

## The vocabulary you need

When talking to **PL/Security people**: "We apply the Decentralized Label Model to consent governance. Consent labels form a join-semilattice with bottom. Data propagates via LIO-style floating labels through a 10-layer composition stack. PosBool why-provenance enables targeted revocation. The lattice properties are proven by property-based testing — not spot-checked, universally quantified."

When talking to **MAS people**: "We extend OperA's organizational model with two mechanisms no published framework provides: norm refinement with four interpretive canons giving full value-to-enforcement traceability, and epistemic carrier dynamics — bounded cross-domain fact carrying formalized via factor graphs and LDPC sparsity bounds. The constitutive/regulative rule separation follows Boella & van der Torre."

When talking to **AI Safety people**: "We demonstrate that externalizing values as weighted axioms evaluated by independent models produces governance overhead below the literature baseline, while providing what Constitutional AI cannot: auditability, amendability, separation of powers, and accumulated case law. The key insight: the alignment tax inverts when LLMs serve as both the governed and the governance."

When talking to **HCI/Ethics people**: "We treat neurodivergent accommodation not as a UX feature but as a constitutional requirement, enforced by the same mechanisms as consent. The system is a governed cognitive extension — Clark & Chalmers formalized, with a self-authored constitution protecting the operator's autonomy and the autonomy of people in their environment."

When talking to **industry/practitioners**: "We built a personal AI system with ambient sensing that actually enforces consent through the entire pipeline, not just at the front door. Consent labels travel with data. Revocation cascades through the system. The governance overhead is 20%. The code is open and the types are extractable."

## The questions you should expect, and honest answers

**"But does it scale?"**
No, and it's not trying to. Single-operator sovereignty is a deliberate simplification that makes the governance problem tractable. Scaling to multi-user requires solving social choice problems we deliberately exclude. The contribution is the formal architecture, not a product.

**"How do you know the 20% figure is real?"**
It's self-reported from development-time analysis of overhead categories. It's not independently measured, and the comparison baseline (30-40% from literature) comes from different systems measuring different things. The papers should present this as indicative, not definitive.

**"Isn't this just access control with extra steps?"**
No. Access control asks "can this principal access this resource?" and answers at the boundary. IFC asks "does this data flow respect the security policy?" and answers *through every computation*. The difference: access control checks the door; IFC checks the entire building. A data laundering attack that transforms data to strip access controls succeeds against access control but fails against IFC (because the floating label tracks what the computation has observed).

**"How is this different from Constitutional AI?"**
Constitutional AI embeds values in model weights via RLHF — you can't inspect, audit, or amend them. This system externalizes values as YAML files evaluated by independent models — fully inspectable, auditable, and amendable. Both approaches have the same goal. Constitutional AI scales; this system provides transparency. They're complementary approaches.

**"The carrier dynamics thing sounds like gossip protocols."**
Gossip protocols spread information *within* a domain. Carrier dynamics carries information *between* domains that don't normally communicate. Gossip is intra-domain consistency; carriers are cross-domain error correction. The key difference: gossip assumes all participants can evaluate the information; carriers work even when the carrying agent doesn't understand the foreign-domain fact — contradiction is detected at the receiving end.

**"What if an agent just... doesn't check the consent label?"**
Then the governance breaks. Code-level enforcement is a discipline requirement. The governor wrapper pattern (AMELI) mitigates this by intercepting at agent boundaries, but there's no cryptographic guarantee. This is a genuine limitation, acknowledged in the theory document. Keyhive-style cryptographic enforcement would be stronger.

**"Is this publishable?"**
Three papers have been identified with target venues. Paper A (consent-as-IFC) targets POST/CSF. Paper B (carrier dynamics) targets AAMAS. Paper C (constitutional governance) targets FAccT. Each is independently self-contained. The implementation is the reference that demonstrates feasibility.
