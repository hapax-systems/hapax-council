"""Connector read/mutation classification for the MCP server families sessions carry.

Unsafe cases first: whatever the manifest admits as read-only evidence, a mutating
connector tool (or one the manifest does not know) must stay side-effecting, so the
cc-task-gate, mcp-connector-mutator-gate and authorization-packet-validator hooks keep
gating it. Then one regression per family for the read tools that used to fail closed.
"""

from __future__ import annotations

import json

import pytest

from shared import mcp_connector_policy as policy
from shared.mcp_connector_policy import (
    EFFECT_PUBLIC,
    EFFECT_READ_ONLY,
    canonicalize_tool_name,
    classify_connector_tool,
    is_side_effecting_connector_tool,
)

# --- unsafe cases: these must stay gated -------------------------------------------------

MUTATING_TOOLS = (
    # GitHub MCP server
    "mcp__github__merge_pull_request",
    "mcp__github__create_pull_request",
    "mcp__github__push_files",
    "mcp__github__create_or_update_file",
    "mcp__github__delete_file",
    "mcp__github__issue_write",
    "mcp__github__sub_issue_write",
    "mcp__github__pull_request_review_write",
    "mcp__github__add_comment_to_pending_review",
    "mcp__github__add_reply_to_pull_request_comment",
    "mcp__github__update_pull_request",
    "mcp__github__update_pull_request_branch",
    "mcp__github__create_branch",
    "mcp__github__create_repository",
    "mcp__github__delete_repository",
    "mcp__github__fork_repository",
    "mcp__github__request_copilot_review",
    "mcp__github__run_secret_scanning",
    # A read, but "label" is a mutating verb token (Gmail labelling); it stays gated.
    "mcp__github__get_label",
    # Claude.ai Google Drive / Gmail / Calendar connectors
    "mcp__claude_ai_Google_Drive__create_file",
    "mcp__claude_ai_Google_Drive__copy_file",
    "mcp__claude_ai_Google_Drive__update_file",
    "mcp__claude_ai_Google_Drive__share_file",
    "mcp__claude_ai_Google_Drive__trash_file",
    "mcp__claude_ai_Gmail__send_message",
    "mcp__claude_ai_Gmail__forward",
    "mcp__claude_ai_Gmail__reply",
    "mcp__claude_ai_Gmail__create_draft",
    "mcp__claude_ai_Gmail__trash_thread",
    "mcp__claude_ai_Gmail__label_message",
    "mcp__claude_ai_Gmail__update_message_labels",
    "mcp__claude_ai_Google_Calendar__create_event",
    "mcp__claude_ai_Google_Calendar__update_event",
    "mcp__claude_ai_Google_Calendar__delete_event",
    "mcp__claude_ai_Google_Calendar__respond_to_event",
    # Other Claude.ai connectors: writes, spend, arbitrary execution, auth flows
    "mcp__claude_ai_Canva__create-design",
    # A job poll, but its name carries the "create" verb token; it stays gated rather
    # than weakening the no-mutating-verb manifest invariant below.
    "mcp__claude_ai_Canva__get-create-design-async-job",
    "mcp__claude_ai_Canva__export-design",
    "mcp__claude_ai_Canva__comment-on-design",
    "mcp__claude_ai_Figma__use_figma",
    "mcp__claude_ai_Figma__upload_assets",
    "mcp__claude_ai_Figma__weave_run_tool",
    "mcp__claude_ai_Figma__download_assets",
    "mcp__claude_ai_Sentry__update_issue",
    "mcp__claude_ai_Sentry__execute_sentry_tool",
    "mcp__claude_ai_Sentry__analyze_issue_with_seer",
    "mcp__claude_ai_Hugging_Face__dynamic_space",
    "mcp__claude_ai_Hugging_Face__hf_fs",
    "mcp__claude_ai_Claude_Docs__create",
    "mcp__claude_ai_Claude_Docs__update",
    "mcp__claude_ai_Claude_Docs__delete",
    "mcp__claude_ai_Claude_Docs__batch",
    "mcp__claude_ai_Claude_Docs__export",
    "mcp__claude_ai_Gmail__authenticate",
    "mcp__claude_ai_Figma__complete_authentication",
)

