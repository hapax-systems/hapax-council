"""Data models for the demo generator agent."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

PERSONAS_PATH = Path(__file__).resolve().parent.parent / "profiles" / "demo-personas.yaml"
AUDIENCES_PATH = Path(__file__).resolve().parent.parent / "profiles" / "demo-audiences.yaml"
VOICE_EXAMPLES_PATH = Path(__file__).resolve().parent.parent / "profiles" / "voice-examples.yaml"
VOICE_PROFILE_PATH = Path(__file__).resolve().parent.parent / "profiles" / "voice-profile.yaml"


class InteractionStep(BaseModel):
    """A single step in a screencast interaction sequence."""

    action: Literal["click", "type", "wait", "scroll", "press"] = Field(
        description="Action to perform"
    )
    target: str = Field(default="", description="CSS selector or text selector for click targets")
    value: str = Field(
        default="",
        description="Text to type, key to press, wait duration in ms, or scroll distance in px",
    )


class InteractionSpec(BaseModel):
    """Specification for recording a screencast interaction."""

    url: str = Field(description="URL to navigate to before interaction")
    viewport_width: int = Field(default=1920, description="Browser viewport width")
    viewport_height: int = Field(default=1080, description="Browser viewport height")
    steps: list[InteractionStep] = Field(
        default_factory=list,
        description="Interaction steps to execute (or empty if using a recipe)",
    )
    recipe: str | None = Field(
        default=None,
        description="Named recipe to use instead of custom steps (e.g. 'chat-health-query')",
    )
    max_duration: float = Field(default=30.0, ge=1.0, le=120.0, description="Safety cap in seconds")


class IllustrationSpec(BaseModel):
    """Specification for an AI-generated conceptual illustration."""

    prompt: str = Field(description="Scene-specific image generation prompt")
    style: str = Field(
        default="",
        description="Style keywords from audience persona (e.g. 'warm minimal illustration')",
    )
    negative_prompt: str = Field(
        default="text, words, labels, letters, numbers, watermark, diagram, chart, UI, screenshot",
        description="What to exclude from the generated image",
    )
    aspect_ratio: str = Field(
        default="16:9",
        description="Image aspect ratio",
    )


class ScreenshotSpec(BaseModel):
    """Instructions for capturing a single screenshot."""

    url: str = Field(description="URL to navigate to")
    viewport_width: int = Field(default=1920, description="Browser viewport width")
    viewport_height: int = Field(default=1080, description="Browser viewport height")
    actions: list[str] = Field(
        default_factory=list,
        description="Playwright actions to execute before capture",
    )
    wait_for: str | None = Field(
        default=None, description="Text or selector to wait for before capture"
    )
    capture: str = Field(
        default="viewport", description="'viewport', 'fullpage', or a CSS selector"
    )


class DemoScene(BaseModel):
    """A single scene in a demo — one screenshot with narration."""

    title: str = Field(description="Scene title (used in slide heading)")
    narration: str = Field(
        description="Spoken narration text — MUST be 5-8 sentences, minimum 120 words"
    )
    duration_hint: float = Field(ge=1.0, description="Estimated duration in seconds")
    key_points: list[str] = Field(
        default_factory=list, description="Bullet points to display on the slide"
    )
    screenshot: ScreenshotSpec | None = Field(
        default=None,
        description="How to capture the visual (required for screenshot visual_type, omit for diagram/chart)",
    )
    visual_type: Literal["screenshot", "diagram", "chart", "screencast", "illustration"] = Field(
        default="screenshot",
        description="Type of visual: screenshot (Playwright), diagram (D2), chart (Matplotlib), screencast (Playwright video), or illustration (AI-generated)",
    )
    diagram_spec: str | None = Field(
        default=None,
        description="D2 source code for diagrams, or chart specification JSON for charts",
    )
    interaction: InteractionSpec | None = Field(
        default=None,
        description="Interaction spec for screencast visual_type — URL, steps, and recording params",
    )
    illustration: IllustrationSpec | None = Field(
        default=None,
        description="Illustration spec for AI-generated conceptual images",
    )
    slide_table: list[list[str]] | None = Field(
        default=None,
        description="Optional table for comparison slides — list of rows, first row is header. Use instead of key_points for comparison/contrast scenes.",
    )
    research_notes: str | None = Field(
        default=None,
        description="Factual grounding for this scene's claims — used by critique stage",
    )


class QualityDimension(BaseModel):
    """Evaluation of one quality dimension."""

    name: str
    passed: bool
    severity: Literal["critical", "important", "minor"] | None = None
    issues: list[str] = Field(default_factory=list)


class DemoQualityReport(BaseModel):
    """Output of the self-critique evaluation."""

    dimensions: list[QualityDimension]
    overall_pass: bool
    revision_notes: str | None = None


class DemoEvalDimension(BaseModel):
    """Evaluation of one output quality dimension."""

    name: str
    category: Literal["text", "visual", "structural"]
    passed: bool
    score: float = Field(ge=0.0, le=1.0, description="Quality score 0.0-1.0")
    issues: list[str] = Field(default_factory=list)
    evidence: str | None = Field(
        default=None,
        description="Quote from narration or screenshot description supporting the evaluation",
    )


class DemoEvalReport(BaseModel):
    """Evaluation report for a single iteration."""

    dimensions: list[DemoEvalDimension]
    overall_pass: bool
    overall_score: float = Field(ge=0.0, le=1.0)
    iteration: int = 1
    adjustments_applied: list[str] = Field(default_factory=list)


class DemoEvalResult(BaseModel):
    """Full evaluation run result across all iterations."""

    scenario: str
    passed: bool
    iterations: int
    final_report: DemoEvalReport
    history: list[DemoEvalReport] = Field(default_factory=list)
    demo_dir: str
    total_duration_seconds: float = 0.0


class SceneSkeleton(BaseModel):
    """Content plan for a single scene — facts only, no prose."""

    title: str
    facts: list[str] = Field(description="Specific facts to state, grounded in research")
    data_citations: list[str] = Field(
        default_factory=list,
        description="Exact numbers/names from research context",
    )
    visual_type: Literal["screenshot", "diagram", "chart", "screencast", "illustration"] = Field(
        default="screenshot",
        description="Type of visual for this scene: screenshot, diagram, chart, screencast, or illustration",
    )
    visual_brief: str = Field(default="", description="What this visual shows and why")
    screenshot: ScreenshotSpec | None = None
    diagram_spec: str | None = None
    interaction: InteractionSpec | None = None
    illustration: IllustrationSpec | None = Field(
        default=None,
        description="Illustration spec for AI-generated conceptual images",
    )
    design_rationale: str | None = Field(
        default=None, description="Why this is built this way (optional)"
    )
    limitation_or_tradeoff: str | None = Field(
        default=None, description="Honest limitation or trade-off to mention (optional)"
    )


class ContentSkeleton(BaseModel):
    """Structured content plan — what to say, with no prose."""

    title: str
    audience: str
    intro_points: list[str] = Field(description="Key points for the opening")
    scenes: list[SceneSkeleton] = Field(min_length=1)
    outro_points: list[str] = Field(description="Key points for the closing")


class DemoScript(BaseModel):
    """Complete demo script produced by the LLM agent."""

    title: str = Field(description="Demo title")
    audience: str = Field(
        description="Resolved audience archetype name (e.g. 'family', 'technical-peer')",
        max_length=50,
    )
    scenes: list[DemoScene] = Field(description="Ordered list of scenes", min_length=1)
    intro_narration: str = Field(description="Opening narration before first scene")
    outro_narration: str = Field(description="Closing narration after last scene")


class AudiencePersona(BaseModel):
    """An audience archetype loaded from demo-personas.yaml."""

    description: str
    tone: str
    vocabulary: str
    show: list[str]
    skip: list[str]
    forbidden_terms: list[str] = Field(default_factory=list)
    max_scenes: int = 10


def load_personas(
    path: Path | None = None,
    extra_path: Path | None = None,
) -> dict[str, AudiencePersona]:
    """Load audience personas from YAML file.

    Args:
        path: Override path for built-in personas YAML.
        extra_path: Optional path to a custom personas YAML file.
            Custom personas are merged into built-ins, overriding on name collision.
    """
    p = path or PERSONAS_PATH
    raw = yaml.safe_load(p.read_text())
    personas = {
        name: AudiencePersona.model_validate(data) for name, data in raw["archetypes"].items()
    }
    # Merge custom personas (override if same name)
    if extra_path and extra_path.exists():
        extra_data = yaml.safe_load(extra_path.read_text())
        for name, config in extra_data.get("archetypes", {}).items():
            personas[name] = AudiencePersona.model_validate(config)
    return personas


@dataclass
class AudienceDossier:
    """A named audience member that overlays on an archetype."""

    key: str  # "my partner"
    archetype: str  # "family"
    name: str  # "Sarah"
    context: str  # free-text background
    calibration: dict = dc_field(default_factory=dict)  # {emphasize: [...], skip: [...]}


def load_audiences(path: Path | None = None) -> dict[str, AudienceDossier]:
    """Load audience dossiers. Returns lowercased-key -> dossier.

    Returns {} if file missing/malformed.
    """
    p = path or AUDIENCES_PATH
    try:
        raw = yaml.safe_load(p.read_text())
        if not isinstance(raw, dict):
            return {}
        result: dict[str, AudienceDossier] = {}
        for key, data in raw.get("audiences", {}).items():
            if not isinstance(data, dict):
                continue
            result[key.lower()] = AudienceDossier(
                key=key,
                archetype=data.get("archetype", "technical-peer"),
                name=data.get("name", key),
                context=data.get("context", ""),
                calibration=data.get("calibration", {}),
            )
        return result
    except (OSError, yaml.YAMLError):
        return {}
