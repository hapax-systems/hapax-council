"""Self-critique and revision loop for demo script quality."""

from __future__ import annotations

import logging

from pydantic_ai import Agent

from agents.demo_models import DemoQualityReport, DemoScript, QualityDimension
from shared.config import get_model

log = logging.getLogger(__name__)

MAX_ITERATIONS = 4

QUALITY_DIMENSIONS = [
    "narrative_coherence",  # Follows framework? Logical arc?
    "audience_calibration",  # Vocabulary appropriate? Respects show/skip?
    "content_adequacy",  # Enough substance? Each scene justified?
    "duration_feasibility",  # Word count × speech rate ≈ target?
    "voice_consistency",  # Matches voice examples? Sounds like the builder?
    "factual_grounding",  # Claims match research context?
    "honesty_accuracy",  # No fabricated stats? System maturity honest? Unique vs generic?
    "visual_appropriateness",  # Right mix of screenshots/diagrams/charts?
    "visual_substance",  # Does each visual convey specific information, not decorative filler?
    "key_points_quality",  # Bullets substantive, not vague?
]

critique_agent = Agent(
    get_model("balanced"),
    system_prompt=(
        "You are a rigorous presentation quality reviewer. Given a demo script, "
        "evaluate it against each quality dimension. Be specific about issues found. "
        "Mark each dimension as passed or failed with severity (critical/important/minor). "
        "Set overall_pass to True only if there are 0 critical issues AND at most 1 important issue."
    ),
    output_type=DemoQualityReport,
)

revision_agent = Agent(
    get_model("balanced"),
    system_prompt=(
        "You are revising a demo script based on quality feedback. Fix ONLY the issues "
        "identified in the quality report. Do not rewrite scenes that passed review. "
        "Preserve the narrative framework and duration constraints. "
        "Keep the same number of scenes unless a scene was flagged for removal. "
        "CRITICAL: If word count is flagged as too low, you MUST substantially expand "
        "EVERY scene's narration with specific details, examples, and explanations. "
        "Each scene narration must be a full paragraph of natural spoken language."
    ),
    output_type=DemoScript,
    model_settings={"max_tokens": 32768},
)


def _format_voice_reference(voice_examples: dict | None) -> str:
    """Format voice examples as a brief reference for prompts."""
    if not voice_examples or not voice_examples.get("examples"):
        return ""
    lines = ["\n## Voice Reference — match this voice when revising narration:"]
    for key, ex in voice_examples["examples"].items():
        if key != "bad_example":
            lines.append(f'- {ex["label"]}: "{ex["text"].strip()[:150]}..."')
    return "\n".join(lines) + "\n"


def _build_critique_prompt(
    script: DemoScript,
    research_context: str,
    style_guide: dict,
    framework: dict,
    target_seconds: int,
    voice_examples: dict | None = None,
) -> str:
    """Build the prompt for the critique agent."""
    dimension_descriptions = {
        "voice_consistency": "Does the narration match the voice examples (matter-of-fact, first-person, concrete)? No pitch language, no breathless selling.",
        "factual_grounding": "Only flag as critical if the narration contains INVENTED numbers or claims that CONTRADICT the research context. Minor rephrasings are fine — e.g. '73 of 78 components are healthy' is correct if research shows 73/78 healthy. Details from common system knowledge (like schedule times from CLAUDE.md) are acceptable. Do NOT flag correct statements that are simply worded differently.",
        "honesty_accuracy": "Cross-reference ALL numbers, dollar amounts, percentages, error rates, and specific counts in the narration against the Research Context. Any statistic not in the research context is FABRICATED. ALSO check for fabricated ANECDOTES: any sentence starting with 'Yesterday...', 'Last week...', 'Last Tuesday...', or describing specific events that happened ('it reminded me that Sarah...', 'the system detected that the document processing service crashed...', 'it noticed I hadn't logged any exercise...') — these are fabricated stories, flag as critical. Only present-tense descriptions of capabilities and hypothetical framings are allowed.",
        "visual_appropriateness": (
            "Right mix of visual types for the content? Each visual must DIRECTLY illustrate "
            "the scene's key message (Mayer's Coherence Principle). Illustration scenes must not "
            "depict architecture, data, or workflows — those have dedicated visual types."
        ),
        "visual_substance": (
            "Does each visual convey specific information, not decorative filler? "
            "Charts where ALL values are identical are decorative filler — flag as critical. "
            "Charts with fabricated data not in research context are also filler. "
            "Diagram scenes whose narration discusses something unrelated to the diagram are mismatched."
        ),
        "key_points_quality": "Bullets substantive, not vague?",
    }
    dimensions_text = "\n".join(
        f"- **{d}**: {dimension_descriptions.get(d, 'evaluate this dimension')}"
        for d in QUALITY_DIMENSIONS
    )

    # Voice consistency criteria from examples
    voice_section = ""
    if voice_examples and voice_examples.get("examples"):
        good_examples = []
        bad_example = ""
        for key, ex in voice_examples["examples"].items():
            if key == "bad_example":
                bad_example = ex["text"].strip()
            else:
                good_examples.append(f'"{ex["text"].strip()}"')

        voice_section = f"""
## Voice Consistency Reference
The narration should sound like Examples A-D below (matter-of-fact, first-person, concrete).
It should NOT sound like the Bad Example (pitch mode, breathless, selling).

Good voice examples:
{chr(10).join(f"Example {chr(65 + i)}: {ex}" for i, ex in enumerate(good_examples))}

Bad Example (pitch mode — narration sounding like this FAILS voice_consistency):
"{bad_example}"
"""
    else:
        avoid_text = ""
        if style_guide.get("avoid"):
            avoid_text = "Style AVOID list: " + "; ".join(style_guide["avoid"])
        voice_section = f"\n{avoid_text}\n"

    return f"""Evaluate this demo script against all quality dimensions.

## Script
{script.model_dump_json(indent=2)}

## Quality Dimensions to Evaluate
{dimensions_text}

## Context for Evaluation
Target duration: {target_seconds} seconds ({target_seconds / 60:.0f} minutes)
Narrative framework: {framework.get("name", "unknown")}
{voice_section}

## Research Context (for factual grounding check)
{research_context[:3000]}

For each dimension, report:
- passed: true/false
- severity: critical (blocks demo) / important (should fix) / minor (nice to have)
- issues: specific items to fix

Set overall_pass=True only if 0 critical AND ≤1 important issues."""