UNKNOWN_TOOLS = (
    "mcp__github__frobnicate_repository",
    "mcp__claude_ai_Google_Drive__frobnicate",
    "mcp__claude_ai_Context7__frobnicate",
    "mcp__claude_ai_Some_New_Connector__get_thing",
    "mcp__some_new_server__list_things",
)


@pytest.mark.parametrize("tool_name", MUTATING_TOOLS)
def test_mutating_connector_tools_stay_side_effecting(tool_name: str) -> None:
    classification = classify_connector_tool(tool_name)

    assert classification is not None
    assert classification.side_effecting, classification
    assert EFFECT_READ_ONLY not in classification.effect_classes
    assert is_side_effecting_connector_tool(tool_name)


@pytest.mark.parametrize("tool_name", UNKNOWN_TOOLS)
def test_unknown_connector_tools_fail_closed(tool_name: str) -> None:
    classification = classify_connector_tool(tool_name)

    assert classification is not None
    assert classification.side_effecting, classification
    assert classification.matched_by != "manifest"


@pytest.mark.parametrize(
    "tool_name",
    (
        "mcp__claude_ai_Google_Drive__share_file",
        "mcp__claude_ai_Gmail__send_message",
        "mcp__claude_ai_Gmail__forward",
        "mcp__claude_ai_Gmail__reply",
        "mcp__github__merge_pull_request",
    ),
)
def test_egress_connector_tools_keep_public_surface(tool_name: str) -> None:
    classification = classify_connector_tool(tool_name)

    assert classification is not None
    assert EFFECT_PUBLIC in classification.effect_classes
    assert "public" in classification.required_mutation_surfaces


