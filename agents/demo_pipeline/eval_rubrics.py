"""Evaluation rubrics for demo output quality — structural checks and LLM text evaluation."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.messages import BinaryContent

from agents.demo_models import DemoEvalDimension
from shared.config import get_model

log = logging.getLogger(__name__)


def check_files_present(demo_dir: Path) -> DemoEvalDimension:
    """Verify all expected output files exist."""
    issues = []
    required = ["script.json", "metadata.json", "demo.html"]
    for f in required:
        if not (demo_dir / f).exists():
            issues.append(f"Missing required file: {f}")

    screenshots_dir = demo_dir / "screenshots"
    if not screenshots_dir.exists() or not list(screenshots_dir.glob("*.png")):
        issues.append("No screenshots found in screenshots/ directory")

    # Check script.json references match actual screenshots
    script_path = demo_dir / "script.json"
    if script_path.exists():
        script = json.loads(script_path.read_text())
        scene_count = len(script.get("scenes", []))
        png_count = len(list(screenshots_dir.glob("*.png"))) if screenshots_dir.exists() else 0
        if png_count < scene_count:
            issues.append(f"Only {png_count} screenshots for {scene_count} scenes")

    passed = len(issues) == 0
    return DemoEvalDimension(
        name="files_present",
        category="structural",
        passed=passed,
        score=1.0 if passed else 0.0,
        issues=issues,
    )


def check_metadata_correctness(
    demo_dir: Path, expected_audience: str | None = None
) -> DemoEvalDimension:
    """Verify metadata.json has correct values."""
    issues = []
    meta_path = demo_dir / "metadata.json"

    if not meta_path.exists():
        return DemoEvalDimension(
            name="metadata_correctness",
            category="structural",
            passed=False,
            score=0.0,
            issues=["metadata.json not found"],
        )

    meta = json.loads(meta_path.read_text())

    required_keys = {"title", "audience", "scope", "scenes", "format", "duration", "primary_file"}
    missing = required_keys - set(meta.keys())
    if missing:
        issues.append(f"Missing metadata keys: {missing}")

    if expected_audience and meta.get("audience") != expected_audience:
        issues.append(
            f"Audience mismatch: expected '{expected_audience}', got '{meta.get('audience')}'"
        )

    script_path = demo_dir / "script.json"
    if script_path.exists():
        script = json.loads(script_path.read_text())
        if meta.get("scenes") != len(script.get("scenes", [])):
            issues.append(
                f"Scene count mismatch: metadata={meta.get('scenes')}, script={len(script.get('scenes', []))}"
            )

    duration = meta.get("duration", 0)
    if duration <= 0:
        issues.append(f"Invalid duration: {duration}")

    # Note: quality_pass is a pipeline-internal signal (self-critique passed or not).
    # It should not penalize the eval — the eval judges the actual output quality directly.

    passed = len(issues) == 0
    return DemoEvalDimension(
        name="metadata_correctness",
        category="structural",
        passed=passed,
        score=max(0.0, 1.0 - len(issues) * 0.25),
        issues=issues,
    )


def check_html_integrity(demo_dir: Path) -> DemoEvalDimension:
    """Verify demo.html has expected structure."""
    issues = []
    html_path = demo_dir / "demo.html"

    if not html_path.exists():
        return DemoEvalDimension(
            name="html_integrity",
            category="structural",
            passed=False,
            score=0.0,
            issues=["demo.html not found"],
        )

    html = html_path.read_text()

    if "data:image/" not in html:
        issues.append("No base64 images found in HTML player")

    if "#282828" not in html and "#1d2021" not in html and "#32302f" not in html:
        issues.append("Dark background color not found (expected #282828, #1d2021, or #32302f)")

    script_path = demo_dir / "script.json"
    if script_path.exists():
        script = json.loads(script_path.read_text())
        for scene in script.get("scenes", []):
            if scene["title"] not in html:
                issues.append(f"Scene title '{scene['title']}' not found in HTML")
                break

    if "play" not in html.lower() and "autoplay" not in html.lower():
        issues.append("No player controls found in HTML")

    passed = len(issues) == 0
    return DemoEvalDimension(
        name="html_integrity",
        category="structural",
        passed=passed,
        score=max(0.0, 1.0 - len(issues) * 0.2),
        issues=issues,
    )


def run_structural_checks(
    demo_dir: Path,
    expected_audience: str | None = None,
) -> list[DemoEvalDimension]:
    """Run all deterministic structural checks."""
    return [
        check_files_present(demo_dir),
        check_metadata_correctness(demo_dir, expected_audience),
        check_html_integrity(demo_dir),
    ]


# ── Text evaluation models ──────────────────────────────────────────────────


class DimScore(BaseModel):
    """Score for a single text dimension."""

    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    issues: list[str] = Field(default_factory=list)
    evidence: str | None = None


class TextEvalOutput(BaseModel):
    """Structured output from text evaluation LLM."""

    voice_consistency: DimScore
    audience_calibration: DimScore
    duration_feasibility: DimScore
    key_points_quality: DimScore
    narrative_coherence: DimScore


text_eval_agent = Agent(
    get_model("balanced"),
    system_prompt=(
        "You are a rigorous presentation quality evaluator. Given a demo script's "
        "narration and metadata, evaluate it against specific quality dimensions. "
        "Be precise and cite specific narration text as evidence for any issues found. "
        "Score each dimension 0.0-1.0 where 0.8+ is passing."
    ),
    output_type=TextEvalOutput,
)


def _build_text_eval_prompt(
    script_data: dict,
    style_guide: dict,
    target_seconds: int,
    voice_examples: dict | None = None,
) -> str:
    """Build the prompt for text quality evaluation."""
    narrations = []
    key_points_all = []
    for i, scene in enumerate(script_data.get("scenes", []), 1):
        narrations.append(f"Scene {i} ({scene['title']}): {scene['narration']}")
        key_points_all.extend(scene.get("key_points", []))

    total_words = sum(len(s.get("narration", "").split()) for s in script_data.get("scenes", []))
    total_words += len(script_data.get("intro_narration", "").split())
    total_words += len(script_data.get("outro_narration", "").split())

    # Voice consistency section — prefer examples over flat lists
    voice_section = ""
    if voice_examples and voice_examples.get("examples"):
        good_examples = []
        bad_example = ""
        for key, ex in voice_examples["examples"].items():
            if key == "bad_example":
                bad_example = ex["text"].strip()
            else:
                good_examples.append(f'"{ex["text"].strip()}"')
        voice_section = f"""### 1. voice_consistency
