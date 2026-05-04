"""Programme authoring — asset resolution for Hapax-authored programmes.

The programme planner (``agents.programme_manager.planner``) emits
``ProgrammePlan`` instances whose ``narrative_beat`` strings encode the
*intent* of a segmented-content programme (e.g. ``"tier-list segment on
'EXL3 quants'. Source candidates from vault + RAG..."``). Translating
that intent into concrete assets — candidate lists, vault-note
outlines, RAG hits, content-resolver-fetched media — is what this
package does.

The seven segmented-content roles introduced in PR #2465 each have a
different acquisition pattern. Rather than a single LLM-driven
resolver, the per-role functions in :mod:`asset_resolver` use
existing Qdrant + profile + filesystem infrastructure directly.
Returning structured dataclasses (rather than the formatted-string
output of :mod:`shared.knowledge_search`) lets the narrative composer
and director surfaces consume resolved assets without re-parsing.

References
----------
- ``agents/programme_manager/prompts/programme_plan.md`` — the seven
  segmented-content narrative-beat templates
- ``shared/programme.py`` — ``ProgrammeRole`` (19 roles, 7 segmented)
- cc-task ``programme-authors-autonomous-generation-segmented-types``
"""

from agents.programme_authors.asset_resolver import (
    IcebergAssets,
    InterviewAssets,
    LectureAssets,
    ProgrammeAssets,
    RantAssets,
    ReactAssets,
    TierListAssets,
    Top10Assets,
    resolve_assets,
    resolve_iceberg,
    resolve_interview,
    resolve_lecture,
    resolve_rant,
    resolve_react,
    resolve_tier_list,
    resolve_top_10,
)

__all__ = [
    "IcebergAssets",
    "InterviewAssets",
    "LectureAssets",
    "ProgrammeAssets",
    "RantAssets",
    "ReactAssets",
    "TierListAssets",
    "Top10Assets",
    "resolve_assets",
    "resolve_iceberg",
    "resolve_interview",
    "resolve_lecture",
    "resolve_rant",
    "resolve_react",
    "resolve_tier_list",
    "resolve_top_10",
]
