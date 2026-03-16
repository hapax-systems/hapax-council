# Consent Channel Selection in Ambient Computing Systems

**Date:** 2026-03-15
**Status:** Research complete, awaiting operator decisions
**Scope:** Formal model for selecting the appropriate consent modality when guests enter an ambient sensing environment
**Context:** hapax-council interpersonal_transparency axiom, studio ingestion pipeline, voice daemon perception layer

---

## 0. The Core Insight

> "A principal must know all the ways it can provide consent, but it can't know which way is right until the situation arises. It is obligated to pick the easiest path — otherwise it would be implicitly making consent harder than it could be, which is akin to deception or fraud."

This insight contains three formal claims that the literature separately validates:

1. **Enumeration obligation**: The system must maintain a complete inventory of consent channels (the "covering" problem).
2. **Runtime selection**: The correct channel is context-dependent and cannot be pre-committed (the "matching" problem).
3. **Friction minimization as duty**: Making consent harder than necessary is normatively equivalent to a dark pattern (the "friction" problem).

---

## 1. Literature Findings by Theme

### 1.1 Ambient Intelligence and Ubicomp Consent

**Langheinrich (2001)** established six privacy principles for ubiquitous computing adapted from Fair Information Practices: notice, choice and consent, proximity and locality, anonymity and pseudonymity, security, and access and recourse. His key observation for channel selection: in ubicomp environments where hundreds of devices from multiple collectors constantly query information, traditional consent mechanisms (pressing OK buttons) become physically impossible. He proposed a Privacy Awareness System (PawS) where data collectors announce and implement data usage policies, and data subjects have technical means to track their personal information.

**The bystander problem** is well-studied. A 2025 ACM TOCHI systematic review found that smart home policies rarely provide embedded mechanisms to alert bystanders or handle objections, instead placing the burden on device owners. Only a small share of smart camera manufacturers even acknowledge that their cameras capture bystanders. Research has explored four privacy awareness mechanisms for bystanders: a Privacy Dashboard, a Mobility App, an Ambient Light, and a Privacy Speaker that broadcasts data practices through audio.

**Social dynamics** compound the problem. Bystanders feel hesitant to voice privacy concerns while visiting homes, fearing strain on relationships. This means the system — not the operator — must facilitate consent, because relying on social interaction creates an implicit coercion channel.

**Connection to hapax-council:** The studio ingestion pipeline design (section 6.4) already encodes the consent facilitation principle. But it does not formalize *how* to select among channels, only that the system must offer one. The bystander research validates the design choice that the system (not the operator) surfaces consent opportunities.

