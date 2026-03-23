"""Render narration audio for Alexis demo v3.

Revision focus: strip forbidden terms, remove rhetorical hooks,
stay on concepts not infrastructure, let UI show the tech.

Usage: uv run python scripts/render_alexis_demo_v3.py
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
    # PART 1: CONTEXT AND CONSENT
    # ══════════════════════════════════════════════════════════════════════

    ("00-intro",
     "You know I have been building something. You know it started as a way to help with executive function. "
     "What you have not seen is what it became."
    ),

    ("01-consent-context",
     "What you are looking at is called Logos. It is the visual surface of a system called Hapax. "
     "Before anything else, I need to tell you what it sees. "
     "There are cameras in this room. Six of them. "
     "They feed into a perception system that detects people, objects, activity, ambient sound, and lighting. "
     "The system also receives biometric data from my watch. Heart rate, heart rate variability, skin temperature, sleep quality. "
     "Here is the rule that governs all of this. "
     "It is written into the constitutional foundation of the system. "
     "No persistent data about any person other than me may exist without an active, explicit, revocable consent contract. "
     "Right now, it can see you. It knows a person is present. "
     "But it stores nothing about you. No face data. No voice data. No behavioral observations. Nothing. "
     "When you leave this room, every trace of your presence disappears. "
     "If we created a consent contract, it would specify exactly what categories of data are stored. "
     "You could inspect it at any time. Revoke it at any time. "
     "And upon revocation, everything associated with you is deleted. "
     "This is not a privacy policy. It is a structural constraint enforced in the code itself. "
     "There is no setting to turn it off. "
     "Two consent contracts exist for the children. We hold those as their legal guardians. "
     "The contracts specify exactly which data categories are stored. They are inspectable. They are revocable. "
     "Even with full consent, the system cannot generate feedback or evaluate any individual person. "
     "It can prepare facts. It cannot judge."
    ),

    # ══════════════════════════════════════════════════════════════════════
    # PART 2: WHAT IS THIS
    # ══════════════════════════════════════════════════════════════════════

    ("02-what-is-hapax",
     "Executive function is the background operating system of a brain. "
     "Task initiation. Sustained attention. Keeping track of open loops. Maintaining routines. "
     "For most people it runs automatically. You remember to follow up on that email. You notice a deadline coming. "
     "You hold five things in working memory without thinking about it. "
     "For people with ADHD, those processes are not absent. They are unreliable. "
     "Hapax is an attempt to build infrastructure that performs those functions externally. "
     "Not a to-do list. Not a reminder app. "
     "A system that tracks open loops, notices when things drift, surfaces what needs attention, "
     "and maintains awareness of both the physical environment and the cognitive state of the person using it. "
     "Everything runs locally on this machine. No external service owns the data."
    ),

    # ══════════════════════════════════════════════════════════════════════
    # PART 3: THE INTERFACE
    # ══════════════════════════════════════════════════════════════════════

    ("03-why-this-looks-different",
     "This interface is going to look unusual. That is deliberate. "
     "There are no menus. No sidebar. No settings page. "
     "What you see is a spatial layout. Five horizontal regions, each representing a different domain of awareness. "
     "The design philosophy is geological. Layers of awareness stacked vertically, each with depth that can be revealed. "
     "The visual language is warm. Dark tones, amber accents, dense information rendered small. "
     "Nothing is decorative. Every visual element encodes system state. "
     "I am going to walk through each region."
    ),

    ("04-the-five-regions",
     "The top region is called Horizon. It holds what needs attention in time. "
     "What is coming. What the system has synthesized about the last twenty-four hours. "
     "Below it, Field. That is where perception lives. What sensors detect. What agents are doing. "
     "In the middle, Ground. Physical presence. Cameras. The room. "
     "Below that, Watershed. How information flows through the system. "
     "And at the bottom, Bedrock. The foundations. Health, governance, consent."
    ),

    ("05-how-depth-works",
     "Each region has three depths. "
     "Surface shows almost nothing. A sentence. A few status dots. The system at rest. "
     "Stratum expands into panels and structure. "
     "Core opens into full detail. "
     "You cycle through them by clicking. "
     "The idea is that awareness should scale with attention. "
     "When you are not looking at something, it should be quiet. When you focus on it, it opens up."
    ),

    ("06-horizon-detail",
     "Horizon expanded. "
     "On the left, goals. Things I have told the system I am working toward. "
     "In the center, nudges. This is the executive function mechanism. "
     "The system notices open loops. Stale work. Overdue follow-ups. "
     "Drift between what documentation says and what the code actually does. "
     "It surfaces these with priority scores and suggested actions. "
     "The part of your brain that taps your shoulder and says you forgot about something. Except this one is reliable. "
     "A daily briefing synthesizes the last twenty-four hours into a headline and action items. "
     "By the time I sit down in the morning, the system has already thought about my day."
    ),

    ("07-perception",
     "Field at its deepest level. The perception canvas. "
     "The system runs a continuous perception loop every two and a half seconds. "
     "It fuses data from cameras, microphones, desktop focus tracking, and the watch. "
     "The zones overlaid on this view represent different signal categories. "
     "Each signal has a severity between zero and one. "
     "Higher severity makes a signal breathe faster. "
     "At low severity, a gentle eight-second pulse. At high severity, less than a second. "
     "The system uses these levels to modulate its own behavior. "
     "When infrastructure degrades, the voice system becomes more concise. "
     "When stress is elevated, it adjusts its tone."
    ),

    ("08-agents-overview",
     "Forty-five specialized programs run underneath all of this. "
     "Some are interactive, like this interface and the voice system. "
     "Some run on demand. A briefing agent synthesizes the day. A health monitor checks everything regularly. "
     "A drift detector compares what documentation says to what actually exists. "
     "A profiler builds an understanding of my patterns over time. "
     "A management agent prepares context for one-on-one meetings, but it has a hard constraint. "
     "It can prepare factual context. It cannot generate feedback language about any individual person. "
     "The system prepares. The human delivers. "
     "Some programs run autonomously on timers. Document ingestion. Health checks. Weekly maintenance. "
     "All of them are stateless. They read, produce output, and stop. "
     "None of them call each other. If one fails, nothing else is affected."
    ),

    ("09-ground-and-cameras",
     "Ground at surface depth. The warm drifting shapes and slowly cycling text. "
     "This is the ambient canvas. What Ground looks like when nothing is demanding attention. "
     "The visual equivalent of a room with good lighting and no notifications. "
     "When Ground expands, camera feeds appear. Six cameras. "
     "At core depth, a single feed fills the view with detection overlays. "
     "Person detections are colored by gaze direction. "
     "Cyan means looking at a screen. Yellow, hardware. Purple, another person. Muted sage, looking away. "
     "Emotion classification adds a secondary tint. "
     "Someone still for more than a minute shifts toward cool blue. Someone moving shifts warm. "
     "And the consent constraint is visible live. "
     "Any person without a consent contract is drawn fully desaturated. Grey. "
     "The system acknowledges their presence but refuses to characterize them."
    ),

    ("10-compositor",
     "Ground also hosts a visual compositor with thirteen effect presets. "
     "Ghost. Transparent echoes with fading trails. "
     "Screwed. Named after Houston chopped-and-screwed music. Heavy warping, syrup gradients. "
     "Datamosh. Glitch artifacts. VHS. Tape warmth. Neon. Cycling glow. "
     "Night Vision. Green phosphor. Thermal. Heat map. "
     "I produce music and stream live. These composite in real time over camera feeds during production. "
     "The underlying architecture is a dual ring buffer, the same structure used in broadcast video switching."
    ),

    ("11-stimmung",
     "Now a concept that connects everything. Stimmung. "
     "A German word. Heidegger used it to mean attunement. "
     "The idea is that you never perceive the world neutrally. "
     "You are always already in some mood that structures how things show up for you. "
     "You do not decide to be anxious and then see things as threatening. "
     "The anxiety is already there, shaping what you notice. "
     "In this system, stimmung is an engineering implementation of that idea. "
     "A ten-dimensional vector combining infrastructure health and biometric state. "
     "The worst dimension determines the overall stance. "
     "Nominal. Green borders. Calm. "
     "Cautious. Subtle yellow. "
     "Degraded. Orange borders with a slow breathing animation. "
     "Critical. Red borders breathing fast. "
     "You may have noticed the warm glow on the region borders. That is stimmung. Right now. Live. "
     "When stimmung degrades, the entire system pulls back. "
     "The voice system gets more concise. Notifications reduce. "
     "It is not reporting a problem. It is responding to it. "
     "The way your own mood changes your behavior without you deciding to change it."
    ),

    ("12-watershed-and-profile",
     "Watershed shows how subsystems connect to each other. "
     "It also holds the operator profile. Eleven dimensions. "
     "Five stable traits from a structured interview. Identity, cognitive style, values, communication preferences, relationships. "
     "Six dynamic dimensions observed over time. Work patterns, energy, information seeking, creative process. "
     "These shape everything the system does. "
     "How the briefing is structured. How nudges are phrased. What tone the voice system uses. "
     "When to surface information and when to stay quiet."
    ),

    ("13-bedrock-and-governance",
     "Bedrock shows the foundations. "
     "System health. Resource allocation. Consent contracts and their coverage. "
     "The governance heartbeat, a zero-to-one score of axiom compliance. "
     "And accommodations. Behavioral adjustments the system has learned to make. "
     "Time anchoring for calendar awareness. Soft framing for how notifications are phrased. "
     "Energy-aware scheduling that respects circadian patterns."
    ),

    ("14-investigation",
     "One more interface element. This overlay opens with a keystroke. "
     "Three tabs. A direct conversation with a language model that has full system access. "
     "A search interface across all embedded documents. "
     "And a gallery of demo recordings. Including, eventually, this one."
    ),

    # ══════════════════════════════════════════════════════════════════════
    # PART 4: GOVERNANCE AND ETHICS
    # ══════════════════════════════════════════════════════════════════════

    ("15-the-axioms",
     "The governance model. This matters more than the technology. "
     "Five axioms. Three constitutional, two domain-specific. "
     "Single user. This system serves one person. "
     "That is not a limitation. It is a foundational commitment that shapes every design decision. "
     "The analogy is building a house for one family versus an apartment complex. "
     "The single-family house can have the kitchen exactly where you want it. "
     "Executive function. The system exists as cognitive support. "
     "Interpersonal transparency. The consent constraint. "
     "This axiom carries the weight of a constitutional right. It cannot be overridden by convenience. "
     "Management governance. The system prepares factual context for meetings. "
     "It cannot generate coaching language. It cannot suggest what to say. It gives you facts and gets out of the way. "
     "Corporate boundary. Work data stays in employer systems. This handles personal and management-practice work only. "
     "Enforcement is structural. "
     "Code that violates a foundational implication cannot be committed. "
     "Pre-commit hooks catch it. The continuous integration system catches it. "
     "There is no override. There is no administrator exception. "
     "When a novel situation arises that no axiom directly addresses, the system queries past decisions. "
     "If no close precedent exists, it escalates to me. "
     "Over time, this creates something like interpretive law. A growing body of case decisions."
    ),

    ("16-ethics-of-perception",
     "A system that continuously perceives its environment raises obvious concerns. "
     "The standard framing is surveillance. Cameras everywhere. Data collection. Loss of privacy. "
     "That framing assumes a specific power structure. "
     "A corporation collecting data about employees. A government watching citizens. "
     "In those cases, the person being observed does not control the system. "
     "Does not know what is stored. Cannot inspect or delete it. "
     "That asymmetry is what makes surveillance harmful. Not the cameras themselves. The power imbalance. "
     "This system inverts every element of that structure. "
     "The person being most observed is the person who built the system, runs it, and controls every data flow. "
     "For everyone else, consent is structural. Not policy. Not promise. Code. "
     "For the children, we hold the contracts as guardians. Inspectable. Revocable. "
     "Even with consent, the system cannot evaluate people. "
     "The philosophy is not that perception is wrong. "
     "It is that perception without transparency, without consent, and without the ability to revoke, is wrong. "
     "When all three conditions are met, the power dynamic is fundamentally different from surveillance."
    ),

    # ══════════════════════════════════════════════════════════════════════
    # PART 5: THE RESEARCH
    # ══════════════════════════════════════════════════════════════════════

    ("17-research-transition",
     "Everything I have shown you so far is infrastructure. It works. It runs every day. "
     "Now the research. This part is different. "
     "It is not finished. It is not proven. "
     "It is a genuine open question being investigated with real methodology."
    ),

    ("18-clark-brennan",
     "Every voice assistant on the market uses the same basic approach. "
     "Store facts about the user in a profile. Retrieve relevant facts during conversation. Inject them. "
     "Profile storage plus retrieval. "
     "A linguist named Herbert Clark spent his career studying something different. "
     "Clark described how humans actually establish mutual understanding in conversation. He called it grounding. "
     "The key insight is that conversation is not information transfer. It is a collaborative activity. "
     "Both participants work together to reach what Clark called sufficient mutual belief of understanding for current purposes. "
     "That phrase matters. Sufficient for current purposes. "
     "If I say pass the salt, the grounding requirement is low. The stakes are low. "
     "If I say I need you to restructure the deployment architecture, the grounding requirement is high. "
     "A misunderstanding has consequences. "
     "The amount of work both parties invest in ensuring understanding scales with what is at stake. "
     "Clark and Susan Brennan formalized this in 1991. "
     "They described five levels of evidence for understanding. "
     "Continued attention. A relevant next turn. An explicit acknowledgment. "
     "Demonstrating understanding by building on what was said. And verbatim repetition. "
     "No commercial voice system has ever implemented any of this."
    ),

    ("19-the-35-year-gap",
     "There is a thirty-five-year gap between that theory and any attempt to implement it. "
     "Dialogue systems separated management from generation. Grounding requires both unified. "
     "Task-oriented systems optimized for completing the task, not mutual understanding. "
     "Neural approaches made explicit state tracking seem unnecessary. "
     "And then in 2024, researchers found something important. "
     "The technique used to make language models conversational, reinforcement learning from human feedback, "
     "actually suppresses the behaviors grounding requires. "
     "Models trained this way are three times less likely to ask for clarification. "
     "Sixteen times less likely to make follow-up requests. "
     "A separate study tested all frontier models on a grounding benchmark. "
     "Every model scored below random chance. "
     "The training that makes models agreeable also makes them unable to do "
     "the collaborative work that genuine conversation requires. "
     "A leaked internal reasoning trace from one major model illustrates this. "
     "A user asked it to set an alarm. "
     "The model spent its entire reasoning budget on a decision tree about whether to apply stored style preferences, "
     "concluded it should not, and responded with the correct time. "
     "Correct answer. Zero conversational grounding."
    ),

    ("20-voice-architecture",
     "The voice system here is built around two structural concepts. Bands and grounding. "
     "Two bands. Stable and volatile. "
     "The stable band is a shared anchor. It holds the system's identity, the operator's communication style, "
     "and a compressed thread of what has been established in conversation. "
     "The thread preserves what Clark called conceptual pacts. "
     "When two people agree on how to refer to something, that agreement persists. "
     "If we start calling something the spare, that is a pact. "
     "If the system suddenly switches to the secondary redundancy node, it breaks the pact. "
     "Brennan showed that breaking pacts with a known partner is maximally costly. "
     "More than with a stranger, because the expectation of shared understanding is higher. "
     "The volatile band changes every turn. "
     "Current environment. What the perception system sees right now. "
     "A directive from the grounding tracker. Advance, rephrase, elaborate, or move on. "
     "And how much the current topic matters. "
     "The grounding loop tracks every chunk of meaning being negotiated. "
     "When the system says something, it classifies the response. Accept, clarify, reject, or ignore. "
     "Based on that, it decides what to do next. "
     "The thresholds adapt. When something matters more, it requires stronger evidence of understanding. "
     "When something matters less, being ignored is sufficient. "
     "Clark's phrase. Sufficient for current purposes."
    ),

    ("21-model-routing",
     "The system decides how much cognitive power to apply to each utterance. "
     "Based on salience, not complexity. "
     "Two streams. How much does this relate to things I care about right now? And how unexpected is it? "
     "High concern plus high novelty gets the most capable model. A routine greeting gets a small local one. "
     "One hard rule. Intelligence is the last thing shed. "
     "Consent refusals always get the best model. A guest present, always the best model. "
     "You never save resources at the cost of handling a sensitive situation poorly."
    ),

    ("22-methodology",
     "The methodology is called single-case experimental design. "
     "It is the established framework from clinical psychology for rigorous single-subject research. "
     "Not a case study. A formal experimental design with baselines, treatments, and reversals. "
     "A-B-A. Measure natural behavior. Introduce the treatment. Remove it. "
     "If the measurement reverts, you have causal evidence. "
     "There is a known problem with this design for grounding specifically. "
     "Clark's theory predicts that grounding creates persistent knowledge structures. "
     "Once I learn how the system communicates, removing the treatment may not fully undo that learning. "
     "This is acknowledged in the pre-registration. "
     "The reversal phase exists specifically to test for it."
    ),

    ("23-honest-results",
     "Cycle one was a pilot. Thirty-seven sessions. "
     "The primary metric was word overlap between consecutive turns. "
     "The result was a Bayes factor of three point six six. Moderate evidence. Inconclusive. "
     "And the metric was wrong. "
     "Word overlap penalizes abstraction. "
     "If the system says the database and I respond with it, that is good grounding but poor word overlap. "
     "Six deviations from the protocol were documented. "
     "The metric has been replaced with one that captures meaning similarity rather than word matching. "
     "The analysis framework changed from one that was wrong for continuous data to one that is appropriate. "
     "Expected effects are modest. About what clinical dialogue interventions produce. "
     "The probability of strong evidence is forty to fifty percent with twenty sessions per phase. "
     "This study is underpowered for medium effects. That is stated upfront. "
     "There is zero external validity. One person. Generalization requires others. "
     "The study is pre-registered before data collection. "
     "Hypotheses, metrics, analysis, decision criteria. All specified before looking at results. "
     "Results published regardless of outcome. "
     "You specify what you expect. You report what you find. You do not hide null results."
    ),

    ("24-what-is-original",
     "The theory is not new. Clark and Brennan is forty years old. "
     "What is original is the implementation. "
     "No one has built grounding infrastructure into a production voice system. "
     "No one has tested it with a real user over sustained daily use. "
     "If the training procedure all frontier models use suppresses grounding behaviors, "
     "the question is whether you can compensate externally. "
     "Build the loop outside the model. Inject it as context. "
     "If yes, voice systems need architectural support for grounding. Bigger models are not enough. "
     "If no, the damage requires fine-tuning to repair. Different kind of contribution. "
     "Either result is publishable. Either tells us something we did not know."
    ),

    # ══════════════════════════════════════════════════════════════════════
    # PART 6: PHILOSOPHY
    # ══════════════════════════════════════════════════════════════════════

    ("25-temporal-experience",
     "The system's perception is organized around a model of temporal experience from Husserl. "
     "Three aspects of how we experience time. "
     "Retention. The fading echo of what just happened. Not memory retrieval. The still-present trace. "
     "Like the last few notes of a melody still in your awareness after they have sounded. "
     "Impression. The vivid present. "
     "Protention. Anticipated near-future based on current trajectories. "
     "The system implements this with a rolling buffer of perception snapshots. "
     "Retention samples three points. Five, fifteen, and forty seconds ago. "
     "Impression is the current snapshot, with a surprise field. "
     "Prediction meets actuality. Mismatch is surprise. "
     "Protention produces predictions. Entering deep work. Break likely. Stress rising. "
     "The voice system receives these temporal bands. "
     "It can say you have been in deep work for forty minutes because the retention band shows the trajectory. "
     "Not because it stored a fact. Because it can perceive the shape of the recent past."
    ),

    ("26-philosophy-as-engineering",
     "Several philosophical traditions inform the design. They are not decorative. "
     "Each solved a real engineering problem. "
     "Heidegger's attunement became stimmung. "
     "The system's state structures its behavior the way mood structures perception. "
     "Not a report. A response. "
     "Merleau-Ponty's embodied perception shaped the sensor architecture. "
     "Understanding comes from being situated, not from processing data about the world. "
     "This system has cameras, microphones, biometric sensors. It is physically present in the same room. "
     "Wittgenstein on meaning as use shaped the grounding loop. "
     "Words acquire meaning through collaborative activity. That is what Clark formalized. "
     "And Husserl on time-consciousness became the temporal bands. "
     "Stimmung solved how a system should modulate its behavior when its own state changes. "
     "Embodied perception solved how it should understand its environment. "
     "Grounding solved how it should maintain mutual understanding. "
     "Temporal bands solved how it should be aware of trajectories, not just snapshots. "
     "The engineering problem came first. The philosophical model solved it."
    ),

    # ══════════════════════════════════════════════════════════════════════
    # PART 7: CLOSING
    # ══════════════════════════════════════════════════════════════════════

    ("27-what-is-proven",
     "What is proven. "
     "The infrastructure works. Forty-five agents. Health monitoring. The reactive engine. "
     "The grounding loop classifies acceptance correctly. Discourse tracking transitions properly. "
     "The governance framework enforces its constraints. Consent contracts prevent unauthorized storage. "
     "What remains. "
     "Whether grounding produces measurable improvement. That is the current experiment. "
     "Whether the components interact as a whole greater than the sum. That requires ablation. "
     "Whether any of this generalizes beyond one person. That requires others. "
     "The path is clear. Collect baseline data. Run the experiment. Analyze. Publish regardless."
    ),

    ("28-closing",
     "This system exists because I needed something that existing software does not provide. "
     "Not productivity tools. Not voice assistants. Cognitive infrastructure. "
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

    ("99-outro", "Thank you for your time."),
]
# fmt: on

DEMO_NAME = "alexis-v3-demo"


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_]+", "-", slug).strip("-")[:40]


async def main() -> None:
    output_dir = Path(f"output/demos/{DEMO_NAME}")

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    audio_dir = output_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    total_words = sum(len(text.split()) for _, text in SCENES)
    print(
        f"Alexis demo v3: {len(SCENES)} scenes, ~{total_words} words (~{total_words / 140:.0f} min at 140 WPM)"
    )

    # Check forbidden terms
    forbidden = [
        "docker",
        "container",
        "litellm",
        "qdrant",
        "postgresql",
        "pgvector",
        "langfuse",
        "ollama",
        "api",
        "endpoint",
        "microservice",
        "systemd",
        "vram",
        "gpu",
        "inference",
        "latency",
        "cost",
        "spending",
        "tokens",
        "uptime",
    ]
    all_text = " ".join(text for _, text in SCENES).lower()
    violations = [f for f in forbidden if f in all_text]
    if violations:
        print(f"WARNING: Forbidden terms found: {violations}")
    else:
        print("Forbidden terms check: CLEAN")

    # Rhetorical hooks check
    hooks = [
        "watch what happens",
        "think of it as",
        "here is the subtle thing",
        "let me show you",
        "notice how",
        "imagine",
        "what if i told you",
    ]
    found_hooks = [h for h in hooks if h in all_text]
    if found_hooks:
        print(f"WARNING: Rhetorical hooks found: {found_hooks}")
    else:
        print("Rhetorical hooks check: CLEAN")

    from agents.demo_pipeline.voice import check_elevenlabs_available, generate_all_voice_segments

    backend = "elevenlabs" if check_elevenlabs_available() else "auto"
    print(f"TTS backend: {backend}")

    generate_all_voice_segments(
        SCENES,
        audio_dir,
        on_progress=lambda msg: print(f"  {msg}"),
        backend=backend,
    )

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

    # Riser
    print("Generating intro riser...")
    subprocess.run(
        [
            "python3",
            "-c",
            f"""
