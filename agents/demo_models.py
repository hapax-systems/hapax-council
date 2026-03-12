"""Re-export from hapax-demo package for backwards compatibility."""

from pathlib import Path

from demo.models import *  # noqa: F401, F403
from demo.models import (  # noqa: F401 — explicit for type checkers
    AudienceDossier,
    AudiencePersona,
    ContentSkeleton,
    DemoEvalDimension,
    DemoEvalReport,
    DemoEvalResult,
    DemoQualityReport,
    DemoScene,
    DemoScript,
    IllustrationSpec,
    InteractionSpec,
    InteractionStep,
    QualityDimension,
    SceneSkeleton,
    ScreenshotSpec,
    configure_paths,
    get_config_dir,
    load_audiences,
    load_personas,
)

# Backwards-compatible path constants — configure the package on import
_profiles = Path(__file__).resolve().parent.parent / "profiles"
configure_paths(
    personas=_profiles / "demo-personas.yaml",
    audiences=_profiles / "demo-audiences.yaml",
    voice_examples=_profiles / "voice-examples.yaml",
    voice_profile=_profiles / "voice-profile.yaml",
    config_dir=_profiles,
)

# Legacy constants for any code that references them directly
PERSONAS_PATH = _profiles / "demo-personas.yaml"
AUDIENCES_PATH = _profiles / "demo-audiences.yaml"
VOICE_EXAMPLES_PATH = _profiles / "voice-examples.yaml"
VOICE_PROFILE_PATH = _profiles / "voice-profile.yaml"
