"""Re-export from hapax-demo package for backwards compatibility."""

from demo.pipeline.video import *  # noqa: F401, F403
from demo.pipeline.video import (  # noqa: F401
    CROSSFADE_DURATION,
    FPS,
    SCENE_TITLE_DURATION,
    TITLE_DURATION,
    _build_scene_clips,
    _title_clip,
    assemble_video,
)