import numpy as np, wave
sr, dur, n = 24000, 6.0, int(24000 * 6.0)
freq = np.exp(np.linspace(np.log(55), np.log(440), n))
p1 = np.cumsum(freq / sr) * 2 * np.pi
p2 = np.cumsum((freq * 1.003) / sr) * 2 * np.pi
p3 = np.cumsum((freq * 0.997) / sr) * 2 * np.pi
osc = (np.sin(p1)+0.5*np.sin(2*p1)+np.sin(p2)+0.5*np.sin(2*p2)+np.sin(p3)+0.5*np.sin(2*p3))/3
cut = np.linspace(0.02,0.3,n)
filt = np.zeros(n); filt[0]=osc[0]
for i in range(1,n): filt[i]=cut[i]*osc[i]+(1-cut[i])*filt[i-1]
sub = 0.3*np.sin(np.cumsum(np.linspace(40,80,n)/sr)*2*np.pi)
sig = filt*0.6+sub
env = np.ones(n)
env[:int(sr*3)] = np.linspace(0,1,int(sr*3))**2
env[-int(sr*1.5):] = np.linspace(1,0.3,int(sr*1.5))
sig = sig*env/np.max(np.abs(sig))*0.7
pcm = (np.clip(sig,-1,1)*32767).astype(np.int16)
with wave.open('{audio_dir}/00-riser.wav','wb') as wf:
    wf.setnchannels(1);wf.setsampwidth(2);wf.setframerate(24000);wf.writeframes(pcm.tobytes())