def _manifest_entries() -> list[dict]:
    payload = json.loads(policy.DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
    return list(payload["tools"])


def _function_part(canonical: str) -> str:
    return canonical.split(".", 1)[1] if "." in canonical else canonical


def test_no_read_only_manifest_name_carries_a_mutating_verb() -> None:
    offenders = []
    for entry in _manifest_entries():
        if list(entry.get("effect_classes") or ()) != [EFFECT_READ_ONLY]:
            continue
        for name in (entry["canonical_name"], *entry.get("aliases", ())):
            function = _function_part(canonicalize_tool_name(str(name)))
            if policy._MUTATING_FUNCTION_RE.match(
                function
            ) or policy._MUTATING_FUNCTION_TOKEN_RE.search(function):
                offenders.append((entry["canonical_name"], name))

    assert offenders == []


def test_no_manifest_name_is_claimed_by_two_entries() -> None:
    owners: dict[str, list[str]] = {}
    for entry in _manifest_entries():
        names = {
            canonicalize_tool_name(str(name))
            for name in (entry["canonical_name"], *entry.get("aliases", ()))
        }
        for key in names:
            owners.setdefault(key, []).append(str(entry["canonical_name"]))

    collisions = {key: entries for key, entries in owners.items() if len(entries) > 1}
    assert collisions == {}


def test_read_only_manifest_entries_require_no_mutation_surface() -> None:
    for entry in _manifest_entries():
        if EFFECT_READ_ONLY not in (entry.get("effect_classes") or ()):
            continue
        assert list(entry["effect_classes"]) == [EFFECT_READ_ONLY], entry["canonical_name"]
        assert list(entry.get("required_mutation_surfaces") or ["connector"]) == ["connector"]


# --- regressions: read tools that failed closed ------------------------------------------

READ_ONLY_TOOLS_BY_FAMILY = {
    "github": (
        "mcp__github__get_me",
        "mcp__github__pull_request_read",
        "mcp__github__issue_read",
        "mcp__github__get_commit",
        "mcp__github__get_file_contents",
        "mcp__github__get_latest_release",
        "mcp__github__get_release_by_tag",
        "mcp__github__get_tag",
        "mcp__github__get_team_members",
        "mcp__github__get_teams",
        "mcp__github__list_branches",
        "mcp__github__list_commits",
        "mcp__github__list_issue_fields",
        "mcp__github__list_issue_types",
        "mcp__github__list_issues",
        "mcp__github__list_pull_requests",
        "mcp__github__list_releases",
        "mcp__github__list_repository_collaborators",
        "mcp__github__list_tags",
        "mcp__github__search_code",
        "mcp__github__search_commits",
        "mcp__github__search_issues",
        "mcp__github__search_pull_requests",
        "mcp__github__search_repositories",
        "mcp__github__search_users",
    ),
    "context7": (
        "mcp__context7__resolve-library-id",
        "mcp__context7__query-docs",
        "mcp__claude_ai_Context7__resolve-library-id",
        "mcp__claude_ai_Context7__query-docs",
    ),
    "claude_ai_google_drive": (
        "mcp__claude_ai_Google_Drive__search_files",
        "mcp__claude_ai_Google_Drive__list_recent_files",
        "mcp__claude_ai_Google_Drive__get_file_metadata",
        "mcp__claude_ai_Google_Drive__get_file_permissions",
        "mcp__claude_ai_Google_Drive__read_file_content",
        "mcp__claude_ai_Google_Drive__download_file_content",
    ),
    "claude_ai_gmail": (
        "mcp__claude_ai_Gmail__get_message",
        "mcp__claude_ai_Gmail__get_thread",
        "mcp__claude_ai_Gmail__get_draft",
        "mcp__claude_ai_Gmail__list_drafts",
        "mcp__claude_ai_Gmail__list_labels",
        "mcp__claude_ai_Gmail__search_threads",
    ),
    "claude_ai_google_calendar": (
        "mcp__claude_ai_Google_Calendar__get_event",
        "mcp__claude_ai_Google_Calendar__list_calendars",
        "mcp__claude_ai_Google_Calendar__list_events",
        "mcp__claude_ai_Google_Calendar__search_events",
        "mcp__claude_ai_Google_Calendar__suggest_time",
    ),
}

# Read tools of connector services the manifest has not admitted. Admitting them is a
# new capability surface (manifest entry + capability-inventory baseline), not a
# classifier repair, so until then they must keep failing closed.
UNADMITTED_CONNECTOR_READS = (
    "mcp__claude_ai_Figma__get_metadata",
    "mcp__claude_ai_Canva__read-design",
    "mcp__claude_ai_Sentry__search_issues",
    "mcp__claude_ai_Hugging_Face__hub_repo_search",
    "mcp__claude_ai_Claude_Docs__read",
)


@pytest.mark.parametrize("tool_name", UNADMITTED_CONNECTOR_READS)
def test_unadmitted_connector_services_stay_fail_closed(tool_name: str) -> None:
    classification = classify_connector_tool(tool_name)

    assert classification is not None
    assert classification.side_effecting
    assert classification.matched_by == "heuristic_unknown_connector_service"


@pytest.mark.parametrize(
    "tool_name",
    [
        pytest.param(tool, id=f"{family}:{tool}")
        for family, tools in READ_ONLY_TOOLS_BY_FAMILY.items()
        for tool in tools
    ],
)
def test_connector_read_tools_classify_as_read_only_evidence(tool_name: str) -> None:
    classification = classify_connector_tool(tool_name)

    assert classification is not None
    assert classification.matched_by == "manifest", classification
    assert classification.effect_classes == (EFFECT_READ_ONLY,)
    assert not classification.side_effecting
    assert not is_side_effecting_connector_tool(tool_name)


def test_receipt_gate_admits_connector_reads_without_a_claim() -> None:
    for tools in READ_ONLY_TOOLS_BY_FAMILY.values():
        for tool_name in tools:
            result = policy.evaluate_connector_receipt_gate(tool_name, task_id=None, role=None)
            assert result.allowed, (tool_name, result.reason_code)
            assert result.reason_code == "read_only_or_unclassified"


@pytest.mark.parametrize(
    "tool_name",
    ["mcp__github__pull_request_read", "mcp__claude_ai_Google_Drive__search_files"],
)
def test_is_side_effecting_cli_exits_ten_for_reads(tool_name: str) -> None:
    # The three PreToolUse hooks consume this exit code: 10 admits, 0 gates, other fails.
    assert policy.main(["is-side-effecting", tool_name]) == 10


def test_is_side_effecting_cli_exits_zero_for_mutators() -> None:
    assert policy.main(["is-side-effecting", "mcp__github__issue_write"]) == 0
    assert policy.main(["is-side-effecting", "mcp__claude_ai_Gmail__send_message"]) == 0
