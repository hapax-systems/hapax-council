"""Demo generator agent — produces audience-tailored demos from natural language requests."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from opentelemetry.trace import get_current_span, get_tracer
from pydantic_ai import Agent

try:
    from shared import langfuse_config  # noqa: F401
except ImportError:
    pass

tracer = get_tracer(__name__)

from agents.demo_models import (
    AudiencePersona,
    ContentSkeleton,
    DemoScript,
    load_audiences,
    load_personas,
)
from agents.demo_pipeline.slides import render_slides
from shared.config import PROFILES_DIR, get_model

log = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output" / "demos"

# Map common natural-language audience hints to archetypes
AUDIENCE_HINTS: dict[str, str] = {
    "wife": "family",
    "husband": "family",
    "partner": "family",
    "mom": "family",
    "dad": "family",
    "parent": "family",
    "friend": "family",
    "kid": "family",
    "child": "family",
    "engineer": "technical-peer",
    "developer": "technical-peer",
    "architect": "leadership",
    "manager": "leadership",
    "director": "leadership",
    "vp": "leadership",
    "cto": "leadership",
    "report": "team-member",
    "team": "team-member",
    "colleague": "team-member",
    "investor": "leadership",
    "executive": "leadership",
    "recruiter": "leadership",
    "intern": "team-member",
    "client": "leadership",
    "customer": "leadership",
}


def parse_duration(duration_str: str | None, audience: str) -> int:
    """Parse duration string to seconds. Falls back to audience defaults."""
    AUDIENCE_DEFAULTS = {
        "family": 180,
        "team-member": 420,
        "leadership": 600,
        "technical-peer": 720,
    }
    if duration_str is None:
        return AUDIENCE_DEFAULTS.get(audience, 420)
    duration_str = duration_str.strip().lower()
    if duration_str.endswith("m"):
        return int(float(duration_str[:-1]) * 60)
    if duration_str.endswith("s"):
        return int(float(duration_str[:-1]))
    return int(float(duration_str))


def parse_request(text: str) -> tuple[str, str]:
    """Parse 'scope for audience' from natural language. Returns (scope, audience).

    Uses non-greedy match on scope so 'X for Y for Z' splits as scope='X', audience='Y for Z'.
    """
    match = re.match(r"(.+?)\s+for\s+(.+)", text, re.IGNORECASE)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return text.strip(), "technical-peer"


def resolve_audience(audience_text: str, personas: dict[str, AudiencePersona]) -> tuple[str, str]:
    """Resolve audience text to archetype name + extra context."""
    lower = audience_text.lower()

    # Direct archetype match
    if lower in personas:
        return lower, ""

    # Named dossier match — check demo-audiences.yaml for named people
    dossiers = load_audiences()
    for dossier_key, dossier in dossiers.items():
        if dossier_key in lower:
            archetype = dossier.archetype
            if archetype in personas:
                return archetype, audience_text
            break

    # Hint-based matching (word boundaries to avoid false positives)
    for hint, archetype in AUDIENCE_HINTS.items():
        if re.search(rf"\b{re.escape(hint)}\b", lower):
            extra = audience_text if archetype != lower else ""
            return archetype, extra

    # Default to technical-peer
    return "technical-peer", audience_text


def build_planning_prompt(
    scope: str,
    audience_name: str,
    persona: AudiencePersona,
    research_context: str,
    planning_context: str,
    duration_constraints: dict | None = None,
    planning_overrides: str | None = None,
) -> str:
    """Build the enriched LLM prompt for demo scene planning."""
    show_list = "\n".join(f"  - {item}" for item in persona.show)
    skip_list = "\n".join(f"  - {item}" for item in persona.skip)
    forbidden_section = ""
    if persona.forbidden_terms:
        terms_list = "\n".join(f"- {t}" for t in persona.forbidden_terms)
        forbidden_section = (
            f"\n\nFORBIDDEN TERMS (never use these words or phrases in narration):\n"
            f"{terms_list}\n"
            f"Using any of these terms will cause the demo to FAIL evaluation."
        )

    # Use the larger scene count between persona and duration tier
    max_scenes = persona.max_scenes
    target_seconds = duration_constraints["max_seconds"] if duration_constraints else 420
    if duration_constraints:
        scene_min, scene_max = duration_constraints["scenes"]
        max_scenes = max(max_scenes, scene_max)

    prompt = f"""Plan a demo of: {scope}

Target audience: {audience_name}
Audience description: {persona.description}
Tone: {persona.tone}
Vocabulary level: {persona.vocabulary}

What to show:
{show_list}

What to skip:
{skip_list}
{forbidden_section}
Target scene count: {max_scenes} scenes (minimum {duration_constraints["scenes"][0] if duration_constraints else 3})

{planning_context}

## Research Context
{research_context}

Available web interfaces for screenshots:

