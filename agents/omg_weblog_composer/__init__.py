"""omg.lol weblog composer — ytb-OMG8 Phase A.

Phase A ships the structural draft composer: aggregate source data
(chronicle, completed programmes, axiom precedents) into a markdown
draft with YAML frontmatter, write to a vault path, and leave
``approved: false`` for operator review. Phase B (publisher, shipped
as #1307) consumes the approved draft.

Per the cc-task "Never fully autonomous" — weblog is
operator-reviewed-before-publish; Phase A scaffolds, operator writes.

LLM composition is deferred: this composer emits a structural
skeleton with placeholder sections + aggregated-context summary.
A future Phase A-plus can add LLM-backed body generation.

Usage:
    uv run python -m agents.omg_weblog_composer [--iso-date YYYY-MM-DD]
"""

from agents.omg_weblog_composer.composer import (
    WeblogComposer,
    WeblogDraft,
    compose_iso_date_slug,
    main,
)

__all__ = ["WeblogComposer", "WeblogDraft", "compose_iso_date_slug", "main"]