Does the narration sound like these good examples (matter-of-fact, first-person, concrete)?

{chr(10).join(f"Good Example {chr(65 + i)}: {ex}" for i, ex in enumerate(good_examples))}

Does it sound like this BAD example (pitch mode)? If so, it fails:
"{bad_example}"

The narration should match the good examples in tone, register, and style."""
    else:
        avoid_items = style_guide.get("avoid", [])
        embrace_items = style_guide.get("embrace", [])
        voice_section = f"""### 1. voice_consistency
Voice should be: {style_guide.get("voice", "first-person")}
Cadence should be: {style_guide.get("cadence", "state-explain-show")}
Transitions should be: {style_guide.get("transitions", "functional")}
MUST AVOID: {"; ".join(avoid_items)}
SHOULD EMBRACE: {"; ".join(embrace_items)}
Opening rule: {style_guide.get("opening", "")}
Closing rule: {style_guide.get("closing", "")}"""

    return f"""Evaluate this demo script's text quality.

## Narration Text

Intro: {script_data.get("intro_narration", "")}

{chr(10).join(narrations)}

Outro: {script_data.get("outro_narration", "")}

## Key Points (all scenes)
{chr(10).join(f"- {kp}" for kp in key_points_all)}

## Evaluation Criteria

{voice_section}

