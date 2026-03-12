"""Re-export from hapax-demo package for backwards compatibility."""

from demo.pipeline.slides import *  # noqa: F401, F403
from demo.pipeline.slides import (  # noqa: F401
    AUDIENCE_LABELS,
    generate_marp_markdown,
    render_slides,
)
