"""Render narration audio for kids demo — Agatha (11) and Simon (8).

Same substance as Alexis v4. Adjusted for two brilliant kids who care
about both the ideas and the spectacle. No condescension. No simplification
of concepts — just clearer framing and more concrete anchors.

Usage: uv run python scripts/render_kids_demo.py
"""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
from pathlib import Path

# fmt: off
SCENES: list[tuple[str, str]] = [

    ("00-intro",
     "This is something your dad built. It is called Hapax."
    ),

    ("01-what-it-is",
     "Executive function is the part of your brain that keeps track of things. "
     "Did you finish that assignment? Is it time to leave for practice? "
     "What were you supposed to bring tomorrow? "
     "For most people, that tracking happens in the background without effort. "
     "For people with ADHD, those processes work, but not reliably. "
     "Hapax is a system that does that tracking externally. "
     "It runs on this computer. Forty-five separate programs, each with a specific job. "
     "Some watch for things that need attention. Some prepare information before it is needed. "
     "Some run on timers, checking things every fifteen minutes. "
     "The data stays on this machine. The thinking sometimes happens on external servers, "
     "but the data always comes back here."
    ),

    ("02-consent",
     "Before looking at what it does, there is a rule that governs everything. "
     "This system has cameras. Six of them. It also reads heart rate data from a smartwatch. "
     "The rule says: no data about any person other than your dad can be stored "
     "without a consent contract. "
     "A consent contract specifies exactly what kinds of data are kept. "
     "It can be inspected. It can be revoked. "
     "If it is revoked, everything connected to that person gets deleted. "
     "This rule is not a setting. It is built into the code. There is no way to turn it off. "
     "Two consent contracts exist. One for each of you. "
     "Your parents hold those contracts as your legal guardians. "
     "Even with consent, the system cannot write opinions about anyone. "
     "It can prepare facts. It cannot judge."
    ),

    ("03-the-interface",
     "This interface is called Logos. It does not look like any app you have used. "
     "There are no menus. No tabs. No settings page. "
     "The screen is divided into five horizontal regions. Each one represents a different kind of awareness. "
     "Top to bottom: time, cognition, presence, flow, and infrastructure. "
     "Each region has three depths. "
     "Surface is quiet. Almost nothing visible. "
     "Stratum shows panels and structure. "
     "Core opens into full detail. "
     "The idea is that information should only appear when you are looking for it."
    ),

    ("04-horizon",
     "The top region is Horizon. It is about time. "
     "Goals on the left. Nudges in the center. "
     "Nudges are the system noticing things that need attention. "
     "An overdue follow-up. Documentation that has drifted from reality. Work that has gone stale. "
     "Each nudge has a priority score and a suggested action. "
     "A daily briefing generates every morning at seven. "
     "Meeting preparation generates at six thirty. "
     "By the time your dad sits down, the system has already organized the day."
    ),

    ("05-perception",
     "The next region is Field. This is where perception lives. "
     "A perception loop runs every two and a half seconds. "
     "It combines data from cameras, microphones, desktop focus tracking, and the smartwatch. "
     "The zones on this view represent signal categories. Each signal has a severity from zero to one. "
     "Higher severity makes the signal pulse faster. "
     "Low severity, an eight-second cycle. High severity, less than a second. "
     "The system uses these to adjust its own behavior. "
     "When things are degraded, the voice system gets shorter. When stress is elevated, tone changes."
    ),

    ("06-agents",
     "Forty-five programs run underneath. "
     "Some are interactive, like this interface and the voice system. "
     "Some run on demand. A briefing agent. A health monitor that checks eighty-five things. "
     "A drift detector that compares what documentation says to what actually exists. "
     "A management agent that prepares context for meetings "
     "but cannot write opinions about any person. "
     "Some run on timers. Document ingestion. Health checks. Weekly cleanup. "
     "All of them are stateless. They read, produce output, and stop. "
     "None of them talk to each other. If one breaks, nothing else is affected."
    ),

    ("07-ground",
     "The middle region is Ground. Physical presence. "
     "At surface depth, the ambient canvas. Warm shapes, cycling text, live contextual data. "
     "Profile facts at low opacity. Circadian context. Activity state. Biometric readings. "
     "Everything calm. Present but not demanding. "
     "When Ground expands, camera feeds appear. Six cameras. "
     "At core depth, a single camera fills the view with detection overlays. "
     "The detection system combines information from all six cameras. "
     "If one camera can see a face and another can see a body, it connects them into one person. "
     "Person detections are colored by where someone is looking. "
     "Cyan for a screen. Yellow for hardware. Purple for another person. "
     "Emotion detection adds a tint. Happy is green. Sad is blue. Angry is red. "
     "Depth estimation adds spatial awareness, so the system knows how far away things are. "
     "Detection types can be turned on and off from the interface. "
     "And the consent rule is visible. "
     "Anyone without a consent contract appears grey. "
     "The system sees them but will not characterize them."
    ),

    ("08-effects",
     "Ground also has a visual compositor. Thirteen effect presets. "
     "Ghost. Transparent echoes with fading trails. "
     "Screwed. Named after a style of Houston hip-hop production. Heavy warping, syrup gradients. "
     "Datamosh. Glitch artifacts. VHS. Tape warmth. Neon. Cycling glow. "
     "Night Vision. Green phosphor. Thermal. Heat map. "
     "These are for music production and live streaming. "
     "They composite in real time over camera feeds. "
     "The architecture underneath is a dual ring buffer. "
     "One for live frames, one for delayed overlay. "
     "Same structure used in broadcast television."
    ),

    ("09-stimmung",
     "A concept that connects everything. Stimmung. "
     "It is a German word meaning attunement. "
     "The philosopher Heidegger used it to describe how mood shapes what you notice. "
     "You do not decide to be worried and then start seeing problems. "
     "The worry is already there, filtering what gets through. "
     "In this system, stimmung is a ten-dimensional measurement. "
     "Seven dimensions are infrastructure. Three are biometric. "
     "The worst dimension sets the overall state. "
     "Nominal. Green. Cautious. Yellow. Degraded. Orange, with a slow breathing animation. Critical. Red, breathing fast. "
     "The glow you see on the borders is stimmung. Live. Right now. "
     "When stimmung degrades, the whole system responds. "
     "Voice gets shorter. Notifications reduce. Everything pulls back."
    ),

    ("10-governance",
     "Five rules govern the system. Three are constitutional. Two are domain-specific. "
     "Single user. The system serves one person. "
     "Executive function. The system exists as cognitive support. "
     "Interpersonal transparency. The consent rule. "
     "Management governance. The system prepares facts for meetings but cannot coach or evaluate anyone. "
     "Corporate boundary. Work data stays in work systems. "
     "Enforcement is structural. Code that violates a rule cannot be committed. "
     "There is no override. There is no exception. "
     "When something new comes up that no rule covers, "
     "the system checks past decisions. If nothing matches, it asks your dad."
    ),

    ("11-ethics",
     "Continuous perception raises a question. Is this surveillance? "
     "Surveillance means cameras controlled by someone with power over the people being watched. "
     "A company watching employees. A government watching citizens. "
     "The person being watched cannot see the data. Cannot delete it. Cannot opt out. "
     "That power imbalance is what makes it harmful. "
     "This system is built the opposite way. "
     "The person most watched is the person who built it and controls every data flow. "
     "For everyone else, consent is enforced by the code itself. "
     "For you two, the contracts are held by your parents. Inspectable. Revocable. "
     "Perception is not the problem. Perception without transparency and without the ability to say no is the problem."
    ),

    ("12-research-intro",
     "Everything shown so far is infrastructure. It works. It runs daily. "
     "Now the research. This is the reason the system exists. "
     "The infrastructure is the instrument. The research is the purpose. "
     "It is not finished. It is not proven. "
     "It is a real question being tested with real methodology."
    ),

    ("13-clark",
     "Every voice assistant uses the same approach. "
     "Store facts about the user. Retrieve them during conversation. Inject them. "
     "A linguist named Herbert Clark studied something different. "
     "Clark described how humans actually build understanding in conversation. He called it grounding. "
     "Conversation is not one person sending information to another. "
     "It is two people working together to make sure they actually understand each other. "
     "The amount of effort both people put into that depends on what is at stake. "
     "Low stakes, low effort. High stakes, a lot of effort. "
     "Clark and Susan Brennan wrote this down formally in 1991. "
     "In 1994, a researcher named David Traum turned it into a formal model. "
     "Seven specific actions: initiate, continue, acknowledge, repair, request repair, request acknowledgment, cancel. "
     "A state machine that tracks every piece of meaning in a conversation. "
     "No voice assistant has ever used Clark, Brennan, or Traum."
    ),

    ("14-why-not",
     "Thirty-five years between that research and any attempt to build it. "
     "Then in 2024, researchers named Shaikh and colleagues published two important studies. "
     "They found that the training used to make language models conversational "
     "actually suppresses the behaviors grounding requires. "
     "Models trained this way are three times less likely to ask for clarification. "
     "Sixteen times less likely to follow up. "
     "Tested on a grounding benchmark, every model scored twenty-three percent. Below random chance at thirty-three. "
     "The training that makes them agreeable makes them unable to do "
     "the collaborative work real conversation requires. "
     "A leaked internal trace from one major voice assistant shows this clearly. "
     "A user asked it to set an alarm. "
     "The model spent all its reasoning on whether to apply stored style preferences from a profile. "
     "It decided not to, and gave the correct time. "
     "Right answer. Zero actual conversation."
    ),

    ("15-voice-system",
     "The voice system here tracks every piece of meaning being negotiated, "
     "following Traum's state machine model. "
     "It also preserves what Clark called conceptual pacts. "
     "When two people agree on what to call something, that agreement sticks. "
     "If the system suddenly uses a different name for the same thing, that breaks the pact. "
     "When it says something, it classifies the response. Accept, clarify, reject, or ignore. "
     "Based on that, it decides what to do next. "
     "The quality of grounding is measured by a composite score. "
     "Fifty percent from the acceptance rate. Twenty-five percent from trends. "
     "Fifteen percent from consecutive negative signals. Ten percent from engagement. "
     "If something matters more, stronger evidence of understanding is required. "
     "If something matters less, being ignored is sufficient. "
     "It also decides how much power to use for each response. "
     "High concern plus high novelty gets the best model. "
     "A routine greeting gets a small local one. "
     "One rule: consent situations and guest situations always get the best model."
    ),

    ("16-methodology",
     "The methodology is single-case experimental design. "
     "A formal framework from clinical psychology for studying one subject rigorously. "
     "Measure natural behavior. Introduce the treatment. Remove it. "
     "If the measurement reverts, there is evidence of causation. "
     "There is a known problem with this design for grounding. It is called the maturation threat. "
     "Once the operator learns how the system communicates, "
     "removing the treatment might not fully undo that learning. "
     "The operator might keep acting as if the features were still on. "
     "That is why the reversal phase matters. "
     "If scores drop when the treatment is removed, the effect is real. "
     "If they stay the same, it might be learning, not the treatment. "
     "The pilot was thirty-seven sessions. "
     "The result was inconclusive. The metric was wrong. "
     "It measured word matching when it should have measured meaning similarity. "
     "Six deviations from the protocol were documented. "
     "In clinical psychology, effects this size are called small to medium. "
     "Cohen's d of zero point three to zero point six. "
     "The probability of strong evidence is forty to fifty percent. "
     "The study is pre-registered. All criteria set before data collection. "
     "Results published regardless of outcome."
    ),

    ("17-philosophy",
     "Several philosophical traditions shaped the design. Each solved a real engineering problem. "
     "Heidegger's idea of attunement became stimmung. "
     "How the system's state shapes its behavior, the way mood shapes perception. "
     "Merleau-Ponty's idea of embodied perception shaped the sensor system. "
     "Understanding comes from being present in the world, not from processing data about it. "
     "Wittgenstein's idea that meaning comes from use shaped the grounding loop. "
     "Words do not have fixed meanings. They get meaning from how people use them together. "
     "Husserl's model of time-consciousness became the temporal bands. "
     "Retention, impression, protention. The fading past, the vivid present, the anticipated future. "
     "The engineering problem came first. The philosophical model solved it."
    ),

    ("18-what-is-proven",
     "What is proven. "
     "The infrastructure works. Forty-five agents. Health monitoring. The reactive engine. "
     "The grounding loop classifies correctly. The governance framework enforces its constraints. "
     "What remains. "
     "Whether grounding produces measurable improvement. That is the current experiment. "
     "Whether the components work better together than separately. That requires ablation. "
     "Whether any of this works for anyone other than one person. That requires others to try it."
    ),

    ("19-closing",
     "Hapax exists because existing software does not do what was needed. "
     "The research exists because the gap between conversation theory and conversation technology "
     "turned out to be worth investigating. "
     "The governance exists because building a perception system without structural consent "
     "would be irresponsible. "
     "The experiment has not run. The hypothesis may be wrong. "
     "What exists is a system that works, a research program with clear methodology, "
     "and a governance framework that treats ethics as structure."
    ),

    ("99-outro", "That is Hapax."),
]
# fmt: on