def _build_revision_prompt(
    script: DemoScript,
    report: DemoQualityReport,
    research_context: str,
    style_guide: dict,
    framework: dict,
    target_seconds: int,
    voice_examples: dict | None = None,
    forbidden_terms: list[str] | None = None,
) -> str:
    """Build the prompt for the revision agent."""
    issues_text = "\n".join(
        f"- {d.name}: {'; '.join(d.issues)}" for d in report.dimensions if not d.passed
    )

    # Calculate word count targets for explicit guidance
    target_words = int(target_seconds * 2.5)
    current_words = len((script.intro_narration or "").split()) + len(
        (script.outro_narration or "").split()
    )
    for scene in script.scenes:
        current_words += len(scene.narration.split())
    words_needed = target_words - current_words
    words_per_scene = target_words // (len(script.scenes) + 2) if script.scenes else 150

    word_guidance = ""
    if words_needed > 0:
        word_guidance = f"""
## MANDATORY: Word Count Targets (THIS IS THE #1 PRIORITY)
Current total: {current_words} words
Target total: {target_words} words (for {target_seconds}s at 150 words/minute)
DEFICIT: {words_needed} words — you MUST add this many words.
Minimum per scene: {words_per_scene} words. COUNT THEM. If a scene narration is under {words_per_scene} words, it WILL be rejected.
Intro: 15-30 words MAXIMUM (plays over static title card). Outro: 15-30 words MAXIMUM.
Put substantive content in scene narrations, NOT in intro/outro.

YOUR PREVIOUS REVISION WAS TOO SHORT. Each scene narration must be a FULL PARAGRAPH of 5-8 sentences.
A single scene narration should look like this (notice the length):
"The dashboard shows the health of all seventy-eight components in the stack. Each one has a status indicator, and right now they're all green. The daily briefing section is generated automatically at seven AM — it summarizes which scheduled tasks ran, whether any services needed attention, and flags anything unusual. The health monitor runs every fifteen minutes across seventeen check groups, and it can auto-fix about half the common failures without any intervention. Below that is the cost tracker, which breaks down cloud API spending by model and service. The whole design principle is that the system surfaces what matters and handles what it can, so the operator only gets pulled in when something genuinely requires a decision."

That example is ~130 words. EVERY scene needs this level of detail. Do NOT write 2-3 sentence narrations.

HOW TO EXPAND:
- Start with what this feature/capability IS (1-2 sentences)
- Give a SPECIFIC example from daily use (2-3 sentences)
- Explain WHY it matters or what problem it solves (1-2 sentences)
- Add a personal reflection or comparison (1 sentence)
"""
    elif words_needed < -int(target_words * 0.15):
        # Over budget by more than 15% — only trim if genuinely excessive
        excess = -words_needed
        # Use target-based max, not aggressive division — leave headroom
        max_per_scene = int(target_words * 1.10) // len(script.scenes) if script.scenes else 180
        # Only list scenes that are significantly over the per-scene average
        scene_wcs = [(sc.title, len(sc.narration.split())) for sc in script.scenes]
        avg_per_scene = target_words // len(script.scenes) if script.scenes else 150
        over_scenes = [(t, wc) for t, wc in scene_wcs if wc > avg_per_scene + 30]
        over_scenes.sort(key=lambda x: x[1], reverse=True)
        longest_text = (
            ", ".join(f"'{t}' ({wc}w)" for t, wc in over_scenes[:3])
            if over_scenes
            else "trim evenly"
        )
        # Only ask to cut down to 110%, not all the way to target
        cut_target = -words_needed - int(target_words * 0.05)  # Leave 5% buffer
        word_guidance = f"""
## MANDATORY: Cut Word Count
Current total: {current_words} words
Target total: {target_words} words (for {target_seconds}s at 150 words/minute)
EXCESS: {excess} words — cut approximately {cut_target} words (aim for {int(target_words * 1.05)} total).
Do NOT over-cut — being 5-10% over target is acceptable. Being under target is worse than over.
Maximum per scene: {max_per_scene} words. Scenes to trim: {longest_text}

HOW TO CUT (without losing substance):
- Remove redundant restatements of the same point
- Cut transition sentences that add no information ("This is important because...")
- Remove generic statements that could apply to any system
- Keep specific numbers and concrete details — cut filler words and qualifiers
- Intro/outro: 15-30 words MAXIMUM
"""

    # Visual variety fix guidance
    visual_guidance = ""
    has_visual_issue = any(
        d.name == "visual_appropriateness" and not d.passed for d in report.dimensions
    )
    if has_visual_issue:
        types = [s.visual_type for s in script.scenes]
        screenshot_count = types.count("screenshot")
        screencast_count = types.count("screencast")
        diagram_count = types.count("diagram")
        chart_count = types.count("chart")
        total_scenes = len(types)
        need_ss = (total_scenes + 1) // 2 - screenshot_count - screencast_count
        # Identify which diagram scenes to convert
        convert_candidates = []
        for i, s in enumerate(script.scenes):
            if s.visual_type == "diagram":
                convert_candidates.append(f"Scene {i + 1} '{s.title}'")
        convert_list = (
            "\n".join(f"  - {c}" for c in convert_candidates[:need_ss])
            if need_ss > 0
            else "(none needed)"
        )
        visual_guidance = f"""
## VISUAL VARIETY FIX (CRITICAL — THIS MUST BE FIXED)
Current mix: {screenshot_count} screenshots, {screencast_count} screencasts, {diagram_count} diagrams, {chart_count} charts
Need at least {(total_scenes + 1) // 2} screenshots+screencasts total. Currently have {screenshot_count + screencast_count}. MUST CONVERT {max(0, need_ss)} diagram scenes to screenshots.

HOW TO CONVERT A DIAGRAM SCENE TO A SCREENSHOT:
1. Set visual_type to "screenshot"
2. Set diagram_spec to null
3. Add a screenshot spec: {{"url": "http://localhost:5173/", "viewport_width": 1920, "viewport_height": 1080, "actions": [], "wait_for": null, "capture": "viewport"}}
4. Use different URLs and scroll positions to show different parts of the UI

CANDIDATE SCENES TO CONVERT (pick {max(0, need_ss)} of these):
{convert_list}

AVAILABLE SCREENSHOT URLs (MUST distribute correctly):
- http://localhost:5173/ — dashboard (MAX 2 — static page, duplicates are identical)
- http://localhost:5173/chat — chat interface (up to 3 — each gets a unique question, so each looks different)
- http://localhost:5173/demos — demo listing (MAX 2 — static page, duplicates are identical)
IMPORTANT: / and /demos are STATIC pages — multiple screenshots are pixel-identical. Use /chat for additional screenshots.
With 2+5+2 = 9 screenshots max. Fill remaining scenes with diagrams and charts using REAL data only.

RULES:
- At least {(total_scenes + 1) // 2}/{total_scenes} scenes MUST be screenshots or screencasts
- NEVER 3+ consecutive scenes with the same visual_type
- Must include at least one of EACH route: /, /chat, /demos
- Maximum 2 screencast scenes
"""

    return f"""Revise this demo script to fix the identified quality issues.

## Current Script
{script.model_dump_json(indent=2)}

## Issues to Fix
{issues_text}

{f"Revision notes: {report.revision_notes}" if report.revision_notes else ""}
{word_guidance}
{visual_guidance}

## Constraints
- Fix ONLY the identified issues — do NOT break things that are working
- PRESERVE all diagram_spec and screenshot specs from scenes that aren't flagged
- Illustration scenes should have prompts that describe something directly related to the scene's narration
- Illustrations are for abstract concepts only — if the scene describes architecture, use a diagram; if it shows data, use a chart
- Max 3 illustrations per demo
- Keep the same narrative framework: {framework.get("name", "unknown")}
- Target duration: {target_seconds} seconds
- Preserve scene count unless explicitly flagged
- Style guide: voice={style_guide.get("voice", "first-person")}, cadence={style_guide.get("cadence", "state-explain-show")}
{chr(10).join(f'- FORBIDDEN TERM: "{t}" — do NOT use this word anywhere in narration' for t in (forbidden_terms or []))}
{_format_voice_reference(voice_examples)}
Return the complete revised DemoScript."""


