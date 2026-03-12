"""Re-export from hapax-demo package for backwards compatibility."""

from demo.pipeline.chapters import *  # noqa: F401, F403
from demo.pipeline.chapters import (  # noqa: F401
    build_chapter_list_from_script,
    generate_ffmetadata,
    inject_chapters,
)
