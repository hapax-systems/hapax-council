"""Render narration audio for Alexis demo v2 — expanded to 45 minutes.

Hand-crafted narration. No LLM generation. Operator-approved voice.
Rendered via ElevenLabs (or Kokoro fallback), then choreographed via Opus.

Usage: uv run python scripts/render_alexis_demo_v2.py
"""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
from pathlib import Path

# fmt: off
SCENES: list[tuple[str, str]] = [

    # ══════════════════════════════════════════════════════════════════════
    # PART 1: CONTEXT AND CONSENT (5 min)
    # ══════════════════════════════════════════════════════════════════════

    ("00-intro",
     "You know I have been building something. You know it started as a way to help with executive function. "
     "What you have not seen is what it became."
    ),

    ("01-consent-context",
     "What you are looking at right now is called Logos. It is the visual surface of that system. "
     "It is going to look unusual. Nothing here works like a normal application. "
     "There are no menus, no sidebar, no settings page. "
     "What you see is a spatial layout. Five horizontal regions stacked vertically, each representing a different domain of awareness. "
     "We will walk through every one of them. "
     "But before I show you what any of this does, I need to tell you something about what it sees. "
     "There are cameras in this room. Six of them. "
     "They feed into a perception system that continuously detects people, objects, activity, ambient sound, and lighting. "
     "The system also receives data from my watch. Heart rate, heart rate variability, skin temperature, sleep quality. "
     "So here is the part that matters most. "
     "There is a rule built into the constitutional foundation of this system. "
     "It says: no persistent data about any non-operator person may exist without an active, explicit, revocable consent contract. "
     "Right now, it can see you. It knows a person is present. "
     "But it stores nothing about you. No face data. No voice data. No behavioral observations. Nothing. "
     "When you leave this room, every trace of your presence disappears. "
     "If we created a consent contract, it would specify exactly what categories of data are stored. "
     "You could inspect it at any time. Revoke it at any time. "
     "And upon revocation, everything associated with you is deleted. "
     "This is not a privacy policy. It is a structural constraint enforced at every data ingestion point in the code. "
     "There is no setting to turn it off. "
     "Two consent contracts exist for the children. We hold those as their legal guardians. "
     "The contracts specify exactly which data categories are stored. They are inspectable. They are revocable. "
     "Even with full consent, the system cannot generate feedback or evaluate any individual person. "
     "It can prepare facts. It cannot judge. "
     "I will come back to the ethics of this in detail later. For now, that is the foundation."
    ),

    # ══════════════════════════════════════════════════════════════════════
    # PART 2: WHAT IS HAPAX (3 min)
    # ══════════════════════════════════════════════════════════════════════

    ("02-what-is-hapax",
     "So. What is Hapax. "
     "Executive function is the set of cognitive processes that handle task initiation, sustained attention, "
     "keeping track of open loops, and maintaining routines. "
     "Think of it as the background operating system of a brain. "
     "For most people it runs automatically. You remember to follow up on that email. You notice a deadline coming. "
     "You keep five things in working memory without thinking about it. "
     "For people with ADHD, those processes are not absent. They are unreliable. "
     "Hapax is an attempt to build infrastructure that performs those functions externally. "
     "Not a to-do list. Not a reminder app. "
     "A system that actually tracks open loops, notices when things drift, surfaces what needs attention, "
     "and maintains awareness of the physical and cognitive environment. "
     "Seven repositories. Forty-five agents. A voice system. Camera feeds. Biometric streaming from a smartwatch. A reactive engine. "
     "Everything runs locally on this workstation. No cloud service owns the data. "
     "The only external calls are to language model APIs, and those go through a gateway I control."
    ),

    # ══════════════════════════════════════════════════════════════════════
    # PART 3: THE TERRAIN — VISUAL WALKTHROUGH (8 min)
    # ══════════════════════════════════════════════════════════════════════

    ("03-terrain-intro",
     "Now let me orient you to what you are seeing. "
     "This is going to look like nothing you have encountered before. "
     "There is no precedent for this layout in conventional software. "
     "The design philosophy is geological. Layers of awareness stacked vertically, each with depth that can be revealed. "
     "The visual language is warm. Dark zinc tones, amber accents, monospace typography. Dense information rendered small. "
     "Nothing is decorative. Every visual element encodes system state. "
     "The screen is divided into five horizontal regions. Each one can glow or breathe depending on system health. "
     "I am going to expand each region one at a time so you can see what lives inside."
    ),

    ("04-terrain-walk",
     "This top region is called Horizon. It holds time-oriented information. "
     "What is coming, what needs attention, what the system has synthesized about the last twenty-four hours. "
     "Below it is Field. That is where agents and perception live. "
     "What the system's autonomous processes are doing, what sensors detect about the environment. "
     "The middle region is Ground. That is about physical presence. "
     "Cameras, ambient state, the room itself. This is where the system meets the physical world. "
     "Below that, Watershed. Flow and routing. "
     "How information moves through the system. Which processes feed into which others. "
     "And at the bottom, Bedrock. Infrastructure. "
     "Health checks, GPU memory, governance, consent status, accommodations. "
     "The foundations that everything else depends on."
    ),

    ("05-depth-demo",
     "Each region has three depths. This is the key interaction pattern. "
     "Surface shows minimal information. A sentence or two. A few status dots. "
     "This is the system at rest. Awareness without demand. "
     "Stratum expands into panels and grids. "
     "You see structure. The agent list, the camera grid, the governance panels. "
     "Core opens into full detail. "
     "The perception canvas fills the Field region. The hero camera fills Ground. "
     "The flow topology graph fills Watershed. "
     "You cycle depth by clicking a region or pressing its keyboard shortcut. "
     "Surface is calm. Stratum is informational. Core is immersive. "
     "Every region follows this same progression. "
     "The idea is that awareness should scale with attention. "
     "When you are not looking at something, it should be quiet. "
     "When you focus on it, it should open up."
    ),

    ("06-horizon",
     "Let me take you into Horizon. "
     "What you are seeing now is the expanded view. "
     "On the left, goals. Things I have told the system I am working toward. It tracks progress automatically. "
     "In the center, nudges. This is the executive function in action. "
     "The system notices open loops. Stale work. Overdue follow-ups. "
     "Drift between what documentation says and what the code actually does. "
     "It surfaces these as nudges with priority scores and suggested actions. "
     "Think of it as the part of your brain that taps your shoulder and says, you forgot about that thing. "
     "Except this one actually works consistently. "
     "On the right, the reactive engine. "
     "This is the filesystem-as-bus architecture. "
     "When a file changes on disk, rules fire, actions cascade. "
     "Deterministic work runs first, synchronously. "
     "Then language-model-driven synthesis, bounded by a concurrency semaphore so the GPU does not get saturated. "
     "Below everything, a daily briefing. "
     "Every morning at seven, the system synthesizes the last twenty-four hours into a headline and action items. "
     "Meeting preparation generates at six thirty. "
     "By the time I sit down, the system has already thought about my day."
    ),

    ("07-field-perception",
     "Now Field. This is where perception lives. "
     "What you are looking at is the perception canvas. "
     "The system runs a continuous perception loop every two and a half seconds. "
     "It fuses data from cameras, microphones, desktop focus tracking, and the watch. "
     "The result is a unified picture of what is happening in the physical environment. "
     "The zones overlaid on this canvas represent signal categories. "
     "Time context in the top left. Governance in the top right. "
     "Work signals on the left side. Infrastructure in the bottom right. "
     "Profile state at the top center. Ambient sensor readings at the bottom. "
     "Each signal has a severity between zero and one. "
     "Here is the subtle thing to notice. Higher severity makes a signal breathe faster. "
     "At low severity, a gentle eight-second pulse. Barely perceptible. "
     "At high severity, less than a second. Urgent. Impossible to ignore. "
     "This is not decoration. The system uses these severity levels to modulate its own behavior. "
     "When infrastructure degrades, the voice system becomes more concise. "
     "When operator stress is elevated, it adjusts its tone. "
     "That modulation comes from something called stimmung, which I will explain shortly."
    ),

    ("08-agents",
     "Underneath all of this are forty-five agents organized in three tiers. "
     "Tier one is interactive. This interface you are looking at. A voice system that is always listening. "
     "And the command-line integration that is how the system was built and is maintained. "
     "Tier two is on-demand. These are language-model-driven agents. "
     "A briefing agent synthesizes the day. A health monitor runs eighty-five checks across every service. "
     "A drift detector compares documentation to implementation and flags divergence. "
     "A scout agent watches for relevant technology updates. "
     "A profiler builds an understanding of my patterns over time. "
     "A management agent prepares context for one-on-one meetings. "
     "That last one has a hard constraint. It can prepare factual context. It cannot generate feedback language. "
     "The system prepares. The human delivers. That is an axiom. "
     "Tier three runs autonomously on timers. "
     "A RAG ingest pipeline watches for new documents and embeds them into a vector database. "
     "Health monitoring runs every fifteen minutes. Knowledge maintenance prunes stale vectors weekly. "
     "All agents are stateless. They read from the filesystem and vector database, produce output, and terminate. "
     "No agent calls another agent. Flat orchestration. Cascading failures cannot happen. "
     "This is a deliberate architectural choice. "
     "If an agent crashes, nothing else is affected. The call graph stays auditable."
    ),

    ("09-ground-ambient",
     "Now I want to show you Ground properly. "
     "What you are looking at right now is Ground at surface depth. "
     "The warm tones. The drifting organic shapes. The slowly cycling text fragments. "
     "Phrases like 'externalized executive function' and 'consent must thread invariantly' float through on twelve-second cycles. "
     "This is the ambient canvas. It is what Ground looks like when nothing is demanding attention. "
     "It is deliberately calm. "
     "The visual equivalent of a room with good lighting and no notifications."
    ),

    ("10-ground-cameras",
     "Now watch what happens when Ground expands. "
     "Stratum. The camera grid appears. Six feeds in a two-column layout. "
     "The borders are color-coded. Red means recording. Amber means stale. Green means active. Grey means inactive. "
     "Three of these are high-resolution Logitech BRIO units. Three are standard C920 units. "
     "Three more infrared cameras are on the way for night vision perception. "
     "And now core. The hero camera fills the region. "
     "The colored outlines you see on objects and people are detection overlays. "
     "Person detections are color-coded by gaze direction. "
     "Cyan means looking at a screen. Yellow means looking at hardware. Purple means looking at another person. A muted sage for looking away. "
     "Emotion classification adds a secondary tint. Happy is green. Sad is blue. Angry is red. "
     "Someone who has been sitting still for more than a minute shifts toward cool blue. Someone moving shifts toward warm yellow. "
     "Non-person entities are drawn dimmer. Furniture, instruments, electronics, containers. "
     "And the consent constraint is visible live. "
     "Any person without a consent contract is drawn fully desaturated. Grey. "
     "The system acknowledges presence but structurally refuses to characterize it."
    ),

    ("11-effects",
     "Ground also hosts a visual compositor with thirteen effect presets. "
     "I will cycle through a few of them. "
     "Ghost. Transparent echoes with fading four-frame trails. Subtle pan and zoom drift. "
     "Trails. Bright additive motion with hue shifting. "
     "Screwed. Named after Houston chopped-and-screwed music. "
     "Heavy warping, band displacement, syrup gradients, stutter phases. "
     "The visual equivalent of slowed, pitched-down production. "
     "Datamosh. Simulated codec glitch artifacts. Difference blending with high contrast. "
     "VHS. Lo-fi tape warmth. Soft blur, sepia tone, tracking noise, intermittent stutters. "
     "Neon. Color-cycling glow with four-degree hue rotation per tick. "
     "Night Vision. Green phosphor monochrome with scanlines. Optimized for the infrared cameras. "
     "Thermal. Inverted monochrome with hue rotation for heat-map appearance. "
     "This is not a toy. "
     "I produce music and stream live. These effects composite in real time over camera feeds during production sessions. "
     "The compositor runs a dual ring buffer canvas. "
     "One buffer for live frames polled at one hundred millisecond intervals. "
     "One for delayed overlay frames at two hundred milliseconds with a three-frame offset. "
     "This enables temporal effects like trails and ghosting. "
     "Same architecture as a broadcast video switcher."
    ),

    ("12-stimmung",
     "Now the concept I mentioned earlier. Stimmung. "
     "It is a German word. Heidegger used it to mean attunement. "
     "The idea is that you never perceive the world neutrally. "
     "You are always already in some mood that structures how things show up for you. "
     "You do not decide to be anxious and then see things as threatening. "
     "The anxiety is already there, shaping what you notice. "
     "In this system, stimmung is an engineering implementation of that idea. "
     "It is a ten-dimensional vector. "
     "Seven dimensions are infrastructure. System health. GPU memory pressure. Error rates. Processing throughput. "
     "Perception confidence. API cost pressure. And the grounding quality score from the voice system. "
     "Three dimensions are biometric. "
     "Operator stress inferred from heart rate variability. "
     "Energy from sleep quality and circadian phase. "
     "Physiological coherence, which is the coefficient of variation across all biometric signals. "
     "The worst dimension determines the overall stance. "
     "Below a certain threshold, nominal. Green borders. Calm. "
     "Higher, cautious. A subtle yellow tint. "
     "Higher still, degraded. Orange borders with a six-second breathing animation. "
     "At the highest level, critical. Red borders breathing every two seconds. "
     "You may have noticed the warm glow on the region borders. That is stimmung. Right now, live. "
     "Here is what makes it more than a dashboard metric. "
     "When stimmung degrades, the entire system pulls back. "
     "The voice system gets more concise. Notifications become less frequent. Effort levels drop. "
     "It is not reporting a problem. It is responding to it. "
     "The way your own mood changes your behavior without you deciding to change it."
    ),

    ("13-watershed",
     "Watershed shows flow. How data and decisions move through the system. "
     "At core depth, it renders a directed acyclic graph. "
     "Nine nodes. Perception, stimmung, temporal bands, apperception, phenomenal context, voice, compositor, the reactive engine, consent. "
     "Edges show which subsystems feed into which others. Active edges are highlighted. "
     "The profile also lives here. Eleven dimensions. "
     "Five are stable traits derived from a structured interview. "
     "Identity. Neurocognitive style. Values. Communication preferences. Relationships. "
     "Six are dynamic behavioral dimensions observed over time. "
     "Work patterns. Energy and attention. Information seeking. Creative process. Tool usage. Communication patterns. "
     "These dimensions shape everything. "
     "How the briefing is structured. How nudges are phrased. "
     "What tone the voice system uses. When to surface information and when to stay quiet."
    ),

    ("14-bedrock",
     "Bedrock is infrastructure and governance. "
     "The health panel runs eighty-five checks. Containers, APIs, databases, GPU state. "
     "The VRAM panel shows memory allocation on the graphics card. "
     "Twenty-four gigabytes shared between local language models, voice synthesis, embedding models, and perception. "
     "Thirteen Docker containers run the services. LiteLLM for API routing. Qdrant for vector storage. "
     "Langfuse for observability. PostgreSQL, Redis, Prometheus, Grafana. "
     "The cost panel tracks daily API spending across Claude and Gemini. "
     "The consent panel shows active contracts and their coverage by data category. "
     "The governance panel shows the axiom compliance heartbeat. A zero-to-one score. "
     "And accommodations. Behavioral adjustments the system has learned to make. "
     "Time anchoring for calendar awareness. Soft framing for notification phrasing. "
     "Energy-aware scheduling that respects circadian patterns. "
     "Peak hours and low hours, observed and respected."
    ),

    ("15-investigation",
     "One more interface element. This overlay opens with a keystroke. "
     "Three tabs. "
     "Chat is a direct conversation with a language model that has full system access. "
     "It can query agent state, run health checks, inspect configuration, search embedded documents. "
     "Insight connects to a retrieval pipeline. "
     "It searches across all embedded documents, agent outputs, and system knowledge. "
     "Results include structured data and Mermaid diagrams. "
     "Demos is a gallery of pre-generated demo recordings. Including, eventually, this one."
    ),

    # ══════════════════════════════════════════════════════════════════════
    # PART 4: GOVERNANCE AND ETHICS (6 min)
    # ══════════════════════════════════════════════════════════════════════

    ("16-axioms",
     "Now the governance model. This matters more than the technology. "
     "Five axioms. Three constitutional, two domain. "
     "First. Single user. This system serves one person. "
     "That is not a limitation. It is a foundational commitment. "
     "Every architectural decision leverages this constraint rather than working around it. "
     "No authentication. No roles. No collaboration features. "
     "Think of it like the difference between building a house for one family versus an apartment complex. "
     "The single-family house can have the kitchen exactly where you want it. "
     "Second. Executive function. The system's purpose is cognitive support. "
     "Zero-configuration agents. Errors that include next actions. Routine work automated. "
     "Third. Interpersonal transparency. The consent rule I described at the beginning. "
     "This axiom has the philosophical weight of a constitutional right. "
     "It cannot be overridden by convenience or optimization. "
     "The two domain axioms. "
     "Management governance. Language models prepare context. Humans deliver feedback. "
     "The system will never generate coaching language about a team member. "
     "Never suggest what to say in a difficult conversation. "
     "It gives you the facts and gets out of the way. "
     "Corporate boundary. Work data stays in employer systems. "
     "This system handles personal and management-practice work only. "
     "Enforcement. Tier zero violations are blocked. "
     "Code that violates a tier-zero implication cannot be committed. "
     "Pre-commit hooks catch it. CI gates catch it. "
     "There is no override. There is no administrator exception. "
     "When a novel situation arises, agents query a database of past decisions called precedents. "
     "No close precedent means escalation to the operator. "
     "Over time, this creates something like interpretive law. A growing body of case decisions."
    ),

    ("17-ethics",
     "The ethical question is worth addressing directly and thoroughly. "
     "A system that continuously perceives its environment raises obvious concerns. "
     "The standard framing is surveillance. Cameras everywhere. Data collection. Loss of privacy. "
     "That framing assumes a specific power structure. "
     "A corporation collecting data about employees. A government watching citizens. "
     "In those cases, the person being observed does not control the system. "
     "Does not know what is stored. Cannot inspect or delete it. "
     "That asymmetry is what makes surveillance harmful. Not the cameras themselves. The power imbalance. "
     "This system inverts every element of that structure. "
     "The person being most observed is the person who built the system, runs it, and controls every data flow. "
     "For everyone else, consent is structurally enforced. Not by policy. Not by promise. By code that prevents storage without a contract. "
     "For the children. Two consent contracts exist. As their legal guardians, we hold those contracts on their behalf. "
     "The contracts specify which data categories are stored. The contracts are inspectable and revocable. "
     "The management governance axiom adds a further layer. "
     "Even with full consent, the system cannot generate feedback or coaching language about any individual. "
     "It can prepare facts. It cannot evaluate people. "
     "The philosophy is not that perception is inherently wrong. "
     "It is that perception without transparency, without consent, and without the ability to revoke, is wrong. "
     "When all three of those conditions are met, the power dynamic is fundamentally different from surveillance."
    ),

    # ══════════════════════════════════════════════════════════════════════
    # PART 5: THE RESEARCH (12 min)
    # ══════════════════════════════════════════════════════════════════════

    ("18-research-transition",
     "Everything I have shown you so far is infrastructure. It works. It runs every day. "
     "Now I want to tell you about the research. "
     "This part is different. It is not finished. It is not proven. "
     "It is a genuine open question being investigated with real methodology. "
     "The research lives in the voice system."
    ),

    ("19-clark-brennan",
     "Every voice AI system on the market uses the same basic approach. "
     "They store facts about you in a profile. When you talk, they retrieve relevant facts and inject them into the conversation. "
     "ChatGPT Memory. Gemini. Alexa. All of them. Profile storage plus retrieval. "
     "There is a linguist named Herbert Clark who spent his career studying something different. "
     "Clark described how humans actually establish mutual understanding in conversation. "
     "He called it grounding. "
     "The key insight is that conversation is not information transfer. It is a collaborative activity. "
     "Both participants work together to reach what Clark called 'sufficient mutual belief of understanding for current purposes.' "
     "That phrase is important. Sufficient for current purposes. "
     "If I say 'pass the salt' at dinner, you do not need to verify that I meant sodium chloride and not potassium chloride. "
     "The grounding requirement is low because the stakes are low. "
     "If I say 'I need you to restructure the deployment architecture,' the grounding requirement is high. "
     "A misunderstanding has real consequences. The amount of work both parties do to ensure understanding scales with what is at stake. "
     "Clark and his colleague Susan Brennan formalized this in 1991. "
     "They described five levels of evidence for understanding, from weakest to strongest. "
     "Continued attention. A relevant next turn. An explicit acknowledgment. "
     "Demonstrating understanding by building on what was said. And verbatim repetition. "
     "No commercial AI system has ever implemented any of this."
    ),

    ("20-why-gap",
     "There is a thirty-five-year gap between that theory and any attempt to implement it. "
     "The reasons are structural, not technical. "
     "Dialogue systems were built by engineers who separated dialogue management from language generation. "
     "Grounding requires both to be unified. "
     "Task-oriented systems like pizza ordering bots optimized for completing the task, not for mutual understanding. "
     "Statistical and then neural approaches made explicit state tracking seem unnecessary. "
     "Transformers appeared to handle conversation without formal grounding mechanisms. "
     "And then in 2024, researchers found something striking. "
     "The technique used to make language models conversational, reinforcement learning from human feedback, "
     "actually suppresses the specific behaviors that grounding requires. "
     "Models trained this way are three times less likely to ask for clarification. "
     "Sixteen times less likely to make follow-up requests. "
     "A separate study by the same research group tested frontier models on a grounding benchmark called Rifts. "
     "All models scored twenty-three percent. Below random chance at thirty-three percent. "
     "The training procedure that makes models agreeable also makes them unable to do the collaborative work that genuine conversation requires. "
     "Think about what that means. "
     "Every major AI assistant on the market has been specifically trained to be bad at the thing humans rely on most in conversation. "
     "A leaked Gemini system prompt from March 2025 illustrates this perfectly. "
     "A user asked Gemini to set an alarm for eight forty-five AM. "
     "The model's internal reasoning spent its entire budget on a four-step decision tree about whether to apply stored style preferences, "
     "concluded it should not, and produced 'Alarm set for eight forty-five AM.' "
     "Correct response. Zero conversational grounding. "
     "It checked a profile, evaluated a trigger, and treated the interaction as a lookup, not a conversation."
    ),

    ("21-voice-architecture",
     "The voice system here is built around two structural concepts. Bands and grounding. "
     "There are two bands. Stable and volatile. "
     "The stable band is a shared anchor. It contains the system's base identity, the operator's communication style, "
     "and a compressed conversation thread. "
     "The thread is critical. It preserves what Clark and Brennan call conceptual pacts. "
     "When two people agree on how to refer to something, that agreement persists. "
     "If you and I start calling the backup server 'the spare,' that is a pact. "
     "If the system suddenly switches to 'the secondary redundancy node,' it breaks the pact. "
     "Brennan showed in 1996 that breaking pacts with a single known partner is maximally costly. "
     "More costly than breaking pacts with a stranger, because the expectation of shared understanding is higher. "
     "The thread uses tiered compression. "
     "Recent entries preserve the operator's exact words. "
     "Middle entries use referring expressions. "
     "Oldest entries reduce to keywords. "
     "This is informed by research on the lost-in-the-middle problem. "
     "Language models attend most strongly to the beginning and end of context, not the middle. "
     "The volatile band changes every turn. Four components. "
     "A conversational policy that specifies how to speak based on the operator's profile and current environment. "
     "A phenomenal context block describing what is happening in the physical environment right now. "
     "A grounding directive from the discourse unit ledger telling the model what to do next. "
     "Advance, rephrase, elaborate, or move on. "
     "And salience context from the concern graph. How much the current topic matters to the operator."
    ),

    ("22-grounding-loop",
     "The grounding loop tracks the state of every discourse unit. "
     "A discourse unit is a chunk of meaning being negotiated between two participants. "
     "When the system says something, it creates a new discourse unit in a pending state. "
     "It then classifies the operator's response as one of four acceptance types. "
     "Accept means understanding was sufficient. "
     "Clarify means partial understanding, more information needed. "
     "Reject means the operator disagrees or does not understand. "
     "Ignore means the operator moved on without engaging. "
     "The discourse unit transitions through states based on these signals. "
     "Pending to grounded on acceptance. "
     "Pending to repair on clarification, with up to two repair attempts before abandoning. "
     "Pending to contested on rejection. Pending to ungrounded on ignore. "
     "The thresholds for these transitions are dynamic. They depend on concern overlap. "
     "High concern plus low grounding quality requires explicit acceptance. "
     "Low concern plus high grounding quality allows the system to accept that being ignored is sufficient. "
     "This is Clark's phrase. Sufficient for current purposes. "
     "The grounding quality index is a composite of four signals. "
     "Fifty percent rolling acceptance rate. Twenty-five percent trend. "
     "Fifteen percent consecutive negative penalty. Ten percent engagement. "
     "Based on this, the system calibrates its effort level. "
     "Elaborative effort at high activation. Efficient effort at low activation. "
     "Escalation is immediate. De-escalation requires two consecutive turns at the lower level. "
     "This prevents oscillation."
    ),

    ("23-salience",
     "The system decides how much cognitive power to apply to each utterance. Based on salience, not complexity. "
     "The model is inspired by Corbetta and Shulman's dual-attention model from neuroscience. "
     "Two streams of attention. "
     "A dorsal stream that is top-down and goal-directed. In this system, that is concern overlap. "
     "How much does this utterance relate to things the operator currently cares about? "
     "Computed as cosine similarity between the utterance embedding and a concern graph in the vector database. "
     "A ventral stream that is bottom-up and stimulus-driven. That is novelty. "
     "How far is this utterance from any known pattern? "
     "A third signal is dialog features. Question versus assertion, hedging, word count. "
     "Weighted. Fifty-five percent concern, fifteen percent novelty, thirty percent dialog features. "
     "The weights shift across a conversation. Early turns rely on dialog features. "
     "As the concern graph accumulates context, concern overlap takes over. "
     "Five model tiers. Below zero point one five, canned responses. "
     "Up to zero point four five, a fast local model on the GPU. "
     "Up to zero point six, Gemini Flash. Up to zero point seven eight, Claude Sonnet. "
     "Above that, Claude Opus. "
     "One hard rule. Intelligence is the last thing shed. "
     "Consent refusals always get the best model. Guest present, always the best model. "
     "You never save money at the cost of handling a sensitive situation poorly."
    ),

    ("24-research-methodology",
     "Here is where I want to be precise, because this matters. "
     "The methodology is called single-case experimental design. SCED. "
     "It is the established framework from clinical psychology for rigorous single-subject research. "
     "Not a case study. Not anecdotal. A formal experimental design with baselines, treatments, and reversals. "
     "The design is A-B-A. Baseline. Treatment. Reversal. "
     "You measure natural behavior. Introduce the treatment. Then remove it. "
     "If the measurement reverts, you have causal evidence. "
     "If it does not, the effect may be real but confounded with learning. "
     "There is a known problem with this design for grounding specifically. "
     "Clark's theory predicts that grounding creates persistent knowledge structures. "
     "Once I learn how the system communicates, removing the treatment may not fully undo that learning. "
     "This is called the maturation threat. It is acknowledged in the pre-registration. "
     "The reversal phase exists specifically to test for it. "
     "Partial reversal would suggest both a real effect and a learning component."
    ),

    ("25-honest-assessment",
     "Now the honest part. "
     "Cycle one was a pilot. Thirty-seven sessions. The primary metric was word overlap between consecutive turns. "
     "The result was a Bayes factor of three point six six. Moderate evidence. Inconclusive. "
     "More importantly, the metric was wrong. "
     "Word overlap penalizes abstraction and paraphrasing. "
     "If the system says 'the database' and I respond with 'it,' that is good grounding but poor word overlap. "
     "Six deviations from the pre-registered protocol were documented. "
     "The metric has been replaced with turn-pair coherence measured through semantic embeddings. "
     "Captures meaning similarity, not word matching. "
     "The analysis framework changed from beta-binomial, which was a model misspecification for continuous data, "
     "to Bayesian estimation with a Student-t likelihood. "
     "Full probability distribution over effect size. Not a binary yes-or-no significance test. "
     "The decision criterion uses highest density intervals and a region of practical equivalence. "
     "More conservative than standard significance testing. "
     "Expected effects are modest. Cohen's d of zero point three to zero point six. "
     "About what clinical dialogue interventions produce in the meta-analytic literature. "
     "Power analysis says the probability of achieving strong evidence is forty to fifty percent with twenty sessions per phase. "
     "Most likely the result lands in the moderate range. "
     "This study is underpowered for medium effects. That is stated upfront in the pre-registration. "
     "There is zero external validity. One person. Generalization requires others to try it. "
     "The study is pre-registered before data collection begins. "
     "Hypotheses, metrics, analysis framework, decision criteria. All specified before looking at results. "
     "Results will be published regardless of outcome. "
     "That is the part that separates good science from motivated reasoning. "
     "You specify what you expect. You report what you find. You do not hide null results."
    ),

    ("26-significance",
     "What is actually original here. "
     "The theory is not new. Clark and Brennan is forty years old. Traum's computational model is thirty. "
     "What is original is the implementation. "
     "No one has built grounding infrastructure into a production voice system. "
     "No one has tested it with a real user over sustained daily use. "
     "No research prototype has attempted it at this scale. "
     "The RLHF finding makes this particularly relevant. "
     "If the training procedure that all frontier models use actively suppresses grounding behaviors, "
     "then the question is whether you can compensate for that externally. "
     "Can you build the grounding loop outside the model and inject it as context? "
     "If yes, the implication is that production voice systems need architectural support for grounding. "
     "Bigger models and better training data are not sufficient. "
     "If no, the implication is that the damage from RLHF requires fine-tuning to repair. "
     "That would be a different kind of contribution. A Cycle three investigation. "
     "Either result is publishable. Either result tells us something we did not know."
    ),

    # ══════════════════════════════════════════════════════════════════════
    # PART 6: PHILOSOPHY AND FOUNDATIONS (5 min)
    # ══════════════════════════════════════════════════════════════════════

    ("27-temporal-bands",
     "One more architectural concept before the philosophy. "
     "The system's perception is organized around a model of temporal experience drawn from Husserl's phenomenology. "
     "Husserl described three aspects of how we experience time. "
     "Retention. The fading echo of what just happened. "
     "Not memory retrieval. The still-present trace. "
     "Like the last few notes of a melody that are still in your awareness even after they have sounded. "
     "Impression. The vivid present. What is happening right now. "
     "Protention. Anticipated near-future. What you expect is about to happen based on current trajectories. "
     "The system implements this with a sixty-entry ring buffer of perception snapshots, "
     "each taken every five hundred milliseconds. "
     "From this buffer, three temporal bands are derived. "
     "Retention samples three entries from the ring. One at five seconds ago. One at fifteen seconds. One at forty seconds. "
     "Each captures flow state, activity mode, audio energy, heart rate, and presence. "
     "Impression is the current snapshot. It includes a surprise field. "
     "The system makes predictions about what will happen next. "
     "When prediction meets actuality, surprise emerges from the mismatch. "
     "Protention uses a statistical prediction engine. "
     "Predictions like 'entering deep work' or 'break likely' or 'stress rising,' each with a confidence score. "
     "These temporal bands feed into the voice system. "
     "It can say 'you have been in deep work for forty minutes' not because it stored that fact, "
     "but because the retention band shows the trajectory. "
     "Not retrieval. Perception of the shape of the recent past."
    ),

    ("28-philosophy",
     "Several philosophical traditions inform the design. They are not decorative. "
     "Each is a case where a philosophical insight solved a real engineering problem. "
     "Heidegger's attunement became stimmung. "
     "The system's mood structures its behavior the way Heidegger described mood structuring perception. "
     "You do not decide to be anxious and then perceive things as threatening. "
     "The anxiety is already there, shaping what shows up for you. "
     "When the system's health degrades, it does not just flag a warning. "
     "The degradation changes how every other subsystem behaves. "
     "Merleau-Ponty's embodied perception shaped the sensor architecture. "
     "Understanding does not come from processing data about the world. "
     "It comes from being situated in the world. "
     "This system has cameras, microphones, biometric sensors. It is physically present in the same room. "
     "Its perception is actively constructed from ongoing sensory input, not retrieved from a database. "
     "Wittgenstein on meaning as use shaped the grounding loop. "
     "Words do not have fixed meanings that are decoded. "
     "They acquire meaning through the collaborative activity of conversation. "
     "That is precisely what Clark formalized. Grounding is a joint activity, not information transfer. "
     "And Husserl on time-consciousness became the temporal bands. "
     "Stimmung solved how a system should modulate its behavior when its own state changes. "
     "Embodied perception solved how it should understand its environment. "
     "Grounding solved how it should maintain mutual understanding. "
     "Temporal bands solved how it should be aware of trajectories, not just snapshots. "
     "These are not references chosen to sound impressive. "
     "They are the actual design rationale. "
     "The engineering problem came first. The philosophical model solved it."
    ),

    # ══════════════════════════════════════════════════════════════════════
    # PART 7: WHAT IS PROVEN AND CLOSING (4 min)
    # ══════════════════════════════════════════════════════════════════════

    ("29-what-is-proven",
     "What is proven. "
     "The infrastructure works. Forty-five agents run reliably. "
     "The reactive engine processes filesystem events. Health monitoring catches failures. "
     "The voice daemon maintains conversation. "
     "The grounding loop classifies acceptance correctly. "
     "The discourse unit state machine transitions properly. "
     "Eighty-five tests verify the grounding implementation. "
     "One hundred ninety-two algebraic property tests verify the type system across ten composition layers. "
     "The governance framework enforces its constraints. "
     "Consent contracts prevent unauthorized storage. Axiom implications block violating code. "
     "What remains to be proven. "
     "Whether grounding infrastructure produces measurable improvement in conversation quality. That is Cycle two. "
     "Whether the treatment components interact as a gestalt or merely add linearly. That requires ablation studies. "
     "Whether prompted models are sufficient or whether the RLHF damage requires fine-tuning. That would be Cycle three. "
     "Whether any of this generalizes beyond one person. That requires conceptual replication by others. "
     "The path is clear. Collect baseline data. Run the A-B-A experiment. "
     "Analyze with Bayesian estimation. Publish regardless of outcome."
    ),

    ("30-closing",
     "This system exists because I needed something that existing software does not provide. "
     "Not productivity tools. Not AI assistants. Cognitive infrastructure. "
     "The research exists because the gap between conversation theory and conversation technology "
     "turned out to be both interesting and tractable. "
     "The governance exists because building a perception system without structural consent constraints "
     "would be irresponsible regardless of intent. "
     "Nothing here is finished. The experiment has not run. The data has not been collected. "
     "The hypothesis may be wrong. "
     "What exists is a system that works, a research program with clear methodology, "
     "and a governance framework that treats ethics as structure rather than policy. "
     "That is Hapax."
    ),

    ("99-outro", "Thank you for your time and attention."),
]
# fmt: on