def _check_word_count(script: DemoScript, target_seconds: int) -> QualityDimension | None:
    """Deterministic word count check. Returns a failing dimension if outside acceptable range.

    Thresholds: 70% floor (too short) and 135% ceiling (too long) of target words.
    The floor is generous to prevent oscillation where revision alternates between
    "too long" → aggressive trim → "too short" → expand → "too long" cycles.
    """
    target_words = int(target_seconds * 2.5)  # 150 words/minute = 2.5 words/second
    min_words = int(target_words * 0.70)  # 70% threshold — generous to prevent oscillation
    max_words = int(target_words * 1.35)  # 135% threshold — matches safety cap

    total_words = len((script.intro_narration or "").split())
    total_words += len((script.outro_narration or "").split())
    scene_word_counts = []
    for scene in script.scenes:
        wc = len(scene.narration.split())
        scene_word_counts.append((scene.title, wc))
        total_words += wc

    if min_words <= total_words <= max_words:
        return None

    # Build specific issues
    issues = []
    if total_words < min_words:
        issues.append(
            f"Total narration: {total_words} words, need at least {min_words} (target: {target_words})",
        )
        issues.append(
            f"Deficit: {target_words - total_words} words ({total_words / target_words * 100:.0f}% of target)",
        )
        min_per_scene = target_words // (len(script.scenes) + 2) if script.scenes else 100
        short_scenes = [(t, wc) for t, wc in scene_word_counts if wc < min_per_scene]
        if short_scenes:
            issues.append(
                f"Short scenes (need {min_per_scene}+ words each): "
                + ", ".join(f"'{t}' ({wc}w)" for t, wc in short_scenes[:5])
            )
    else:
        issues.append(
            f"Total narration: {total_words} words, maximum is {max_words} (target: {target_words})",
        )
        issues.append(
            f"Excess: {total_words - target_words} words ({total_words / target_words * 100:.0f}% of target)",
        )

    return QualityDimension(
        name="duration_feasibility",
        passed=False,
        severity="critical",
        issues=issues,
    )


def _check_intro_outro_length(script: DemoScript) -> QualityDimension | None:
    """Deterministic intro/outro length check. They play over static title cards — must be brief."""
    max_words = 35  # ~14 seconds at 150 wpm
    issues = []

    intro_words = len((script.intro_narration or "").split())
    if intro_words > max_words:
        issues.append(
            f"Intro narration is {intro_words} words (max {max_words}). "
            f"It plays over a static title card — keep it to 1-2 sentences."
        )

    outro_words = len((script.outro_narration or "").split())
    if outro_words > max_words:
        issues.append(
            f"Outro narration is {outro_words} words (max {max_words}). "
            f"Keep the closing to 1-2 sentences."
        )

    if not issues:
        return None

    return QualityDimension(
        name="intro_outro_length",
        passed=False,
        severity="critical",
        issues=issues,
    )