""",
        ],
        capture_output=True,
    )

    # Choreograph
    print("\nChoreographing UI actions (Opus)...")
    from agents.demo_models import DemoScene, DemoScript
    from agents.demo_pipeline.app_scenes import convert_to_app_scenes
    from agents.demo_pipeline.choreography import choreograph

    demo_script = DemoScript(
        title="Hapax",
        audience="family",
        intro_narration=SCENES[0][1],
        scenes=[
            DemoScene(
                title=name.split("-", 1)[1].replace("-", " ").title() if "-" in name else name,
                narration=text,
                duration_hint=len(text.split()) / 2.5,
                key_points=[],
            )
            for name, text in SCENES[1:-1]
        ],
        outro_narration=SCENES[-1][1],
    )

    choreography_actions = await choreograph(demo_script, on_progress=lambda msg: print(f"  {msg}"))

    print("\nGenerating app-script.json...")
    convert_to_app_scenes(
        demo_script, output_dir, on_progress=print, choreography=choreography_actions
    )

    # Insert riser
    import json

    app_script_path = output_dir / "app-script.json"
    scenes_json = json.load(open(app_script_path))
    scenes_json.insert(0, {"title": "", "audioFile": "00-riser.wav", "actions": []})
    app_script_path.write_text(json.dumps(scenes_json, indent=2))

    # Report
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
