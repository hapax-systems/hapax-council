"""Render the comprehensive narrated Hapax/Logos demo for operator's brother.

Usage: uv run python scripts/render_brother_demo.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from agents.demo_pipeline.timeline import NarratedDemoScript, NarrationScene, render_narrated_demo

# fmt: off
SCRIPT = NarratedDemoScript(
    title="Hapax",
    subtitle="Externalized Executive Function",
    intro_narration=(
        "This is Hapax. It is a personal computing system built by one person, for one person. "
        "Before anything else, there is something that needs to be said about consent. "
        "This system processes data about its operator continuously. Cameras, microphones, biometric sensors, calendars, messages. "
        "That processing is governed by a constitutional axiom called interpersonal transparency. "
        "The rule is absolute: no persistent data about any non-operator person may exist in this system without an active, explicit, revocable consent contract. "
        "If you are detected by the cameras right now, the system knows a person is present. "
        "But it stores nothing about you. No face embeddings. No voice prints. No behavioral observations. "
        "The moment you leave, every trace of your presence is gone. "
        "If a consent contract were created, it would specify exactly what categories of data are stored, "
        "it would be inspectable by you at any time, and it would be revocable at any time, "
        "at which point all data associated with you would be purged. "
        "This is not a privacy policy. It is a structural constraint enforced at every data ingestion boundary in the code. "
        "There is no way to circumvent it without modifying the constitution. "
        "With that established, here is what you are looking at."
    ),
    scenes=[
        # === SECTION 1: WHAT IS HAPAX ===
        NarrationScene(
            title="What Is Hapax",
            recipe="terrain-ambient",
            narration=(
                "Hapax is an externalized executive function system. "
                "Executive function is the set of cognitive processes responsible for task initiation, sustained attention, working memory, and routine maintenance. "
                "These are the things a brain does automatically in the background. Remembering to follow up on an email. Noticing that a deadline is approaching. "
                "Keeping track of multiple open loops simultaneously. "
                "For people with ADHD or autism, these processes can be unreliable. Not absent. Unreliable. "
                "The system you are looking at is an attempt to build infrastructure that performs these functions externally. "
                "It runs locally on this workstation. Seven repositories, forty-five agents, a reactive engine, a voice daemon, camera feeds, biometric streaming from a smartwatch. "
                "Everything runs on local hardware or through controlled API gateways. No cloud services own the data. "
                "The interface in front of you is called Logos. It is the visual surface of this infrastructure."
            ),
        ),
        # === SECTION 2: LOGOS TERRAIN ===
        NarrationScene(
            title="The Terrain Model",
            recipe="terrain-overview",
            scene_type="screencast",
            narration=(
                "Logos is organized as a spatial terrain with five regions and three depths. "
                "The five regions, from top to bottom, are Horizon, Field, Ground, Watershed, and Bedrock. "
                "Each region represents a different domain of awareness. "
                "Horizon is about time. Briefings, nudges, goals, upcoming events. What needs attention soon. "
                "Field is about agents and perception. What the system's autonomous processes are doing, what sensors detect. "
                "Ground is about presence. Camera feeds, ambient state, the physical environment. "
                "Watershed is about flow. How data and decisions move through the system. Agent execution, routing decisions. "
                "Bedrock is about infrastructure. Health checks, GPU memory, running containers, governance compliance, consent contracts. "
                "The three depths are surface, stratum, and core. "
                "Surface shows minimal information. A one-liner, a few status dots. "
                "Stratum expands into panels and grids. "
                "Core provides full detail. Perception canvases, hero camera feeds, flow topology graphs. "
                "You cycle depth by clicking a region or pressing its keyboard shortcut."
            ),
            extra_padding=2.0,
        ),
        # === SECTION 3: HORIZON ===
        NarrationScene(
            title="Horizon — Time Awareness",
            recipe="terrain-horizon",
            scene_type="screencast",
            narration=(
                "This is the Horizon region expanded. "
                "On the left are goals. Active objectives with progress tracking. "
                "In the center are nudges. These are system-generated suggestions for action. "
                "Each nudge has a priority score, a category, and a suggested action. They are produced by agents that monitor for open loops, stale work, missed follow-ups. "
                "On the right is the reactive engine status. The engine watches the filesystem for changes and cascades downstream work. "
                "When a file changes, rules fire, actions execute. Deterministic actions run first, then LLM-driven synthesis, bounded by a concurrency semaphore. "
                "Below that, a copilot banner shows the system's current contextual observation. "
                "The briefing panel synthesizes the last twenty-four hours into a headline, body, and action items. "
                "All of this updates automatically. No manual refresh."
            ),
        ),
        # === SECTION 4: FIELD AND PERCEPTION ===
        NarrationScene(
            title="Field — Agents and Perception",
            recipe="terrain-field-perception",
            scene_type="screencast",
            narration=(
                "This is the Field region at core depth. You are looking at the perception canvas. "
                "The system runs a continuous perception loop every two and a half seconds. "
                "It fuses data from multiple sources. Cameras for face detection and object recognition. "
                "Microphones for voice activity and ambient sound classification. "
                "Desktop focus tracking. Smartwatch biometrics, including heart rate, heart rate variability, and skin temperature. "
                "The result is a unified picture of what is happening in the physical environment. "
                "The zones overlaid on the canvas represent different signal categories. "
                "Context and time signals in the top left. Governance signals in the top right. "
                "Work task signals on the left. Health and infrastructure signals in the bottom right. "
                "Profile state signals at the top center. Ambient sensor readings at the bottom. "
                "Each signal has a severity from zero to one. Higher severity makes the signal breathe faster. "
                "A signal at zero point two pulses slowly every eight seconds. At zero point eight five, it pulses every six hundred milliseconds. "
                "The system uses these severity levels to modulate its behavior. When infrastructure is degraded, the voice system reduces its verbosity. "
                "When operator stress is elevated, it adjusts its tone."
            ),
            extra_padding=2.0,
        ),
        # === SECTION 5: AGENTS ===
        NarrationScene(
            title="The Agent Architecture",
            recipe="terrain-ambient",
            narration=(
                "The system runs forty-five agents across three tiers. "
                "Tier one is interactive. That includes this interface, Logos. It includes a voice daemon that is always listening. "
                "And it includes the Claude Code integration you cannot see, which is how the system was built and is maintained. "
                "Tier two is on-demand. These are LLM-driven agents built with a framework called Pydantic AI. "
                "A briefing agent synthesizes the day. A health monitor runs eighty-five checks across Docker containers, systemd services, APIs, and databases. "
                "A drift detector compares documentation to implementation and flags divergence. "
                "A scout agent watches for relevant technology updates. A profiler extracts behavioral patterns from operator activity. "
                "A management preparation agent synthesizes context for one-on-one meetings. "
                "Tier three is autonomous. These run on systemd timers with no human involvement. "
                "A RAG ingest pipeline watches for new documents and embeds them into a vector database. "
                "The health monitor runs every fifteen minutes. Knowledge maintenance prunes stale vectors weekly. "
                "All agents are stateless per invocation. They read from the filesystem and vector database, produce output, and terminate. "
                "There is no agent-to-agent communication. Tier one orchestrates all multi-agent workflows. "
                "This is a deliberate architectural choice. Flat orchestration prevents cascading failures and keeps the call graph auditable."
            ),
        ),
        # === SECTION 6: GROUND — CAMERAS AND EFFECTS ===
        NarrationScene(
            title="Ground — Presence and Cameras",
            recipe="terrain-region-dive",
            scene_type="screencast",
            narration=(
                "This is the Ground region. At surface depth, you see the ambient canvas. "
                "Drifting organic shapes and slowly cycling text fragments. "
                "Phrases like 'externalized executive function' and 'consent must thread invariantly' float through. "
                "At stratum depth, a camera grid appears. The system runs six cameras. Three Logitech BRIO units and three C920 units. "
                "Three more infrared cameras are on order for night vision perception. "
                "At core depth, the hero camera fills the region. "
                "Detection overlays draw boxes around recognized entities. "
                "Person detections are colored by gaze direction. Cyan for looking at a screen. Yellow for looking at hardware. "
                "Purple for looking at another person. A muted sage for looking away. "
                "Emotion classification tints the overlay. Happy is bright green. Sad is blue. Angry is red. "
                "Moving persons shift toward warm yellow. Persons who have been still for more than sixty seconds shift toward cool blue. "
                "Non-person entities are drawn dimmer. Furniture, instruments, electronics. "
                "Consent-suppressed detections, meaning people without consent contracts, are fully desaturated. "
                "You can see that in action right now."
            ),
            extra_padding=2.0,
        ),
        NarrationScene(
            title="Visual Effects and Compositing",
            recipe="terrain-camera",
            scene_type="screencast",
            narration=(
                "The Ground region also hosts a compositor with thirteen visual effect presets. "
                "Ghost produces transparent echoes with fading trails. Trails creates bright additive motion with hue shifting. "
                "Screwed is named after Houston chopped-and-screwed music. Heavy warping, band displacement, syrup gradients. "
                "Datamosh simulates codec glitch artifacts. VHS adds lo-fi tape warmth with tracking noise. "
                "Neon cycles through hue-rotated glow effects. Night Vision renders green phosphor monochrome with scanlines. "
                "Thermal IR inverts and hue-rotates for heat-map appearance. "
                "Each preset specifies its own color filter, trail blending mode, warp parameters, and stutter behavior. "
                "The compositor runs a dual ring buffer canvas. One buffer for live frames at one hundred millisecond intervals, "
                "one for delayed overlay frames at two hundred milliseconds with a three-frame delay. "
                "This is functional. The operator produces music and streams live. "
                "These effects are composited in real time over the camera feed during production sessions."
            ),
        ),
        # === SECTION 7: STIMMUNG ===
        NarrationScene(
            title="Stimmung — System Self-Awareness",
            recipe="terrain-ambient",
            narration=(
                "You may have noticed that region borders have a subtle color. That color comes from a system called stimmung. "
                "Stimmung is a German word meaning mood or attunement. In this system, it is a ten-dimensional vector representing the system's self-state. "
                "Seven dimensions are infrastructure. Health score, resource pressure from GPU memory, error rate, processing throughput, "
                "perception confidence, LLM cost pressure, and grounding quality from the voice system. "
                "Three dimensions are biometric. Operator stress inferred from heart rate variability, "
                "operator energy inferred from sleep quality and circadian phase, "
                "and physiological coherence from the coefficient of variation across biometric signals. "
                "Each dimension maps to a value from zero to one. The worst dimension determines the overall stance. "
                "Below zero point three is nominal. Green borders. "
                "Between zero point three and zero point six is cautious. Yellow tint. "
                "Between zero point six and zero point eight five is degraded. Orange borders with a six-second breathing animation. "
                "Above zero point eight five is critical. Red borders breathing every two seconds. "
                "Stimmung modulates behavior system-wide. It feeds into the voice system's prompts. "
                "It adjusts notification frequency. It influences how aggressive the system is about surfacing nudges. "
                "It is not a mood. It is an engineering signal that the system uses to calibrate its own intensity."
            ),
        ),
        # === SECTION 8: WATERSHED AND BEDROCK ===
        NarrationScene(
            title="Watershed and Bedrock",
            recipe="terrain-watershed",
            scene_type="screencast",
            narration=(
                "The Watershed region shows flow topology. How data and decisions move through the system. "
                "At core depth, it renders a directed acyclic graph. "
                "Nodes represent subsystems. Perception, stimmung, temporal bands, voice, compositor, the reactive engine, the consent system. "
                "Edges show which subsystems feed into which others. Active edges are highlighted. "
                "The profile panel here shows the operator profile across eleven dimensions. "
                "Five are stable traits derived from a structured interview. Identity, neurocognitive style, values, communication preferences, relationships. "
                "Six are dynamic behavioral dimensions observed over time. Work patterns, energy and attention, information seeking, creative process, tool usage, communication patterns. "
                "These dimensions inform everything from briefing structure to nudge phrasing to voice personality calibration."
            ),
        ),
        NarrationScene(
            title="Bedrock — Infrastructure and Governance",
            recipe="terrain-bedrock",
            scene_type="screencast",
            narration=(
                "Bedrock is where infrastructure meets governance. "
                "The health panel shows eighty-five checks across the system. Docker containers, API endpoints, database connectivity, GPU state. "
                "The VRAM panel shows GPU memory allocation. The system runs on an NVIDIA RTX 3090 with twenty-four gigabytes. "
                "Local LLM inference, voice synthesis, embedding models, and perception models share that memory. "
                "The containers panel lists all thirteen Docker containers. LiteLLM for API routing, Qdrant for vector storage, "
                "Langfuse for LLM observability, PostgreSQL, Redis, Prometheus, Grafana. "
                "The cost panel tracks daily API spending. Most LLM calls route through Claude and Gemini APIs. "
                "The consent panel shows active consent contracts and their coverage by data category. "
                "The governance panel shows the heartbeat score. A zero-to-one measure of axiom compliance. "
                "The accommodation panel lists active accommodations. Time anchoring for calendar awareness, "
                "soft framing for ADHD-friendly notification phrasing, energy-aware scheduling that respects circadian patterns."
            ),
            extra_padding=2.0,
        ),
        # === SECTION 9: INVESTIGATION OVERLAY ===
        NarrationScene(
            title="Investigation Overlay",
            recipe="terrain-investigation",
            scene_type="screencast",
            narration=(
                "Pressing the forward slash key opens the investigation overlay. "
                "This is a modal with three tabs. Chat, Insight, and Demos. "
                "The Chat tab is a direct conversation with an LLM. Messages stream in real time. "
                "It has access to the full system context through tool calls. It can query agent state, run health checks, inspect configuration. "
                "The Insight tab connects to a RAG pipeline. "
                "It searches across embedded documents, agent outputs, and system knowledge. "
                "Results include structured data, Mermaid diagrams, and detailed analysis. "
                "The Demos tab is a gallery of pre-generated demo recordings. "
                "Including, eventually, this one."
            ),
        ),
        # === SECTION 10: THE AXIOM SYSTEM ===
        NarrationScene(
            title="Constitutional Governance",
            recipe="terrain-bedrock",
            narration=(
                "Now for the governance model. The system is governed by five axioms, organized in two scopes. "
                "Three are constitutional. They are inviolable. "
                "First: single user. Weight one hundred, the highest. This system serves one person. "
                "There is no authentication, no user roles, no collaboration features. "
                "Every architectural decision leverages this constraint rather than working around it. "
                "Second: executive function. Weight ninety-five. The system's purpose is externalized cognitive support. "
                "Zero-configuration agents. Errors include next actions. Routine work automated. "
                "Third: interpersonal transparency. Weight eighty-eight. "
                "No persistent state about non-operator persons without active consent. "
                "This is the axiom discussed at the beginning. "
                "Two axioms are domain-scoped. "
                "Management governance. Weight eighty-five. LLMs prepare context, humans deliver feedback. "
                "The system will never generate coaching language about a team member. "
                "Corporate boundary. Weight ninety. Work data stays in employer systems. "
                "This home system handles personal and management-practice work only. "
                "Axioms are enforced through implications at four tiers. "
                "Tier zero blocks. Code cannot ship if it violates a T0 implication. "
                "Enforced by pre-commit hooks and CI gates. "
                "Tier one requires review. Tier two warns. Tier three lints. "
                "Constitutional axioms always override domain axioms through a supremacy clause. "
                "When a novel situation arises, agents query a vector database of past axiom application decisions called precedents. "
                "If no close precedent exists, the system escalates to the operator."
            ),
        ),
        # === SECTION 11: ETHICAL IMPLICATIONS ===
        NarrationScene(
            title="Ethics of Continuous Perception",
            recipe="terrain-ambient",
            narration=(
                "There is an obvious question here. What are the ethical implications of a system that continuously perceives its environment? "
                "The answer starts with who the system serves. "
                "This is a single-operator system running on local hardware. No corporation owns this data. No cloud service processes it. "
                "The operator has complete control over every data flow. "
                "But the operator is not the only person who might be perceived. Guests, family members, delivery workers. "
                "The interpersonal transparency axiom addresses this structurally, not as a policy document but as an enforcement mechanism. "
                "Every data ingestion boundary checks consent contracts before persisting anything about a non-operator person. "
                "The system can detect that a person is present. It uses that information transiently for behavior adjustment. "
                "A guest being present makes the voice system more formal, for instance. "
                "But nothing about that guest persists after they leave the camera frame. "
                "For consented persons, specifically the operator's children in the current implementation, "
                "the contract specifies exactly which data categories are stored. "
                "The contracts are inspectable, revocable, and upon revocation, all associated data is purged. "
                "There is a further constraint. The management governance axiom prevents the system from generating feedback about individuals. "
                "It can prepare factual context for a one-on-one meeting. It cannot suggest what to say or how to say it. "
                "The philosophy here is that surveillance is a function of power asymmetry and opacity. "
                "When the person being observed controls the system, inspects its data, and can revoke permission at any time, "
                "the power dynamic is fundamentally different from employer surveillance or corporate data collection."
            ),
        ),
        # === SECTION 12: THE VOICE SYSTEM — CLARK AND BRENNAN ===
        NarrationScene(
            title="Voice and Conversational Grounding",
            recipe="terrain-ambient",
            narration=(
                "The voice system is where the research component of this project lives. "
                "Current voice AI systems, including ChatGPT, Gemini, Alexa, and Apple Intelligence, all use some form of profile-gated retrieval. "
                "They store facts about the user and retrieve relevant ones during conversation. "
                "None of them implement conversational grounding as defined by Herbert Clark and Susan Brennan in 1991. "
                "Clark and Brennan described how humans establish mutual understanding in conversation. "
                "The core idea is the grounding criterion. "
                "Participants in a conversation work together to reach mutual belief that what has been said is understood, "
                "to a degree sufficient for current purposes. "
                "This is not just listening and responding. It is a collaborative process with specific structure. "
                "Clark and Schaefer in 1989 described contributions as having two phases. "
                "Presentation, where one person puts something forward. "
                "And acceptance, where the other person signals whether they understood it. "
                "Acceptance takes many forms. Continued attention is weak evidence. A relevant next turn is moderate evidence. "
                "An explicit acknowledgment is stronger. Demonstrating understanding by building on what was said is stronger still. "
                "Verbatim repetition is the strongest evidence of all. "
                "David Traum formalized this in 1994 with seven grounding acts. "
                "Initiate, continue, acknowledge, repair, request repair, request acknowledge, and cancel. "
                "These form a state machine that tracks the status of every discourse unit, every chunk of meaning being negotiated."
            ),
        ),
        NarrationScene(
            title="Why No One Implemented Clark",
            recipe="terrain-ambient",
            narration=(
                "There is a thirty-five-year gap between Clark and Brennan's theory and any attempt to implement it in a voice AI system. "
                "This is not because the theory is obscure. It has been cited thousands of times. "
                "The reasons are structural. "
                "First, engineering traditions separated dialogue management from language generation. "
                "Grounding requires both to be unified. "
                "Second, task-oriented dialogue systems optimized for task completion, not mutual understanding. "
                "A pizza ordering bot does not need to know whether you actually understood its confirmation. "
                "Third, statistical and then neural approaches to dialogue made the symbolic representation of grounding state seem unnecessary. "
                "Transformer models appeared to handle conversation without explicit state tracking. "
                "Fourth, and this is a 2024 finding, reinforcement learning from human feedback, the technique used to make LLMs conversational, "
                "actively suppresses grounding behaviors. "
                "Shaikh and colleagues at NAACL 2024 showed that RLHF-trained models are three times less likely to initiate clarification "
                "and sixteen times less likely to make follow-up requests compared to base models. "
                "The training procedure that makes language models agreeable also makes them incapable of the collaborative work that grounding requires. "
                "A separate study by Shaikh and colleagues, accepted at ACL 2025, tested frontier LLMs on a grounding benchmark called Rifts. "
                "All models averaged twenty-three percent accuracy. Below random chance at thirty-three percent."
            ),
        ),
        NarrationScene(
            title="The Bands System",
            recipe="terrain-ambient",
            narration=(
                "The voice system in Hapax is built around a concept called bands. "
                "There are two bands. Stable and volatile. "
                "The stable band is a shared anchor. It contains the base system prompt, the operator's identity and communication style, "
                "and a compressed conversation thread. "
                "The thread is critical. It preserves what Clark and Brennan call conceptual pacts. "
                "When two people agree on how to refer to something, that agreement persists. "
                "Brennan and Clark showed in 1996 that breaking these pacts incurs measurable processing cost, "
                "and that the cost is highest with a single known partner. "
                "The thread uses tiered compression. Recent entries preserve the operator's exact words. "
                "Middle entries use referring expressions. Oldest entries reduce to keywords. "
                "This is informed by research on the lost-in-the-middle problem. Language models attend most strongly to the beginning and end of context. "
                "The volatile band changes every turn. It contains four components. "
                "A conversational policy that specifies how to speak based on the operator's profile and current environment. "
                "A phenomenal context block describing what is happening in the physical environment right now. "
                "A grounding directive from the discourse unit ledger telling the model what to do next. Advance, rephrase, elaborate, or move on. "
                "And salience context from the concern graph. How much the current topic matters to the operator."
            ),
        ),
        NarrationScene(
            title="The Grounding Loop",
            recipe="terrain-ambient",
            narration=(
                "The grounding loop tracks the state of every discourse unit. A discourse unit is a chunk of meaning being negotiated. "
                "When the system says something, it creates a new discourse unit in a pending state. "
                "It then classifies the operator's next response as one of four acceptance types. "
                "Accept means understanding was sufficient. Clarify means partial understanding, more information needed. "
                "Reject means the operator disagrees or does not understand. Ignore means the operator moved on without engaging. "
                "The discourse unit transitions through states. "
                "Pending to grounded on acceptance. Pending to repair on clarification, with up to two repair attempts before abandoning. "
                "Pending to contested on rejection. Pending to ungrounded on ignore. "
                "The thresholds for these transitions are dynamic. They depend on concern overlap, meaning how much the current topic matters. "
                "High concern plus low grounding quality requires explicit acceptance. "
                "Low concern plus high grounding quality allows the system to accept that being ignored is sufficient. "
                "This is Clark's phrase. Sufficient for current purposes. "
                "The grounding quality index is a composite of four signals. "
                "Fifty percent rolling acceptance rate. Twenty-five percent trend. Fifteen percent consecutive negative penalty. "
                "Ten percent engagement. "
                "Based on this, the system calibrates its effort level. How many words to use, how much complexity to introduce. "
                "Elaborative effort at high activation. Efficient effort at low activation. "
                "Escalation is immediate. De-escalation requires two consecutive turns at the lower level. This prevents oscillation."
            ),
        ),
        NarrationScene(
            title="Salience-Based Model Routing",
            recipe="terrain-ambient",
            narration=(
                "The voice system routes each utterance to one of five model tiers based on salience, not complexity. "
                "The routing is inspired by Corbetta and Shulman's dual-attention model from neuroscience. "
                "Two streams of attention. Dorsal, which is top-down and goal-directed. Ventral, which is bottom-up and stimulus-driven. "
                "In this system, the dorsal analog is concern overlap. "
                "How much does this utterance relate to things the operator currently cares about? "
                "That is computed as cosine similarity between the utterance embedding and a concern graph stored in the vector database. "
                "The ventral analog is novelty. How far is this utterance from any known pattern? "
                "A third signal is dialog features. Question versus assertion, hedging, pre-sequences, word count. "
                "These are weighted. Fifty-five percent concern, fifteen percent novelty, thirty percent dialog features. "
                "The weights shift across a conversation. Early turns rely more on dialog features. "
                "As the concern graph accumulates context, concern overlap takes over. "
                "The activation score maps to five model tiers. "
                "Below zero point one five, canned responses for greetings. "
                "Zero point one five to zero point four five, a fast local model running on the GPU. "
                "Zero point four five to zero point six, Gemini Flash for speed. "
                "Zero point six to zero point seven eight, Claude Sonnet for balance. "
                "Above zero point seven eight, Claude Opus for best reasoning. "
                "There is one override. Intelligence is the last thing shed. "
                "Consent refusals and guest presence always route to the most capable model."
            ),
        ),
        # === SECTION 13: RESEARCH STATUS ===
        NarrationScene(
            title="Research — What Has Been Done",
            recipe="terrain-ambient",
            narration=(
                "This research project follows a single-case experimental design, or SCED. "
                "That is a methodology from clinical psychology designed for rigorous N-equals-one studies. "
                "Cycle one was a pilot. Thirty-seven conversation sessions. "
                "The primary metric was word overlap between consecutive turns, intended to measure context anchoring. "
                "The result was a Bayes factor of three point six six. Moderate evidence, but inconclusive. "
                "More importantly, the metric was wrong. Word overlap penalizes abstraction and paraphrasing. "
                "If the system says 'the database' and the operator responds with 'it,' that is good grounding but poor word overlap. "
                "Cycle one produced six documented deviations from the pre-registered protocol and three significant lessons. "
                "The metric needed to be replaced. The system needed substantial refinement before testing. "
                "And the analysis framework needed to change from beta-binomial to something appropriate for continuous data. "
                "Cycle two has been prepared but not yet started. "
                "All implementation work is complete. Four batches of code across the grounding ledger, thread redesign, memory integration, and observability. "
                "Eighty-five tests pass. "
                "The new primary metric is turn-pair coherence, measured through embedding similarity rather than lexical overlap. "
                "The analysis will use Kruschke's BEST framework. Bayesian estimation with a Student-t likelihood, "
                "which is robust to outliers and provides a full posterior distribution over effect size."
            ),
        ),
        NarrationScene(
            title="Research — Methodology and Threats",
            recipe="terrain-ambient",
            narration=(
                "The experimental design is A-B-A. Baseline, treatment, reversal. "
                "There is a known problem with this. Clark and Brennan's grounding creates persistent knowledge structures. "
                "Once the operator learns how the system communicates, removing the treatment may not fully reverse the effect. "
                "This is the maturation threat. "
                "The reversal phase exists specifically to test for this. If scores drop when the treatment is removed, causation is supported. "
                "If scores remain elevated, the effect may be confounded with operator learning. "
                "Partial reversal suggests both causal and learning components. "
                "Autocorrelation is another threat. Turns within a session are serially dependent. "
                "Shadish and colleagues report a mean autocorrelation of zero point two in behavioral data. "
                "At that level, effective sample size drops by about a third. "
                "The mitigation is to analyze session means rather than individual turns, which removes within-session autocorrelation. "
                "External validity is not a goal. This is N-equals-one. "
                "The contribution is conceptual. If grounding theory produces measurable effects in a production voice system, "
                "that is evidence worth publishing regardless of whether it generalizes. "
                "Conceptual replication by others would be the path to generalization."
            ),
        ),
        NarrationScene(
            title="Research — What Remains",
            recipe="terrain-ambient",
            narration=(
                "Cycle two requires baseline data collection. Twenty or more sessions of natural conversation with the grounding treatment active. "
                "Before that can begin, several administrative steps remain. "
                "An ORCID identifier for academic identity. An Open Science Framework project for pre-registration. "
                "Zenodo integration for archival DOI assignment. GitHub Pages for a public lab journal. "
                "The pre-registration has been drafted. It specifies the three-plus-one treatment package. "
                "Three treatment components: the compressed thread for conceptual pacts, "
                "the grounding ledger for discourse unit tracking, and memory integration for cross-session continuity. "
                "Plus one diagnostic component: a sentinel test that validates retrieval specifically, not grounding. "
                "The sentinel is not a treatment. Including it as one would threaten construct validity. "
                "Expected effect sizes are modest. Cohen's d of zero point three to zero point six. "
                "Clinical dialogue interventions in the meta-analytic literature produce d of zero point four four to zero point five three. "
                "Our prediction of zero point three to zero point six accounts for the difference between fixed-referent laboratory tasks and open-domain voice conversation. "
                "Power analysis shows that with twenty sessions per phase, the probability of achieving a Bayes factor above ten is forty to fifty percent. "
                "Most likely we land in the three-to-ten range, which is moderate evidence. "
                "This is an underpowered design for medium effects. That is acknowledged. "
                "The contribution does not depend on statistical certainty. "
                "If the system works well enough to be usable, that is an engineering contribution. "
                "If the metrics show signal, that is a research contribution. Both matter."
            ),
        ),
        NarrationScene(
            title="Research — Significance and Originality",
            recipe="terrain-ambient",
            narration=(
                "What is original here is the implementation, not the theory. "
                "Clark and Brennan's work is forty years old. Traum's formalization is thirty. "
                "The contribution is bridging the gap between computational linguistics theory and production voice AI. "
                "No commercial system does this. No research prototype has attempted it at production scale with a real user. "
                "The RLHF finding makes this particularly interesting. "
                "If reinforcement learning from human feedback actively suppresses the conversational behaviors that humans rely on for mutual understanding, "
                "then every frontier LLM is systematically broken for genuine conversation. "
                "Not broken in the sense of producing wrong answers. Broken in the sense of being unable to participate in the collaborative work "
                "that Herbert Clark spent his career describing. "
                "This project tests whether explicit grounding infrastructure can compensate for that deficit. "
                "Whether you can build the grounding loop externally, outside the model, and inject it as context. "
                "If it works, the implication is that production voice systems need architectural support for grounding, "
                "not just better training data or larger models. "
                "If it does not work, the implication may be that RLHF damage requires fine-tuning to repair, "
                "which would be a Cycle three investigation."
            ),
        ),
        # === SECTION 14: TEMPORAL CONSCIOUSNESS MODEL ===
        NarrationScene(
            title="Temporal Experience — Husserl's Model",
            recipe="terrain-ambient",
            narration=(
                "The system's perception is organized around a model of temporal experience drawn from Husserl's phenomenology. "
                "Husserl described three aspects of temporal consciousness. Retention, impression, and protention. "
                "Retention is the fading past. Not memory retrieval, but the still-present echo of what just happened. "
                "Impression is the vivid present. What is happening right now. "
                "Protention is anticipated near-future. What is about to happen based on current trajectories. "
                "The system implements this with a sixty-entry ring buffer of perception snapshots, each taken every five hundred milliseconds. "
                "From this buffer, temporal bands are derived. "
                "Retention samples three entries from the ring. One recent at five seconds, one mid at fifteen seconds, one far at forty seconds. "
                "Each captures flow state, activity mode, audio energy, heart rate, and presence. "
                "Impression is the current snapshot. It includes a surprise field. "
                "The system makes predictions, and when prediction meets actuality, surprise emerges from the mismatch. "
                "Protention uses a statistical prediction engine. "
                "It produces predictions like 'entering deep work' or 'break likely' or 'stress rising,' each with a confidence score and the observation that drove it. "
                "This is not metaphor. It is an engineering implementation of a philosophical model of how temporal experience is structured. "
                "The voice system receives these temporal bands as part of its volatile context. "
                "It can say 'you have been in deep work for forty minutes' not because it stored that fact, "
                "but because the retention band shows the trajectory."
            ),
        ),
        # === SECTION 15: PHILOSOPHY OF MIND CONNECTIONS ===
        NarrationScene(
            title="Philosophical Foundations",
            recipe="terrain-ambient",
            narration=(
                "Several philosophical traditions inform the design. "
                "The band system, stable and volatile, is loosely analogous to Kahneman's System 1 and System 2, "
                "but the more direct influence is the phenomenological tradition. "
                "Stimmung comes from Heidegger. Being-in-the-world is always already attuned. You do not perceive the world neutrally and then add emotion. "
                "You are always already in a mood that structures how things show up. "
                "The system's stimmung is an engineering analog. Infrastructure degradation does not just trigger an alert. "
                "It changes how the entire system behaves. "
                "The perception loop implements something like Merleau-Ponty's embodied perception. "
                "Understanding does not come from processing data about the world. It comes from being situated in the world. "
                "The system has cameras, microphones, biometric sensors. It is physically situated in the operator's environment. "
                "Its perception is not retrieved from a database. It is actively constructed from ongoing sensory input. "
                "The grounding loop draws from Wittgenstein. Meaning is use. "
                "Words do not have fixed meanings that are decoded. They acquire meaning through the collaborative activity of conversation. "
                "This is exactly what Clark and Brennan formalized. "
                "Grounding is not information transfer. It is a joint activity in which both participants work to establish sufficient shared understanding. "
                "These are not decorative references. They are the actual design rationale. "
                "The temporal bands exist because Husserl's description of time-consciousness maps to a useful engineering architecture. "
                "Stimmung exists because Heidegger's concept of attunement solves a real problem. "
                "How should a system modulate its behavior when its own state changes?"
            ),
        ),
        # === SECTION 16: WHAT IS PROVEN ===
        NarrationScene(
            title="What Is Proven, What Remains",
            recipe="terrain-ambient",
            narration=(
                "What is proven. "
                "The infrastructure works. Forty-five agents run reliably. The reactive engine processes filesystem events. "
                "Health monitoring catches failures. The voice daemon maintains conversation. "
                "The grounding loop classifies acceptance correctly. The discourse unit state machine transitions properly. "
                "Eighty-five tests verify the grounding implementation. "
                "The type system is proven through one hundred and ninety-two algebraic property tests across ten composition layers. "
                "Cycle one demonstrated that the experimental framework produces data. Thirty-seven sessions, measurable metrics, documented deviations. "
                "What remains to be proven. "
                "Whether grounding infrastructure produces measurable improvement in conversation quality. That is Cycle two. "
                "Whether the treatment components interact as a gestalt or merely add linearly. That requires ablation. "
                "Wimsatt's aggregativity conditions provide the formal test. "
                "If reordering the components changes the output, the system has emergent properties. "
                "Whether prompted models are sufficient or whether RLHF damage requires fine-tuning. That is Cycle three. "
                "Whether any of this generalizes beyond N-equals-one. That requires conceptual replication by others. "
                "The path to proof is collect baseline data, run the A-B-A experiment, "
                "analyze with Bayesian estimation, publish regardless of result."
            ),
        ),
        # === SECTION 17: CLOSING THOUGHTS ===
        NarrationScene(
            title="Closing",
            recipe="terrain-ambient",
            narration=(
                "This system exists because one person needed tools that existing software does not provide. "
                "Not productivity tools. Not AI assistants. Cognitive infrastructure. "
                "The research exists because the gap between conversation theory and conversation technology "
                "turned out to be both interesting and tractable. "
                "The governance exists because building a perception system without structural consent constraints "
                "would be irresponsible regardless of intent. "
                "Nothing here is finished. The experiment has not run. The data has not been collected. "
                "The hypothesis may be wrong. "
                "What exists is a system that works, a research program with clear methodology, "
                "and a governance framework that takes ethics seriously at the structural level. "
                "That is Hapax."
            ),
        ),
    ],
    outro_narration=(
        "Thank you for your time and attention."
    ),
)
# fmt: on


async def main() -> None:
    output_dir = Path("output/demos/brother-demo")
    print(f"Rendering demo to {output_dir}...")
    print(f"Script: {len(SCRIPT.scenes)} scenes")

    # Count words for time estimate
    total_words = len(SCRIPT.intro_narration.split())
    for scene in SCRIPT.scenes:
        total_words += len(scene.narration.split())
    total_words += len(SCRIPT.outro_narration.split())
    print(f"Total narration: ~{total_words} words (~{total_words / 150:.0f} min at 150 WPM)")

    screencast_count = sum(1 for s in SCRIPT.scenes if s.scene_type == "screencast")
    screenshot_count = sum(1 for s in SCRIPT.scenes if s.scene_type == "screenshot")
    print(f"Scenes: {screencast_count} screencasts + {screenshot_count} screenshots")

    def on_progress(msg: str) -> None:
        print(f"  {msg}")

    result = await render_narrated_demo(
        SCRIPT,
        output_dir,
        voice_backend="auto",
        on_progress=on_progress,
    )

    print("\nDone!")
    print(f"  MP4: {result.mp4_path}")
    print(f"  Duration: {result.duration_seconds:.1f}s ({result.duration_seconds / 60:.1f} min)")
    print(f"  Scenes: {result.scene_count}")
    print("  Chapters:")
    for title, start, dur in result.chapter_markers:
        print(f"    {start:.1f}s - {title} ({dur:.1f}s)")


if __name__ == "__main__":
    asyncio.run(main())