### 2. audience_calibration
Target audience: {script_data.get("audience", "unknown")}
Family audience = no technical jargon, warm, accessible.
Technical audience = precise terminology, design rationale.

### 3. duration_feasibility
Target duration: {target_seconds} seconds
Total word count: {total_words}
Speech rate: ~150 words/minute (2.5 words/second)
Expected words for target: ~{int(target_seconds * 2.5)}
Tolerance: +/-20%

### 4. key_points_quality
Each key point should be substantive and specific.
Must contain concrete facts, numbers, or outcomes — not vague platitudes.

### 5. narrative_coherence
Script should follow a clear narrative arc.
Scenes should build logically. Opening should set context. Closing should land on impact.

For each dimension: score 0.0-1.0 (0.8+ = pass), list specific issues with evidence quotes."""


async def run_text_evaluation(
    script_data: dict,
    style_guide: dict,
    target_seconds: int,
    voice_examples: dict | None = None,
) -> list[DemoEvalDimension]:
    """Run LLM-based text quality evaluation on script narration."""
    prompt = _build_text_eval_prompt(
        script_data, style_guide, target_seconds, voice_examples=voice_examples
    )
    result = await text_eval_agent.run(prompt)
    output = result.output

    dimensions = []
    for name in [
        "voice_consistency",
        "audience_calibration",
        "duration_feasibility",
        "key_points_quality",
        "narrative_coherence",
    ]:
        dim_score: DimScore = getattr(output, name)
        dimensions.append(
            DemoEvalDimension(
                name=name,
                category="text",
                passed=dim_score.passed,
                score=dim_score.score,
                issues=dim_score.issues,
                evidence=dim_score.evidence,
            )
        )
    return dimensions


# ── Visual evaluation ───────────────────────────────────────────────────────


class VisualEvalOutput(BaseModel):
    """Structured output from visual evaluation LLM."""

    visual_clarity: DimScore
    visual_variety: DimScore
    theme_compliance: DimScore
    visual_narration_alignment: DimScore


visual_eval_agent = Agent(
    get_model("gemini-pro"),
    system_prompt=(
        "You are a visual quality evaluator for presentation screenshots. "
        "You will receive multiple screenshots from a demo presentation along with "
        "their scene narrations. Evaluate the visual quality across four dimensions. "
        "Be specific — cite which screenshot/scene has issues. "
        "Score each dimension 0.0-1.0 where 0.8+ is passing. "
        "Focus on whether the visuals look professional and serve the presentation well. "
        "A polished, attractive presentation with any consistent color scheme should score high. "
        "Don't penalize for specific color choices as long as the overall look is cohesive."
    ),
    output_type=VisualEvalOutput,
)


def _load_screenshots_as_content(
    demo_dir: Path,
    script_data: dict,
) -> list[str | BinaryContent]:
    """Load screenshots and interleave with narration text for the vision prompt."""
    content: list[str | BinaryContent] = []
    screenshots_dir = demo_dir / "screenshots"

    for i, scene in enumerate(script_data.get("scenes", []), 1):
        pattern = f"{i:02d}-*.png"
        matches = list(screenshots_dir.glob(pattern))
        if not matches:
            content.append(
                f"\n--- Scene {i}: {scene['title']} ---\n[Screenshot missing]\nNarration: {scene['narration']}\n"
            )
            continue

        screenshot_path = matches[0]
        image_bytes = screenshot_path.read_bytes()
        image = BinaryContent(data=image_bytes, media_type="image/png")

        content.append(
            f"\n--- Scene {i}: {scene['title']} ---\nNarration: {scene['narration']}\nKey points: {', '.join(scene.get('key_points', []))}\n"
        )
        content.append(image)

    return content


def _build_visual_eval_prompt(script_data: dict) -> str:
    """Build the text portion of the visual evaluation prompt."""
    return f"""Evaluate the visual quality of these demo screenshots.

