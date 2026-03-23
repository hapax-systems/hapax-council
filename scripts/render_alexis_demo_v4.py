"""Render narration audio for Alexis demo v4.

Third person. No rhetoric. Consent gentle, cameras later.
Factually accurate (not local-only — uses external APIs).
Voice: Lily (soft, velvety).

Usage: uv run python scripts/render_alexis_demo_v4.py
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
    # PART 1: CONTEXT
    # ══════════════════════════════════════════════════════════════════════

    ("00-intro",
     "This is a system called Hapax. "
     "It started as a tool for executive function support and became a research project. "
     "The research is the point. The system is the instrument."
    ),

    ("01-what-is-hapax",
     "Executive function is the set of cognitive processes that handle task initiation, sustained attention, "
     "keeping track of open loops, and maintaining routines. "
     "For most people, these processes run automatically. "
     "For people with ADHD, they are not absent. They are unreliable. "
     "Hapax is infrastructure that performs those functions externally. "
     "It tracks open loops. It notices when things drift. It surfaces what needs attention. "
     "It maintains awareness of both the physical environment and the cognitive state of the person using it. "
     "Forty-five specialized agents handle different aspects of this work. "
     "The system runs on a local workstation but calls external language model services through a controlled gateway. "
     "The data stays on the local machine. The reasoning sometimes happens externally."
    ),

    ("02-consent-foundation",
     "Before looking at what the system does, there is something important about how it is governed. "
     "Hapax has a set of constitutional axioms. Rules that cannot be overridden by any other part of the system. "
     "One of these axioms concerns other people. "
     "It states that no persistent data about any person other than the operator may exist "
     "without an active, explicit, revocable consent contract. "
     "A consent contract specifies which categories of data are stored. "
     "The contract can be inspected at any time. It can be revoked at any time. "
     "Upon revocation, all data associated with that person is deleted. "
     "This is not a policy. It is a structural constraint enforced at every data ingestion point in the code. "
     "There is no setting to disable it. "
     "Two consent contracts currently exist, for the operator's children. "
     "Those are held by the operator and the operator's spouse as legal guardians. "
     "Even with consent, the system cannot generate evaluative language about any individual. "
     "It can prepare factual context. It cannot judge. "
     "The ethics of this are addressed in more detail later. For now, this is the foundational rule."
    ),

    # ══════════════════════════════════════════════════════════════════════
    # PART 2: THE INTERFACE
    # ══════════════════════════════════════════════════════════════════════

    ("03-what-logos-looks-like",
     "The interface is called Logos. It is going to look unfamiliar. "
     "There are no menus, no sidebar, no settings page. "
     "The screen is divided into five horizontal regions, each representing a different domain of awareness. "
     "The design philosophy is geological. Layers stacked vertically, each with depth that can be revealed. "
     "The visual language is warm and dense. Dark tones, amber accents, monospace typography. "
     "Every visual element encodes system state. Nothing is decorative."
    ),

    ("04-the-five-regions",
     "The top region is Horizon. It holds what needs attention in time. "
     "Briefings, nudges, goals, the reactive engine. "
     "Below it, Field. Perception and agents. What the system knows about the environment and what its programs are doing. "
     "In the middle, Ground. Physical presence. The ambient canvas, cameras, visual effects. "
     "Below that, Watershed. How information flows through the system. The operator profile. "
     "At the bottom, Bedrock. Health, governance, consent, accommodations."
    ),

    ("05-depth",
     "Each region has three depths. "
     "Surface shows almost nothing. A sentence, a few status indicators. The system at rest. "
     "Stratum expands into panels and structure. "
     "Core opens into full detail. "
     "Awareness scales with attention. What the operator is not looking at stays quiet. What they focus on opens up."
    ),

    ("06-horizon",
     "Horizon expanded. "
     "Goals on the left. Things the operator has told the system to track. "
     "Nudges in the center. The executive function mechanism. "
     "The system notices open loops, stale work, overdue follow-ups, "
     "and drift between documentation and reality. "
     "It surfaces these with priority scores and suggested actions. "
     "A daily briefing synthesizes the previous twenty-four hours into a headline and action items. "
     "Meeting preparation generates automatically before each scheduled meeting. "
     "On the right, the reactive engine. When a file changes on disk, rules fire and downstream work cascades."
    ),

    ("07-perception",
     "Field at its deepest level shows the perception canvas. "
     "A continuous perception loop runs every two and a half seconds. "
     "It fuses data from cameras, microphones, desktop focus tracking, and a smartwatch. "
     "The zones overlaid on this view represent different signal categories. "
     "Each signal has a severity between zero and one. "
     "Higher severity makes a signal pulse faster. "
     "At low severity, a gentle eight-second cycle. At high severity, less than a second. "
     "The system uses these severity levels to modulate its own behavior. "
     "When infrastructure health degrades, the voice system becomes more concise. "
     "When operator stress is elevated, tone adjusts."
    ),

    ("08-agents",
     "Forty-five specialized agents run underneath the interface. "
     "Some are interactive, like Logos itself and the voice system. "
     "Some run on demand. A briefing agent. A health monitor that checks eighty-five things. "
     "A drift detector that compares documentation to reality. "
     "A profiler that builds understanding of operator patterns over time. "
     "A management agent that prepares context for meetings "
     "but cannot generate feedback language about any person. "
     "Some run autonomously on timers. Document ingestion. Health checks. Weekly maintenance. "
     "All are stateless. They read, produce output, and stop. "
     "None call each other. If one fails, nothing else is affected."
    ),

    ("09-ground",
     "Ground at surface depth. "
     "The ambient canvas shows warm drifting shapes alongside live contextual content. "
     "Profile facts cycle through at low opacity. Circadian context, activity state, biometric readings. "
     "Faint nudge indicators sit at the periphery. "
     "Everything at surface depth is deliberately calm. Present but not demanding. "
     "When Ground expands, camera feeds appear. Six cameras in the workspace. "
     "At core depth, a single feed fills the view with detection overlays. "
     "The detection system fuses data across all cameras. "
     "If one camera sees a face and another sees a body, they are correlated into a single entity. "
     "Person detections are colored by gaze direction. "
     "Cyan for looking at a screen. Yellow for hardware. Purple for another person. "
     "Emotion classification adds a secondary tint. Depth estimation provides spatial awareness. "
     "Someone still for more than a minute shifts toward cool blue. Someone moving shifts warm. "
     "Detection tiers and individual classifiers can be toggled from the interface. "
     "The consent constraint is visible here. "
     "Any person without a consent contract is drawn fully desaturated. Grey. "
     "The system registers their presence but structurally will not characterize them."
    ),

    ("10-effects",
     "Ground also hosts a visual compositor with thirteen effect presets. "
     "Ghost produces transparent echoes with fading trails. "
     "Screwed, named after Houston chopped-and-screwed music, applies heavy warping and syrup gradients. "
     "Datamosh simulates codec glitch artifacts. VHS adds tape warmth. "
     "Neon cycles through hue-rotated glow. Night Vision renders green phosphor. Thermal simulates a heat map. "
     "The operator produces music and streams live. "
     "These effects composite in real time over camera feeds during production sessions. "
     "The underlying architecture uses a dual ring buffer, "
     "the same structure used in broadcast video switching."
    ),

    ("11-stimmung",
     "A concept that connects everything. Stimmung. "
     "A German word that Heidegger used to mean attunement. "
     "The idea is that perception is never neutral. "
     "There is always a mood that structures how things appear. "
     "Anxiety does not follow a decision to be anxious. It is already present, shaping what gets noticed. "
     "In this system, stimmung is an engineering implementation of that idea. "
     "A ten-dimensional vector combining infrastructure health and biometric state. "
     "The worst dimension sets the stance. "
     "Nominal. Green borders. Cautious. Yellow. Degraded. Orange with a breathing animation. Critical. Red, breathing fast. "
     "The warm glow visible on the region borders right now is stimmung. Live. "
     "When stimmung degrades, the whole system responds. "
     "Voice becomes more concise. Notifications reduce. "
     "It is not reporting a problem. It is responding to it."
    ),

    ("12-watershed-and-profile",
     "Watershed shows how subsystems connect. "
     "At core depth, a graph of nine nodes and their relationships. "
     "Perception feeds stimmung. Stimmung feeds voice. Consent gates everything. "
     "The operator profile also lives here. Eleven dimensions. "
     "Five stable traits from an interview. Identity, cognitive style, values, communication preferences, relationships. "
     "Six dynamic dimensions observed over time. Work patterns, energy, creative process. "
     "These shape how the briefing is structured, how nudges are phrased, "
     "what tone the voice uses, when to surface information and when to stay quiet."
    ),

    ("13-bedrock",
     "Bedrock shows the foundations. "
     "Health checks. Resource allocation. Active consent contracts and their coverage. "
     "A governance heartbeat measuring axiom compliance. "
     "And accommodations. Time anchoring for calendar awareness. "
     "Soft framing for how notifications are phrased. "
     "Energy-aware scheduling that respects circadian patterns."
    ),

    ("14-investigation",
     "One more interface element. An overlay that opens with a keystroke. "
     "A direct conversation with a language model that has full system access. "
     "A search interface across all embedded documents. "
     "And a gallery of demo recordings."
    ),

    # ══════════════════════════════════════════════════════════════════════
    # PART 3: GOVERNANCE AND ETHICS
    # ══════════════════════════════════════════════════════════════════════

    ("15-axioms",
     "The governance model. Five axioms. Three constitutional, two domain-specific. "
     "Single user. The system serves one person. "
     "This is a foundational commitment that shapes every design decision. "
     "Executive function. The system exists as cognitive support. "
     "Interpersonal transparency. The consent constraint described earlier. "
     "It carries the weight of a constitutional right. It cannot be overridden by convenience. "
     "Management governance. The system prepares factual context for meetings. "
     "It cannot generate coaching language. It cannot suggest what to say. "
     "Corporate boundary. Work data stays in employer systems. "
     "Enforcement is structural. Code that violates a foundational implication cannot be committed. "
     "There is no override. There is no administrator exception. "
     "When a novel situation arises, the system queries past decisions. "
     "If no close precedent exists, it escalates to the operator. "
     "Over time, this creates something like interpretive law."
    ),

    ("16-ethics",
     "Continuous perception of an environment raises concerns. "
     "The standard framing is surveillance. "
     "That framing assumes a specific power structure. "
     "A corporation collecting data about employees. A government watching citizens. "
     "In those cases, the person being observed does not control the system, "
     "does not know what is stored, and cannot inspect or delete it. "
     "That asymmetry is what makes surveillance harmful. Not the cameras. The power imbalance. "
     "This system inverts that structure. "
     "The person most observed is the person who built it, runs it, and controls every data flow. "
     "For everyone else, consent is structural. "
     "For the children, the contracts are held by guardians, are inspectable, and are revocable. "
     "Even with consent, the system cannot evaluate people. "
     "Perception without transparency, without consent, and without the ability to revoke, is the problem. "
     "When all three conditions are met, the dynamic is fundamentally different."
    ),

    # ══════════════════════════════════════════════════════════════════════
    # PART 4: THE RESEARCH
    # ══════════════════════════════════════════════════════════════════════

    ("17-transition",
     "Everything shown so far is infrastructure. It works. It runs daily. "
     "Now the research. This is the reason the system exists. "
     "The infrastructure is the instrument. The research is the purpose. "
     "It is not finished. It is not proven. "
     "It is a genuine open question being investigated with formal methodology."
    ),

    ("18-clark",
     "Every voice assistant on the market uses the same approach. "
     "Store facts about the user. Retrieve relevant facts during conversation. Inject them. "
     "Profile storage plus retrieval. "
     "A linguist named Herbert Clark spent his career studying something different. "
     "Clark described how humans establish mutual understanding in conversation. He called it grounding. "
     "Conversation is not information transfer. It is a collaborative activity. "
     "Both participants work together to reach what Clark called "
     "sufficient mutual belief of understanding for current purposes. "
     "The amount of work both parties invest in ensuring understanding scales with what is at stake. "
     "Low-stakes exchanges require little grounding. High-stakes exchanges require a lot. "
     "Clark and Susan Brennan formalized this in 1991. "
     "They described five levels of evidence for understanding, from continued attention to verbatim repetition. "
     "In 1994, David Traum built a computational model of grounding with seven formal acts. "
     "Initiate, continue, acknowledge, repair, request repair, request acknowledgment, and cancel. "
     "These form a state machine that tracks every chunk of meaning being negotiated. "
     "No commercial voice system has ever implemented Clark, Brennan, or Traum."
    ),

    ("19-gap",
     "Thirty-five years between that theory and any attempt to implement it. "
     "Dialogue systems separated management from generation. Grounding requires both unified. "
     "Task-oriented systems optimized for completing the task, not mutual understanding. "
     "Neural approaches made explicit state tracking seem unnecessary. "
     "Then in 2024, Shaikh and colleagues published two studies that changed the picture. "
     "The first, at NAACL 2024, showed that reinforcement learning from human feedback, "
     "the technique used to make language models conversational, "
     "actually suppresses the behaviors grounding requires. "
     "Models trained this way are three times less likely to ask for clarification. "
     "Sixteen times less likely to follow up. "
     "The second study, accepted at ACL 2025, tested frontier models on a grounding benchmark called Rifts. "
     "Every model scored twenty-three percent. Below random chance at thirty-three. "
     "The training that makes models agreeable makes them unable to do "
     "the collaborative work that genuine conversation requires. "
     "A leaked internal reasoning trace from one major voice assistant illustrates this concretely. "
     "A user asked the assistant to set an alarm for eight forty-five. "
     "The model spent its entire reasoning budget on a four-step decision tree "
     "about whether to apply stored style preferences from the user's profile. "
     "It concluded it should not apply them, and responded with the correct time. "
     "Correct answer. Zero conversational grounding. "
     "It treated the exchange as a database lookup, not a conversation."
    ),

    ("20-voice-architecture",
     "The voice system in Hapax is built around two structural concepts. Bands and grounding. "
     "Two bands. Stable and volatile. "
     "The stable band holds the system's identity, the operator's communication style, "
     "and a compressed thread of what has been established in conversation. "
     "The thread preserves what Clark called conceptual pacts. "
     "When two people agree on how to refer to something, that agreement persists. "
     "Breaking a pact with a known partner is maximally disruptive "
     "because the expectation of shared understanding is higher. "
     "The volatile band changes every turn. "
     "Current environment. A directive from the grounding tracker. "
     "How much the current topic matters. "
     "The grounding loop tracks every chunk of meaning being negotiated, "
     "following Traum's state machine model. "
     "When the system says something, it classifies the response. Accept, clarify, reject, or ignore. "
     "Based on that classification, it decides what to do next. "
     "The quality of grounding is measured by a composite index. "
     "Fifty percent comes from the rolling acceptance rate. "
     "Twenty-five percent from the trend in recent responses. "
     "Fifteen percent from consecutive negative signals. "
     "Ten percent from overall engagement level. "
     "Thresholds adapt. When something matters more, stronger evidence of understanding is required. "
     "When something matters less, being ignored is sufficient. "
     "Clark's phrase. Sufficient for current purposes."
    ),

    ("21-salience",
     "The system decides how much cognitive power to apply to each utterance based on salience. "
     "Two streams. How much does this relate to current concerns? And how unexpected is it? "
     "High concern plus high novelty routes to the most capable model. "
     "A routine greeting routes to a small local one. "
     "One hard rule. Intelligence is the last thing shed. "
     "Consent refusals always get the best model. A guest present, always the best model."
    ),

    ("22-methodology",
     "The methodology is single-case experimental design. "
     "The established framework from clinical psychology for rigorous single-subject research. "
     "A formal experimental design with baselines, treatments, and reversals. "
     "A-B-A. Measure natural behavior. Introduce the treatment. Remove it. "
     "If the measurement reverts, there is causal evidence. "
     "There is a known problem with this design for grounding specifically. "
     "It is called the maturation threat. "
     "Grounding creates persistent knowledge structures. "
     "Once the operator learns how the system communicates, "
     "removing the treatment may not fully undo that learning. "
     "The operator might keep behaving as if the grounding features were still active. "
     "This is acknowledged in the pre-registration. "
     "The reversal phase exists specifically to test for it. "
     "If scores drop when the treatment is removed, there is causal evidence. "
     "If they stay elevated, the effect may be real but confounded with learning."
    ),

    ("23-results",
     "The pilot was thirty-seven sessions. "
     "The primary metric was word overlap between consecutive turns. "
     "Bayes factor of three point six six. Moderate evidence. Inconclusive. "
     "The metric was wrong. Word overlap penalizes abstraction. "
     "If the system says 'the database' and the operator responds with 'it,' "
     "that is good grounding but poor word overlap. "
     "Six deviations from the protocol were documented. "
     "The metric has been replaced with one that captures meaning similarity rather than word matching. "
     "The analysis framework has been corrected. "
     "Expected effects are modest. "
     "In clinical psychology, dialogue interventions typically produce a Cohen's d "
     "between zero point four and zero point five. That is a small to medium effect. "
     "This study expects zero point three to zero point six. "
     "The probability of strong evidence is forty to fifty percent with twenty sessions per phase. "
     "Underpowered for medium effects. Stated upfront. "
     "Zero external validity. One person. "
     "The study is pre-registered. All criteria specified before data collection. "
     "Results published regardless of outcome."
    ),

    ("24-originality",
     "The theory is not new. Clark and Brennan is forty years old. Traum is thirty. "
     "The implementation is new. "
     "No one has built grounding infrastructure into a production voice system. "
     "No one has tested it with a real user over sustained daily use. "
     "If the training procedure all frontier models use suppresses grounding behaviors, "
     "the question is whether external compensation is possible. "
     "Build the loop outside the model. Inject it as context. "
     "If that works, voice systems need architectural support for grounding. "
     "If it does not, the damage requires fine-tuning to repair. "
     "Either result is publishable. Either tells us something that is not currently known."
    ),

    # ══════════════════════════════════════════════════════════════════════
    # PART 5: PHILOSOPHY
    # ══════════════════════════════════════════════════════════════════════

    ("25-temporal",
     "The system's perception is organized around a model of temporal experience from Husserl. "
     "Three aspects of time-consciousness. "
     "Retention. The fading echo of what just happened. Not memory retrieval. The still-present trace. "
     "Like the last notes of a melody still in awareness after they have sounded. "
     "Impression. The vivid present. "
     "Protention. Anticipated near-future based on current trajectories. "
     "The system implements this with a rolling buffer of perception snapshots. "
     "Retention samples three points. Five, fifteen, and forty seconds ago. "
     "Impression is the current snapshot, with a surprise field. "
     "Prediction meets actuality. Mismatch is surprise. "
     "Protention produces predictions. Entering deep work. Break likely. Stress rising. "
     "The voice system receives these temporal bands. "
     "It can reference forty minutes of deep work not because it stored that fact, "
     "but because the retention band shows the trajectory."
    ),

    ("26-philosophy",
     "Several philosophical traditions inform the design. Each solved a real engineering problem. "
     "Heidegger's attunement became stimmung. "
     "The system's state structures its behavior the way mood structures perception. "
     "Merleau-Ponty's embodied perception shaped the sensor architecture. "
     "Understanding comes from being situated, not from processing data about the world. "
     "The system has cameras, microphones, biometric sensors. It is physically present in the same room. "
     "Wittgenstein on meaning as use shaped the grounding loop. "
     "Words acquire meaning through collaborative activity. That is what Clark formalized. "
     "Husserl on time-consciousness became the temporal bands. "
     "Stimmung solved how a system should modulate behavior when its own state changes. "
     "Embodied perception solved how it should understand its environment. "
     "Grounding solved how it should maintain mutual understanding. "
     "Temporal bands solved how it should perceive trajectories, not just snapshots. "
     "The engineering problem came first. The philosophical model solved it."
    ),

    # ══════════════════════════════════════════════════════════════════════
    # PART 6: CLOSING
    # ══════════════════════════════════════════════════════════════════════

    ("27-proven",
     "What is proven. "
     "The infrastructure works. Forty-five agents. Health monitoring. The reactive engine. "
     "The grounding loop classifies acceptance correctly. Discourse tracking transitions properly. "
     "The governance framework enforces its constraints. "
     "What remains. "
     "Whether grounding produces measurable improvement. That is the current experiment. "
     "Whether the components interact as something greater than the sum. That requires ablation. "
     "Whether any of this generalizes beyond one person. That requires others. "
     "The path is clear. Collect baseline data. Run the experiment. Analyze. Publish regardless."
    ),

    ("28-closing",
     "Hapax exists because existing software does not provide what was needed. "
     "Not productivity tools. Not voice assistants. Cognitive infrastructure. "
     "The research exists because the gap between conversation theory and conversation technology "
     "turned out to be both interesting and tractable. "
     "The governance exists because building a perception system without structural consent constraints "
     "would be irresponsible regardless of intent. "
     "The experiment has not run. The data has not been collected. The hypothesis may be wrong. "
     "What exists is a system that works, a research program with clear methodology, "
     "and a governance framework that treats ethics as structure rather than policy."
    ),

    ("99-outro", "Thank you."),
]
# fmt: on

DEMO_NAME = "alexis-v4-demo"


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
    print(f"Alexis demo v4: {len(SCENES)} scenes, ~{total_words} words")

    # Validate
    forbidden = [
        "docker",
        "container",
        "litellm",
        "qdrant",
        "postgresql",
        "pgvector",
        "langfuse",
        "ollama",
        "endpoint",
        "microservice",
        "systemd",
        "vram",
        "gpu",
        "inference",
        "latency",
        "spending",
        "tokens",
        "uptime",
    ]
    hooks = [
        "watch what happens",
        "let me show you",
        "notice how",
        "imagine ",
        "what if i told you",
        "think of it as",
    ]
    all_text = " ".join(text for _, text in SCENES).lower()

    violations = [f for f in forbidden if f in all_text]
    found_hooks = [h for h in hooks if h in all_text]
    first_person = sum(1 for word in all_text.split() if word in ("i", "my", "me", "i'm", "i've"))

    print(f"Forbidden terms: {violations if violations else 'CLEAN'}")
    print(f"Rhetorical hooks: {found_hooks if found_hooks else 'CLEAN'}")
    print(f"First person words: {first_person}")

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
    print("Generating riser...")
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

    print("\nChoreographing (Opus)...")
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

    print("\nAssembling app-script.json...")
    convert_to_app_scenes(
        demo_script, output_dir, on_progress=print, choreography=choreography_actions
    )

    import json

    app_script_path = output_dir / "app-script.json"
    scenes_json = json.load(open(app_script_path))
    scenes_json.insert(0, {"title": "", "audioFile": "00-riser.wav", "actions": []})
    app_script_path.write_text(json.dumps(scenes_json, indent=2))

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