def _check_visual_variety(script: DemoScript) -> QualityDimension | None:
    """Deterministic visual variety check."""
    issues = []
    total = len(script.scenes)
    screencast_count = sum(1 for s in script.scenes if s.visual_type == "screencast")

    if screencast_count > 2:
        issues.append(f"{screencast_count} screencast scenes — max 2 allowed (expensive to record)")

    # Max 3 illustration scenes
    illustration_count = sum(1 for s in script.scenes if s.visual_type == "illustration")
    if illustration_count > 3:
        issues.append(
            f"{illustration_count} illustration scenes — max 3 allowed. "
            f"Use screenshots, diagrams, or charts for remaining scenes."
        )

    # Illustrations must have illustration spec
    for i, s in enumerate(script.scenes):
        if s.visual_type == "illustration" and not s.illustration:
            issues.append(
                f"Scene {i + 1} '{s.title}' has visual_type=illustration but no illustration spec"
            )

    # Check screenshot route concentration: too many screenshots of the same route
    # produce identical-looking images (scroll actions rarely change the visible content)
    if total >= 6:
        from collections import Counter

        route_counts: Counter[str] = Counter()
        for s in script.scenes:
            if s.visual_type == "screenshot" and s.screenshot:
                url = s.screenshot.url.rstrip("/")
                if url.endswith(":5173"):
                    route_counts["/"] += 1
                elif "/chat" in url:
                    route_counts["/chat"] += 1
                elif "/demos" in url:
                    route_counts["/demos"] += 1
                else:
                    route_counts[url] += 1
        for route, count in route_counts.items():
            # /chat screenshots are each visually unique (different questions),
            # but / and /demos are static — multiple screenshots are duplicates.
            max_per_route = 3 if route == "/chat" else 2
            if count > max_per_route:
                issues.append(
                    f"{count} screenshots of route '{route}' (max {max_per_route} per route). "
                    f"Use /chat for more screenshots (each is unique) or switch to diagrams/charts."
                )

    # Check for empty visual specs (would produce fallback images)
    for i, s in enumerate(script.scenes):
        if s.visual_type in ("diagram", "chart") and not s.diagram_spec:
            issues.append(
                f"Scene {i + 1} '{s.title}' has visual_type={s.visual_type} but empty diagram_spec"
            )
        if s.visual_type == "screenshot" and not s.screenshot:
            issues.append(
                f"Scene {i + 1} '{s.title}' has visual_type=screenshot but no screenshot spec"
            )
        if s.visual_type == "screencast" and not s.interaction:
            issues.append(
                f"Scene {i + 1} '{s.title}' has visual_type=screencast but no interaction spec"
            )

    # Check screenshot ratio: at least 50% must be screenshots or screencasts
    ss_count = sum(1 for s in script.scenes if s.visual_type in ("screenshot", "screencast"))
    if total > 0 and ss_count < (total + 1) // 2:
        issues.append(
            f"Only {ss_count}/{total} scenes use screenshots/screencasts "
            f"(need at least {(total + 1) // 2}). Too many diagrams."
        )

    # Check consecutive same type (3+ in a row is a problem)
    types = [s.visual_type for s in script.scenes]
    for i in range(len(types) - 2):
        if types[i] == types[i + 1] == types[i + 2]:
            issues.append(f"3+ consecutive {types[i]} scenes (scenes {i + 1}-{i + 3})")
            break

    # Check mandatory routes: /, /chat, /demos must each appear at least once
    # (only for demos with 6+ scenes — small demos may not need all routes)
    if total < 6:
        if not issues:
            return None
        return QualityDimension(
            name="visual_appropriateness",
            passed=False,
            severity="critical",
            issues=issues,
        )
    screenshot_urls = set()
    for s in script.scenes:
        if s.visual_type == "screenshot" and s.screenshot:
            # Normalize URL to route
            url = s.screenshot.url.rstrip("/")
            if url.endswith(":5173"):
                screenshot_urls.add("/")
            elif "/chat" in url:
                screenshot_urls.add("/chat")
            elif "/demos" in url:
                screenshot_urls.add("/demos")
        elif s.visual_type == "screencast" and s.interaction:
            url = s.interaction.url.rstrip("/")
            if url.endswith(":5173"):
                screenshot_urls.add("/")
            elif "/chat" in url:
                screenshot_urls.add("/chat")
            elif "/demos" in url:
                screenshot_urls.add("/demos")
    missing_routes = {"/", "/chat", "/demos"} - screenshot_urls
    if missing_routes:
        issues.append(
            f"Missing mandatory screenshot routes: {', '.join(sorted(missing_routes))}. "
            f"Must have at least one screenshot/screencast of each cockpit-web route."
        )

    # Note: all-ones charts are caught by LLM critique (visual_substance),
    # not as a deterministic failure — the revision model can't change
    # visual_type from chart→diagram without rewriting diagram_spec format.

    if not issues:
        return None

    return QualityDimension(
        name="visual_appropriateness",
        passed=False,
        severity="critical",
        issues=issues,
    )


def _sanitize_d2_label(text: str, max_len: int = 50) -> str:
    """Sanitize text for use as a D2 node label inside double quotes."""
    import re as _re

    # Remove characters that break D2 syntax
    text = text.replace('"', "'").replace("\\", "")
    text = text.replace("{", "(").replace("}", ")")
    text = text.replace(";", ",").replace("`", "'")
    # Collapse whitespace
    text = _re.sub(r"\s+", " ", text).strip()
    # Truncate at word boundary
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0]
    return text


def _generate_d2_from_scene(scene: DemoScene) -> str:
    """Generate a substantive D2 diagram from scene content.

    Uses key_points and title to create a multi-node diagram rather than
    a single placeholder rectangle.
    """
    safe_title = _sanitize_d2_label(scene.title, 60)
    # Extract key points for diagram nodes
    points = scene.key_points[:4] if scene.key_points else []
    if not points:
        # Fall back to splitting narration into key phrases
        words = scene.narration.split()
        if len(words) > 20:
            points = [" ".join(words[i : i + 5]) for i in range(0, min(20, len(words)), 5)]
        else:
            points = [safe_title]

    lines = ["direction: down"]
    # Title node — simple format, no inline styles (avoids D2 parse issues)
    lines.append(f'title: "{safe_title}"')
    for idx, point in enumerate(points):
        safe_point = _sanitize_d2_label(point)
        node_id = f"p{idx}"
        lines.append(f'{node_id}: "{safe_point}"')
        if idx == 0:
            lines.append(f"title -> {node_id}")
        else:
            lines.append(f"p{idx - 1} -> {node_id}")

    return "\n".join(lines)


