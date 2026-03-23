"""Render narration audio for Alexis demo.

Usage: uv run python scripts/render_alexis_demo.py
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

# fmt: off
SCENES: list[tuple[str, str]] = [

    # ── 0: OPENING — CONSENT WITH CONTEXT ───────────────────────────────
    ("00-intro",
     "You know I have been building something. You know it started as a way to help with executive function. "
     "What you have not seen is what it became. "
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
     "I will come back to the ethics of this in detail later. For now, that is the foundation."
    ),

    # ── 1: WHAT IS HAPAX ────────────────────────────────────────────────
    ("01-what-is-hapax",
     "So. What is Hapax. "
     "Executive function is the set of cognitive processes that handle task initiation, sustained attention, keeping track of open loops, and maintaining routines. "
     "Think of it as the background operating system of a brain. "
     "For most people it runs automatically. You remember to follow up on that email. You notice a deadline coming. "
     "You keep five things in working memory without thinking about it. "
     "For people with ADHD, those processes are not absent. They are unreliable. "
     "Hapax is an attempt to build infrastructure that performs those functions externally. "
     "Not a to-do list. Not a reminder app. "
     "A system that actually tracks open loops, notices when things drift, surfaces what needs attention, "
     "and maintains awareness of the physical and cognitive environment. "
     "Seven repositories. Forty-five agents. A voice system. Camera feeds. Biometric streaming. A reactive engine. "
     "Everything runs locally on this workstation. No cloud service owns the data."
    ),

    # ── 2: FIRST LOOK AT THE TERRAIN ────────────────────────────────────
    ("02-terrain-intro",
     "Now let me orient you to what you are seeing. "
     "This is going to look like nothing you have encountered before. There is no precedent for this layout in conventional software. "
     "The screen is divided into five horizontal regions. Each one will glow or breathe depending on system state. "
     "I am going to expand each region one at a time so you can see what lives inside."
    ),

    # ── 3: TERRAIN WALKTHROUGH ──────────────────────────────────────────
    ("03-terrain-walk",
     "This top region is called Horizon. It holds time-oriented information. What is coming, what needs attention. "
     "Below it is Field. That is where agents and perception live. What the system knows, what sensors detect. "
     "The middle region is Ground. That is about physical presence. Cameras, ambient state, the room itself. "
     "Below that, Watershed. Flow and routing. How information moves through the system. "
     "And at the bottom, Bedrock. Infrastructure. Health checks, GPU memory, governance, consent status. "
     "Each region has three depths. Surface shows a sentence or two. "
     "Stratum expands into panels. "
     "Core opens into full detail. "
     "Watch what happens when I cycle the depth on Ground."
    ),

    # ── 4: DEPTH DEMO ───────────────────────────────────────────────────
    ("04-depth-demo",
     "This is Ground at surface depth. The warm drifting shapes and slowly cycling text. "
     "That ambient canvas is always here. Phrases like 'externalized executive function' float through. "
     "Now stratum. A camera grid appears. Six feeds, color-coded borders. "
     "And core. A single hero camera fills the region. Detection overlays appear. "
     "I will come back to all of this. For now, notice the pattern. "
     "Surface is calm. Stratum is informational. Core is immersive. "
     "Every region follows this same progression."
    ),

    # ── 5: HORIZON DEEP ────────────────────────────────────────────────
    ("05-horizon",
     "Let me take you into Horizon. "
     "What you are seeing now is the expanded view. "
     "On the left, goals. Things I have told the system I am working toward. It tracks progress. "
     "In the center, nudges. This is the executive function in action. "
     "The system notices open loops. Stale work. Overdue follow-ups. "
     "Drift between what documentation says and what the code actually does. "
     "It surfaces these as nudges with priority scores. "
     "Think of it as the part of your brain that taps your shoulder and says, you forgot about that thing. "
     "Except this one actually works consistently. "
     "On the right, the reactive engine. "
     "When a file changes on disk, rules fire, actions cascade. "
     "Deterministic work runs first. Then language-model synthesis, bounded by concurrency limits. "
     "Below everything, a daily briefing. The last twenty-four hours, synthesized into a headline and action items."
    ),

    # ── 6: FIELD AND PERCEPTION ─────────────────────────────────────────
    ("06-field",
     "Now Field. This is where perception lives. "
     "What you are looking at is the perception canvas. "
     "The system runs a continuous perception loop every two and a half seconds. "
     "It fuses data from cameras, microphones, desktop focus tracking, and the watch. "
     "The zones overlaid on this canvas represent signal categories. "
     "Time context in the top left. Governance in the top right. Work signals on the left side. Infrastructure in the bottom right. "
     "Each signal has a severity between zero and one. "
     "Here is the subtle thing to notice. Higher severity makes a signal breathe faster. "
     "Low severity, a gentle eight-second pulse. High severity, less than a second. Urgent. "
     "This is not decoration. The system uses these levels to modulate its own behavior. "
     "When infrastructure degrades, the voice system becomes more concise. "
     "When stress is elevated, it adjusts its tone. "
     "That modulation comes from something called stimmung, which I will explain shortly."
    ),

    # ── 7: AGENTS ───────────────────────────────────────────────────────
    ("07-agents",
     "Underneath all of this are forty-five agents in three tiers. "
     "Tier one is interactive. This interface. A voice system that is always listening. And the command-line tool that built everything. "
     "Tier two is on-demand. Language-model-driven. "
     "A briefing agent synthesizes the day. A health monitor runs eighty-five checks. "
     "A drift detector compares documentation to reality. A scout watches for technology updates. "
     "A profiler builds an understanding of my patterns. "
     "A management agent prepares context for one-on-one meetings. "
     "That last one has a hard constraint. It can prepare factual context. It cannot generate feedback language. "
     "The system prepares. The human delivers. That is an axiom. "
     "Tier three runs autonomously on timers. Document ingestion. Health monitoring. Weekly knowledge maintenance. "
     "All agents are stateless. They read, produce output, terminate. "
     "No agent calls another agent. Flat orchestration. Cascading failures cannot happen."
    ),

    # ── 8: GROUND AMBIENT ──────────────────────────────────────────────
    ("08-ground-ambient",
     "Now I want to show you Ground properly. "
     "What you are looking at right now is Ground at surface depth. "
     "The warm tones, the drifting organic shapes, the slowly cycling text fragments. "
     "This is the ambient canvas. It is what Ground looks like when nothing is demanding attention. "
     "It is deliberately calm. The visual equivalent of a room with good lighting."
    ),

    # ── 9: GROUND CAMERAS ──────────────────────────────────────────────
    ("09-ground-cameras",
     "Now watch what happens when Ground expands. "
     "Stratum. The camera grid. Six feeds. The borders are color-coded. "
     "Red means recording. Amber means stale. Green means active. Grey means inactive. "
     "And now core. The hero camera fills the region. "
     "The colored outlines you see on objects and people are detection overlays. "
     "Person detections are color-coded by gaze direction. "
     "Cyan means looking at a screen. Yellow means looking at hardware. Purple means looking at another person. A muted sage for looking away. "
     "Emotion classification adds a secondary tint. Happy is green. Sad is blue. Angry is red. "
     "Someone still for more than a minute shifts toward cool blue. Someone moving shifts warm. "
     "And the consent constraint you can see live. "
     "Any person without a consent contract is drawn fully desaturated. Grey. "
     "The system acknowledges presence but refuses to characterize it."
    ),

    # ── 10: EFFECTS ─────────────────────────────────────────────────────
    ("10-effects",
     "Ground also hosts a visual compositor. "
     "Thirteen effect presets. I will cycle through a few. "
     "Ghost. Transparent echoes with fading trails. "
     "Trails. Bright additive motion with hue shifting. "
     "Screwed. Named after Houston chopped-and-screwed music. Heavy warping, syrup gradients. "
     "Datamosh. Simulated codec glitch artifacts. "
     "VHS. Tape warmth and tracking noise. "
     "Neon. Hue-rotated glow cycling. "
     "Night Vision. Green phosphor monochrome. "
     "Thermal. Heat map appearance. "
     "This is not a toy. "
     "I produce music and stream live. These effects composite in real time over camera feeds during production. "
     "The compositor runs a dual ring buffer. One for live frames, one for delayed overlay with a three-frame offset. "
     "Same architecture as a broadcast video switcher."
    ),

    # ── 11: STIMMUNG ───────────────────────────────────────────────────
    ("11-stimmung",
     "Now the concept I mentioned earlier. Stimmung. "
     "It is a German word. Heidegger used it to mean attunement. "
     "The idea is that you never perceive the world neutrally. "
     "You are always already in some mood that structures how things show up for you. "
     "You do not decide to be anxious and then see things as threatening. The anxiety is already there, shaping what you notice. "
     "In this system, stimmung is an engineering implementation of that idea. "
     "Ten dimensions. Seven are infrastructure. Health, GPU pressure, error rates, throughput, perception confidence, cost pressure, and voice grounding quality. "
     "Three are biometric. Stress from heart rate variability. Energy from sleep and circadian phase. "
     "Physiological coherence from the variation across biometric signals. "
     "The worst dimension sets the overall stance. "
     "Nominal. Green borders. Cautious. Yellow. Degraded. Orange with a breathing animation. Critical. Red, breathing fast. "
     "You may have noticed the warm glow on the region borders. That is stimmung. Right now, live. "
     "When stimmung degrades, the entire system pulls back. "
     "The voice system gets more concise. Notifications reduce. Effort levels drop. "
     "It is not a dashboard metric. It is a self-regulating mechanism."
    ),

    # ── 12: WATERSHED ──────────────────────────────────────────────────
    ("12-watershed",
     "Watershed shows flow. "
     "At core depth, a graph of how subsystems connect. "
     "Perception feeds stimmung. Stimmung feeds voice. The engine watches the filesystem. Consent gates everything. "
     "The profile lives here too. Eleven dimensions. "
     "Five stable traits from a structured interview. Identity, cognitive style, values, communication preferences, relationships. "
     "Six dynamic behavioral dimensions observed over time. Work patterns, energy, information seeking, creative process, tool usage, communication. "
     "These shape everything. Briefing structure. Nudge phrasing. Voice personality. When to surface information and when to stay quiet."
    ),

    # ── 13: BEDROCK ────────────────────────────────────────────────────
    ("13-bedrock",
     "Bedrock. Infrastructure and governance. "
     "Health. Eighty-five checks across containers, APIs, databases, GPU state. "
     "VRAM. Twenty-four gigabytes on the graphics card, shared between local models, voice synthesis, embeddings, and perception. "
     "Containers. Thirteen Docker services. Cost tracking. "
     "The consent panel shows active contracts. "
     "The governance panel shows the axiom compliance heartbeat. "
     "And accommodations. Behavioral adjustments the system has learned. "
     "Time anchoring for calendar awareness. Soft framing for ADHD-friendly phrasing. "
     "Energy-aware scheduling that respects circadian patterns."
    ),

    # ── 14: INVESTIGATION ──────────────────────────────────────────────
    ("14-investigation",
     "One more interface element. This overlay opens with a keystroke. "
     "Three tabs. Chat is a direct conversation with a language model that has full system access. "
     "Insight connects to embedded document search. "
     "Demos is a gallery of recordings like this one."
    ),

    # ── 15: AXIOMS ─────────────────────────────────────────────────────
    ("15-axioms",
     "Now the governance model. This matters. "
     "Five axioms. Three constitutional, two domain. "
     "First. Single user. This system serves one person. "
     "That is not a limitation. It is a foundational commitment. Every architectural decision leverages this constraint. "
     "No authentication. No roles. No collaboration features. "
     "Think of it like the difference between building a house for one family versus an apartment complex. "
     "The single-family house can have the kitchen exactly where you want it. "
     "Second. Executive function. The system exists as cognitive support. "
     "Zero-configuration agents. Errors that include next actions. Routine work automated. "
     "Third. Interpersonal transparency. The consent rule I described at the beginning. "
     "This axiom has the weight of a constitutional right. It cannot be overridden by convenience or optimization. "
     "The two domain axioms. "
     "Management governance. Language models prepare context. Humans deliver feedback. "
     "The system will never generate coaching language about a team member. Never suggest what to say in a difficult conversation. "
     "It gives you facts and gets out of the way. "
     "Corporate boundary. Work data stays in employer systems. This system handles personal and management-practice work only. "
     "Enforcement. Tier zero violations are blocked. Code violating a tier-zero implication cannot be committed. "
     "Pre-commit hooks catch it. CI gates catch it. There is no override. There is no administrator exception. "
     "When a novel situation arises, agents query a database of past decisions called precedents. "
     "No close precedent means escalation to the operator. This creates interpretive law over time."
    ),

    # ── 16: ETHICS ─────────────────────────────────────────────────────
    ("16-ethics",
     "The ethical question is worth addressing directly. "
     "A system that continuously perceives its environment raises obvious concerns. "
     "The standard framing is surveillance. Cameras everywhere. Data collection. Loss of privacy. "
     "That framing assumes a specific power structure. "
     "A corporation collecting data about employees. A government watching citizens. "
     "In those cases, the person being observed does not control the system. Does not know what is stored. Cannot inspect or delete it. "
     "That asymmetry is what makes surveillance harmful. "
     "This system inverts every element of that structure. "
     "The person being most observed is the person who built the system, runs it, and controls every data flow. "
     "For everyone else, consent is structurally enforced. Not by policy. Not by promise. By code. "
     "For the children. Two consent contracts exist. As their legal guardians, we hold those contracts. "
     "The contracts specify what data categories are stored. They are inspectable. They are revocable. "
     "Even with full consent, the system cannot generate feedback or coaching language about any individual. "
     "It can prepare facts. It cannot evaluate people. "
     "The philosophy is not that perception is wrong. "
     "It is that perception without transparency, without consent, and without the ability to revoke, is wrong. "
     "When all three conditions are met, the power dynamic is fundamentally different from surveillance."
    ),

    # ── 17: TRANSITION TO RESEARCH ─────────────────────────────────────
    ("17-research-intro",
     "Everything I have shown you so far is infrastructure. It works. It runs every day. "
     "Now I want to tell you about the research. "
     "This part is different. It is not finished. It is not proven. "
     "It is a genuine open question being investigated with real methodology. "
     "The research lives in the voice system."
    ),

    # ── 18: CLARK AND BRENNAN ──────────────────────────────────────────
    ("18-clark",
     "Every voice AI system on the market uses the same basic approach. "
     "They store facts about you in a profile. When you talk, they retrieve relevant facts and inject them. "
     "ChatGPT Memory. Gemini. Alexa. All of them. Profile storage plus retrieval. "
     "There is a linguist named Herbert Clark who spent his career studying something different. "
     "Clark described how humans actually establish mutual understanding in conversation. He called it grounding. "
     "The key insight is that conversation is not information transfer. It is a collaborative activity. "
     "Both participants work together to reach what Clark called 'sufficient mutual belief of understanding for current purposes.' "
     "That phrase matters. Sufficient for current purposes. "
     "If I say 'pass the salt,' you do not need to verify I mean sodium chloride. The stakes are low. The grounding requirement is low. "
     "If I say 'I need you to restructure the deployment architecture,' the grounding requirement is high. A misunderstanding has consequences. "
     "Clark and Susan Brennan formalized this in 1991. "
     "No commercial AI system has ever implemented it."
    ),

    # ── 19: WHY THE GAP ────────────────────────────────────────────────
    ("19-why-gap",
     "There is a thirty-five-year gap between that theory and any attempt to implement it. The reasons are structural. "
     "Dialogue systems separated management from generation. Grounding requires both unified. "
     "Task-oriented bots optimized for completing the task, not mutual understanding. "
     "Neural approaches made explicit state tracking seem unnecessary. "
     "And then in 2024, researchers found something striking. "
     "The technique used to make language models conversational, reinforcement learning from human feedback, "
     "actually suppresses the behaviors grounding requires. "
     "Models trained this way are three times less likely to ask for clarification. Sixteen times less likely to follow up. "
     "A separate study tested frontier models on a grounding benchmark. All scored below random chance. "
     "The training that makes models agreeable also makes them unable to do the collaborative work that real conversation requires. "
     "Every major AI assistant on the market has been specifically trained to be bad at the thing humans rely on most in conversation."
    ),

    # ── 20: THE ARCHITECTURE ───────────────────────────────────────────
    ("20-architecture",
     "The voice system here is built around two concepts. Bands and grounding. "
     "Two bands. Stable and volatile. "
     "The stable band is a shared anchor. System identity. Operator communication style. "
     "And a compressed conversation thread. "
     "The thread preserves what Clark called conceptual pacts. "
     "When two people agree on how to refer to something, that agreement persists. "
     "If we start calling the backup server 'the spare,' that is a pact. "
     "If the system suddenly says 'the secondary redundancy node,' it breaks the pact. "
     "Brennan showed that breaking pacts with a known partner is maximally costly. "
     "The volatile band changes every turn. Current environment. Perception state. "
     "A grounding directive from the discourse tracker. And salience context. "
     "The grounding loop tracks every chunk of meaning being negotiated. "
     "When the system says something, it creates a discourse unit. Then classifies the response. Accept, clarify, reject, or ignore. "
     "If you clarified, it rephrases. If you rejected, it presents reasoning. If you ignored, it lets it go. "
     "The thresholds adapt. When something matters more, it requires stronger evidence of understanding. "
     "When something matters less, being ignored is sufficient. Clark's phrase again. Sufficient for current purposes."
    ),

    # ── 21: SALIENCE ───────────────────────────────────────────────────
    ("21-salience",
     "The system also decides how much cognitive power to apply to each utterance. Based on salience, not complexity. "
     "Two streams of attention, inspired by neuroscience. "
     "Top-down: how much does this relate to things you care about right now? "
     "Bottom-up: how novel or unexpected is it? "
     "High concern plus high novelty gets the best model. Routine greeting gets a small local model. "
     "One hard rule. Intelligence is the last thing shed. "
     "Consent refusals always get the best model. Guest present, always the best model. "
     "You never save money at the cost of handling a sensitive situation poorly."
    ),

    # ── 22: THE SCIENCE ────────────────────────────────────────────────
    ("22-science",
     "Here is where I want to be precise, because this matters. "
     "The methodology is called single-case experimental design. SCED. "
     "It is the established framework from clinical psychology for rigorous single-subject research. "
     "Not a case study. Not anecdotal. A formal experimental design with baselines, treatments, and reversals. "
     "The design is A-B-A. Baseline. Treatment. Reversal. "
     "You measure natural behavior. Introduce the treatment. Then remove it. "
     "If the measurement reverts, you have causal evidence. If it does not, the effect may be real but confounded with learning. "
     "There is a known problem with this design for grounding specifically. "
     "Clark's theory predicts that grounding creates persistent knowledge structures. "
     "Once I learn how the system communicates, removing the treatment may not fully undo that learning. "
     "This is called the maturation threat. It is acknowledged in the pre-registration. "
     "The reversal phase exists specifically to test for it."
    ),

    # ── 23: HONEST ASSESSMENT ──────────────────────────────────────────
    ("23-honesty",
     "Now the honest part. "
     "Cycle one was a pilot. Thirty-seven sessions. The primary metric was word overlap between turns. "
     "The result was moderate evidence. Inconclusive. "
     "And the metric was wrong. Word overlap penalizes abstraction. "
     "If the system says 'the database' and I say 'it,' that is good grounding but poor word overlap. "
     "Six deviations from the protocol were documented. "
     "The metric has been replaced. Turn-pair coherence measured through semantic embeddings. Captures meaning similarity, not word matching. "
     "The analysis framework changed from a model that was wrong for continuous data to one that is appropriate. "
     "Bayesian estimation. Full probability distribution over effect size. Not a binary yes-or-no. "
     "Expected effects are modest. About what clinical dialogue interventions produce. "
     "Power analysis says the probability of strong evidence is forty to fifty percent. "
     "Most likely the result lands in the moderate range. "
     "This study is underpowered for medium effects. That is stated upfront. "
     "There is zero external validity. One person. Generalization requires others to try it. "
     "The study is pre-registered before data collection. "
     "Hypotheses, metrics, analysis, decision criteria. All specified before looking at results. "
     "Results published regardless of outcome. "
     "That is the part that separates science from motivated reasoning. "
     "You specify what you expect. You report what you find. You do not hide null results."
    ),

    # ── 24: SIGNIFICANCE ───────────────────────────────────────────────
    ("24-significance",
     "What is actually original here. "
     "The theory is not new. Clark and Brennan is forty years old. "
     "What is original is the implementation. "
     "No one has built grounding infrastructure into a production voice system. "
     "No one has tested it with a real user over sustained daily use. "
     "The RLHF finding makes it relevant. "
     "If the training procedure all frontier models use suppresses grounding behaviors, "
     "the question is whether you can compensate externally. "
     "Build the grounding loop outside the model. Inject it as context. "
     "If yes, production voice systems need architectural support for grounding. Bigger models are not enough. "
     "If no, RLHF damage requires fine-tuning. Different contribution. "
     "Either result is publishable. Either tells us something we did not know."
    ),

    # ── 25: TEMPORAL BANDS ─────────────────────────────────────────────
    ("25-temporal",
     "One more concept. The system's perception is organized around a model of temporal experience from Husserl. "
     "Three aspects of how we experience time. "
     "Retention. The fading echo of what just happened. "
     "Not memory retrieval. The still-present trace. "
     "Like the last few notes of a melody still in your awareness after they have sounded. "
     "Impression. The vivid present. "
     "Protention. Anticipated near-future based on current trajectories. "
     "The system implements this with a ring buffer of perception snapshots. "
     "Retention samples three points. Five, fifteen, and forty seconds ago. "
     "Impression is the current snapshot, with a surprise field. Prediction meets actuality. Mismatch is surprise. "
     "Protention uses statistical predictions. Entering deep work. Break likely. Stress rising. "
     "The voice system receives these temporal bands. "
     "It can say 'you have been in deep work for forty minutes' because the retention band shows the trajectory. "
     "Not because it stored a fact. Because it can see the shape of the recent past."
    ),

    # ── 26: PHILOSOPHY ─────────────────────────────────────────────────
    ("26-philosophy",
     "Several philosophical traditions inform the design. They are not decorative. "
     "Heidegger's attunement became stimmung. The system's mood structures its behavior the way Heidegger described mood structuring perception. "
     "Merleau-Ponty's embodied perception shaped the sensor architecture. "
     "Understanding comes from being situated, not from processing data about the world. "
     "This system has cameras, microphones, biometric sensors. It is physically present in the same room. "
     "Wittgenstein on meaning as use shaped the grounding loop. "
     "Words acquire meaning through collaborative activity. That is what Clark formalized. "
     "And Husserl on time-consciousness became the temporal bands. "
     "Each is a case where a philosophical insight solved a real engineering problem. "
     "Stimmung solved how a system should modulate its behavior when its own state changes. "
     "Embodied perception solved how it should understand its environment. "
     "Grounding solved how it should maintain mutual understanding. "
     "Temporal bands solved how it should be aware of trajectories, not just snapshots."
    ),

    # ── 27: WHAT IS PROVEN ─────────────────────────────────────────────
    ("27-proven",
     "What is proven. "
     "The infrastructure works. Forty-five agents. Reactive engine. Health monitoring. "
     "The grounding loop classifies acceptance correctly. Discourse tracking transitions properly. "
     "Eighty-five tests verify grounding. One hundred ninety-two algebraic property tests verify the type system. "
     "What remains. "
     "Whether grounding produces measurable improvement. That is Cycle two. "
     "Whether the components interact as a whole greater than the sum. That requires ablation. "
     "Whether prompted models suffice or RLHF damage requires fine-tuning. Cycle three. "
     "Whether any of this generalizes beyond one person. That requires others. "
     "The path. Collect baseline data. Run the experiment. Analyze. Publish regardless."
    ),

    # ── 28: CLOSING ────────────────────────────────────────────────────
    ("28-closing",
     "This system exists because I needed something that does not exist. "
     "The research exists because the gap between conversation theory and conversation technology "
     "turned out to be both interesting and tractable. "
     "The governance exists because building a perception system without structural consent would be irresponsible. "
     "None of this is finished. The experiment has not run. The hypothesis may be wrong. "
     "What exists is infrastructure that works, a research program with clear methodology, "
     "and a governance framework that treats ethics as structure rather than policy. "
     "That is Hapax."
    ),

    ("99-outro", "Thank you for listening."),
]
# fmt: on


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_]+", "-", slug).strip("-")[:40]


async def main() -> None:
    output_dir = Path("output/demos/alexis-demo/audio")

    # Clear old audio
    if output_dir.exists():
        import shutil

        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    total_words = sum(len(text.split()) for _, text in SCENES)
    print(f"Alexis demo: {len(SCENES)} scenes, ~{total_words} words (~{total_words / 140:.0f} min)")

    from agents.demo_pipeline.voice import generate_all_voice_segments

    generate_all_voice_segments(
        SCENES,
        output_dir,
        on_progress=lambda msg: print(f"  {msg}"),
        backend="auto",
    )

    # Apply 5% speedup
    import shutil
    import subprocess

    if shutil.which("ffmpeg"):
        print("Applying 5% speedup...")
        for name, _ in SCENES:
            path = output_dir / f"{name}.wav"
            if path.exists():
                tmp = output_dir / f"_tmp_{name}.wav"
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(path), "-filter:a", "atempo=1.05", str(tmp)],
                    capture_output=True,
                )
                tmp.rename(path)

    import wave

    total_dur = 0.0
    for name, _ in SCENES:
        path = output_dir / f"{name}.wav"
        if path.exists():
            with wave.open(str(path), "rb") as wf:
                dur = wf.getnframes() / wf.getframerate()
            total_dur += dur
            print(f"  {name}: {dur:.1f}s")

    print(f"\nTotal audio: {total_dur:.0f}s ({total_dur / 60:.1f} min)")


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(line_buffering=True)
    asyncio.run(main())
