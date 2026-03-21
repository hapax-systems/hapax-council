# Privacy-Aware Voice UX Patterns: Graceful Degradation When Consent Is Missing

**Date:** 2026-03-15
**Status:** Research complete
**Scope:** Concrete UX patterns for a voice assistant that must degrade gracefully when person-adjacent data lacks consent
**Context:** hapax-council consent infrastructure (ConsentStateTracker, ConsentSession, ConsentGatedWriter), voice daemon tools (search_documents, get_calendar_today, search_emails)

---

## 0. The Design Tension

The system has two competing obligations:

1. **Executive function axiom** (weight 95): Maximize utility for the operator. The assistant should feel responsive, capable, knowledgeable.
2. **Interpersonal transparency axiom** (weight 88): Never disclose or process person-adjacent data without that person's consent.

When search results, calendar events, or emails contain information about non-consented persons, the system must serve obligation 2 without destroying obligation 1. The goal is a voice assistant that feels like a **thoughtful friend who knows when to be discreet** — not a bureaucratic gatekeeper.

---

## 1. How Existing Assistants Handle Multi-Person Privacy

### 1.1 Apple HomePod / Siri

Siri on HomePod recognizes up to six household voices. Personal results (calendar, messages, reminders) are gated by voice recognition:
- **Recognized voice** → full personal results
- **Unrecognized voice** → non-personal responses only (general knowledge, music, timers)
- No consent prompt — unrecognized users simply get degraded service silently

The on-device processing model means Siri's voice trigger system uses speaker recognition to avoid waking for non-owners, reducing accidental disclosure. But there is no consent flow for visitors — the only mechanism is the binary recognized/not-recognized gate.

**What to steal:** The silent degradation for unrecognized voices is the right instinct. The user never hears "ACCESS DENIED." They just get less.

**What to reject:** No consent offering at all. Siri treats visitors as second-class citizens permanently.

### 1.2 Amazon Alexa

Alexa's Voice ID identifies up to six household profiles. For personalized results, voice recognition must match. For multi-person environments:
- Non-profiled users get shared household results (shared calendar, shared lists)
- Alexa Smart Properties (hospitality) uses a "forget me" wake phrase: "Alexa, delete everything I said today"
- Amazon introduced voice-forward consent (VFC) in 2022 for skill-level permissions — users can grant data access to a specific skill mid-conversation

**What to steal:** The VFC pattern — asking for specific scope mid-conversation rather than an all-or-nothing gate. Also the "forget me" self-service deletion pattern.

**What to reject:** VFC research found that just-in-time voice consent can undermine informed consent principles because users feel pressured to agree quickly to resume their task.

### 1.3 Google Home / Assistant

Google's approach differentiates by "personal results" as a toggleable category:
- Personal results include calendar, contacts, and emails
- The operator can enable/disable personal results per device
- Voice Match identifies household members; unrecognized voices cannot access personal results
- Guest Mode (introduced 2021) pauses saving interactions, doesn't link activity to accounts

**What to steal:** The "Guest Mode" concept — a named, understandable degraded state rather than silent reduction. And the per-category toggle (personal results vs. general).

**What to reject:** Guest Mode is operator-initiated (you say "turn on guest mode"), not system-detected. It requires the operator to anticipate when guests arrive.

### 1.4 Synthesis: What None of Them Do

No major assistant:
- Detects non-household presence and automatically adjusts
- Offers consent to a visitor mid-session
- Distinguishes between mentioning a person and disclosing information about them
- Provides consent-aware filtering of search/retrieval results
- Supports gradual consent (consent to calendar names but not email content)

This is the gap hapax-council can fill.

---

## 2. Abstraction Levels for Person-Adjacent Data

### 2.1 The Abstraction Ladder

Five levels of increasing disclosure, each adding person-adjacent information:

| Level | Calendar Example | Email Example | Search Example |
|-------|-----------------|---------------|----------------|
| **L0: Existence only** | "You have 3 meetings today" | "You have 12 unread emails" | "I found 4 relevant results" |
| **L1: Temporal/structural** | "You have a meeting at 2pm, 60 minutes" | "You got an email 20 minutes ago about the budget" | "I found results from your calendar and email" |
| **L2: Role/category** | "You have a meeting at 2pm with your design team" | "You got an email from someone on your team about the budget" | "Results mention team members and project context" |
| **L3: Consented names** | "You have a meeting at 2pm with Alice (consented) and 2 others" | "Email from Alice about the budget, mentions 2 other people" | "Results include context from Alice (consented) and redacted persons" |
| **L4: Full disclosure** | "Meeting at 2pm with Alice, Bob, and Carol" | "Email from Alice, Bob cc'd, about Carol's budget proposal" | Full search results with all names |

### 2.2 Which Level Preserves the Most Utility?

**L2 (role/category abstraction) is the sweet spot for most scenarios.** Here's why:

- **L0 is too abstract for executive function.** "You have 3 meetings" doesn't help the operator plan their day. They need time, duration, and context.
- **L1 is functional but stripped.** Time-only calendar readouts are useful but miss the social context that helps the operator prepare ("your 1:1" vs "the all-hands" changes how you prepare).
- **L2 preserves social context without naming individuals.** "Your design team meeting at 2pm" tells the operator what to prepare for. "An email from your manager about Q2 planning" provides enough context to prioritize.
- **L3 adds precision for consented persons only.** Useful when the operator has some consented relationships (e.g., spouse) and wants full detail for those.
- **L4 requires universal consent** — everyone mentioned has a contract.

### 2.3 The Role Abstraction Strategy

The system needs a mapping from person identity to role/category. Sources:

1. **Calendar metadata**: Google Calendar includes `organizer`, `attendee` fields. The meeting title often encodes the group ("Design Sync", "1:1 with...").
2. **Email headers**: `From`, `To`, `Cc` fields plus contact group membership.
3. **Contact groups**: Google Contacts supports labels/groups — "Team", "Family", "External".
4. **Frequency**: Contacts that appear often in calendar/email can be categorized by interaction pattern without naming them.

The role mapping itself is operator-only data (what groups people belong to) and does not require consent from the persons being categorized — it's the operator's own organizational schema. Only the *disclosure* of names to the operator (or others) via voice requires consent.

### 2.4 Concrete Implementation: Abstraction Functions

```
def abstract_attendees(attendees: list[Attendee], consent_registry) -> str:
    """Convert attendee list to consent-aware description."""
    consented = [a for a in attendees if consent_registry.has_active(a.email)]
    unconsented_count = len(attendees) - len(consented)

    if not attendees:
        return ""
    if all consented:
        return f"with {', '.join(a.display_name for a in consented)}"
    if consented and unconsented_count:
        names = ', '.join(a.display_name for a in consented)
        return f"with {names} and {unconsented_count} other{'s' if unconsented_count > 1 else ''}"
    # No one consented — use role abstraction
    return abstract_by_role(attendees)

def abstract_by_role(attendees: list[Attendee]) -> str:
    """Fall back to role/team when no names are available."""
    # Check if all attendees share a group
    groups = get_shared_groups(attendees)
    if groups:
        return f"with your {groups[0].lower()}"
    if len(attendees) == 1:
        return "with 1 other person"
    return f"with {len(attendees)} people"
```

### 2.5 The "Mention vs. About" Distinction

Critical semantic distinction for search results:

- **Mentioning someone exists**: "Your meeting includes other attendees" — acknowledges their presence without identifying them. This is **metadata about the operator's schedule**, not data about the other person.
- **Revealing information about them**: "Alice said she disagrees with the proposal" — this is Alice's opinion, behavior, or state. This requires Alice's consent.

The line: **structural facts about the operator's data (who is involved) are operator data. Behavioral, opinion, or state facts about other people are person-adjacent data.**

This maps to the existing DLM label semantics: the owner of "the operator has a meeting" is the operator. The owner of "Alice said X in that meeting" is Alice.

---

## 3. Contextual Consent Prompting Patterns

### 3.1 The Discretion Prompt

Instead of blocking, offer a choice:

> "I found what you're looking for, but some of it involves people who haven't agreed to be part of this system. Want me to give you the parts that are just about your schedule and skip the personal details?"

This pattern:
- Acknowledges the result exists (preserving executive function)
- Explains *why* it's being filtered (transparency, not mystery)
- Offers a specific alternative (filtered read, not total denial)
- Uses natural language ("haven't agreed" not "lack consent contracts")

### 3.2 The Gradual Reveal

For calendar events:

1. First pass (always): "You have a design review at 2pm, about an hour."
2. If asked "who's in it?": "There are 4 attendees. I can name the ones who are in the system — that's Alice. The others, I'd need to keep general."
3. If pressed: "I want to be careful here. Three of the attendees aren't in my consent records. I can tell you it's your usual design team, but I'll hold back specific names."

This mirrors how a thoughtful human assistant would handle it — give what you can, explain the boundary, offer alternatives.

### 3.3 Mid-Conversation Consent Initiation

When the operator asks about someone specific who lacks consent:

> **Operator**: "What did Sarah say in that email?"
> **System**: "Sarah doesn't have a consent contract with the system. I can see there's an email from her, but I can't read you the content. Would you like me to start a consent process for her? I could send her a link, or you could introduce the idea next time she's here."

This pattern:
- Confirms the data exists (the email is there)
- Explains the specific block (Sarah's consent status)
- Offers concrete next steps (send link, wait for visit)
- Does NOT read the email content even to "summarize" it

### 3.4 The Operator-as-Intermediary Pattern

For cases where the system holds information it cannot disclose:

> "I have search results that are relevant, but they're interleaved with information about people outside the consent system. I can give you the parts that are purely about your work — project status, dates, your own notes. For the people parts, you already have access to the source material directly if you want to check."

This reminds the operator that they can access their own email/calendar directly — the system isn't hiding the data, it's just declining to be the delivery mechanism for person-adjacent data without consent.

### 3.5 Patterns to Avoid

**The compliance checkbox**: "I am unable to disclose this information due to consent policy violation. Please obtain consent contract ID for person 'sarah' and retry." — This is a system error message, not a conversation.

**The apologetic loop**: "I'm sorry, I can't... I'm really sorry, but I'm not able to... I apologize for the inconvenience..." — Excessive apology signals the system is broken, not careful.

**The unexplained gap**: Silently omitting information without acknowledgment. If the operator asks "read me my emails" and three of five are redacted, they need to know *why* they only heard two.

**The over-explanation**: "Per section 4.2 of the interpersonal transparency axiom, implication it-consent-002 at severity tier T0..." — Nobody wants to hear the axiom numbering system.

---

## 4. The Detection Paradox in Retrieval

### 4.1 The Three Layers of Processing

When a search query returns results that might contain person-adjacent data, there are three distinct processing layers:

| Layer | Operation | Example | Consent Required? |
|-------|-----------|---------|-------------------|
| **Detection** | System identifies that a result contains person references | NER detects "Alice" in result text | No — this is metadata about the result, not disclosure |
| **Disclosure** | System reveals to the operator that a specific person is mentioned | "This result mentions Alice" | Depends — see 4.2 |
| **Reasoning** | System draws conclusions about the person from result content | "Alice seems frustrated based on this email" | Yes — absolutely |

### 4.2 The Detection Layer Is Not Disclosure

The system MUST be able to detect person-adjacent data to enforce consent. This is the same principle as `it-environmental-001` (T2): transient perception without persistence is permitted for governance enforcement.

Concretely: running NER on a search result to tag it as "contains person references" is a **governance operation**, not a data processing operation. The result of NER (entity labels) is consent-system metadata, not operator-facing disclosure. The system needs this to decide what to filter.

This resolves the detection paradox: **the system processes results at the detection layer to decide what to show at the disclosure layer.** The detection layer is infrastructure; the disclosure layer is where consent gates apply.

### 4.3 When Does Detection Become Disclosure?

Detection becomes disclosure when:
1. The system tells the operator *which specific person* is mentioned: "This result mentions Alice" — this is disclosure of Alice's association with the content.
2. The system tells the operator *what the person did/said/felt*: "Alice wrote that she disagrees" — this is disclosure of Alice's behavior.
3. The system uses the person's data to shape its reasoning: "Based on Alice's emails, your project is at risk" — this is processing.

Detection does NOT become disclosure when:
1. The system says "this result contains references to people without consent contracts" — no specific person is named.
2. The system says "I found 3 results but 2 contain person-adjacent data" — count without identity.
3. The system internally tags a result as containing person-X data but reports only "filtered" to the operator.

### 4.4 The Naming Threshold

There is a meaningful difference between:
- "Your 2pm meeting has attendees who aren't in the consent system" — no disclosure
- "Your 2pm meeting includes Sarah, who isn't in the consent system" — disclosure of Sarah's association with the meeting

The second case reveals that Sarah is in the operator's calendar at that time. Is this person-adjacent data about Sarah?

**Analysis**: The meeting is the *operator's* data. Sarah's presence on the operator's calendar is a fact about the operator's schedule, not about Sarah. However, the system *naming* Sarah while also saying she lacks consent creates an odd disclosure: it reveals her name specifically in the context of saying it shouldn't reveal things about her.

**Proposed rule**: The system may name a person in the context of explaining their consent status ONLY if the operator directly asks about that person. If the operator says "tell me about my 2pm meeting," the system should say "4 attendees, 3 without consent" rather than listing names with consent flags.

If the operator says "is Sarah in my 2pm meeting?" — they already know Sarah exists and are asking about their own schedule. Confirming "yes, she's on the invite list" is operator data. But "yes, and she marked herself as tentative" is Sarah's behavioral data and requires consent.

### 4.5 Implementation: The Privacy Filter Pipeline

```
Query → Retrieval → NER Detection → Consent Check → Abstraction → Disclosure

1. RETRIEVAL: Standard Qdrant/API query, returns raw results
2. NER DETECTION: Scan results for person entities (names, emails, roles)
   - Output: result + set of detected person references
   - This is a governance operation, not stored or disclosed
3. CONSENT CHECK: For each detected person, check ConsentRegistry
   - Partition into: consented_persons, unconsented_persons
4. ABSTRACTION: Apply the appropriate abstraction level
   - Consented persons: L4 (full names)
   - Unconsented persons: L2 (role/category) or L0 (count only)
   - Mixed: L3 (consented names + count of others)
5. DISCLOSURE: Deliver the abstracted result via voice
```

### 4.6 NER Limitations and Safety Margins

NER is not perfect. Research shows that NER-based anonymization "fails to provide any kind of privacy guarantee" because masking only predefined entity types does not sufficiently reduce re-identification risk. A result might say "the person you met at the coffee shop last Tuesday" — no named entity, but clearly person-adjacent.

**Safety margin**: When the system is uncertain whether content is person-adjacent, err toward abstraction. The executive function cost of over-filtering is lower than the transparency axiom cost of under-filtering. A false positive (filtering non-person data) wastes a few seconds of the operator's time. A false negative (disclosing person-adjacent data) violates a T0 axiom.

**Practical approach**: Use NER as the first pass, but also flag results that contain second-person pronouns in quoted speech ("he said", "she thinks"), emotional/opinion language attributed to others, or behavioral descriptions ("Alice always...", "Bob tends to...").

---

## 5. Privacy Design Strategies Applied to Voice

### 5.1 The Eight Strategies (Hoepman Framework)

The established privacy design strategies, adapted for voice retrieval:

| Strategy | Voice Application |
|----------|-------------------|
| **Minimize** | Return fewer results; prefer results without person-adjacent data |
| **Separate** | Process person detection and content delivery in separate pipeline stages |
| **Abstract** | Use role/category labels instead of names (the abstraction ladder) |
| **Hide** | Redact person names from voice output; replace with pronouns or roles |
| **Inform** | Tell the operator when and why information is being withheld |
| **Control** | Let the operator adjust abstraction level; let them initiate consent flows |
| **Enforce** | ConsentGatedWriter blocks persistence; voice filter blocks disclosure |
| **Demonstrate** | Audit trail of what was filtered, why, and what consent state applied |

### 5.2 Graceful Degradation as a Design Pattern

Drawing from the Springer design patterns for graceful degradation: the system should degrade along a **defined feature ladder**, not collapse from "full" to "broken."

The degradation levels for the voice assistant:

| State | Available Features | Unavailable Features | User Experience |
|-------|-------------------|---------------------|-----------------|
| **Full** (operator alone, or all guests consented) | All tools, full names, full content | None | Normal assistant |
| **Partial** (some guests unconsented) | Tools with abstracted output, consented names, structural data | Person-adjacent content for unconsented persons | "I can give you the schedule but I'll keep some names general" |
| **Curtailed** (guest detected, consent pending) | General knowledge, timers, music, weather. No personal data retrieval | All personal data tools | "I'm in guest mode right now — I can help with general things" |
| **Minimal** (consent refused, guest present) | Same as curtailed + awareness that curtailment is active | Same as curtailed | "While you have company, I'll stick to general topics" |

The key insight: **degradation should affect the content of responses, not the availability of the assistant.** The assistant should always respond — just with varying levels of detail.

### 5.3 Contextual Integrity Applied (Nissenbaum Framework)

Helen Nissenbaum's contextual integrity theory provides the normative framework. Privacy is maintained when information flows conform to contextual norms. The five parameters:

1. **Data subject**: The person the information is about
2. **Sender**: Who is transmitting (the voice assistant)
3. **Recipient**: Who receives (the operator, and anyone in earshot)
4. **Information type**: What kind of information (schedule, opinion, behavioral fact)
5. **Transmission principle**: Under what conditions (with consent, in confidence, publicly)

The critical parameter for hapax-council is **recipient**. When the operator is alone, the recipient is just the operator. When a guest is present, the recipient includes the guest — and the guest may overhear information about third parties who have no relationship with the guest at all.

This means consent requirements escalate in shared spaces:
- Operator alone: consent needed from persons mentioned in results
- Guest present: consent needed from persons mentioned AND consideration of whether the guest should hear it
- The presence of unconsented Guest A may also block disclosure about consented Person B, because Guest A would overhear it

**This is a non-obvious escalation.** The system needs to model not just "does Alice consent to the system processing her data" but "does Alice consent to her data being spoken aloud in front of Guest X."

### 5.4 The Overhearing Problem

Voice output is inherently broadcast in the physical space. This creates a unique constraint that text-based systems don't face:

- A phone screen only shows to the person holding it
- A voice assistant speaks to everyone in the room

This means the consent check must consider not just the data subject's consent, but the audience. If Alice has a consent contract and Bob (unconsented guest) is in the room, should the system speak Alice's name in a calendar event?

**Proposed resolution**: When a guest is present (consent state is GUEST_DETECTED, CONSENT_PENDING, or CONSENT_REFUSED), the system treats voice output as **public within the room** and applies the strictest applicable consent level. This means:
- Even consented persons' data may be abstracted if speaking it aloud would reveal it to unconsented listeners
- The operator can access full detail via a private channel (phone screen, text interface) if needed
- The voice assistant should suggest this: "I have the details — want me to send them to your phone instead?"

---

## 6. Concrete Voice Interaction Patterns

### 6.1 Pattern: The Discreet Calendar Briefing

**Scenario**: Operator asks "what's on my calendar today?" while a guest is present.

**Full mode** (operator alone):
> "You have three meetings today. First up, design review at 10am with Alice and Bob, about the dashboard redesign. Then your 1:1 with Sarah at 1pm. And the all-hands at 3pm — Carol is presenting the Q2 numbers."

**Partial mode** (guest present, consent state CONSENT_GRANTED):
> "You have three meetings today. Design review at 10, about an hour. Your 1:1 at 1pm. And the all-hands at 3. Want me to text you the details?"

**Curtailed mode** (guest present, consent PENDING or REFUSED):
> "You have three meetings today — at 10, 1, and 3. I can give you more detail once it's just us, or I can send it to your phone."

### 6.2 Pattern: The Filtered Search Result

**Scenario**: Operator asks "what did I talk about in yesterday's meetings?"

**Full mode**:
> "In your design review, Alice proposed moving the deadline to March 20th and Bob raised concerns about the API. In your 1:1, Sarah mentioned she's considering the team lead role. The all-hands covered Q2 targets."

**Partial mode** (some names consented):
> "In your design review, the team discussed moving the deadline and there were some API concerns. In your afternoon 1:1, you covered a career development topic. The all-hands was about Q2 targets. There's more detail I'm holding back because some of the people involved aren't in the consent system — want me to send it to your phone?"

### 6.3 Pattern: The Consent Initiation Offer

**Scenario**: Operator asks about a specific person who lacks consent.

> **Operator**: "What's the latest from Sarah?"
> **System**: "I can see emails and calendar events involving Sarah, but she's not in the consent system so I can't read you the details. I can tell you there are 3 recent emails and she's in your 1pm meeting today. Want me to set up a consent link for her?"
> **Operator**: "Yeah, do that."
> **System**: "I'll queue a consent page for Sarah. You can share the link with her, or the system will offer it next time she's here in person."

### 6.4 Pattern: The Ambient Downshift

**Scenario**: The system detects a guest mid-conversation.

> **System** (was mid-briefing): "...and your 3pm is the all-hands about — actually, I notice someone else just came in. I'll keep things general until we sort that out."
> (ConsentStateTracker transitions to GUEST_DETECTED)
> (After debounce, if consent offering triggers):
> **System**: "Hey, welcome. I'm the operator's voice assistant, and the room has microphones and cameras. I won't record anything about you unless you're okay with it — want me to explain what that means, or are you good with it?"

### 6.5 Pattern: The Proactive Privacy Bookmark

When the system is in partial mode and the guest leaves:

> (ConsentStateTracker transitions to NO_GUEST after absence_clear_s)
> **System**: "Looks like it's just us again. I had some things I was holding back earlier — your 1:1 with Sarah was about the team lead role, and Bob's API concerns from the design review looked pretty serious. Want me to catch you up on what I skipped?"

This is the "thoughtful friend" pattern — they remember what they couldn't say in front of others and circle back when it's safe.

---

## 7. The Privacy Filter Pipeline — Technical Architecture

### 7.1 Where It Fits

The privacy filter sits between tool execution and voice output, wrapping existing tool handlers:

```
Operator query
  → LLM selects tool (search_documents, get_calendar_today, etc.)
  → Tool handler executes (unchanged — full results from Qdrant/API)
  → Privacy Filter (NEW)
    → NER detection on result text
    → Consent check per detected entity
    → Abstraction based on consent state and audience
  → Filtered result → LLM → Voice output
```

### 7.2 The Filter Must Be Pre-LLM, Not Post-LLM

Critical architecture decision: the privacy filter must run BEFORE the result reaches the LLM, not after.

Why: If unfiltered results go to the LLM, the LLM has already "seen" the person-adjacent data and may incorporate it into its reasoning, even if instructed not to disclose it. LLM instruction-following is not a reliable privacy mechanism.

The filter must intercept the raw tool result, redact/abstract it, and pass only the filtered version to the LLM. The LLM never sees the unredacted data. This is defense in depth — the LLM cannot leak what it never received.

### 7.3 Filter Components

1. **PersonEntityDetector**: NER-based scan of result text. Uses spaCy or a lightweight model to identify PERSON entities, email addresses, and phone numbers. Maintains a local cache of detected entities per session.

2. **ConsentResolver**: Maps detected entities to consent status. Uses ConsentRegistry.get_contract_for() for known persons, defaults to "unconsented" for unknown entities.

3. **AudienceAnalyzer**: Checks current ConsentStateTracker phase to determine if the physical audience includes unconsented listeners.

4. **AbstractionEngine**: Applies the appropriate abstraction level based on consent status and audience. Uses the abstraction ladder (L0-L4) and role mapping.

5. **FilterAuditLog**: Records what was filtered, why, and what the operator received. This is the "demonstrate" strategy — the system can prove it applied its policies.

### 7.4 Integration Point: Existing Tool Handlers

The existing `handle_search_documents`, `handle_get_calendar_today`, and `handle_search_emails` in `agents/hapax_voice/tools.py` currently return raw results to the LLM via `params.result_callback`. The privacy filter wraps `result_callback`:

```python
# Conceptual — actual implementation would be a decorator or middleware
original_callback = params.result_callback

async def filtered_callback(result):
    filtered = await privacy_filter.filter(result, consent_registry, audience_state)
    await original_callback(filtered)

params.result_callback = filtered_callback
```

This means existing tool handlers need zero changes. The filter is purely additive.

---

## 8. Open Design Questions

### 8.1 Should the LLM Know WHY Something Was Filtered?

Two options:
- **Option A**: Pass filtered text only. The LLM sees "[3 attendees, names withheld]" and reads it verbatim.
- **Option B**: Pass filtered text plus a metadata note: "[3 attendees, names withheld — 2 lack consent contracts, 1 consented but guest present in room]". The LLM can then explain *why* it's being general.

Option B produces more natural conversation but gives the LLM information about consent states that it might inadvertently disclose ("I can't say their names because they haven't consented" reveals that the system has consent tracking, which might confuse or alarm a guest).

**Recommendation**: Option A for guest-present scenarios. Option B for operator-alone scenarios where the operator might want to know why detail is missing.

### 8.2 Should the Operator Be Able to Override?

Can the operator say "just tell me, I don't care about consent right now"?

The interpersonal transparency axiom at T0 says no — `it-consent-002` explicitly states implied consent is insufficient, and operator override would bypass the other person's consent entirely. The system should explain this once if asked, then not repeat itself:

> "I hear you, but this is one of those things I can't budge on. The whole point of the consent system is that it applies even when it's inconvenient. You can always check your email or calendar directly — I'm just not the right channel for it right now."

### 8.3 What About Data the Operator Created About Others?

If the operator writes a note that says "Sarah mentioned she's unhappy with the project direction" — is that the operator's data or Sarah's?

**Analysis**: The note is the operator's creation (operator is the author). The *content* contains person-adjacent information about Sarah (her opinion). The DLM label should be: owner=operator, but with a taint that requires Sarah's consent for automated processing/disclosure.

Practically: the operator can read their own notes. The system should not proactively surface or analyze notes containing person-adjacent data without consent. If the operator asks "what are my notes about the project?", the system can return the note with Sarah's name abstracted.

### 8.4 Retroactive Consent and Historical Data

If Sarah grants consent today, does the system retroactively un-filter past interactions that mentioned her? The existing `process_curtailed_segments` function handles retroactive audio processing. The same pattern should apply to retrieval: once consent is granted, the privacy filter updates its cache and future queries return full results.

But should the system proactively re-deliver previously filtered information? ("By the way, now that Sarah's in the system, here's what I was holding back from yesterday's meeting briefing.") This would be useful but potentially surprising. Recommend making it opt-in: the operator can ask "anything you were holding back about Sarah?" and the system can answer.

---

## 9. Summary of Recommended Patterns

| Pattern | When to Use | Voice Example |
|---------|------------|---------------|
| **Abstraction Ladder** | Any retrieval with mixed consent | "Meeting at 2pm with your design team" instead of names |
| **Discretion Prompt** | Search returns mixed results | "I found results but some mention unconsented people. Want the non-personal parts?" |
| **Gradual Reveal** | Operator asks follow-up questions | Start with L2, offer L3/L4 as they ask more |
| **Ambient Downshift** | Guest detected mid-conversation | "I'll keep things general — someone just came in" |
| **Privacy Bookmark** | Guest leaves after curtailment | "Now that it's just us, here's what I was holding back" |
| **Channel Redirect** | Complex data in guest-present mode | "Want me to send the details to your phone instead?" |
| **Consent Initiation** | Operator asks about unconsented person | "Sarah's not in the consent system. Want me to set that up?" |
| **Existence Confirmation** | Operator needs to know IF data exists | "There are 3 emails from her, but I can't read them to you yet" |

---

## Sources

### Industry Implementations
- [Apple HomePod Multi-User Voice Recognition](https://www.gearbrain.com/siri-homepod-user-voice-recognition-2647697459.html)
- [Apple Siri Privacy Policy](https://www.apple.com/legal/privacy/data/en/ask-siri-dictation/)
- [Apple Voice Trigger System](https://machinelearning.apple.com/research/voice-trigger)
- [Siri Privacy and Voice Recognition](https://applemagazine.com/siri-privacy/)
- [Google Dialogflow Voice Agent Design Best Practices](https://docs.cloud.google.com/dialogflow/cx/docs/concept/voice-agent-design)
- [Voice User Interface Design Principles (2026)](https://www.parallelhq.com/blog/voice-user-interface-vui-design-principles)

### Academic Research
- [Privacy Work, Contextual Integrity, and Smart Speaker Assistants (2023)](https://www.tandfonline.com/doi/full/10.1080/1369118X.2023.2193241)
- [Privacy and Smart Speakers: A Multi-Dimensional Approach (2021)](https://www.tandfonline.com/doi/full/10.1080/01972243.2021.1897914)
- [Owning and Sharing: Privacy Perceptions of Smart Speaker Users (ACM 2021)](https://dl.acm.org/doi/10.1145/3449119)
- [Understanding Users' Relationship with Voice Assistants and Privacy](https://link.springer.com/chapter/10.1007/978-3-030-50309-3_25)
- [Verbal Consent for Voice Assistants (CHI 2023 Workshop)](https://secure-ai-assistants.github.io/publications/chiworkshop/)
- [Nissenbaum: Privacy as Contextual Integrity (Stanford)](https://crypto.stanford.edu/portia/papers/RevnissenbaumDTP31.pdf)
- [Conference Talk: Nissenbaum on Privacy, Contextual Integrity, and Obfuscation](https://openmined.org/blog/conference-talk-summary-helen-nissenbaum-privacy-contextual-integrity-and-obfuscation/)

### Privacy Design Patterns
- [Privacy Design Strategies (Radboud University)](https://wiki.privacy.cs.ru.nl/Privacy_design_strategies)
- [Critical Analysis of Privacy Design Strategies (ResearchGate)](https://www.researchgate.net/publication/305870977_A_Critical_Analysis_of_Privacy_Design_Strategies)
- [Design Patterns for Graceful Degradation (Springer)](https://link.springer.com/chapter/10.1007/978-3-642-10832-7_3)
- [Framework to Balance Privacy and Data Usability Using Data Degradation (IEEE)](https://ieeexplore.ieee.org/document/5283392)
- [Ambient Notice (Privacy Patterns)](https://privacypatterns.org/patterns/Ambient-notice)

### NER and Privacy-Preserving Information Retrieval
- [AI Meets Anonymity: NER for Privacy (WJARR 2024)](https://wjarr.com/sites/default/files/WJARR-2024-1270.pdf)
- [Anonymization of Unstructured Data via NER (Springer 2018)](https://link.springer.com/chapter/10.1007/978-3-030-00202-2_24)
- [PBa-LLM: Privacy and Bias-aware NLP using NER (arXiv 2025)](https://arxiv.org/html/2507.02966v2)

### Smart Home and Multi-User Design
- [Beyond the Primary User: Smart Home User Types (NN/Group)](https://www.nngroup.com/articles/smart-home-users/)
- [Permission Request Design (NN/Group)](https://www.nngroup.com/articles/permission-requests/)
- [Security and Privacy Problems in Voice Assistant Applications (ScienceDirect 2023)](https://www.sciencedirect.com/science/article/pii/S0167404823003589)

### Regulatory and Compliance
- [EDPB Guidelines 05/2020 on Consent](https://www.edpb.europa.eu/sites/default/files/files/file1/edpb_guidelines_202005_consent_en.pdf)
- [GDPR Compliance Guide 2026](https://secureprivacy.ai/blog/gdpr-compliance-2026)
- [FTC Guide to Voice Assistant Privacy](https://consumer.ftc.gov/articles/how-secure-your-voice-assistant-protect-your-privacy)