def _fix_screenshot_ratio(script: DemoScript) -> DemoScript:
    """Deterministically ensure at least 50% of scenes are screenshots/screencasts.

    The revision model often overcorrects by converting too many screenshots to diagrams.
    This converts the minimum number of diagrams back to screenshots.
    """
    from agents.demo_models import ScreenshotSpec

    total = len(script.scenes)
    if total == 0:
        return script
    needed = (total + 1) // 2
    ss_count = sum(1 for s in script.scenes if s.visual_type in ("screenshot", "screencast"))
    deficit = needed - ss_count

    if deficit <= 0:
        return script

    # Convert diagram scenes to screenshots, preferring middle scenes
    scenes = list(script.scenes)
    # Cycle through known routes for variety
    routes = ["http://localhost:5173/chat", "http://localhost:5173/", "http://localhost:5173/demos"]
    route_idx = 0
    converted = 0

    # Prefer converting diagram scenes (not charts — charts have real data)
    candidates = [(i, s) for i, s in enumerate(scenes) if s.visual_type == "diagram"]
    # Sort by distance from edges (prefer middle scenes)
    mid = total // 2
    candidates.sort(key=lambda x: abs(x[0] - mid))

    for idx, scene in candidates:
        if converted >= deficit:
            break
        scenes[idx] = scene.model_copy(
            update={
                "visual_type": "screenshot",
                "diagram_spec": None,
                "screenshot": ScreenshotSpec(url=routes[route_idx % len(routes)]),
            }
        )
        log.info(
            "Converted scene %d '%s' from diagram to screenshot (ratio fix)", idx + 1, scene.title
        )
        route_idx += 1
        converted += 1

    if converted > 0:
        return script.model_copy(update={"scenes": scenes})
    return script


def _fix_consecutive_types(script: DemoScript) -> DemoScript:
    """Deterministically break up 3+ consecutive scenes with the same visual_type.

    When converting a screenshot to diagram, compensates by converting a
    non-adjacent non-screenshot scene to screenshot to maintain the ratio.
    """
    from agents.demo_models import ScreenshotSpec

    scenes = list(script.scenes)
    types = [s.visual_type for s in scenes]
    changed = False

    for i in range(len(types) - 2):
        if types[i] == types[i + 1] == types[i + 2]:
            # Check the route-aware exception for screenshots
            if types[i] == "screenshot":
                known_routes = set()
                for j in range(i, min(i + 3, len(scenes))):
                    s = scenes[j]
                    if s.screenshot:
                        url = s.screenshot.url.rstrip("/")
                        if url.endswith(":5173"):
                            known_routes.add("/")
                        elif "/chat" in url:
                            known_routes.add("/chat")
                        elif "/demos" in url:
                            known_routes.add("/demos")
                if len(known_routes) >= 3:
                    continue  # Different known routes, acceptable

            # Convert the MIDDLE scene (i+1) to break the run
            mid = i + 1
            old_scene = scenes[mid]
            if types[i] == "screenshot":
                # Preserve the route from the screenshot being removed
                removed_route = None
                if old_scene.screenshot:
                    url = old_scene.screenshot.url.rstrip("/")
                    if url.endswith(":5173"):
                        removed_route = "/"
                    elif "/chat" in url:
                        removed_route = "/chat"
                    elif "/demos" in url:
                        removed_route = "/demos"

                # Convert middle screenshot to a substantive diagram
                scenes[mid] = old_scene.model_copy(
                    update={
                        "visual_type": "diagram",
                        "screenshot": None,
                        "diagram_spec": _generate_d2_from_scene(old_scene),
                    }
                )
                types[mid] = "diagram"
                log.info(
                    "Broke consecutive screenshots: converted scene %d '%s' to diagram",
                    mid + 1,
                    old_scene.title,
                )

                # Compensate: convert a non-adjacent non-screenshot to screenshot
                run_zone = set(range(max(0, i - 1), min(len(scenes), i + 4)))
                candidates = [
                    (j, s)
                    for j, s in enumerate(scenes)
                    if j not in run_zone and types[j] in ("diagram", "illustration")
                ]
                if candidates:
                    candidates.sort(key=lambda x: abs(x[0] - mid), reverse=True)
                    comp_idx, comp_scene = candidates[0]
                    can_convert = True
                    if comp_idx > 0 and types[comp_idx - 1] == "screenshot":
                        if comp_idx > 1 and types[comp_idx - 2] == "screenshot":
                            can_convert = False
                    if comp_idx < len(types) - 1 and types[comp_idx + 1] == "screenshot":
                        if comp_idx < len(types) - 2 and types[comp_idx + 2] == "screenshot":
                            can_convert = False
                    if can_convert:
                        route = removed_route or "/chat"
                        new_url = (
                            f"http://localhost:5173{route}"
                            if route != "/"
                            else "http://localhost:5173/"
                        )
                        scenes[comp_idx] = comp_scene.model_copy(
                            update={
                                "visual_type": "screenshot",
                                "diagram_spec": None,
                                "screenshot": ScreenshotSpec(url=new_url),
                            }
                        )
                        types[comp_idx] = "screenshot"
                        log.info(
                            "Compensated: converted scene %d '%s' to screenshot (%s)",
                            comp_idx + 1,
                            comp_scene.title,
                            route,
                        )

            elif types[i] == "diagram":
                # Pick the least-used route to avoid triggering route concentration limits
                from collections import Counter as _Counter

                _route_counts: _Counter[str] = _Counter()
                _route_limits = {"/chat": 3, "/": 2, "/demos": 2}
                for _s in scenes:
                    if _s.visual_type == "screenshot" and _s.screenshot:
                        _url = _s.screenshot.url.rstrip("/")
                        if _url.endswith(":5173"):
                            _route_counts["/"] += 1
                        elif "/chat" in _url:
                            _route_counts["/chat"] += 1
                        elif "/demos" in _url:
                            _route_counts["/demos"] += 1
                # Pick route with most remaining capacity
                _best_route = "/chat"
                _best_remaining = -1
                for _r, _limit in _route_limits.items():
                    _remaining = _limit - _route_counts.get(_r, 0)
                    if _remaining > _best_remaining:
                        _best_remaining = _remaining
                        _best_route = _r
                _new_url = (
                    f"http://localhost:5173{_best_route}"
                    if _best_route != "/"
                    else "http://localhost:5173/"
                )
                scenes[mid] = old_scene.model_copy(
                    update={
                        "visual_type": "screenshot",
                        "diagram_spec": None,
                        "screenshot": ScreenshotSpec(url=_new_url),
                    }
                )
                types[mid] = "screenshot"
                log.info(
                    "Broke consecutive diagrams: converted scene %d '%s' to screenshot (%s)",
                    mid + 1,
                    old_scene.title,
                    _best_route,
                )
            elif types[i] == "chart":
                scenes[mid] = old_scene.model_copy(
                    update={
                        "visual_type": "diagram",
                        "diagram_spec": old_scene.diagram_spec
                        or (
                            f"direction: down\n"
                            f"{old_scene.title.replace(':', ' -').replace('/', '-')}: "
                            f"{{shape: rectangle; style.fill: '#2d2d2d'}}"
                        ),
                    }
                )
                types[mid] = "diagram"
                log.info(
                    "Broke consecutive charts: converted scene %d '%s' to diagram",
                    mid + 1,
                    old_scene.title,
                )
            changed = True

    if changed:
        return script.model_copy(update={"scenes": scenes})
    return script


