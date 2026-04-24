"""hapax-assets publisher — ytb-AUTH-HOSTING.

Watches `assets/aesthetic-library/` (in council) and mirrors changes into a
checkout of `ryanklee/hapax-assets`, then commits + pushes to `main`. The
external repo's GitHub Action deploys `main` → `gh-pages`, serving the
aesthetic library as a public CDN for omg.lol surfaces that embed
`@font-face`, background-images, etc.

Publishing is one-way (council → CDN). The CDN is not a source of truth;
local filesystem is. URLs are SHA-pinned via
`shared.aesthetic_library.web_export.build_web_url`.

Entry points:
    uv run python -m agents.hapax_assets_publisher --once   # single sync + exit
    uv run python -m agents.hapax_assets_publisher --watch  # long-running daemon
    uv run python -m agents.hapax_assets_publisher --dry-run
"""

from agents.hapax_assets_publisher.config import PublisherConfig
from agents.hapax_assets_publisher.push_throttle import PushThrottle
from agents.hapax_assets_publisher.sync import (
    PathChange,
    build_commit_message,
    has_diff,
    sync_tree,
)

__all__ = [
    "PathChange",
    "PublisherConfig",
    "PushThrottle",
    "build_commit_message",
    "has_diff",
    "sync_tree",
]
