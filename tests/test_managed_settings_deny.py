"""Tests for shared.managed_settings_deny — the deny-only, add-only managed-settings list.

The deny file lives in the repository, which the sessions it restricts can edit. The code that
installs it therefore accepts only MCP deny entries (never allow rules or other keys) and only
ever adds to what is installed: a tampered or shortened file can narrow, never widen. Removing an
entry is a deliberate root act outside this code.
"""

from __future__ import annotations

import json
from pathlib import Path

from shared import managed_settings_deny as msd

REPO_FILE = (
    Path(__file__).resolve().parents[1]
    / "config/claude-code-managed-settings-communication-pathway.json"
)


def _text(deny: list[str], **extra: object) -> str:
    return json.dumps({"permissions": {"deny": deny}, **extra})


# The repository's deny file ---------------------------------------------------------------------


def test_repo_deny_file_is_valid():
    assert msd.validate(json.loads(REPO_FILE.read_text(encoding="utf-8"))) == []


def test_repo_deny_file_covers_the_known_send_tools():
    deny = set(json.loads(REPO_FILE.read_text(encoding="utf-8"))["permissions"]["deny"])
    for tool in (
        "mcp__claude_ai_Gmail__send_message",
        "mcp__claude_ai_Gmail__reply",
        "mcp__claude_ai_Gmail__forward",
        "mcp__claude_ai_Google_Calendar__create_event",
        "mcp__claude_ai_Google_Drive__share_file",
        "mcp__github__create_pull_request",
        "mcp__github__add_issue_comment",
        "mcp__claude-in-chrome",
        "mcp__playwright",
    ):
        assert tool in deny, tool


def test_repo_deny_file_leaves_drafts_and_reads_available():
    deny = set(json.loads(REPO_FILE.read_text(encoding="utf-8"))["permissions"]["deny"])
    assert "mcp__claude_ai_Gmail__create_draft" not in deny
    assert "mcp__claude_ai_Gmail" not in deny
    assert "mcp__github__get_file_contents" not in deny


# Validation: deny-only --------------------------------------------------------------------------


def test_allow_rules_are_rejected():
    errors = msd.validate({"permissions": {"deny": ["mcp__x"], "allow": ["mcp__y"]}})
    assert errors and "permissions" in errors[0]


def test_extra_top_level_keys_are_rejected():
    assert msd.validate({"permissions": {"deny": ["mcp__x"]}, "defaultMode": "bypassPermissions"})


def test_non_mcp_entries_are_rejected():
    assert msd.validate({"permissions": {"deny": ["Bash(rm *)"]}})


def test_non_string_or_empty_entries_are_rejected():
    assert msd.validate({"permissions": {"deny": [""]}})
    assert msd.validate({"permissions": {"deny": [1]}})


def test_well_formed_server_and_tool_entries_are_accepted():
    assert (
        msd.validate({"permissions": {"deny": ["mcp__playwright", "mcp__github__push_files"]}})
        == []
    )


# Merge: add-only --------------------------------------------------------------------------------


def test_merge_keeps_entries_the_candidate_dropped():
    assert msd.merge_monotonic(["mcp__a", "mcp__b"], ["mcp__a"]) == ["mcp__a", "mcp__b"]


def test_merge_adds_new_entries_sorted_and_deduplicated():
    assert msd.merge_monotonic(["mcp__b"], ["mcp__a", "mcp__a"]) == ["mcp__a", "mcp__b"]


def test_render_is_deterministic():
    assert msd.render(["mcp__b", "mcp__a"]) == msd.render(["mcp__a", "mcp__b", "mcp__a"])
    assert json.loads(msd.render(["mcp__a"])) == {"permissions": {"deny": ["mcp__a"]}}


# Plan: what the installer would write ----------------------------------------------------------


def test_plan_first_install_writes_the_candidate():
    result = msd.plan(None, _text(["mcp__a"]))
    assert result.errors == []
    assert json.loads(result.write_text) == {"permissions": {"deny": ["mcp__a"]}}


def test_plan_invalid_candidate_writes_nothing():
    result = msd.plan(msd.render(["mcp__a"]), _text(["mcp__a"], defaultMode="bypassPermissions"))
    assert result.errors
    assert result.write_text is None


def test_plan_malformed_candidate_writes_nothing():
    result = msd.plan(msd.render(["mcp__a"]), "{not json")
    assert result.errors
    assert result.write_text is None


def test_plan_shortened_candidate_keeps_installed_and_reports_the_removal_request():
    result = msd.plan(msd.render(["mcp__a", "mcp__b"]), _text(["mcp__a"]))
    assert result.write_text is None
    assert result.removal_requests == ["mcp__b"]


def test_plan_unchanged_candidate_writes_nothing():
    result = msd.plan(msd.render(["mcp__a"]), _text(["mcp__a"]))
    assert result.write_text is None
    assert result.errors == []


def test_plan_refuses_when_installed_file_is_invalid():
    result = msd.plan('{"permissions": {"allow": ["mcp__a"]}}', _text(["mcp__a"]))
    assert result.errors
    assert result.write_text is None