def _fix_route_concentration(script: DemoScript) -> DemoScript:
    """Deterministically redistribute screenshots to avoid route concentration.

    The revision model consistently fails to distribute screenshots across routes.
    This function reassigns excess same-route screenshots to underrepresented routes.
    """
    from collections import Counter
    from urllib.parse import urlparse

    from agents.demo_models import ScreenshotSpec

    routes = ["/", "/chat", "/demos"]
    # /chat screenshots are each visually unique (different questions seeded),
    # but / and /demos are static pages — duplicates are pixel-identical.
    route_limits = {"/": 2, "/chat": 3, "/demos": 2}

    # Count screenshots per route
    route_counts: Counter[str] = Counter()
    scene_routes: list[str | None] = []
    for s in script.scenes:
        if s.visual_type == "screenshot" and s.screenshot:
            url = s.screenshot.url.rstrip("/")
            parsed = urlparse(url)
            if parsed.hostname in ("localhost", "127.0.0.1"):
                path = parsed.path.rstrip("/") or "/"
                if path in routes:
                    route_counts[path] += 1
                    scene_routes.append(path)
                else:
                    scene_routes.append(None)
            else:
                scene_routes.append(None)
        else:
            scene_routes.append(None)

    # Check if any route is over limit
    over_routes = {r: c for r, c in route_counts.items() if c > route_limits.get(r, 2)}
    if not over_routes:
        return script

    # Find under-represented routes to reassign to
    under_routes = [r for r in routes if route_counts[r] < route_limits.get(r, 2)]

    log.info("Route concentration fix: over=%s, under=%s", over_routes, under_routes)

    # Reassign excess screenshots — prefer scenes in the middle (not first/last)
    patched_scenes = list(script.scenes)
    for over_route, count in over_routes.items():
        excess = count - route_limits.get(over_route, 2)
        # Find indices of scenes using the over-route (prefer middle scenes)
        indices = [i for i, r in enumerate(scene_routes) if r == over_route]
        # Skip first and last occurrence, reassign from the middle
        reassign_indices = indices[1:-1] if len(indices) > 2 else indices[1:]
        reassigned = 0
        for idx in reassign_indices:
            if reassigned >= excess:
                break
            if under_routes:
                # Reassign to under-represented route
                target_route = under_routes[0]
                new_url = (
                    f"http://localhost:5173{target_route}"
                    if target_route != "/"
                    else "http://localhost:5173/"
                )
                old_scene = patched_scenes[idx]
                patched_scenes[idx] = old_scene.model_copy(
                    update={
                        "screenshot": ScreenshotSpec(
                            url=new_url,
                            viewport_width=old_scene.screenshot.viewport_width
                            if old_scene.screenshot
                            else 1920,
                            viewport_height=old_scene.screenshot.viewport_height
                            if old_scene.screenshot
                            else 1080,
                        ),
                    }
                )
                log.info(
                    "Reassigned scene %d '%s' from %s to %s",
                    idx + 1,
                    old_scene.title,
                    over_route,
                    target_route,
                )
                route_counts[over_route] -= 1
                route_counts[target_route] += 1
                scene_routes[idx] = target_route
                reassigned += 1
                if route_counts[target_route] >= route_limits.get(target_route, 2):
                    under_routes.pop(0)
            else:
                # All routes maxed — try diagram conversion first
                total_scenes = len(patched_scenes)
                current_ss = sum(
                    1 for s in patched_scenes if s.visual_type in ("screenshot", "screencast")
                )
                needed_ss = (total_scenes + 1) // 2
                if current_ss > needed_ss:
                    old_scene = patched_scenes[idx]
                    patched_scenes[idx] = old_scene.model_copy(
                        update={
                            "visual_type": "diagram",
                            "screenshot": None,
                            "diagram_spec": _generate_d2_from_scene(old_scene),
                        }
                    )
                    log.info(
                        "Converted scene %d '%s' from screenshot to diagram (all routes full)",
                        idx + 1,
                        old_scene.title,
                    )
                    route_counts[over_route] -= 1
                    scene_routes[idx] = None
                    reassigned += 1
                else:
                    # Can't convert to diagram without breaking ratio —
                    # reassign to the least-used other route (even if at limit).
                    # A static route slightly over limit is better than /chat over limit.
                    other_routes = [r for r in routes if r != over_route]
                    if other_routes:
                        best = min(other_routes, key=lambda r: route_counts.get(r, 0))
                        new_url = (
                            f"http://localhost:5173{best}"
                            if best != "/"
                            else "http://localhost:5173/"
                        )
                        old_scene = patched_scenes[idx]
                        patched_scenes[idx] = old_scene.model_copy(
                            update={
                                "screenshot": ScreenshotSpec(
                                    url=new_url,
                                    viewport_width=old_scene.screenshot.viewport_width
                                    if old_scene.screenshot
                                    else 1920,
                                    viewport_height=old_scene.screenshot.viewport_height
                                    if old_scene.screenshot
                                    else 1080,
                                ),
                            }
                        )
                        log.info(
                            "Force-reassigned scene %d '%s' from %s to %s (all routes at limit)",
                            idx + 1,
                            old_scene.title,
                            over_route,
                            best,
                        )
                        route_counts[over_route] -= 1
                        route_counts[best] += 1
                        scene_routes[idx] = best
                        reassigned += 1

    return script.model_copy(update={"scenes": patched_scenes})