LOGOS WEB (http://localhost:5173) — the custom dashboard:
- / — Main dashboard with health, agents, timers, briefing, scout, drift, goals panels
- /chat — Chat interface with streaming LLM responses
- /demos — Demo listing page

OPEN WEBUI (http://localhost:3080) — general-purpose LLM chat interface:
- / — Chat page with model selection and conversation history

IMPORTANT: For screenshot specs, do NOT set wait_for — the pipeline automatically uses
known-good selectors for each route. Only set url and any actions needed.

Screenshot actions use SIMPLE syntax (NOT Playwright API):
- "scroll 1000" — scroll to middle panels (agents, timers)
- "scroll 2000" — scroll to lower panels (briefing, scout, drift, goals)
- "scroll 3000" — scroll to bottom panels
- "click .selector" — click an element
- "type some text" — type text into focused element
- "wait 2000" — wait 2 seconds
IMPORTANT: The dashboard is tall — small scrolls (200-400px) won't show different content.
Use scroll values of 1000+ to see genuinely different dashboard panels.
Do NOT use page.evaluate(), page.locator(), or any Playwright API syntax — those will be ignored.

Generate a DemoScript with scenes that showcase the requested scope, tailored to this audience.
For each scene, choose the visual type using this decision framework:

STEP 1 — What is this scene communicating?
  A. A UI feature or live capability → screenshot (show the real system)
  B. Architecture, relationships, or component topology → diagram (D2)
  C. Quantitative data, trends, or comparisons → chart (only if real data exists in Research Context)
  D. Dynamic behavior that static images can't capture → screencast (max 2 per demo)
  E. A workflow or process sequence → diagram (D2), using the System Workflows section from Research Context for accurate step sequences
  F. An abstract concept, motivation, or "why" that has no concrete relationships to diagram → illustration (AI-generated conceptual image, max 3 per demo)

STEP 2 — Audience calibration:
  - Family/non-technical: simplify diagrams (3-5 nodes max), use simple chart types (bar only), skip architecture diagrams unless essential. Use illustration for abstract/motivational scenes.
  - Technical peer: full detail diagrams, complex charts ok, show design rationale
  - Leadership: high-level diagrams, KPI charts, focus on impact
  - Team member: operational diagrams, show the cadence and automation

STEP 3 — Coherence check:
  Does this visual DIRECTLY illustrate the scene's key message? If not, switch to a different type or use a clean title-card slide. A decorative visual is worse than no visual.

Visual types:
- 'screenshot' — ONLY use localhost:5173 with paths: /, /chat, /demos
- 'diagram' — for architecture/relationships (include D2 source in diagram_spec)
- 'chart' — for data trends/comparisons (include chart spec JSON in diagram_spec)
- 'screencast' — for showing LIVE interactions (chat streaming, dashboard scrolling, agent execution)
- 'illustration' — for abstract concepts, motivation, personal meaning. NOT for architecture, data, or workflows.
  * Include an illustration spec with a descriptive prompt of what to visualize
  * The pipeline adds audience-appropriate style automatically
  * Max 3 illustration scenes per demo
  * No text will appear in the image — all text goes in key_points

SCREENCAST RULES:
- Use screencast when showing dynamic behavior that a static screenshot can't capture
- Maximum 2 screencast scenes per demo (expensive to record)
- You MUST use a named recipe — do NOT write custom interaction steps (they will be ignored)
- Set interaction with recipe name and url only. Example: interaction=InteractionSpec(url="http://localhost:5173/chat", recipe="chat-health-query")

Available recipes and what they show on screen:
- 'chat-health-query' — types "What is the current system health?" in /chat, waits for streaming response
- 'chat-briefing-query' — types "Give me today's briefing summary" in /chat, waits for streaming response
- 'chat-system-overview' — types "What can you help me with?" in /chat, waits for streaming response
- 'dashboard-overview' — scrolls through the main dashboard panels on /
- 'run-health-agent' — clicks health_monitor agent on dashboard, waits for output

CRITICAL: Your narration MUST match what the recipe actually types on screen. If you use 'chat-health-query', narrate about asking the system health question — do NOT narrate about a different question. The viewer will see text being typed that contradicts the narration.

D2 diagram syntax rules (CRITICAL — invalid syntax causes render failures):
- Valid shapes: rectangle, square, circle, oval, diamond, cylinder, cloud, person, page, hexagon, package, queue, step, callout, stored_data, document, parallelogram, text, code
- INVALID shapes that will FAIL: eye, mic, phone, server, gear, bell, arrows, star, shield, lock, globe, box, terminal
- Do NOT add inline style.fill or style.stroke — the Gruvbox theme is applied automatically
- Keep diagrams simple: 3-7 nodes with labeled connections
- CORRECT shape syntax — shape goes INSIDE braces with 'shape:' property:
  'LiteLLM: {{\n  shape: rectangle\n}}\n\nOllama: {{\n  shape: cylinder\n}}\n\nLiteLLM -> Ollama: routes models'
- WRONG (DO NOT DO THIS): 'LiteLLM: rectangle' — this creates a child node named "rectangle", NOT a shape
- WRONG: 'Node: rectangle {{content}}' — "rectangle" becomes a child, not a shape
- For labels different from the node ID: 'MyNode: {{\n  label: "Display Name"\n  shape: cloud\n}}'
- For sublabels: 'MyNode: {{\n  label: "LiteLLM Gateway"\n  shape: rectangle\n  near: "127.0.0.1:4000"\n}}'

DIAGRAM VARIETY — each diagram must look visually DISTINCT from the others:
- Vary direction: use 'direction: right' for architectures, 'direction: down' for flows/pipelines, omit direction for clusters
- Use semantic shapes: cylinder for databases/storage, cloud for external services, person for actors/users, hexagon for central hubs, diamond for decisions, queue for buffers, document for files/reports
- Do NOT make every diagram a left-to-right chain of rectangles — that looks repetitive
- Each diagram should use a DIFFERENT dominant shape and layout pattern

IMPORTANT: Screenshot URLs MUST be http://localhost:5173/ or http://localhost:5173/chat or http://localhost:5173/demos. No other URLs exist.

Chart spec JSON format (use this exact structure, NOT Chart.js format):
  Bar: {{"type": "bar", "title": "Title", "data": {{"labels": ["A", "B"], "values": [10, 20]}}}}
  Horizontal bar: {{"type": "horizontal-bar", "title": "Title", "data": {{"labels": ["A", "B"], "values": [10, 20]}}}}
  Stacked bar: {{"type": "stacked-bar", "title": "Title", "data": {{"labels": ["A", "B"], "datasets": [{{"label": "Series 1", "data": [10, 20]}}, {{"label": "Series 2", "data": [5, 15]}}]}}}}
  Line: {{"type": "line", "title": "Title", "data": {{"x": [1, 2, 3], "y": [10, 20, 30]}}}}
  Area: {{"type": "area", "title": "Title", "data": {{"x": [1, 2, 3], "y": [10, 20, 30]}}, "xlabel": "Time", "ylabel": "Count"}}
  Pie: {{"type": "pie", "title": "Title", "data": {{"labels": ["A", "B", "C"], "values": [40, 35, 25]}}}}
  Gauge: {{"type": "gauge", "title": "Title", "data": {{"value": 74, "max": 75, "label": "Score"}}}}
  Network: {{"type": "network", "title": "Title", "data": {{"nodes": ["A", "B", "C"], "edges": [{{"source": "A", "target": "B"}}, {{"source": "B", "target": "C"}}]}}}}
  Multi-line: {{"type": "stacked-line", "title": "Title", "data": {{"labels": ["Day 1", "Day 2"], "datasets": [{{"label": "Series A", "data": [10, 20]}}, {{"label": "Series B", "data": [5, 15]}}]}}}}
  Timeline: {{"type": "timeline", "title": "Title", "data": {{"events": [{{"time": "07:00", "event": "Briefing"}}, {{"time": "12:00", "event": "Update"}}]}}}}

CHART DATA INTEGRITY (CRITICAL — violations cause automatic rejection):
- EVERY number in a chart MUST come verbatim from the Research Context. Do NOT invent illustrative data.
- If you don't have real data for a chart, use a DIAGRAM instead. Diagrams show relationships and architecture; charts show data. No data = no chart.
- Charts with placeholder/round numbers (10, 20, 30, 40) or suspiciously clean percentages (75%, 20%, 5%) are obvious fabrications and will be rejected.

ALLOWED CHART TYPES (use ONLY these — any other type will fail to render):
  bar, horizontal-bar, stacked-bar, line, area, pie, gauge, network, stacked-line, timeline
Do NOT invent chart types. "combined", "dashboard", "hierarchical", "heatmap", "treemap" etc. do NOT exist.

CHART TYPE SELECTION — match the chart to the data:
- Comparisons between categories → bar or horizontal-bar
- Proportions/composition → pie
- Trends over time → line, area, or stacked-line
- Single KPI/score → gauge
- Relationships/flow → network
- Event sequence → timeline
- Do NOT use the same chart type twice in a row

Each scene needs narration text, 2-4 key_points, and a visual type.
Tailor bullet complexity to the audience vocabulary level.
Write narration as natural spoken language — this will be read aloud by text-to-speech.

CRITICAL NARRATION STYLE RULE — visuals are STATIC images (screenshots, diagrams, charts), NOT live demos:
- NEVER write narration that references on-screen activity: "as you can see", "notice on screen", "if I click here", "watch as", "look at this data", "you'll see it updating"
- INSTEAD, narrate the concept, the design rationale, and personal experience: "The dashboard shows health status", "I built this to track...", "The architecture uses..."
- The visual ILLUSTRATES the topic; the narration EXPLAINS the topic. They complement, not describe each other.

CRITICAL NARRATION LENGTH RULES — YOUR DEMO WILL BE REJECTED IF NARRATIONS ARE TOO SHORT:
- Total word count across ALL narrations (intro + scenes + outro) MUST be at least {int(target_seconds * 2.5 * 0.65)} words. Target: {int(target_seconds * 2.5)} words.
- Each scene narration: MINIMUM {duration_constraints["words_per_scene"][0] if duration_constraints else 100} words, aim for {duration_constraints["words_per_scene"][1] if duration_constraints else 200} words.
- Intro narration: 15-30 words MAXIMUM (1-2 sentences). Plays over static title card — keep brief.
- Outro narration: 15-30 words MAXIMUM (1-2 sentences).
- Speech rate: 150 words/minute (2.5 words/second). Short narration = demo plays too fast.
- Write full paragraphs (5-8 sentences per scene) with concrete details from the research context.
- For 10+ minute demos: each scene is a mini-explanation (what it is → how it works → why it matters). Use REAL data only.
- COUNT YOUR WORDS. If a narration feels like 2-3 sentences, it's too short. Each scene needs a full spoken paragraph.

VISUAL-NARRATION ALIGNMENT (CRITICAL — misaligned scenes fail evaluation):
- Each scene's visual MUST directly illustrate the narration topic. Plan the visual FIRST, then write narration about what the visual shows.
- Screenshot of / (dashboard) → narrate health monitoring, system overview, or operational metrics
- Screenshot of /chat → narrate the conversational interface, how it works, or what you can ask
- Screenshot of /demos → narrate the demo system itself
- Diagram → narrate the architecture, flow, or relationships shown IN the diagram
- Chart → narrate the data, trends, or comparisons shown IN the chart
- Self-check: "If I mute the narration and show only the image, does the topic remain clear?"
- WRONG: narration about "automated scheduling" paired with a generic dashboard screenshot
- RIGHT: narration about "automated scheduling" paired with a diagram showing the timer→agent→notification flow

VISUAL VARIETY RULES (CRITICAL — violations cause evaluation failure):
- PREFER screenshots and screencasts over diagrams. The audience wants to SEE the real system, not abstract diagrams.
- STRICT RATIO: At least 50% of scenes MUST be screenshots or screencasts. Count your scenes: if you have N scenes, at least ceil(N/2) must be screenshots or screencasts. For 18 scenes, that means 9+ screenshots/screencasts and at most 9 diagrams. VIOLATION OF THIS RATIO WILL FAIL EVALUATION.
- MAXIMUM 2 screencast scenes per demo (expensive to record).
- MANDATORY screenshot allocation — you MUST use ALL FOUR of these:
  * At least 1 screenshot of http://localhost:5173/ (dashboard top — no scroll)
  * At least 1 screenshot of http://localhost:5173/ with "scroll 400" (dashboard bottom half)
  * At least 1 screenshot of http://localhost:5173/chat (the chat interface — different page!)
  * At least 1 screenshot of http://localhost:5173/demos (the demo listing — different page!)
  * MAXIMUM 2 screenshots of / or /demos — these are STATIC pages, multiple screenshots are pixel-identical duplicates. Use /chat for additional screenshots (up to 5) since each gets a unique question seeded automatically and looks different.
- NEVER use the same visual type 3+ times in a row. Always alternate diagram→screenshot or screenshot→diagram. After 2 consecutive diagrams, the NEXT scene MUST be a screenshot or screencast.
- When choosing between a diagram and a screenshot for any scene, DEFAULT TO SCREENSHOT unless the topic genuinely cannot be illustrated by any existing web page (e.g. showing a data flow that has no UI representation).
- Do NOT invent screenshot URLs. Only these 3 routes exist: http://localhost:5173/, http://localhost:5173/chat, http://localhost:5173/demos
- Charts must use ONLY real data from the Research Context. If you don't have real numbers, use a screenshot or diagram instead.

HONESTY AND ACCURACY RULES (violations cause automatic rejection):
- NEVER invent statistics, percentages, cost figures, or time-savings claims. Only cite numbers that appear verbatim in the Research Context below.
- This system is UNDER ACTIVE DEVELOPMENT. Do not narrate as if it's been running in daily life for months. Use "it's designed to...", "so far it can...".
- NEVER claim reliability like "hasn't given me trouble" or "runs smoothly" — the system is actively being developed and debugged.
- Do NOT describe generic LLM capabilities (answering questions, writing emails, summarizing) as unique to this system.
- CLEARLY DISTINGUISH what LLMs already do (chat, answer questions, summarize text) from what THIS SYSTEM adds on top (agents that run autonomously, self-monitoring, profile learning across 13 dimensions, management support tools, executive function accommodation). This boundary is critical for non-technical audiences to understand what the builder actually created.
- The primary value is NOT "saving time on maintenance" or "system health monitoring." Those are background infrastructure. The real value is: life organization, domain balance (work/personal/health), better relationships, executive function support, and personal growth.
- Do NOT assume what ADHD/autism means for the operator. Only describe specific accommodations that are actually built into the system and visible in the Research Context. No generic "struggles with..." framing.

NARRATIVE STRUCTURE RULES:
- Scene 1 MUST be a big-picture overview: what this whole thing is, in plain terms, before ANY features. Use a screenshot of the dashboard (/) to show it's real, but the narration explains the overall concept — NOT the dashboard's health panel.
- Scene 2-3 MUST include ONE overall system diagram showing the major pieces (knowledge, agents, chat, briefings, monitoring) and how they connect. This gives the viewer a mental map before diving into details.
- After scenes 1-3, each scene goes deeper into one specific capability.
- Do NOT lead with technical infrastructure (health monitoring, self-healing, cost tracking). Lead with what it DOES for the person — life organization, understanding people, achieving goals.
- System health and self-healing are background plumbing. Mention once briefly in ONE sentence, not as a featured scene or key point.
- The narration for dashboard screenshots should focus on what the FEATURES do for the user, not describe the UI layout or health panels.
- The Research Context includes a "Major System Components" section listing components that MUST appear in any full-system demo. Each component listed there needs at least a mention in narration, and the most important ones deserve their own scene.
- SELF-DEMO CAPABILITY IS MANDATORY: If the Major System Components section mentions a "Self-Demo System", you MUST dedicate at least one scene to it. This is a unique, differentiating capability — the system generates demos OF ITSELF. Use a screenshot of http://localhost:5173/demos to show the demo listing page, and narrate how the pipeline works (content planning, screenshots, voice cloning, evaluation loop). This scene is NON-NEGOTIABLE for any full-system demo.
- For components that are desktop apps (like Obsidian), use a DIAGRAM to show data flows since Playwright can only screenshot web services.

TONE RULES (violations cause automatic rejection):
- This is NOT a pitch, NOT a presentation, NOT a story about the builder. Describe the software directly.
- Do NOT narrate the act of showing: "this is what I built", "let me show you", "what I've been working on", "here's my...". Just describe the system.
- No metaphors about workshops, garages, or labs. This is software. Describe it as software.
- Do NOT frame every feature around "this helps me with X" — describe what the feature DOES and HOW it works. Let the audience draw their own conclusions about value.
- Narrate like an engineer explaining software: matter-of-fact, specific, honest about what works and what doesn't yet.

VISUAL SUBSTANCE RULES (violations cause automatic rejection):
- Every visual MUST convey specific, meaningful information about THIS system. No decorative or generic illustrations.
- Diagrams must show REAL architecture from the Research Context: actual service names, actual data flows, actual agent names. No generic "Data Source → Processor → Output" diagrams.
- Charts must use REAL numbers from the Research Context. If the research says 76 health checks or 14 agents, use those exact numbers. No round-number placeholders.
- Each diagram should have a distinct topology: not everything is a left-to-right flow. Use clusters, hierarchies, cycles, hub-and-spoke patterns based on what the architecture actually looks like.
- If you can't make a visual that conveys real, specific information about this system, use a screenshot instead."""

    if planning_overrides:
        prompt += f"""

## EVALUATION FEEDBACK — CRITICAL CORRECTIONS
The following corrections are from evaluation of a previous iteration. These OVERRIDE any conflicting instructions above.
Follow these instructions EXACTLY:

{planning_overrides}
"""

    return prompt


def _load_system_description() -> str:
    """Load system description from available sources."""
    # Try CLAUDE.md first
    claude_md = PROFILES_DIR.parent.parent / "hapaxromana" / "CLAUDE.md"
    if claude_md.exists():
        return claude_md.read_text()[:4000]

    # Fallback to manifest
    manifest = PROFILES_DIR / "manifest.json"
    if manifest.exists():
        return manifest.read_text()[:4000]

    return "A three-tier autonomous agent system with web dashboard, health monitoring, and 13+ agents."


# Agent definition
agent = Agent(
    get_model("balanced"),
    system_prompt=(
        "You are an expert presentation planner producing demo scripts for a personal "
        "agent infrastructure system. You plan scenes with precise narration, "
        "audience-appropriate vocabulary, and deliberate visual choices. "
        "Follow the narrative framework provided. Respect the duration constraints exactly. "
        "Match the presenter's style guide. Ground every claim in the research context. "
        "Each scene must justify its inclusion."
    ),
    output_type=DemoScript,
    model_settings={"max_tokens": 32768},
)

# Two-pass agents
content_agent = Agent(
    get_model("balanced"),
    system_prompt=(
        "You are a content planner for technical demos. Your job is to decide WHAT to show "
        "and WHAT facts to state — not how to say them. Output a structured content skeleton "
        "with specific facts, data citations, visual choices, and design rationale. "
        "Do NOT write narration prose. Only output structured content plans."
    ),
    output_type=ContentSkeleton,
    model_settings={"max_tokens": 16384},
)

# Opus-tier content planner — used for app format where content quality is paramount
content_agent_opus = Agent(
    get_model("claude-opus"),
    system_prompt=(
        "You are a content planner for technical demos. Your job is to decide WHAT to show "
        "and WHAT facts to state — not how to say them. Output a structured content skeleton "
        "with specific facts, data citations, visual choices, and design rationale. "
        "Do NOT write narration prose. Only output structured content plans."
    ),
    output_type=ContentSkeleton,
    model_settings={"max_tokens": 16384},
)

voice_agent = Agent(
    get_model("claude-opus"),
    system_prompt=(
        "You are a narration writer. You transform structured content plans into spoken "
        "narration that matches provided voice examples exactly. You write in the voice "
        "of the builder describing their own work — matter-of-fact, first-person, concrete. "
        "Every narration passage should sound like it was written by the same person who "
        "wrote the voice examples."
    ),
    output_type=DemoScript,
    model_settings={"max_tokens": 32768},
)


def build_content_prompt(
    scope: str,
    audience_name: str,
    persona: AudiencePersona,
    research_context: str,
    framework: dict,
    duration_constraints: dict,
    target_seconds: int,
    never_rules: list[str] | None = None,
    voice_profile: dict | None = None,
) -> str:
    """Build the Pass 1 prompt — content planning only, no prose."""
    show_list = "\n".join(f"  - {item}" for item in persona.show)
    skip_list = "\n".join(f"  - {item}" for item in persona.skip)
    forbidden_section = ""
    if persona.forbidden_terms:
        terms_list = "\n".join(f"- {t}" for t in persona.forbidden_terms)
        forbidden_section = f"\n\nFORBIDDEN TERMS (never reference these concepts):\n{terms_list}\n"

    max_scenes = persona.max_scenes
    scene_min, scene_max = duration_constraints["scenes"]
    max_scenes = max(max_scenes, scene_max)

    result = f"""Plan the content for a demo of: {scope}

Target audience: {audience_name}
Audience description: {persona.description}
Vocabulary level: {persona.vocabulary}

What to show:
{show_list}

What to skip:
{skip_list}
{forbidden_section}
Scene count: {scene_min}-{max_scenes} scenes. AIM FOR {max_scenes} SCENES. Each scene should make 2-3 points, not 5-7. If a topic needs 5+ facts, SPLIT it into multiple scenes with different visuals. Fewer scenes = overstuffed slides where the viewer sees the same image too long while hearing too many unrelated points.

## Narrative Framework: {framework["name"]}
Flow: {framework["section_flow"]}
Structure:
{chr(10).join(f"  {i}. {s}" for i, s in enumerate(framework["structure"], 1))}

## OPENING RULE (Critical — demos that fail this feel aimless)
The viewer must know WHAT THIS IS within 15 seconds. The intro_narration + Scene 1 must answer:
"What am I looking at?" in plain, concrete terms. NOT vague framing like "I've been working on something"
or "this handles cognitive overhead." Instead: "I built a personal AI system that runs on my computer."
Scene 1 should orient the viewer — show what the system DOES (not how it's built). Lead with a demo
of the most impressive or relatable capability, not an architecture diagram.

## Research Context
{research_context}

## Visual Rules

The logos web dashboard is at http://localhost:5173 with these pages:
- / — Main dashboard with health, VRAM, containers, timers, briefing, scout, drift, goals, cost panels
- /chat — Chat interface with streaming LLM responses
- /demos — Demo listing page

For screenshot specs, do NOT set wait_for — the pipeline handles selectors automatically.
Screenshot actions use SIMPLE syntax: "scroll 1000", "scroll 2000", "click .selector", "wait 2000".
Do NOT use page.evaluate(), page.locator(), or Playwright API — those are ignored. Use scroll values of 1000+ to show different dashboard panels.

Visual types:
- 'screenshot' — actual UI (ONLY localhost:5173 paths: /, /chat, /demos). Can screenshot same route at different scroll positions using actions=["scroll 1000"].
- 'diagram' — architecture/relationships. Include D2 source in diagram_spec.
- 'chart' — data trends/comparisons. You MUST include the chart spec JSON in diagram_spec.

CRITICAL: Every chart scene MUST have a complete JSON object in diagram_spec. An empty diagram_spec for a chart scene will crash the renderer. Example: diagram_spec='{{"type": "bar", "title": "Health Checks", "data": {{"labels": ["Pass", "Fail"], "values": [75, 3]}}}}'

D2 syntax: valid shapes are rectangle, square, circle, oval, diamond, cylinder, cloud, person, page, hexagon, package, queue, step, callout, stored_data, document, parallelogram, text, code. No inline styles.

Chart spec JSON format:
  Bar: {{"type": "bar", "title": "Title", "data": {{"labels": ["A", "B"], "values": [10, 20]}}}}
  Horizontal bar: {{"type": "horizontal-bar", "title": "Title", "data": {{"labels": ["A", "B"], "values": [10, 20]}}}}
  Stacked bar: {{"type": "stacked-bar", "title": "Title", "data": {{"labels": ["A", "B"], "datasets": [{{"label": "Series 1", "data": [10, 20]}}, {{"label": "Series 2", "data": [5, 15]}}]}}}}
  Line: {{"type": "line", "title": "Title", "data": {{"x": [1, 2, 3], "y": [10, 20, 30]}}}}
  Area: {{"type": "area", "title": "Title", "data": {{"x": [1, 2, 3], "y": [10, 20, 30]}}, "xlabel": "X", "ylabel": "Y"}}
  Pie: {{"type": "pie", "title": "Title", "data": {{"labels": ["A", "B", "C"], "values": [40, 35, 25]}}}}
  Gauge: {{"type": "gauge", "title": "Title", "data": {{"value": 74, "max": 75, "label": "Score"}}}}
  Network: {{"type": "network", "title": "Title", "data": {{"nodes": ["A", "B", "C"], "edges": [{{"source": "A", "target": "B"}}, {{"source": "B", "target": "C"}}]}}}}
  Multi-line: {{"type": "stacked-line", "title": "Title", "data": {{"labels": ["Day 1", "Day 2"], "datasets": [{{"label": "Series A", "data": [10, 20]}}, {{"label": "Series B", "data": [5, 15]}}]}}}}
  Timeline: {{"type": "timeline", "title": "Title", "data": {{"events": [{{"time": "07:00", "event": "Briefing"}}, {{"time": "12:00", "event": "Update"}}]}}}}

ALLOWED CHART TYPES (use ONLY these — any other type will fail to render):
  bar, horizontal-bar, stacked-bar, line, area, pie, gauge, network, stacked-line, timeline
Do NOT invent chart types like "combined", "dashboard", "hierarchical", "heatmap", "treemap" — these will crash.

CRITICAL — chart data integrity: EVERY number in a chart must come verbatim from the Research Context. No invented data. If no real data exists for a chart, use a DIAGRAM instead.
Common chart violations that WILL FAIL review:
- Fabricated percentages/ratios ("40% local, 60% cloud") — if the research doesn't have those exact numbers, use a diagram
- All-ones charts (every value = 1) — this is just a bulleted list rendered as a useless chart. Use a DIAGRAM with labeled nodes instead
- Fabricated gauge values — only use gauge if you have an exact count from research (e.g. "77/78 healthy")
- Invented pie chart splits — if you don't know the real proportions, use a diagram showing the relationship instead
RULE: If your chart would have all identical values OR any invented number, switch to visual_type "diagram" with D2 source code.

CRITICAL — chart types: ONLY use these types: bar, horizontal-bar, stacked-bar, line, area, pie, gauge, network, stacked-line, timeline. Do NOT invent types like "doughnut", "comparison", "combined", "dashboard", "hierarchical" — these will crash.

Diagram variety: vary direction (right, down, omit), use semantic shapes, each diagram must look visually distinct.

Visual variety: AT LEAST HALF of all scenes MUST be screenshots or screencasts. Default to screenshots — only use diagrams when no web page illustrates the concept. MANDATORY: at least one screenshot/screencast of EACH route (/, /chat, /demos). MAX 2 screenshots of / or /demos (static pages). Use /chat for additional screenshots (up to 5). Max 2 screencasts. Max 3 illustrations. NEVER 3 consecutive same visual type. For WORKFLOW scenes, reference the System Workflows section for accurate step sequences — do NOT invent workflow topologies. Illustrations are for abstract concepts only — never for architecture, data, or workflows.

## Family Audience Scene Planning (applies when audience is family)
- Frame EVERY scene through personal impact: "this helps me because...", "the reason this matters is..."
- AVOID pure architecture scenes (e.g. "Three-Tier Agent Architecture") — family viewers don't care about tiers
- Instead of "how it's built", show "what it does for me" — reframe technical concepts through daily life
- Use scene titles that a non-technical person would find interesting, not conference-talk abstracts
- Chart data MUST come from research context — if no real numbers exist for a concept, use a diagram instead

## Slide Content Structure
Slides show key_points as bullet lists next to the visual. Good presentations use structured content:
- Aim for 3-6 key_points per scene (not 2-3). Each bullet should be a specific, concrete claim.
- For scenes that compare/contrast two approaches (e.g. "generic AI vs my system"), plan facts suitable for a comparison table rather than standalone bullets. The voice pass will render these as a slide_table.
- Keep bullet text short (8-15 words) — the narration provides the detail, bullets reinforce the takeaway.

## Honesty Rules
- Only cite numbers that appear verbatim in the Research Context.
- System is under active development — use "designed to", "so far it can".
- Focus on what's architecturally unique, not generic LLM capabilities.
- Do not describe what ADHD/autism means generically — only mention specific built accommodations visible in the Research Context.
- Do NOT plan content about capabilities that aren't in the Research Context. If the research doesn't mention it, the system doesn't do it.
- Do NOT plan facts that reference daily routines, habits, or specific times of day unless they appear in the Research Context (e.g. "timer fires at 07:00" is factual; "every morning I check..." is fabricated).

## Title Rules
- For family/non-technical audiences: use a conversational, personal title (e.g. "What I've Been Building", "My AI System"). Avoid clinical or technical titles like "Executive Function Infrastructure" or "Personal AI Platform".
- For technical audiences: descriptive titles are fine (e.g. "Three-Tier Agent Architecture", "Self-Healing LLM Stack").
- The title appears on the title card — it should look natural, not like a conference talk abstract.

## Output Instructions
Output a ContentSkeleton with:
- title and audience
- intro_points: 2-3 key points for the opening
- scenes: each with title, facts (specific claims grounded in research), data_citations (exact numbers), visual_type, visual_brief, screenshot/diagram_spec/interaction as needed, and optionally design_rationale and limitation_or_tradeoff
- outro_points: 2-3 key points for the closing

Do NOT write narration prose. Only output structured facts and visual plans."""

    # Inject voice profile constraints into content planning too
    if voice_profile:
        constraints = voice_profile.get("constraints", [])
        if constraints:
            constraint_lines = "\n".join(f"- {c}" for c in constraints)
            result += f"\n\n## CONTENT CONSTRAINTS (violations cause evaluation failure)\n{constraint_lines}"
    if never_rules:
        rules = "\n".join(f"- NEVER: {r}" for r in never_rules)
        result += f"\n\n## AUDIENCE-SPECIFIC HARD CONSTRAINTS\n{rules}"
    return result


def build_voice_prompt(
    skeleton: ContentSkeleton,
    voice_examples: dict,
    voice_profile: dict,
    duration_constraints: dict,
    target_seconds: int,
    never_rules: list[str] | None = None,
    audience_dossier_text: str = "",
    style_guide: dict | None = None,
) -> str:
    """Build the Pass 2 prompt — voice application from skeleton + examples.

    Prompt structure is ordered for maximum constraint adherence:
    1. Audience context + never rules (WHO is listening — set direction early)
    2. Voice identity + contrastive pairs (WHO is speaking — anchor register)
    3. Anti-fabrication + certainty levels (grounding rules)
    4. Good examples (gold-standard narration)
    5. Bad examples with annotations (what NOT to do)
    6. Content skeleton (what to say)
    7. Word count + formatting
    8. Constraint summary repeated (recency bias)
    """
    # ── Collect examples ──
    good_examples: list[str] = []
    bad_examples: list[str] = []
    for key, ex in voice_examples.get("examples", {}).items():
        text = ex.get("text", "").strip()
        label = ex.get("label", "")
        violation = ex.get("violation", "")
        if key.startswith("bad_"):
            entry = f'### BAD: {label}\n"{text}"'
            if violation:
                entry += f"\nWHY THIS FAILS: {violation}"
            bad_examples.append(entry)
        else:
            good_examples.append(f'### {label}\n"{text}"')

    # ── Collect contrastive pairs from style guide ──
    contrastive_text = ""
    if style_guide:
        pairs = style_guide.get("contrastive_pairs", [])
        if pairs:
            lines = []
            for pair in pairs:
                lines.append(f'NOT THIS: "{pair["bad"]}"')
                lines.append(f'THIS: "{pair["good"]}"')
                lines.append(f"({pair['violation']})\n")
            contrastive_text = "\n".join(lines)

    # ── Format certainty levels ──
    certainty_text = ""
    levels = voice_profile.get("certainty_levels", {})
    if levels:
        lines = []
        for level_name, level_data in levels.items():
            if isinstance(level_data, dict):
                lines.append(
                    f"- {level_name.upper()}: {level_data.get('description', '')} "
                    f'Example: "{level_data.get("example", "")}"'
                )
        certainty_text = "\n".join(lines)

    # ── Format voice constraints ──
    constraints = voice_profile.get("constraints", [])
    constraint_lines = "\n".join(f"- {c}" for c in constraints) if constraints else ""

    # ── Format sentence patterns, transitions, opening, closing ──
    profile_parts: list[str] = []
    profile_parts.append(f"Role: {voice_profile.get('role', 'operator')}")
    profile_parts.append(f"Register: {voice_profile.get('register', 'technical-conversational')}")
    profile_parts.append(f"Person: {voice_profile.get('person', 'first-person')}")
    profile_parts.append(f"Grounding: {voice_profile.get('grounding', 'concrete')}")
    for key in ("sentence_patterns", "transitions", "opening", "closing"):
        val = voice_profile.get(key, [])
        if isinstance(val, list):
            profile_parts.append(f"{key}: " + "; ".join(str(v) for v in val))
        elif isinstance(val, str):
            profile_parts.append(f"{key}: {val}")
    maturity = voice_profile.get("maturity_framing", {})
    if isinstance(maturity, dict):
        use = maturity.get("use", [])
        avoid = maturity.get("avoid", [])
        if use:
            profile_parts.append("Maturity — USE: " + ", ".join(f'"{u}"' for u in use))
        if avoid:
            profile_parts.append("Maturity — AVOID: " + ", ".join(f'"{a}"' for a in avoid))
    profile_text = "\n".join(profile_parts)

    # ── Word count targets ──
    inflation = 1.45 if target_seconds <= 600 else 1.55
    words_min, words_max = duration_constraints["words_per_scene"]
    words_min = int(words_min * inflation)
    words_max = int(words_max * inflation)
    total_words = int(target_seconds * 2.5 * inflation)
    num_scenes = len(skeleton.scenes)

    skeleton_json = skeleton.model_dump_json(indent=2)

    # ── Never rules with concrete examples ──
    never_text = ""
    if never_rules:
        never_text = "\n".join(f"- NEVER: {r}" for r in never_rules)

    # ── Build prompt in research-validated order ──
    result = f"""Transform this content skeleton into a complete DemoScript with spoken narration.

<audience>
## WHO IS LISTENING — read this first, it determines everything else

{audience_dossier_text if audience_dossier_text else "General audience. No specific dossier provided."}

### HARD CONSTRAINTS — violating ANY of these causes immediate rejection
{never_text if never_text else "No audience-specific constraints."}
</audience>

<voice>
## WHO IS SPEAKING — the register and identity of the narrator

You are the system's architect explaining it to a technically sharp friend over coffee.
You are not selling anything. You are not performing. You are thinking out loud about
something you built. You are not teaching — the audience is smart enough. You are sharing.

{profile_text}

### CONTRASTIVE PAIRS — study these before writing
{contrastive_text if contrastive_text else "No contrastive pairs provided."}
</voice>

<grounding>
## ANTI-FABRICATION — the #1 reason demos fail

FORBIDDEN — if you write ANY of these, the demo WILL be rejected:
- ALL temporal references to events: "Yesterday...", "This morning...", "Last week..."
- Fabricated people, events, counts, dollars, percentages not in source material
- Any specific event at a specific time that is not documented

ALLOWED — use ONLY these patterns:
- Present tense capability: "The system runs health checks every 15 minutes"
- Hypothetical: "If a service crashes overnight, I get a notification"
- Exact data from source material: quote numbers that appear in the research context

### CERTAINTY LEVELS — use the right framing for each claim
{certainty_text if certainty_text else "No certainty levels defined."}

{constraint_lines}

SELF-CHECK: Before finalizing, scan EVERY sentence for temporal markers and hedging language
("seems to", "promising", "might"). Rewrite as present-tense fact or quantified uncertainty.
</grounding>

<good_examples>
## GOLD STANDARD — every passage you write should sound like these

{chr(10).join(good_examples)}
</good_examples>

<bad_examples>
## FAILURES — if your output resembles ANY of these, rewrite it

{chr(10).join(bad_examples)}
</bad_examples>

<content>
## CONTENT SKELETON — what to say (transform this into narration)

{skeleton_json}
</content>

<formatting>
## WORD COUNT & STRUCTURE

- Target per scene: {(words_min + words_max) // 2} words ({words_min} min, {words_max} max)
- Total: ~{total_words} words across all narrations = {target_seconds}s at 150 wpm
- With {num_scenes} scenes + intro + outro, each scene needs ~{total_words // (num_scenes + 2)} words
- Each scene: 4-6 sentences developing ONE specific point from the skeleton
- Intro: 15-30 words MAX. Say what this is. No vague framing.
- Outro: 15-30 words MAX. Land on impact. No ceremony.
- Title: under 6 words. Conversational for family audiences.

## INSTRUCTIONS
1. Use skeleton facts + data_citations as raw material
2. Write in the voice demonstrated by good_examples
3. Include design_rationale and limitation_or_tradeoff where provided
4. Preserve visual_type, screenshot specs, diagram_spec, interaction specs exactly
5. Generate 3-6 key_points per scene (concrete, specific)
6. Set duration_hint = word_count / 2.5
7. For comparison scenes, use slide_table instead of key_points
8. Return: DemoScript with title, audience (archetype name), intro_narration, scenes, outro_narration
</formatting>

<constraints_repeated>
## FINAL REMINDER — these are the rules that get violated most often

1. Do NOT fabricate events, routines, or temporal specificity
2. Do NOT pitch, sell, or use marketing language ("powerful", "seamlessly", "meaningfully")
3. Do NOT explain neurodivergence to someone who knows it — describe the system, not the condition
4. Do NOT hedge with "promising", "seems to", "might" — state the fact or state the uncertainty with numbers
5. Do NOT use generic descriptions — name the component, state the number, cite the source
</constraints_repeated>"""

    return result


async def generate_demo(
    request: str,
    format: str = "slides",
    duration: str | None = None,
    on_progress: Callable[[str], None] | None = None,
    persona_file: Path | None = None,
    lesson_context: str | None = None,
    planning_overrides: str | None = None,
    enable_voice: bool = False,
) -> Path:
    """Generate a complete demo from a natural language request."""

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)
        else:
            log.info(msg)

    # 1. Parse request
    scope, audience_text = parse_request(request)
    progress(f"Scope: {scope} | Audience: {audience_text}")

    # 2. Resolve audience
    personas = load_personas(extra_path=persona_file)
    archetype, extra_context = resolve_audience(audience_text, personas)
    persona = personas[archetype]
    dossier_matched = bool(extra_context)
    progress(f"Resolved audience: {archetype}")

    # 3. Parse duration
    target_seconds = parse_duration(duration, archetype)
    progress(f"Target duration: {target_seconds}s ({target_seconds / 60:.0f}m)")

    # 4. System readiness gate
    with tracer.start_as_current_span(
        "demo.readiness",
        attributes={
            "demo.scope": scope,
            "demo.audience": archetype,
            "demo.audience_text": audience_text,
            "demo.dossier_matched": dossier_matched,
            "demo.target_seconds": target_seconds,
            "demo.format": format,
        },
    ):
        from agents.demo_pipeline.readiness import check_readiness

        progress("Checking system readiness...")
        readiness = check_readiness(
            require_tts=(format == "video" or enable_voice),
            auto_fix=True,
            on_progress=progress,
        )
        if not readiness.ready:
            issues_str = "\n".join(f"  - {i}" for i in readiness.issues)
            raise RuntimeError(
                f"System not ready for demo generation. Issues:\n{issues_str}\n"
                f"Fix these issues and retry."
            )

    # 4.5 Knowledge sufficiency gate
    with tracer.start_as_current_span("demo.sufficiency"):
        from agents.demo_pipeline.sufficiency import check_sufficiency

        progress("Checking knowledge sufficiency...")
        sufficiency = check_sufficiency(
            scope=scope,
            archetype=archetype,
            audience_text=audience_text,
            health_report=readiness.health_report,
            on_progress=progress,
        )
        if sufficiency.confidence == "blocked":
            gaps = [c.detail for c in sufficiency.system_checks if not c.available]
            raise RuntimeError(
                "Insufficient knowledge for demo generation:\n"
                + "\n".join(f"  - {g}" for g in gaps)
            )
        progress(f"Knowledge confidence: {sufficiency.confidence}")

        # Surface actionable tip when personalization could be improved
        if sufficiency.confidence == "adequate" and sufficiency.dimension_scores:
            missing_person = [
                d
                for d in sufficiency.dimension_scores
                if d.category == "person" and d.confidence == "missing"
            ]
            if missing_person:
                progress(
                    f"Tip: Run --gather-dossier to improve personalization. "
                    f"Missing: {', '.join(d.label for d in missing_person)}"
                )

    # 4.7 Drift check gate — ensure docs match reality before demoing
    with tracer.start_as_current_span("demo.drift_check"):
        progress("Checking for documentation drift...")
        try:
            from agents.drift_detector import detect_drift

            drift_report = await detect_drift()
            high_drift = [d for d in drift_report.drift_items if d.severity == "high"]
            if high_drift:
                drift_summary = "\n".join(
                    f"  - [{d.category}] {d.doc_file}: {d.doc_claim} → {d.reality}"
                    for d in high_drift[:5]
                )
                progress(
                    f"WARNING: {len(high_drift)} high-severity drift item(s) detected. "
                    f"Demo may contain stale information.\n{drift_summary}"
                )
            else:
                med_count = sum(1 for d in drift_report.drift_items if d.severity == "medium")
                if med_count:
                    progress(f"Drift check: {med_count} medium items (acceptable)")
                else:
                    progress("Drift check: clean — docs match reality")
        except Exception as e:
            progress(f"Drift check skipped (non-blocking): {e}")

    # 5. Subject research
    with tracer.start_as_current_span("demo.research"):
        from agents.demo_pipeline.research import gather_research

        progress("Researching subject matter...")
        research_context = await gather_research(
            scope=scope,
            audience=archetype,
            on_progress=progress,
            enrichment_actions=sufficiency.enrichment_actions,
            audience_dossier=sufficiency.audience_dossier,
        )

    # 6. Load narrative context
    from agents.demo_pipeline.narrative import (
        format_planning_context,
        get_duration_constraints,
        load_style_guide,
        load_voice_examples,
        load_voice_profile,
        select_framework,
    )

    style_guide = load_style_guide()
    framework = select_framework(archetype)
    duration_constraints = get_duration_constraints(target_seconds)
    planning_context = format_planning_context(
        style_guide, framework, duration_constraints, target_seconds
    )
    if lesson_context:
        planning_context += f"\n\n{lesson_context}"
    voice_examples = load_voice_examples()
    voice_profile = load_voice_profile()

    # 6.5 Resolve display name for title cards (dossier name > archetype label)
    audience_display_name = None
    if sufficiency.audience_dossier:
        audience_display_name = sufficiency.audience_dossier.name  # e.g. "Alex"

    # 6.6 Merge dossier calibration into persona
    dossier_never: list[str] = []
    if sufficiency.audience_dossier and sufficiency.audience_dossier.calibration:
        persona = persona.model_copy()
        persona.show.extend(sufficiency.audience_dossier.calibration.get("emphasize", []))
        persona.skip.extend(sufficiency.audience_dossier.calibration.get("skip", []))
        dossier_never = sufficiency.audience_dossier.calibration.get("never", [])

    # 7. Two-pass demo generation
    # 7a: Content planning (what to show) — facts only, no prose
    with tracer.start_as_current_span(
        "demo.content_plan", attributes={"scope": scope, "audience": archetype}
    ):
        # Use Opus for app format (content quality is paramount for live demos)
        active_content_agent = content_agent_opus if format == "app" else content_agent
        progress(
            f"Pass 1: Planning content structure ({'opus' if format == 'app' else 'balanced'})..."
        )
        content_prompt = build_content_prompt(
            scope,
            archetype,
            persona,
            research_context,
            framework,
            duration_constraints,
            target_seconds,
            never_rules=dossier_never or None,
            voice_profile=voice_profile,
        )
        if extra_context:
            content_prompt += f"\n\nAdditional audience context: {extra_context}"
        if planning_overrides:
            content_prompt += (
                f"\n\n## EVALUATION FEEDBACK — CRITICAL CORRECTIONS\n{planning_overrides}"
            )
        skeleton_result = await active_content_agent.run(content_prompt)
        skeleton = skeleton_result.output
        progress(f"Content plan: {len(skeleton.scenes)} scenes")

        # Emit LLM call metrics
        span = get_current_span()
        span.set_attribute("llm.pass", "content_plan")
        span.set_attribute("llm.scene_count", len(skeleton.scenes))
        span.set_attribute("llm.prompt_chars", len(content_prompt))

    # 7a.5: Intermediate retrieval — pull full source text for planned topics
    with tracer.start_as_current_span("demo.intermediate_retrieval"):
        from agents.demo_pipeline.research import retrieve_for_topics

        topic_list = [scene.title for scene in skeleton.scenes]
        progress(f"Retrieving deep context for {len(topic_list)} topics...")
        deep_context = await retrieve_for_topics(topic_list, audience=archetype, token_budget=30000)
        if deep_context:
            research_context += (
                f"\n\n## Deep Context (Retrieved for Selected Topics)\n\n{deep_context}"
            )
            progress(f"Deep context: {len(deep_context)} chars added to research")

    # 7b: Voice application (how to say it) — prose from skeleton + voice examples
    with tracer.start_as_current_span(
        "demo.voice_apply", attributes={"scenes": len(skeleton.scenes)}
    ):
        progress("Pass 2: Applying voice to content...")
        # Build audience dossier text for the voice prompt
        audience_dossier_text = ""
        if sufficiency.audience_dossier:
            d = sufficiency.audience_dossier
            audience_dossier_text = f"Name: {d.name}\n"
            if d.context:
                audience_dossier_text += f"Context:\n{d.context}\n"
            cal = d.calibration or {}
            if cal.get("emphasize"):
                audience_dossier_text += "Emphasize: " + ", ".join(cal["emphasize"]) + "\n"
            if cal.get("skip"):
                audience_dossier_text += "Skip: " + ", ".join(cal["skip"]) + "\n"

        voice_prompt = build_voice_prompt(
            skeleton,
            voice_examples,
            voice_profile,
            duration_constraints,
            target_seconds,
            never_rules=dossier_never or None,
            audience_dossier_text=audience_dossier_text,
            style_guide=style_guide,
        )
        voice_result = await voice_agent.run(voice_prompt)
        script = voice_result.output

        # Word count safety net: if under 80% of target, retry voice pass once
        target_words = int(target_seconds * 2.5)
        actual_words = (
            len((script.intro_narration or "").split())
            + len((script.outro_narration or "").split())
            + sum(len(s.narration.split()) for s in script.scenes)
        )
        if actual_words < target_words * 0.80:
            progress(
                f"Word count {actual_words}w is {actual_words / target_words * 100:.0f}% of {target_words}w target — retrying voice pass"
            )
            # Build per-scene breakdown so the model sees exactly what's short
            min_per_scene = target_words // len(skeleton.scenes) if skeleton.scenes else 200
            scene_breakdown = "\n".join(
                f"  Scene '{s.title}': {len(s.narration.split())}w (need {min_per_scene}w)"
                for s in script.scenes
            )
            voice_prompt_retry = voice_prompt + (
                f"\n\n## CRITICAL: PREVIOUS ATTEMPT WAS TOO SHORT — {actual_words} WORDS vs {target_words} TARGET"
                f"\nEvery scene narration must be AT LEAST {min_per_scene} words (8-10 full sentences)."
                f"\nPrevious scene word counts:\n{scene_breakdown}"
                f"\n\nEach scene needs TWICE as many words as your previous attempt. "
                f"Write detailed, expansive narrations that develop each point fully."
            )
            voice_result = await voice_agent.run(voice_prompt_retry)
            script = voice_result.output
            actual_words = (
                len((script.intro_narration or "").split())
                + len((script.outro_narration or "").split())
                + sum(len(s.narration.split()) for s in script.scenes)
            )
            progress(f"Retry narration: {actual_words}w ({actual_words / target_words * 100:.0f}%)")

        progress(f"Narration complete: {len(script.scenes)} scenes, {actual_words}w")

        # Emit voice pass metrics
        span = get_current_span()
        span.set_attribute("llm.pass", "voice_apply")
        span.set_attribute("llm.actual_words", actual_words)
        span.set_attribute("llm.target_words", target_words)
        span.set_attribute("llm.word_ratio", round(actual_words / max(target_words, 1), 2))
        span.set_attribute(
            "llm.retried",
            actual_words
            != (
                len((voice_result.output.intro_narration or "").split())
                + len((voice_result.output.outro_narration or "").split())
                + sum(len(s.narration.split()) for s in voice_result.output.scenes)
            ),
        )

    # 8. Self-critique & revision
    with tracer.start_as_current_span("demo.critique"):
        from agents.demo_pipeline.critique import critique_and_revise

        progress("Evaluating script quality...")
        script, quality_report = await critique_and_revise(
            script=script,
            research_context=research_context,
            style_guide=style_guide,
            framework=framework,
            target_seconds=target_seconds,
            on_progress=progress,
            voice_examples=voice_examples,
            forbidden_terms=persona.forbidden_terms or None,
            output_format=format,
        )
        # Emit quality metrics
        span = get_current_span()
        span.set_attribute("quality.overall_pass", quality_report.overall_pass)
        critical_count = sum(
            1 for d in quality_report.dimensions if not d.passed and d.severity == "critical"
        )
        important_count = sum(
            1 for d in quality_report.dimensions if not d.passed and d.severity == "important"
        )
        span.set_attribute("quality.critical_issues", critical_count)
        span.set_attribute("quality.important_issues", important_count)
        span.set_attribute("quality.total_dimensions", len(quality_report.dimensions))
        for dim in quality_report.dimensions:
            span.set_attribute(f"quality.dim.{dim.name}", dim.passed)

        if not quality_report.overall_pass:
            progress(
                f"WARNING: Script has {critical_count + important_count} quality issues remaining"
            )

    # 8.5 Safety net: truncate intro/outro if still too long (plays over static title card)
    max_bookend_words = 35
    for field in ("intro_narration", "outro_narration"):
        text = getattr(script, field, "") or ""
        words = text.split()
        if len(words) > max_bookend_words:
            # Keep first two sentences or max_bookend_words, whichever is shorter
            truncated = []
            for word in words:
                truncated.append(word)
                if len(truncated) >= max_bookend_words and word.endswith((".", "!", "?")):
                    break
                if len(truncated) >= max_bookend_words + 10:  # hard cap
                    truncated[-1] = truncated[-1].rstrip(",;:") + "."
                    break
            new_text = " ".join(truncated)
            progress(f"Truncated {field}: {len(words)} → {len(truncated)} words")
            script = script.model_copy(update={field: new_text})

    # 8.6 Safety net: enforce total word budget by trimming longest scenes
    # Cap at 135% of nominal — generous because actual TTS speech rate varies,
    # and we'd rather have too much narration (minor pacing issue) than truncated
    # mid-sentence content (sounds broken).
    target_words = int(target_seconds * 2.5)
    max_total = int(target_words * 1.35)  # 135% hard cap
    total_words = len((script.intro_narration or "").split()) + len(
        (script.outro_narration or "").split()
    )
    scene_words = [(i, len(s.narration.split())) for i, s in enumerate(script.scenes)]
    total_words += sum(wc for _, wc in scene_words)

    if total_words > max_total:
        excess = total_words - max_total
        progress(
            f"Total {total_words}w exceeds {max_total}w cap, trimming {excess}w from longest scenes"
        )
        # Trim from longest scenes first, proportionally
        scene_words_sorted = sorted(scene_words, key=lambda x: x[1], reverse=True)
        updates = {}
        remaining_excess = excess
        for idx, wc in scene_words_sorted:
            if remaining_excess <= 0:
                break
            # Each scene gives back proportional to its excess over fair share
            fair_share = max_total // (len(script.scenes) + 2)
            trim = min(remaining_excess, max(0, wc - fair_share))
            if trim > 0:
                words = script.scenes[idx].narration.split()
                target_wc = wc - trim
                # Cut at sentence boundary near target
                truncated = []
                for word in words:
                    truncated.append(word)
                    if len(truncated) >= target_wc and word.endswith((".", "!", "?")):
                        break
                    if len(truncated) >= target_wc + 30:
                        truncated[-1] = truncated[-1].rstrip(",;:") + "."
                        break
                new_narration = " ".join(truncated)
                actual_trim = wc - len(truncated)
                remaining_excess -= actual_trim
                updates[idx] = new_narration

        if updates:
            new_scenes = list(script.scenes)
            for idx, new_narration in updates.items():
                new_scenes[idx] = new_scenes[idx].model_copy(update={"narration": new_narration})
            script = script.model_copy(update={"scenes": new_scenes})

        # Final hard-trim pass if sentence-boundary trimming left us over cap
        total_after = len((script.intro_narration or "").split()) + len(
            (script.outro_narration or "").split()
        )
        total_after += sum(len(s.narration.split()) for s in script.scenes)
        if total_after > max_total:
            overshoot = total_after - max_total
            # Hard-trim the single longest scene
            longest_idx = max(
                range(len(script.scenes)), key=lambda i: len(script.scenes[i].narration.split())
            )
            words = script.scenes[longest_idx].narration.split()
            words = words[: len(words) - overshoot]
            if words and not words[-1].endswith((".", "!", "?")):
                words[-1] = words[-1].rstrip(",;:") + "."
            hard_scenes = list(script.scenes)
            hard_scenes[longest_idx] = hard_scenes[longest_idx].model_copy(
                update={"narration": " ".join(words)}
            )
            script = script.model_copy(update={"scenes": hard_scenes})

    # 8.7 Refresh quality report to reflect post-loop fixes (trimming, deterministic fixers)
    from agents.demo_pipeline.critique import (
        _check_intro_outro_length,
        _check_visual_variety,
        _check_word_count,
    )

    det_names = {"duration_feasibility", "visual_appropriateness", "intro_outro_length"}
    quality_report.dimensions = [d for d in quality_report.dimensions if d.name not in det_names]
    for check_fn in [_check_word_count, _check_visual_variety, _check_intro_outro_length]:
        if check_fn == _check_word_count:
            result = check_fn(script, target_seconds)
        else:
            result = check_fn(script)
        if result:
            quality_report.dimensions.append(result)
    critical_count = sum(
        1 for d in quality_report.dimensions if not d.passed and d.severity == "critical"
    )
    important_count = sum(
        1 for d in quality_report.dimensions if not d.passed and d.severity == "important"
    )
    quality_report.overall_pass = critical_count == 0 and important_count <= 1

    # Create output directory
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", scope.lower()).strip("-")[:30]
    demo_dir = OUTPUT_DIR / f"{ts}-{slug}"
    demo_dir.mkdir(parents=True, exist_ok=True)

    # Save script for reproducibility
    (demo_dir / "script.json").write_text(script.model_dump_json(indent=2))

    # 8.5 App format: render audio + app-script.json, skip visuals/slides/video
    if format == "app":
        with tracer.start_as_current_span("demo.app_format"):
            from agents.demo_pipeline.app_scenes import convert_to_app_scenes, render_app_demo_audio
            from agents.demo_pipeline.choreography import choreograph

            progress("Choreographing UI actions (Opus)...")
            choreography_actions = await choreograph(script, on_progress=progress)

            # Use ElevenLabs if available (higher quality), fall back to Kokoro
            from agents.demo_pipeline.voice import check_elevenlabs_available

            tts_backend = "elevenlabs" if check_elevenlabs_available() else "auto"
            speed = 1.0 if tts_backend == "elevenlabs" else 0.90
            progress(f"Rendering app demo audio ({tts_backend})...")
            audio_dir = demo_dir / "audio"
            render_app_demo_audio(
                script, audio_dir, speed_factor=speed, on_progress=progress, backend=tts_backend
            )

            progress("Generating app scene script...")
            convert_to_app_scenes(
                script, demo_dir, on_progress=progress, choreography=choreography_actions
            )

            # Save metadata
            metadata = {
                "title": script.title,
                "audience": archetype,
                "scope": scope,
                "scenes": len(script.scenes),
                "format": "app",
                "quality_pass": quality_report.overall_pass if quality_report else None,
            }
            (demo_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

            demo_name = demo_dir.name
            progress(f"App demo ready: {demo_dir}\nOpen: http://localhost:5173/?demo={demo_name}")
            return demo_dir

    # 9. Generate visuals (screenshots + diagrams + charts + screencasts)
    with tracer.start_as_current_span("demo.visuals", attributes={"count": len(script.scenes)}):
        progress("Generating visuals...")
        visual_dir = demo_dir / "screenshots"
        visual_dir.mkdir(parents=True, exist_ok=True)

        screenshot_specs = []
        screencast_specs = []
        illustration_specs = []
        screenshot_map = {}

        for i, scene in enumerate(script.scenes, 1):
            slug = re.sub(r"[^a-z0-9]+", "-", scene.title.lower()).strip("-")
            name = f"{i:02d}-{slug}"

            if scene.visual_type == "screenshot":
                screenshot_specs.append((name, scene.screenshot))
            elif scene.visual_type == "diagram":
                from agents.demo_pipeline.diagrams import render_d2

                path = render_d2(scene.diagram_spec or "", visual_dir / f"{name}.png")
                screenshot_map[scene.title] = path
            elif scene.visual_type == "chart":
                from agents.demo_pipeline.charts import render_chart

                path = render_chart(scene.diagram_spec or "{}", visual_dir / f"{name}.png")
                screenshot_map[scene.title] = path
            elif scene.visual_type == "screencast":
                if scene.interaction:
                    screencast_specs.append((name, scene.interaction))
                else:
                    log.warning(
                        "Scene '%s' has visual_type=screencast but no interaction spec", scene.title
                    )
            elif scene.visual_type == "illustration":
                if scene.illustration:
                    illustration_specs.append((name, scene.illustration))
                else:
                    log.warning(
                        "Scene '%s' has visual_type=illustration but no illustration spec",
                        scene.title,
                    )

        # Screenshots via Playwright
        if screenshot_specs:
            from agents.demo_pipeline.screenshots import capture_screenshots

            screenshot_paths = await capture_screenshots(
                screenshot_specs, visual_dir, on_progress=progress
            )
            for (_, spec), path in zip(screenshot_specs, screenshot_paths, strict=False):
                # Find scene by screenshot spec match
                for scene in script.scenes:
                    if scene.screenshot == spec and scene.title not in screenshot_map:
                        screenshot_map[scene.title] = path
                        break

            # Post-capture duplicate detection: identical file sizes indicate
            # the scroll/actions produced no visible change (common on SPAs)
            size_to_paths: dict[int, list[Path]] = {}
            for path in screenshot_paths:
                if not path.exists():
                    continue
                sz = path.stat().st_size
                size_to_paths.setdefault(sz, []).append(path)
            for sz, paths_group in size_to_paths.items():
                if len(paths_group) > 1:
                    names = [p.stem for p in paths_group]
                    log.warning(
                        "DUPLICATE SCREENSHOTS DETECTED (%d identical, %d bytes): %s. "
                        "These will appear as the same image in the demo. "
                        "Use different routes (/, /chat, /demos) instead of scroll variations.",
                        len(paths_group),
                        sz,
                        ", ".join(names),
                    )

        # Screencasts via Playwright video recording
        if screencast_specs:
            from agents.demo_pipeline.screencasts import record_screencasts

            screencast_paths = await record_screencasts(
                screencast_specs, visual_dir, on_progress=progress
            )
            for (sc_name, _), path in zip(screencast_specs, screencast_paths, strict=False):
                # Find scene by matching name prefix
                for scene in script.scenes:
                    slug = re.sub(r"[^a-z0-9]+", "-", scene.title.lower()).strip("-")
                    if sc_name.endswith(slug) and scene.title not in screenshot_map:
                        screenshot_map[scene.title] = path
                        break

        # Illustrations via Gemini image generation
        if illustration_specs:
            from agents.demo_pipeline.illustrations import (
                generate_illustrations,
                load_illustration_style,
            )

            # Inject audience style into specs that don't have one
            audience_style = load_illustration_style(script.audience)
            styled_specs = []
            for ill_name, ill_spec in illustration_specs:
                if not ill_spec.style and audience_style:
                    ill_spec = ill_spec.model_copy(update={"style": audience_style})
                styled_specs.append((ill_name, ill_spec))

            illustration_paths = await generate_illustrations(
                styled_specs, visual_dir, on_progress=progress
            )
            for (ill_name, _), path in zip(illustration_specs, illustration_paths, strict=False):
                if path is not None:
                    for scene in script.scenes:
                        slug = re.sub(r"[^a-z0-9]+", "-", scene.title.lower()).strip("-")
                        if ill_name.endswith(slug) and scene.title not in screenshot_map:
                            screenshot_map[scene.title] = path
                            break

    # 10. Render slides
    with tracer.start_as_current_span("demo.slides", attributes={"format": format}):
        progress("Rendering slides...")
        await render_slides(
            script,
            screenshot_map,
            demo_dir,
            render_pdf=(format != "markdown-only"),
            on_progress=progress,
        )

    # 11. Generate voice audio (if requested or video format)
    actual_duration = 0.0
    audio_dir: Path | None = None
    want_voice = format == "video" or enable_voice
    if want_voice:
        with tracer.start_as_current_span("demo.voice"):
            from agents.demo_pipeline.voice import (
                check_tts_available,
                generate_all_voice_segments,
            )
            from agents.demo_pipeline.vram import ensure_vram_available

            # Check TTS service
            tts_available = check_tts_available()
            if not tts_available:
                progress(
                    "WARNING: Chatterbox TTS not running — demo will have no narration. "
                    "To enable voice: cd ~/llm-stack && docker compose --profile tts up -d chatterbox"
                )
            if tts_available:
                # Ensure VRAM (blocking call — run in thread to avoid freezing event loop)
                progress("Checking GPU VRAM...")
                await asyncio.to_thread(ensure_vram_available)

                # Generate voice segments
                voice_segments = []
                if script.intro_narration:
                    voice_segments.append(("00-intro", script.intro_narration))
                for i, scene in enumerate(script.scenes, 1):
                    slug = re.sub(r"[^a-z0-9]+", "-", scene.title.lower()).strip("-")
                    voice_segments.append((f"{i:02d}-{slug}", scene.narration))
                if script.outro_narration:
                    voice_segments.append(("99-outro", script.outro_narration))

                audio_dir = demo_dir / "audio"
                await asyncio.to_thread(
                    generate_all_voice_segments,
                    voice_segments,
                    audio_dir,
                    on_progress=progress,
                )

    # 11b. Assemble video (if video format)
    if format == "video":
        with tracer.start_as_current_span("demo.video"):
            from agents.demo_pipeline.title_cards import generate_title_card
            from agents.demo_pipeline.video import assemble_video

            # Generate title cards
            progress("Generating title cards...")
            title_subtitle = f"For {audience_display_name}" if audience_display_name else None
            intro_card = generate_title_card(
                script.title,
                demo_dir / "intro.png",
                subtitle=title_subtitle,
            )
            outro_card = generate_title_card(
                "Thank You",
                demo_dir / "outro.png",
            )

            # Build duration map from scenes
            durations = {scene.title: scene.duration_hint for scene in script.scenes}

            # Assemble video
            progress("Assembling video...")
            video_path, actual_duration = await assemble_video(
                intro_card=intro_card,
                outro_card=outro_card,
                screenshots=screenshot_map,
                durations=durations,
                audio_dir=audio_dir,
                output_path=demo_dir / "demo.mp4",
                on_progress=progress,
            )

    # 12. Convert audio to MP3 for HTML player (if audio was generated)
    mp3_dir: Path | None = None
    if audio_dir and audio_dir.exists():
        with tracer.start_as_current_span("demo.audio_convert"):
            from agents.demo_pipeline.audio_convert import convert_all_wav_to_mp3

            progress("Converting audio to MP3...")
            convert_all_wav_to_mp3(audio_dir, audio_dir)  # MP3s alongside WAVs
            mp3_dir = audio_dir

    # 13. Generate self-contained HTML player (always)
    with tracer.start_as_current_span("demo.html_player"):
        from agents.demo_pipeline.html_player import generate_html_player

        progress("Generating HTML player...")
        generate_html_player(
            script=script,
            screenshot_map=screenshot_map,
            audio_dir=mp3_dir,
            output_path=demo_dir / "demo.html",
            on_progress=progress,
            audience_display_name=audience_display_name,
        )

    # 14. Inject chapter markers into video (if video was generated)
    if format == "video" and (demo_dir / "demo.mp4").exists():
        with tracer.start_as_current_span("demo.chapters"):
            from agents.demo_pipeline.chapters import (
                build_chapter_list_from_script,
                inject_chapters,
            )

            progress("Injecting chapter markers...")
            try:
                chapters = build_chapter_list_from_script(script, audio_dir)
                inject_chapters(demo_dir / "demo.mp4", chapters)
            except Exception as e:
                log.warning("Chapter injection failed (non-fatal): %s", e)

    # Write metadata
    metadata = {
        "title": script.title,
        "audience": archetype,
        "scope": scope,
        "scenes": len(script.scenes),
        "format": format,
        "duration": actual_duration
        if format == "video" and actual_duration > 0
        else sum(s.duration_hint for s in script.scenes),
        "timestamp": ts,
        "output_dir": str(demo_dir),
        "primary_file": "demo.html",
        "has_video": format == "video" and (demo_dir / "demo.mp4").exists(),
        "has_audio": mp3_dir is not None,
        "target_duration": target_seconds,
        "quality_pass": quality_report.overall_pass,
        "narrative_framework": framework["name"],
    }
    (demo_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

    # Save quality report for debugging
    quality_data = {
        "overall_pass": quality_report.overall_pass,
        "dimensions": [
            {
                "name": d.name,
                "passed": d.passed,
                "severity": d.severity,
                "issues": d.issues,
            }
            for d in quality_report.dimensions
        ],
        "revision_notes": quality_report.revision_notes,
    }
    (demo_dir / "quality_report.json").write_text(json.dumps(quality_data, indent=2))

    progress(f"Demo complete: {demo_dir}")
    return demo_dir


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate audience-tailored system demos",
        prog="python -m agents.demo",
    )
    parser.add_argument(
        "request",
        nargs="?",
        default=None,
        help="Natural language request, e.g. 'the entire system for my partner'",
    )
    parser.add_argument(
        "--audience",
        help="Override audience archetype (family, technical-peer, leadership, team-member)",
    )
    parser.add_argument(
        "--format",
        choices=["slides", "video", "markdown-only", "app"],
        default="slides",
        help="Output format",
    )
    parser.add_argument(
        "--duration",
        type=str,
        default=None,
        help="Target duration, e.g. '5m', '90s', or bare seconds",
    )
    parser.add_argument(
        "--voice", action="store_true", help="Enable TTS voice narration (works with any format)"
    )
    parser.add_argument(
        "--json", action="store_true", help="Print script JSON instead of generating demo"
    )
    parser.add_argument("--persona-file", type=Path, help="Path to custom persona YAML file")
    parser.add_argument(
        "--gather-dossier",
        metavar="AUDIENCE",
        help="Interactively collect audience dossier (e.g., 'my partner')",
    )
    parser.add_argument("--list", action="store_true", help="List previously generated demos")
    args = parser.parse_args()

    if args.list:
        from agents.demo_pipeline.history import list_demos

        demos = list_demos(OUTPUT_DIR)
        if not demos:
            print("No demos found.")
        else:
            for d in demos:
                print(f"  {d['id']}  {d.get('audience', '?'):15s}  {d.get('scope', '')}")
        return

    if args.gather_dossier:
        from agents.demo_pipeline.dossier import (
            gather_dossier_interactive,
            record_relationship_facts,
            save_dossier,
        )

        audience_key = args.gather_dossier
        personas = load_personas(extra_path=args.persona_file)
        archetype = args.audience or "family"

        dossier, responses = gather_dossier_interactive(audience_key, archetype, personas=personas)
        path = save_dossier(dossier)
        n = record_relationship_facts(dossier, responses)
        print(f"Dossier saved to {path}")
        if n:
            print(f"Indexed {n} relationship facts to profile-facts")
        return

    if not args.request:
        parser.error("request is required unless --gather-dossier or --list is used")
    request = args.request
    if args.audience:
        # Override audience in request
        scope, _ = parse_request(request)
        request = f"{scope} for {args.audience}"

    if args.json:
        # Just plan, don't capture/render — use simplified pipeline
        scope, audience_text = parse_request(request)
        personas = load_personas(extra_path=args.persona_file)
        archetype, extra = resolve_audience(audience_text, personas)
        persona = personas[archetype]
        system_desc = _load_system_description()
        prompt = build_planning_prompt(
            scope,
            archetype,
            persona,
            research_context=system_desc,
            planning_context="",
        )
        if extra:
            prompt += f"\n\nAdditional audience context: {extra}"
        result = await agent.run(prompt)
        print(result.output.model_dump_json(indent=2))
    else:
        demo_dir = await generate_demo(
            request,
            format=args.format,
            duration=args.duration,
            on_progress=lambda msg: print(f"  {msg}", file=sys.stderr),
            persona_file=args.persona_file,
            enable_voice=args.voice,
        )
        print(f"\nDemo generated: {demo_dir}")
        for f in sorted(demo_dir.rglob("*")):
            if f.is_file():
                print(f"  {f.relative_to(demo_dir)}")


if __name__ == "__main__":
    asyncio.run(main())