The demo is titled "{script_data.get("title", "Unknown")}" for a {script_data.get("audience", "unknown")} audience.

## Evaluation Criteria

### 1. visual_clarity
- Screenshots should be legible and visually clear
- No error pages, loading spinners, or browser chrome artifacts
- Text in screenshots should be readable at presentation resolution
- Charts, diagrams, and generated visuals count as meaningful content (they don't need to show a live UI)
- A mix of screenshots, diagrams, and charts is normal and expected

### 2. visual_variety
- Screenshots should show different views, pages, or data across scenes
- A demo should not have all screenshots looking nearly identical
- Different scenes should provide visual progression through the subject matter

### 3. theme_compliance
- Visual style should be consistent across all scenes — colors, layout, and tone should feel unified
- Dark backgrounds are preferred but not mandatory — what matters is that the overall look is polished and professional
- Color palette should be cohesive (any well-chosen palette is fine; Gruvbox tones like orange/yellow/blue/green are a bonus, not a requirement)
- Charts and diagrams should look clean and readable — attractive design matters more than specific hex colors

### 4. visual_narration_alignment
- What's shown in each screenshot should relate to what's narrated
- The visual should serve the scene's communication purpose
- If narration discusses a specific feature, the screenshot should show that feature

Score each dimension 0.0-1.0 (0.8+ = pass). Cite specific scenes for any issues."""


async def run_visual_evaluation(
    demo_dir: Path,
    script_data: dict,
) -> list[DemoEvalDimension]:
    """Run vision-model evaluation on demo screenshots."""
    screenshot_content = _load_screenshots_as_content(demo_dir, script_data)

    if not any(isinstance(c, BinaryContent) for c in screenshot_content):
        return [
            DemoEvalDimension(
                name=name,
                category="visual",
                passed=False,
                score=0.0,
                issues=["No screenshots available for evaluation"],
            )
            for name in [
                "visual_clarity",
                "visual_variety",
                "theme_compliance",
                "visual_narration_alignment",
            ]
        ]

    prompt_text = _build_visual_eval_prompt(script_data)
    user_prompt: list[str | BinaryContent] = [prompt_text] + screenshot_content

    result = await visual_eval_agent.run(user_prompt=user_prompt)
    output = result.output

    dimensions = []
    for name in [
        "visual_clarity",
        "visual_variety",
        "theme_compliance",
        "visual_narration_alignment",
    ]:
        dim_score: DimScore = getattr(output, name)
        dimensions.append(
            DemoEvalDimension(
                name=name,
                category="visual",
                passed=dim_score.passed,
                score=dim_score.score,
                issues=dim_score.issues,
                evidence=dim_score.evidence,
            )
        )
    return dimensions


# ── Diagnosis ───────────────────────────────────────────────────────────────


class DiagnosisOutput(BaseModel):
    """LLM diagnosis of evaluation failures."""

    root_causes: list[str] = Field(description="Identified root causes for failures")
    planning_overrides: str = Field(
        description="Additional instructions to append to the planning prompt on next iteration"
    )
    adjustments_summary: list[str] = Field(description="Human-readable list of what will change")
    jargon_replacements: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of jargon term -> plain language replacement, if applicable",
    )


diagnosis_agent = Agent(
    get_model("balanced"),
    system_prompt=(
        "You are a presentation quality improvement specialist. Given evaluation failures, "
        "diagnose root causes and produce specific, actionable planning prompt overrides "
        "that will fix the issues on the next generation attempt. "
        "Be specific — don't say 'improve quality', say exactly what instruction to add. "
        "The overrides will be appended verbatim to the demo planning prompt."
    ),
    output_type=DiagnosisOutput,
)


def _build_diagnosis_prompt(
    eval_dimensions: list[DemoEvalDimension],
    script_data: dict,
    style_guide: dict,
    iteration: int,
    forbidden_terms: list[str] | None = None,
) -> str:
    """Build the diagnosis prompt from evaluation failures."""
    failing = [d for d in eval_dimensions if not d.passed]
    failing_text = "\n".join(
        f"- **{d.name}** (score: {d.score:.2f}): {'; '.join(d.issues)}"
        + (f"\n  Evidence: {d.evidence}" if d.evidence else "")
        for d in failing
    )

    # Per-scene details for targeted fixes
    scene_details = []
    for i, scene in enumerate(script_data.get("scenes", []), 1):
        narration = scene.get("narration", "")
        word_count = len(narration.split())
        visual_type = scene.get("visual_type", "unknown")
        scene_details.append(
            f'  Scene {i} ({scene.get("title", "?")}): {visual_type}, {word_count} words — "{narration[:120]}..."'
        )
    scene_detail_text = "\n".join(scene_details)

    # Word count summary
    total_words = sum(len(s.get("narration", "").split()) for s in script_data.get("scenes", []))
    total_words += len(script_data.get("intro_narration", "").split())
    total_words += len(script_data.get("outro_narration", "").split())

    # Jargon scan — uses forbidden_terms from persona (single source of truth)
    jargon_found: list[str] = []
    audience = script_data.get("audience", "")
    if forbidden_terms:
        for i, scene in enumerate(script_data.get("scenes", []), 1):
            narration = scene.get("narration", "")
            found_in_scene = [t for t in forbidden_terms if t.lower() in narration.lower()]
            if found_in_scene:
                jargon_found.append(f"  Scene {i}: {', '.join(found_in_scene)}")
        # Also check intro/outro
        for label, text in [
            ("Intro", script_data.get("intro_narration", "")),
            ("Outro", script_data.get("outro_narration", "")),
        ]:
            found = [t for t in forbidden_terms if t.lower() in text.lower()]
            if found:
                jargon_found.append(f"  {label}: {', '.join(found)}")

    # Build jargon section if applicable
    jargon_section = ""
    if jargon_found:
        jargon_text = "\n".join(jargon_found)
        jargon_section = f"""
## JARGON DETECTED (audience: {audience})
These technical terms were found in narration and MUST be replaced with plain language:
{jargon_text}
"""

    return f"""The demo evaluation failed on iteration {iteration}. Diagnose the root causes and produce planning prompt overrides.

## Failing Dimensions
{failing_text}

## Current Script Summary
Title: {script_data.get("title", "Unknown")}
Audience: {script_data.get("audience", "unknown")}
Scenes: {len(script_data.get("scenes", []))}
Intro: {script_data.get("intro_narration", "")[:200]}

## Per-Scene Analysis
{scene_detail_text}

Total narration: {total_words} words
{jargon_section}
## Style Guide
Voice: {style_guide.get("voice", "first-person")}
Avoid: {"; ".join(style_guide.get("avoid", []))}

## Instructions
1. For EACH failing dimension, identify the specific root cause with scene numbers
2. If jargon was detected, your override MUST list each term and its plain-language replacement
3. If word count is low, specify EXACTLY how many words each scene needs to add
4. If visual-narration alignment failed, specify which scenes need different visuals and why
5. Produce planning prompt override text as DIRECT INSTRUCTIONS (not suggestions)
6. The override text gets appended to the planning prompt verbatim
7. Keep overrides under 500 words — be precise, not verbose

Example override: "CRITICAL: The narration for the family audience must use NO technical terms. Replace 'API', 'container', 'vector database' with plain language like 'the system', 'a program', 'its memory'."
"""


async def diagnose_failures(
    eval_dimensions: list[DemoEvalDimension],
    script_data: dict,
    style_guide: dict,
    iteration: int,
    forbidden_terms: list[str] | None = None,
) -> DiagnosisOutput:
    """Diagnose evaluation failures and produce planning overrides."""
    prompt = _build_diagnosis_prompt(
        eval_dimensions, script_data, style_guide, iteration, forbidden_terms
    )
    result = await diagnosis_agent.run(prompt)
    return result.output
