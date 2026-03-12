"""Re-export from hapax-demo package for backwards compatibility."""

from demo.pipeline.diagrams import *  # noqa: F401, F403
from demo.pipeline.diagrams import (  # noqa: F401 — tests
    _convert_inline_chain,
    _expand_semicolons,
    _extract_nodes_and_edges,
    _fallback_diagram,
    _simplify_d2,
    _strip_style_blocks,
)
