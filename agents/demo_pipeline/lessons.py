"""Re-export from hapax-demo package for backwards compatibility."""

from demo.pipeline.lessons import *  # noqa: F401, F403
from demo.pipeline.lessons import (  # noqa: F401
    accumulate_lessons,
    extract_lessons,
    format_lessons_block,
    load_lessons,
    load_lessons_for_archetype,
    save_lessons,
)
