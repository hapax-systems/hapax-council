"""omg.lol weblog publisher — ytb-OMG8 Phase B.

The weblog is the highest-gravity omg.lol surface: long-form essays,
retrospectives, programme-arc reflections. Per the cc-task, weblog is
**never fully autonomous** — every entry is operator-reviewed before
publish.

Phase B (this module) ships the publish side: read an approved markdown
file, derive an entry slug, walk the allowlist, post via
``OmgLolClient.set_entry``. Phase A (draft composer) is a follow-up;
operator currently drafts by hand.

Usage:
    uv run python -m agents.omg_weblog_publisher <path-to-draft.md>
    uv run python -m agents.omg_weblog_publisher --dry-run <path>
"""

from agents.omg_weblog_publisher.publisher import (
    WeblogPublisher,
    derive_entry_slug,
    main,
    parse_draft,
    publish_artifact,
)

__all__ = [
    "WeblogPublisher",
    "derive_entry_slug",
    "main",
    "parse_draft",
    "publish_artifact",
]