DEMO_NAME = "alexis-v2-demo"


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_]+", "-", slug).strip("-")[:40]


async def main() -> None:
    output_dir = Path(f"output/demos/{DEMO_NAME}")

    # Clear old
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    audio_dir = output_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    total_words = sum(len(text.split()) for _, text in SCENES)
    print(
        f"Alexis demo v2: {len(SCENES)} scenes, ~{total_words} words (~{total_words / 140:.0f} min at 140 WPM)"
    )

    # ── Render audio ──
    from agents.demo_pipeline.voice import check_elevenlabs_available, generate_all_voice_segments

    backend = "elevenlabs" if check_elevenlabs_available() else "auto"
    print(f"TTS backend: {backend}")

    generate_all_voice_segments(
        SCENES,
        audio_dir,
        on_progress=lambda msg: print(f"  {msg}"),
        backend=backend,
    )

    # No speed adjustment for ElevenLabs (natural pacing)
    if backend != "elevenlabs":
        print("Applying 10% slowdown for Kokoro...")
        for name, _ in SCENES:
            path = audio_dir / f"{name}.wav"
            if path.exists():
                tmp = audio_dir / f"_tmp_{name}.wav"
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(path), "-filter:a", "atempo=0.90", str(tmp)],
                    capture_output=True,
                )
                if tmp.exists():
                    tmp.rename(path)

    # ── Generate riser ──
    print("Generating intro riser...")
    subprocess.run(
        [
            "python3",
            "-c",
            """
import numpy as np, wave
sr, dur, n = 24000, 6.0, int(24000 * 6.0)
t = np.linspace(0, dur, n)
freq = np.exp(np.linspace(np.log(55), np.log(440), n))
p1 = np.cumsum(freq / sr) * 2 * np.pi
p2 = np.cumsum((freq * 1.003) / sr) * 2 * np.pi
p3 = np.cumsum((freq * 0.997) / sr) * 2 * np.pi
osc = (np.sin(p1) + 0.5*np.sin(2*p1) + np.sin(p2) + 0.5*np.sin(2*p2) + np.sin(p3) + 0.5*np.sin(2*p3)) / 3
cut = np.linspace(0.02, 0.3, n)
filt = np.zeros(n); filt[0] = osc[0]
for i in range(1, n): filt[i] = cut[i]*osc[i] + (1-cut[i])*filt[i-1]
sub = 0.3 * np.sin(np.cumsum(np.linspace(40, 80, n) / sr) * 2 * np.pi)
sig = filt * 0.6 + sub
env = np.ones(n)
env[:int(sr*3)] = np.linspace(0, 1, int(sr*3))**2
env[-int(sr*1.5):] = np.linspace(1, 0.3, int(sr*1.5))
sig = sig * env / np.max(np.abs(sig)) * 0.7
pcm = (np.clip(sig, -1, 1) * 32767).astype(np.int16)
with wave.open('"""
            + str(audio_dir / "00-riser.wav")
            + """', 'wb') as wf:
    wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(24000); wf.writeframes(pcm.tobytes())
print('Riser: 6.0s')
""",
        ],
        capture_output=True,
    )

    # ── Choreograph via Opus ──
    print("\nChoreographing UI actions (Opus)...")
    from agents.demo_models import DemoScene, DemoScript
    from agents.demo_pipeline.app_scenes import convert_to_app_scenes
    from agents.demo_pipeline.choreography import choreograph

    # Build a DemoScript from our scenes for choreography
    demo_script = DemoScript(
        title="Hapax",
        audience="family",
        intro_narration=SCENES[0][1],  # 00-intro is the intro
        scenes=[
            DemoScene(
                title=name.split("-", 1)[1].replace("-", " ").title() if "-" in name else name,
                narration=text,
                duration_hint=len(text.split()) / 2.5,
                key_points=[],
            )
            for name, text in SCENES[1:-1]  # skip intro and outro
        ],
        outro_narration=SCENES[-1][1],
    )

    choreography_actions = await choreograph(demo_script, on_progress=lambda msg: print(f"  {msg}"))

    # ── Generate app-script.json ──
    print("\nGenerating app-script.json...")
    convert_to_app_scenes(
        demo_script, output_dir, on_progress=print, choreography=choreography_actions
    )

    # Insert riser as first scene
    import json

    app_script_path = output_dir / "app-script.json"
    scenes_json = json.load(open(app_script_path))
    scenes_json.insert(0, {"title": "", "audioFile": "00-riser.wav", "actions": []})
    app_script_path.write_text(json.dumps(scenes_json, indent=2))

    # ── Report ──
    import wave as wave_mod

    total_dur = 0
    for name, _ in SCENES:
        path = audio_dir / f"{name}.wav"
        if path.exists():
            with wave_mod.open(str(path), "rb") as wf:
                dur = wf.getnframes() / wf.getframerate()
            total_dur += dur

    print("\nDone!")
    print(f"  Audio: {total_dur:.0f}s ({total_dur / 60:.1f} min)")
    print(f"  Scenes: {len(SCENES)}")
    print(f"  URL: http://localhost:5173/?demo={DEMO_NAME}")


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(line_buffering=True)
    asyncio.run(main())