def _fix_fabricated_charts(script: DemoScript) -> DemoScript:
    """Convert chart scenes with likely-fabricated data to diagrams.

    The LLM often generates bar/horizontal-bar charts with round-number values
    (all multiples of 5) that don't correspond to real system metrics.  These
    get flagged by the visual_substance LLM critic but the revision loop can't
    fix them — it just invents different round numbers.  Convert to diagrams
    which convey the same structural information without fake data.
    """
    import json as _json

    patched = list(script.scenes)
    changed = False

    for i, scene in enumerate(patched):
        if scene.visual_type != "chart" or not scene.diagram_spec:
            continue

        try:
            spec = _json.loads(scene.diagram_spec)
        except (ValueError, TypeError):
            continue

        chart_type = spec.get("type", "")
        if chart_type not in ("bar", "horizontal-bar"):
            continue

        values = spec.get("data", {}).get("values", [])
        if not values or not all(isinstance(v, (int, float)) for v in values):
            continue

        # Heuristic: all values are multiples of 5 → likely fabricated
        if all(v % 5 == 0 for v in values):
            log.info(
                "Converting scene %d '%s' from chart to diagram — "
                "chart data looks fabricated (all multiples of 5: %s)",
                i + 1,
                scene.title,
                values,
            )
            patched[i] = scene.model_copy(
                update={
                    "visual_type": "diagram",
                    "diagram_spec": _generate_d2_from_scene(scene),
                }
            )
            changed = True

    if changed:
        return script.model_copy(update={"scenes": patched})
    return script


def _fix_intro_outro(script: DemoScript) -> DemoScript:
    """Deterministically trim intro/outro if they exceed the max word limit.

    These play over static title cards and must be brief. The revision model
    often inflates them.
    """
    max_words = 35
    patches = {}

    intro_words = (script.intro_narration or "").split()
    if len(intro_words) > max_words:
        # Keep the first max_words words and add a period
        trimmed = " ".join(intro_words[:max_words]).rstrip(".,!?") + "."
        patches["intro_narration"] = trimmed
        log.info("Trimmed intro from %d to %d words", len(intro_words), max_words)

    outro_words = (script.outro_narration or "").split()
    if len(outro_words) > max_words:
        trimmed = " ".join(outro_words[:max_words]).rstrip(".,!?") + "."
        patches["outro_narration"] = trimmed
        log.info("Trimmed outro from %d to %d words", len(outro_words), max_words)

    if patches:
        return script.model_copy(update=patches)
    return script