Sources:
- [Langheinrich, Privacy by Design — Principles of Privacy-Aware Ubiquitous Systems (2001)](https://link.springer.com/chapter/10.1007/3-540-45427-6_23)
- [Privacy Awareness System for Ubiquitous Computing Environments](https://dourish.com/classes/ics203bs04/22-Privacy-Ubicomp2002.pdf)
- [Bystander Privacy in Smart Homes: A Systematic Review (ACM TOCHI 2025)](https://dl.acm.org/doi/10.1145/3731755)
- [Connected homes: Is bystander privacy anyone's responsibility? (2025)](https://www.helpnetsecurity.com/2025/11/05/bystander-privacy-smart-cameras/)
- [Privacy Perceptions and Designs of Bystanders in Smart Homes (ACM PACM HCI 2019)](https://dl.acm.org/doi/10.1145/3359161)

### 1.2 GDPR and IoT Consent Mechanisms

The GDPR requires consent to be "freely given, specific, informed, and unambiguous" via "a statement or clear affirmative action." The Article 29 Working Party (now EDPB) recognized that physical motions can qualify as unambiguous indication — swiping on a screen, waving in front of a smart camera, turning a phone in a specified direction — provided clear information is given and agreement to a specific request is indicated.

The EDPB's Guidelines 05/2020 establish that **withdrawing consent must be as easy as giving it.** This is the regulatory basis for the symmetry principle already in the studio design (section 6.4, point 5). The ICO guidance for IoT specifically identifies valid consent modalities: ticking opt-in boxes, clicking buttons, selecting from equally prominent yes/no options, oral consent requests, and just-in-time notices.

Critical gap: GDPR and EDPB guidance address consent *modalities* but do not address the *selection problem* — how to choose among modalities when multiple are available and different guests have different capabilities.

**Connection to hapax-council:** The proposed `it-access-001` implication from the studio design already captures the symmetry requirement. But it needs to be extended: the system must not only offer equally accessible grant/refuse mechanisms, it must select the *lowest-friction available* mechanism for each specific guest.

Sources:
- [EDPB Guidelines 05/2020 on Consent under GDPR](https://www.edpb.europa.eu/sites/default/files/files/file1/edpb_guidelines_202005_consent_en.pdf)
- [ICO Guidance for Consumer IoT Products](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/online-tracking/guidance-for-consumer-internet-of-things-products-and-services/how-do-we-ensure-our-iot-products-process-information-lawfully/)
- [GDPR Consent Requirements (i-scoop)](https://www.i-scoop.eu/gdpr/consent-gdpr/)

### 1.3 Consent Fatigue and Dark Patterns

Consent fatigue occurs when constant consent requests lead users to dismiss them reflexively, granting more data access than intended. The asymmetry between granting and refusing is the core dark pattern: when accepting is one click but refusing requires navigating complex menus, users choose the path of least resistance. Google's EUR 150 million fine stemmed partly from requiring multiple clicks to reject cookies while offering one-click acceptance.

The consent-friction instantiation framework formalizes this:

**F = sigma(1 + epsilon) / (1 + alpha)**

Where sigma is total at-risk utility (stake magnitude), epsilon is communication entropy (unresolved information about preferences), and alpha is stakes-weighted alignment between consent-holder's objective and affected agents. Friction diverges under severe misalignment or high entropy.

Key insight for channel selection: **friction is not just a UX concern — it is a measurable quantity with formal properties.** The framework predicts that calibrated (not excessive) friction optimizes both clarity and participation rates. Zero friction is bad (consent becomes meaningless). Infinite friction is bad (consent becomes impossible). There is an optimum.

**Connection to hapax-council:** This directly maps to the executive_function axiom. The system must compensate for cognitive challenges, not add to cognitive load. Consent friction is a form of cognitive load. The obligation to minimize friction is not just ethical but constitutional within this system.

Sources:
- [Dark Patterns and Legal Requirements of Consent Banners (2021)](https://arxiv.org/pdf/2009.10194)
- [Consent-Friction Instantiation Framework](https://www.emergentmind.com/topics/consent-friction-instantiation)
- [Consent as Friction (Guggenberger, SSRN 2024)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4938421)
- [Three Tips to Avoid Dark Patterns in Consent Interfaces](https://www.capco.com/intelligence/capco-intelligence/three-tips-to-avoid-dark-patterns-in-your-consent-interfaces)

### 1.4 Accessibility and Inclusive Consent

WCAG principles require that information be perceivable by all users and that interface components be operable by all users and assistive technologies. Applied to consent: if the only consent channel requires vision (QR code), it excludes blind guests. If the only channel requires hearing (voice prompt), it excludes deaf guests.

Research on accessible consent for autistic people and people with intellectual disabilities identified nine principles for consent materials, with key relevance:
- **Allow multiple communication styles**: AAC devices, writing, letter-boarding, nonverbal communication (head shaking, nodding, pointing, shrugging) must all be acceptable responses.
- **Presumption of competence**: Assume the person can consent unless proven otherwise. Do not default to requiring a more complex process.
- **Environmental supports**: Private, quiet spaces with minimal sensory disruption. Predictable procedures communicated in advance.
- **Ongoing dialogue**: Consent is not a one-time form signing but a continuous process.

A CHI 2025 paper on consent mechanisms for augmented reality proposed design dimensions including Consent Triggers, Awareness Cues, Interaction Modalities, Visualizations, and Time Frames.

**Connection to hapax-council:** The accommodations system already handles neurodivergent-aware presentation for the operator. The same principles must extend to guest consent channels. A guest with ADHD may need a different consent channel than a neurotypical guest. This connects the AccommodationSet concept to consent channel selection — but for guests, not the operator. The system cannot know a guest's needs in advance, so it must offer all channels simultaneously and let the guest self-select.

Sources:
- [Guidelines for Accessible Consent Materials (PMC 2025)](https://pmc.ncbi.nlm.nih.gov/articles/PMC12448064/)
- [Designing Effective Consent Mechanisms for AR (CHI 2025)](https://dl.acm.org/doi/10.1145/3706598.3713519)
- [A Design Space for Privacy Choices in IoT (CHI 2021)](https://dl.acm.org/doi/fullHtml/10.1145/3411764.3445148)
- [WCAG 2.1](https://www.w3.org/TR/WCAG21/)

### 1.5 Voice-Based Consent

A CHI 2023 paper found that while verbal consent for voice assistants (like Alexa) can increase usability, it can also undermine principles core to informed consent. Expert recommendations included: approach permissions according to the user's ability to opt-out, minimize consent decisions, and ensure platforms follow established consent principles.

Problems with voice consent:
- **Ambient listening paradox**: The device must listen to hear "I consent," which means it is already collecting audio data before consent is given.
- **Multi-user confusion**: In a shared space, whose voice counts? Can one person consent on behalf of others present?
- **Coercion through presence**: Saying "I don't consent" in the homeowner's presence feels socially costly, even if technically easy.
- **Ephemeral record**: Verbal consent leaves no persistent artifact unless explicitly recorded, creating verification problems.

**Connection to hapax-council:** The voice daemon already has speaker identification capabilities. Voice consent is a valid channel *only* when: (a) the guest initiates or responds to a clear prompt, (b) the system can verify speaker identity, (c) the consent utterance is logged as an auditable artifact. The ambient listening paradox is addressed by `it-environmental-001` (T2) — transient perception without persistence is permitted — but the system must not use the pre-consent audio for anything other than detecting the consent utterance itself.

Sources:
- [Legal Obligation and Ethical Best Practice: Towards Meaningful Verbal Consent for Voice Assistants (CHI 2023)](https://dl.acm.org/doi/10.1145/3544548.3580967)
- [Owning and Sharing: Privacy Perceptions of Smart Speaker Users (ACM PACM HCI 2021)](https://dl.acm.org/doi/10.1145/3449119)

### 1.6 Implicit vs. Explicit Consent Signals

The Privacy Patterns catalog defines two relevant patterns:

**Ambient Notice**: Unobtrusive but visible notification while sensors are in use, without interrupting activity flow. Examples include macOS compass arrow for location services, Chrome crosshair for geolocation. The notification should be interactive, allowing real-time adjustment.

**Informed Implicit Consent**: When explicit consent is infeasible for routine services, provide transparent notification before processing occurs. The user implicitly consents by continuing to use the service after being informed.

Legal validity of implicit consent varies by jurisdiction. Under GDPR, implied consent generally does not meet the "clear affirmative action" standard for sensitive data processing. Under HIPAA, implicit consent is permissible for certain treatment uses. The key variable is **the sensitivity of the data being collected.**

For ambient audio/video in a personal space: the data is potentially biometric (voice, face), which is a special category under GDPR requiring *explicit* consent. Continued presence after notification would not suffice as a legal basis in the EU. However, the hapax system's own axioms are *stricter* than GDPR — `it-consent-002` explicitly states that "implied consent, assumed consent, or operator-only consent is insufficient."

**Connection to hapax-council:** The system's own constitutive rules already reject implied consent. This is a deliberate design choice, not a regulatory requirement (the system is personal, not commercial, and may not be subject to GDPR). The `it-consent-002` implication eliminates continued presence, body language, or silence as valid consent signals. Only explicit opt-in counts. This simplifies the channel selection problem: only channels that can carry explicit affirmative action are valid.

Sources:
- [Ambient Notice (Privacy Patterns)](https://privacypatterns.org/patterns/Ambient-notice)
- [Informed Implicit Consent (Privacy Patterns)](https://privacypatterns.org/patterns/Informed-Implicit-Consent)
- [Appropriate Privacy Feedback (Privacy Patterns)](https://privacypatterns.org/patterns/Appropriate-Privacy-Feedback)

---

## 2. Formal Models and Their Relevance

### 2.1 Mechanism Design and Truthful Revelation

Consent channel selection is a mechanism design problem in a specific sense: the system (mechanism designer) must design a protocol where the guest (agent) reveals their true preference about data collection. The revelation principle states that if any mechanism can achieve truthful revelation, an incentive-compatible direct mechanism can too.

Applied to consent: the system should make truthful revelation of preference (consent or refusal) the dominant strategy. This means:
- **No penalty for refusal**: The guest's experience should not degrade (beyond the curtailment of data collection, which is the direct consequence of refusal, not a penalty).
- **No reward for consent**: The guest should not receive better treatment for consenting.
- **Truthful channels only**: Channels where social pressure or confusion could distort the guest's true preference are *not* incentive-compatible.

This rules out verbal consent in front of the operator as the sole channel (social pressure distorts truthful revelation). It supports private, asynchronous channels (phone-based QR code) as more incentive-compatible because they remove the social audience.

**Connection to hapax-council:** The existing Principal model distinguishes sovereign (human) and bound (software) principals. The guest is a sovereign principal with full authority over their own consent. The system is a bound principal acting under delegated authority from the operator. The mechanism design framing adds: the system must design the consent interaction such that the guest has a dominant strategy of truthful preference revelation. This is a *Governor* concern — the GovernorWrapper should enforce that the offered consent mechanism is incentive-compatible.

### 2.2 Social Choice and Impossibility

Arrow's impossibility theorem shows that no preference aggregation method can simultaneously satisfy unrestricted domain, Pareto efficiency, independence of irrelevant alternatives, and non-dictatorship for three or more options. Does this apply?

Not directly, because consent channel selection is not a social choice problem — there is only one decision-maker (the guest). The system selects which channel to offer, but the guest makes the consent decision alone. However, Arrow's framework highlights a subtlety: if the system aggregates information about the guest (capabilities, context, preferences) to select a channel, the aggregation itself could introduce bias. The system must not "choose for" the guest — it must offer, and the guest must select.

This suggests a **menu** approach rather than a **recommendation** approach: offer all available channels simultaneously and let the guest pick, rather than selecting one channel the system thinks is best. Sen's capability approach is more relevant here than Arrow: the system should maximize the guest's *capability set* (the set of channels they can actually use).

### 2.3 Affordance Theory

Gibson's affordance theory, as adapted by Norman and Gaver for digital systems, provides the right vocabulary. A consent channel is an *affordance* — it affords the guest the ability to consent or refuse. Gaver's taxonomy distinguishes:

- **Perceptible affordance**: The guest can see/hear/feel the consent mechanism and knows what it does. (QR code with label, voice prompt with clear options.)
- **Hidden affordance**: The mechanism exists but is not apparent. (A URL they could navigate to, but nobody told them about it.)
- **False affordance**: Something that looks like a consent mechanism but isn't. (A decorative sign that says "Privacy Respected" but offers no actionable choice.)

The obligation in the core insight maps to: *the system must ensure all consent channels are perceptible affordances, not hidden.* A hidden affordance violates the transparency obligation — the guest cannot use a channel they do not know exists. A false affordance violates `it-consent-002` — it creates the appearance of consent without the substance.

**Connection to hapax-council:** This provides a test criterion for channel sufficiency. For each guest, enumerate the channels. For each channel, classify as perceptible/hidden/false given the guest's capabilities. A channel set is sufficient only if at least one channel is perceptible for every foreseeable guest profile.

### 2.4 Constitutive Rules and Counts-As

Searle's constitutive rules framework, already used in `axioms/constitutive-rules.yaml`, provides the institutional semantics. A consent utterance is a *brute fact* (sound waves, button press, screen tap). It *counts as* consent only within an institutional context that the system defines.

Channel selection is fundamentally a constitutive rules problem: **what counts as giving consent in this context?**

The existing constitutive rules handle data classification (files count as certain types). A new class of constitutive rules would handle consent acts:

```
"Tapping 'Allow' on the QR-linked consent page counts as explicit consent
 in context 'ambient-sensing' for scope ['audio', 'video', 'presence']"

"Saying 'yes, I consent to recording' after the system prompt counts as
 explicit consent in context 'ambient-sensing' for scope ['audio']
 when speaker is identified as the prompted guest"
```

Each consent channel requires its own constitutive rule specifying:
- The brute fact (what the guest physically does)
- The institutional status (what it counts as)
- The context (when it counts)
- The scope (what categories of data it covers)
- Defeating conditions (when it does *not* count — e.g., under duress, from a child without guardian consent)

**Connection to hapax-council:** The constitutive-rules.yaml already contains the pattern. Channel selection would add a new category of constitutive rules for consent acts. The existing `cr-consent-active` rule classifies files; the new rules would classify *actions*.

### 2.5 The DLM and Meta-Consent

The DLM (Myers & Liskov) as implemented in `ConsentLabel` provides join-semilattice information flow control. A key DLM property: declassification requires *consent from all owners.* A single owner cannot arbitrarily declassify shared data.

The consent *about* consent (meta-consent) has a label structure:
- The *availability* of a consent channel is operator-controlled data (the operator configures what channels exist).
- The *use* of a consent channel is guest-controlled data (the guest decides which channel to use).
- The *record* of consent is jointly owned (both operator and guest need access for verification).

This means the consent channel metadata carries its own ConsentLabel:
- Owner: operator (configured the system)
- Readers: {operator, guest}
- The channel description must flow to the guest (the guest must be able to read what they are consenting to via this channel)

If a channel's information cannot flow to the guest (because the guest cannot perceive it), the channel is informationally invalid — it cannot carry informed consent.

**Connection to hapax-council:** This is a natural extension of the existing `Labeled[T]` type. A `ConsentChannel` should be `Labeled[ChannelDescription]` where the label ensures the channel description can flow to the guest. A channel where `label.can_flow_to(guest_context)` returns False is invalid for that guest.

### 2.6 Principal-Agent Theory

In the standard framing, the system is the agent and the operator is the principal. But for consent, the guest is a *second principal* with a limited-scope relationship to the system: they have authority *only* over their own consent, and only within the data categories the system collects.

The information asymmetry runs in an unusual direction: the *system* knows more about what data it collects (full sensor inventory, processing pipeline, storage lifecycle) than the *guest* does. This is the opposite of the typical principal-agent information asymmetry. The system must *reduce* its own information advantage by disclosing fully — which is why channel selection matters. The channel is the disclosure mechanism.

The operator has an additional obligation: not to configure the system such that the guest's information disadvantage increases. This is the anti-fraud claim in the core insight. Deliberately offering only high-friction channels when low-friction ones are available is analogous to the agent exploiting information asymmetry against the principal.

---

## 3. Proposed Formal Model for Channel Selection

### 3.1 Definitions

```
ConsentChannel := (id, modality, preconditions, friction, scope, constitutive_rule)
```

Where:
- `id`: Unique identifier (e.g., `qr-phone`, `voice-prompt`, `web-link`, `nfc-tap`)
- `modality`: Sensory/interaction mode required (visual, auditory, tactile, digital)
- `preconditions`: What the guest needs for this channel to be usable (e.g., "has smartphone", "speaks English", "can see screen", "has NFC-capable device")
- `friction`: Cost function F(guest, context) -> R+ (real positive number)
- `scope`: Data categories this channel can convey consent for
- `constitutive_rule`: The counts-as mapping that makes a brute action on this channel into institutional consent

### 3.2 Guest Capability Profile

```
GuestProfile := (capabilities: set[str], context: ContextState)
```

Where capabilities are drawn from a vocabulary:
- `has_smartphone`, `has_nfc`, `can_see`, `can_hear`, `speaks_english`, `speaks_{lang}`,
  `can_read`, `is_adult`, `has_guardian_present`, `motor_ability_fine`, `motor_ability_coarse`

The system cannot know a guest's full profile in advance. The profile is *partially observable.* The system can detect some capabilities (face detection implies `can_see` is *not* a barrier — but the absence of face detection does not imply blindness). The guest self-selects from the offered menu, which reveals their capabilities implicitly.

### 3.3 Channel Availability Function

```
available(channel, guest) := all(p in channel.preconditions => p in guest.capabilities)
```

A channel is available to a guest if and only if the guest has all required capabilities. When the guest profile is partial, availability is a three-valued logic: Yes, No, Unknown.

### 3.4 Friction Ordering

Friction is a partial order on channels, not a total order, because friction depends on the guest:

```
friction(c1, guest) <= friction(c2, guest) does NOT imply
friction(c1, guest') <= friction(c2, guest')
```

A phone-based QR code has low friction for a smartphone-carrying adult but infinite friction for a child without a phone.

Friction components (additive):
- `F_cognitive`: Information processing required (reading text, understanding legal language)
- `F_motor`: Physical actions required (number of taps, distance to walk to screen)
- `F_social`: Social cost (speaking aloud in front of others, admitting to not wanting to be recorded)
- `F_temporal`: Time required (waiting for a page to load, going through multiple screens)
- `F_prerequisite`: Cost of acquiring prerequisites (downloading an app, creating an account)

For the operator's core insight to hold: **F_prerequisite must be zero for the selected channel.** Any channel that requires the guest to acquire something they don't already have (install an app, create an account) cannot be the "easiest path."

### 3.5 The Channel Selection Rule

Given a guest `g` and context `ctx`:

```
1. Enumerate: C_all = all configured ConsentChannels
2. Filter:    C_available = {c in C_all : available(c, g) != No}
3. Offer:     Present all channels in C_available simultaneously
4. Fallback:  If C_available is empty, the system MUST curtail AND
              surface an operator alert (the channel set is insufficient)
```

The system does NOT select one channel. It offers the menu. The guest self-selects. This avoids the social choice problem (the system doesn't aggregate preferences) and respects the guest's sovereignty as a principal.

However, the **presentation order** matters. The menu should be sorted by estimated friction (lowest first), with the caveat that the estimate is based on incomplete information about the guest. This is where the friction function guides UX without constraining choice.

### 3.6 Sufficiency as Set Cover

The channel sufficiency problem is a set cover problem:

```
Universe U = all foreseeable guest capability profiles
For each channel c, S_c = {profiles for which c is available}
The channel set is sufficient iff Union(S_c for all c) = U
```

This is NP-hard in general but the universe is small enough to enumerate for a home environment. The practical test: for each dimension of human capability variation (vision, hearing, language, motor, age, device ownership), at least one channel must not require that capability.

Minimum coverage requirements:
- At least one channel that does not require vision (for blind guests)
- At least one channel that does not require hearing (for deaf guests)
- At least one channel that does not require a device (for guests without phones)
- At least one channel that does not require English (for non-English speakers)
- At least one channel that does not require literacy (for pre-literate children or illiterate adults)
- At least one channel with zero F_prerequisite (no installation, no account)

### 3.7 The Friction Minimization Obligation

The obligation is not that the system *selects* the minimum-friction channel, but that it:

1. Does not *remove* low-friction channels when they are available
2. Does not *hide* low-friction channels behind high-friction ones
3. Does not *require* a high-friction channel when a low-friction one would suffice
4. Presents channels in ascending friction order

This is weaker than "always use the lowest-friction channel" (which would be paternalistic — the guest might prefer a higher-friction channel that gives them more control). It is a **non-interference** obligation: do not add unnecessary friction.

### 3.8 Placement in the Governance Stack

Channel selection is a **Governor** concern (boundary enforcement), not a **Principal** concern (authority delegation). Rationale:

- The Principal type represents *who has authority.* The guest has authority over their consent regardless of channel.
- The Governor validates *how* authority is exercised. The Governor should verify that the offered channel set meets sufficiency requirements and that no channel introduces incentive-incompatible distortions.
- A new GovernorPolicy: `consent_channel_sufficiency` — checks that the offered channel set covers the detected guest's profile (or at minimum, covers the "unknown profile" case).

The ConsentLabel does carry to the channel: the channel description is `Labeled[ChannelDescription]` and must `can_flow_to` the guest's informational context. But this is a *necessary condition*, not a *sufficient* one — the channel must also be physically usable, not just informationally accessible.

---

## 4. Open Questions Requiring Operator Input

### 4.1 Physical Channel Inventory

What consent channels are physically available in the studio?

Candidates based on hardware inventory:
- **QR code on screen**: Display a QR code linking to a consent page on the guest's phone. Requires: guest has smartphone with camera.
- **Voice prompt**: Voice daemon speaks a consent prompt, guest responds verbally. Requires: guest can hear, can speak, system can identify speaker.
- **NFC tap**: NFC tag near the door that opens a consent page. Requires: guest has NFC-capable phone.
- **Physical sign + verbal confirmation**: A posted sign explains the recording, operator verbally confirms guest has read it. Requires: guest can read, operator is present.
- **Web link (SMS/messaging)**: Operator sends a link to the guest's phone. Requires: operator has guest's number, guest has smartphone.
- **Tactile/physical button**: A dedicated consent button or switch in the space. Requires: motor ability only.

Which of these are you willing to implement? Are there others?

### 4.2 Child and Guardian Protocol

When the guest is a minor:
- Does consent come from the child, the guardian, or both?
- What channels are available for a child who may not have a phone?
- Is there a minimum age below which the system just curtails entirely?

### 4.3 Language Coverage

What languages should the consent information be available in? The studio's social context determines this. At minimum, English. What else?

### 4.4 Retroactive Consent Scope

The studio design (section 6.4, point 6) allows retroactive processing of buffered data when consent is granted after curtailment. Should the retroactive scope be:
- All buffered data from the current session?
- Only data from after the guest was detected?
- Configurable per guest preference?

### 4.5 Consent Scope Granularity

The constitutive rules model suggests each channel conveys consent for specific data categories. Should the guest be able to consent to audio but not video, or is it all-or-nothing? Granular consent is more respectful but higher friction.

### 4.6 The "No Channel Works" Fallback

If no available channel can carry consent for a particular guest (e.g., a non-verbal child without a guardian and without a device), the system must curtail. But should it:
- Curtail silently (risk: guest doesn't know they're being curtailed)?
- Curtail with ambient notice (the Ambient Notice pattern — a light, a sound)?
- Alert the operator to facilitate manually?

### 4.7 Consent Duration and Session Binding

Does consent persist across visits? Options:
- Per-session only (expires when guest leaves, detected by absence)
- Per-contract (persistent until revoked, like the existing ConsentContract model)
- Tiered: first visit is per-session, guest can opt into persistent consent

### 4.8 Integration with Existing ConsentContract

Should channel-mediated consent create a full `ConsentContract` in `axioms/contracts/`, or a lighter-weight record? The existing contract model has parties, scope, direction, visibility_mechanism — all of which apply. The `visibility_mechanism` field could record which channel was used.

---

## 5. Connections to Existing Formalisms (Summary)

| Existing Formalism | Connection to Channel Selection |
|---|---|
| **ConsentLabel (DLM join-semilattice)** | Channel descriptions carry labels; a channel is valid only if its description can flow to the guest |
| **Labeled[T]** | ConsentChannel is Labeled[ChannelDescription]; meta-consent has label structure |
| **GovernorWrapper (AMELI)** | Channel sufficiency is a Governor policy; Governor validates offered channel set |
| **Principal (sovereign/bound)** | Guest is sovereign principal; system is bound; channel selection must not constrain guest's authority |
| **ConsentGatedWriter** | Unchanged — remains the write chokepoint; channels feed into the existing contract → label → gate pipeline |
| **ConsentContract** | Channel-mediated consent produces a ConsentContract with visibility_mechanism recording the channel used |
| **Accommodations** | Extends to guest-facing: channel presentation adapts to detected or declared guest needs |
| **Constitutive rules** | New rule category: consent *acts* (brute action counts-as institutional consent in context) |
| **executive_function axiom** | Friction minimization obligation derives from cognitive load reduction mandate |
| **interpersonal_transparency axiom** | Channel sufficiency is a sufficiency probe for it-consent-001 and it-consent-002 |
| **it-environmental-001 (T2)** | Transient perception (detecting guest presence) is permitted without consent; only persistence requires consent channels |
| **it-consent-002 (T0)** | Eliminates implicit consent channels; only explicit affirmative action channels are valid |

---

## 6. Proposed New Implications

Based on this research, the following implications should be added to the interpersonal_transparency axiom:

### it-access-001 (T0) — Channel Sufficiency

> When the system curtails functionality due to absent consent, it must simultaneously offer the opportunity to grant consent. The offered consent channels must collectively cover all foreseeable guest capability profiles (vision, hearing, language, motor, device, age). No single missing capability may render consent impossible.

Already drafted in studio design section 6.4; this research refines the coverage requirement.

### it-access-002 (T1) — Friction Symmetry

> The UX cost of granting consent and refusing consent must be identical for every offered channel. The system must not present, order, or design consent channels such that granting is easier than refusing or vice versa.

### it-access-003 (T1) — Friction Minimization

> The system must not offer only high-friction consent channels when lower-friction channels are available and functional. Channels must be presented in order of ascending estimated friction for the detected guest context.

### it-access-004 (T2) — Channel Audit

> Each consent act must record which channel was used, what information was presented, and the timestamp. The channel record is part of the consent contract's audit trail.

### it-access-005 (T1) — Incentive Compatibility

> Consent channels must be designed such that truthful revelation of the guest's preference (consent or refusal) is the dominant strategy. Channels that introduce social pressure, confusion, or time pressure beyond what is inherent in the consent decision itself are not valid.