DEMO_NAME = "kids-demo"


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
    print(f"Kids demo: {len(SCENES)} scenes, ~{total_words} words")

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

    # Riser + bing
    print("Generating riser + bing...")
    subprocess.run(
        [
            "python3",
            "-c",
            f"""
import numpy as np, wave
sr = 24000
# Riser
dur = 6.0; n = int(sr*dur)
freq = np.exp(np.linspace(np.log(55), np.log(440), n))
p1 = np.cumsum(freq/sr)*2*np.pi; p2 = np.cumsum((freq*1.003)/sr)*2*np.pi; p3 = np.cumsum((freq*0.997)/sr)*2*np.pi
osc = (np.sin(p1)+0.5*np.sin(2*p1)+np.sin(p2)+0.5*np.sin(2*p2)+np.sin(p3)+0.5*np.sin(2*p3))/3
cut = np.linspace(0.02,0.3,n); filt = np.zeros(n); filt[0]=osc[0]
for i in range(1,n): filt[i]=cut[i]*osc[i]+(1-cut[i])*filt[i-1]
sub = 0.3*np.sin(np.cumsum(np.linspace(40,80,n)/sr)*2*np.pi)
sig = filt*0.6+sub; env = np.ones(n); env[:int(sr*3)]=np.linspace(0,1,int(sr*3))**2; env[-int(sr*1.5):]=np.linspace(1,0.3,int(sr*1.5))
sig = sig*env/np.max(np.abs(sig))*0.7; pcm = (np.clip(sig,-1,1)*32767).astype(np.int16)
with wave.open('{audio_dir}/00-riser.wav','wb') as wf:
    wf.setnchannels(1);wf.setsampwidth(2);wf.setframerate(sr);wf.writeframes(pcm.tobytes())
# Bing
dur2 = 0.8; t = np.linspace(0,dur2,int(sr*dur2)); f=880
tone = 0.6*np.sin(2*np.pi*f*t)+0.3*np.sin(2*np.pi*f*2*t)+0.15*np.sin(2*np.pi*f*1.5*t)
env2 = np.exp(-t*5)*(1-np.exp(-t*200)); sig2 = tone*env2/np.max(np.abs(tone*env2))*0.5
pcm2 = (np.clip(sig2,-1,1)*32767).astype(np.int16)
with wave.open('{audio_dir}/00-bing.wav','wb') as wf:
    wf.setnchannels(1);wf.setsampwidth(2);wf.setframerate(sr);wf.writeframes(pcm2.tobytes())
""",
        ],
        capture_output=True,
    )

    # Choreograph
    print("\nChoreographing (Opus)...")
    from agents.demo_models import DemoScene, DemoScript
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
    from agents.demo_pipeline.app_scenes import convert_to_app_scenes

    convert_to_app_scenes(
        demo_script, output_dir, on_progress=print, choreography=choreography_actions
    )

    # Insert riser + bing
    import json

    app_script_path = output_dir / "app-script.json"
    scenes_json = json.load(open(app_script_path))
    scenes_json.insert(0, {"title": "", "audioFile": "00-bing.wav", "actions": []})
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