async def critique_and_revise(
    script: DemoScript,
    research_context: str,
    style_guide: dict,
    framework: dict,
    target_seconds: int,
    on_progress: callable | None = None,
    voice_examples: dict | None = None,
    forbidden_terms: list[str] | None = None,
) -> tuple[DemoScript, DemoQualityReport]:
    """Evaluate script quality and revise if needed. Returns (final_script, final_report).

    Loop: deterministic checks → LLM critique → if issues → revise → repeat. Max MAX_ITERATIONS.
    """

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)
        else:
            log.info(msg)

    current_script = script

    for iteration in range(MAX_ITERATIONS):
        progress(f"Quality evaluation (iteration {iteration + 1}/{MAX_ITERATIONS})...")

        # Deterministic pre-checks (inject into LLM report)
        word_check = _check_word_count(current_script, target_seconds)
        variety_check = _check_visual_variety(current_script)
        intro_check = _check_intro_outro_length(current_script)
        deterministic_failures = [
            d for d in [word_check, variety_check, intro_check] if d is not None
        ]

        if deterministic_failures:
            fail_names = [d.name for d in deterministic_failures]
            progress(f"Deterministic failures: {', '.join(fail_names)}")

        # LLM Critique
        critique_prompt = _build_critique_prompt(
            current_script,
            research_context,
            style_guide,
            framework,
            target_seconds,
            voice_examples=voice_examples,
        )
        critique_result = await critique_agent.run(critique_prompt)
        report = critique_result.output

        # Merge deterministic failures into report (override LLM on these dimensions)
        for det_dim in deterministic_failures:
            # Replace or append the dimension in the report
            report.dimensions = [d for d in report.dimensions if d.name != det_dim.name]
            report.dimensions.append(det_dim)

        # Re-evaluate overall pass after merging
        critical_count = sum(
            1 for d in report.dimensions if not d.passed and d.severity == "critical"
        )
        important_count = sum(
            1 for d in report.dimensions if not d.passed and d.severity == "important"
        )
        report.overall_pass = critical_count == 0 and important_count <= 1

        progress(f"Quality: {critical_count} critical, {important_count} important issues")

        if report.overall_pass:
            progress("Script passed quality review")
            return current_script, report

        # Revise — include word count targets in revision prompt
        progress("Revising script...")
        revision_prompt = _build_revision_prompt(
            current_script,
            report,
            research_context,
            style_guide,
            framework,
            target_seconds,
            voice_examples=voice_examples,
            forbidden_terms=forbidden_terms,
        )
        revision_result = await revision_agent.run(revision_prompt)
        revised = revision_result.output

        # Safeguard: restore visual specs that the revision agent accidentally cleared
        # ONLY restore if the visual_type hasn't changed — if the revision intentionally
        # changed visual_type (e.g. diagram→screenshot), clearing the old spec is correct.
        if len(revised.scenes) == len(current_script.scenes):
            patched_scenes = []
            for old_scene, new_scene in zip(current_script.scenes, revised.scenes, strict=False):
                patches = {}
                same_type = old_scene.visual_type == new_scene.visual_type
                # Restore diagram_spec if revision cleared it AND type is still diagram
                if old_scene.diagram_spec and not new_scene.diagram_spec and same_type:
                    patches["diagram_spec"] = old_scene.diagram_spec
                # Restore screenshot if revision cleared it AND type is still screenshot
                if old_scene.screenshot and not new_scene.screenshot and same_type:
                    patches["screenshot"] = old_scene.screenshot
                # Restore interaction if revision cleared it AND type is still screencast
                if old_scene.interaction and not new_scene.interaction and same_type:
                    patches["interaction"] = old_scene.interaction
                # Restore screencast visual_type if revision changed it away
                # (interaction specs are expensive to create, don't let revision discard them)
                if old_scene.visual_type == "screencast" and new_scene.visual_type != "screencast":
                    if old_scene.interaction:
                        patches["visual_type"] = "screencast"
                        patches["interaction"] = old_scene.interaction
                        log.info("Restored screencast visual_type for scene '%s'", old_scene.title)
                # Restore illustration if revision cleared it AND type is still illustration
                if old_scene.visual_type == "illustration" and old_scene.illustration:
                    if not new_scene.illustration:
                        patches["illustration"] = old_scene.illustration
                # Restore illustration visual_type if revision changed it away
                if (
                    old_scene.visual_type == "illustration"
                    and new_scene.visual_type != "illustration"
                ):
                    if new_scene.visual_type in ("diagram", "chart"):
                        patches["visual_type"] = "illustration"
                        patches["illustration"] = old_scene.illustration
                        log.info(
                            "Restored illustration visual_type for scene '%s'", old_scene.title
                        )
                if patches:
                    new_scene = new_scene.model_copy(update=patches)
                patched_scenes.append(new_scene)
            revised = revised.model_copy(update={"scenes": patched_scenes})

        # Word count preservation safeguard: don't let revision shrink narration
        # when duration_feasibility wasn't the issue being fixed. The revision model
        # often truncates narration while fixing visual variety or factual issues.
        def _word_count(s: DemoScript) -> int:
            wc = len((s.intro_narration or "").split()) + len((s.outro_narration or "").split())
            for sc in s.scenes:
                wc += len(sc.narration.split())
            return wc

        old_wc = _word_count(current_script)
        new_wc = _word_count(revised)
        # If revision lost >15% of words AND the original was already at or above
        # the minimum threshold, restore narration from scenes that weren't flagged
        min_words = int(target_seconds * 2.5 * 0.70)
        if new_wc < old_wc * 0.85 and old_wc >= min_words:
            log.warning(
                "Revision shrank narration from %d to %d words (%.0f%% loss). "
                "Restoring narration for non-flagged scenes.",
                old_wc,
                new_wc,
                (1 - new_wc / old_wc) * 100,
            )
            # Identify which scenes had content issues flagged
            flagged_scenes = set()
            for d in report.dimensions:
                if not d.passed and d.name in (
                    "factual_grounding",
                    "honesty_accuracy",
                    "voice_consistency",
                ):
                    for issue in d.issues:
                        # Extract scene numbers/titles from issue text
                        import re as _re

                        for m in _re.finditer(r"[Ss]cene (\d+)", issue):
                            flagged_scenes.add(int(m.group(1)) - 1)  # 0-indexed

            if len(revised.scenes) == len(current_script.scenes):
                restored_scenes = []
                for idx, (old_sc, new_sc) in enumerate(
                    zip(current_script.scenes, revised.scenes, strict=False)
                ):
                    if (
                        idx not in flagged_scenes
                        and len(new_sc.narration.split()) < len(old_sc.narration.split()) * 0.70
                    ):
                        # Restore longer narration but keep visual changes
                        new_sc = new_sc.model_copy(update={"narration": old_sc.narration})
                        log.info(
                            "Restored narration for scene '%s' (%d→%d words)",
                            old_sc.title,
                            len(old_sc.narration.split()),
                            len(new_sc.narration.split()),
                        )
                    restored_scenes.append(new_sc)
                revised = revised.model_copy(update={"scenes": restored_scenes})
                log.info("After restoration: %d words (was %d)", _word_count(revised), new_wc)

        current_script = revised

    # Apply deterministic fixes that the revision model consistently fails at
    current_script = _fix_screenshot_ratio(current_script)
    current_script = _fix_fabricated_charts(current_script)
    # Route concentration and consecutive types fixers conflict — one can undo the
    # other.  Run them in a convergence loop (max 3 passes) until stable.
    for _pass in range(3):
        before = [s.visual_type for s in current_script.scenes]
        current_script = _fix_route_concentration(current_script)
        current_script = _fix_consecutive_types(current_script)
        after = [s.visual_type for s in current_script.scenes]
        if before == after:
            break
        log.info("Fixer convergence pass %d: types changed, iterating", _pass + 1)
    current_script = _fix_intro_outro(current_script)

    # Max iterations reached
    progress(f"WARNING: Max iterations ({MAX_ITERATIONS}) reached, returning best version")
    # Do one final evaluation
    final_critique = await critique_agent.run(
        _build_critique_prompt(
            current_script,
            research_context,
            style_guide,
            framework,
            target_seconds,
            voice_examples=voice_examples,
        )
    )
    final_report = final_critique.output

    # Recheck deterministic failures against the FINAL script (may have improved)
    det_names = {"duration_feasibility", "visual_appropriateness", "intro_outro_length"}
    # Remove any stale deterministic dimensions from LLM report
    final_report.dimensions = [d for d in final_report.dimensions if d.name not in det_names]
    # Re-run deterministic checks on the final script
    for check_fn in [_check_word_count, _check_visual_variety, _check_intro_outro_length]:
        if check_fn == _check_word_count:
            result = check_fn(current_script, target_seconds)
        elif check_fn == _check_intro_outro_length:
            result = check_fn(current_script)
        else:
            result = check_fn(current_script)
        if result:
            final_report.dimensions.append(result)

    critical_count = sum(
        1 for d in final_report.dimensions if not d.passed and d.severity == "critical"
    )
    important_count = sum(
        1 for d in final_report.dimensions if not d.passed and d.severity == "important"
    )
    final_report.overall_pass = critical_count == 0 and important_count <= 1

    return current_script, final_report
