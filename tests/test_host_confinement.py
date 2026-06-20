"""Tests for the no-dev-on-podium confinement decision core.

The dev→appendix migration confines dev/SDLC EXECUTION to appendix; podium is the
production rig + the operator's interactive thin client. The enforcement
discriminates a LEAKED dispatched lane (one whose dispatch_host says it belongs
elsewhere but is executing here) from the operator's interactive thin-client work
(no dispatch context) and the sanctioned P0 local fallback (dispatch_host=local).
Only a leaked lane's dev mutations are blocked.
"""

from __future__ import annotations

from shared.host_confinement import decide_block

PODIUM = "hapax-podium"
APPENDIX = "hapax-appendix"


def test_leaked_lane_on_podium_is_blocked() -> None:
    block, reason = decide_block(
        current_host=PODIUM, dispatch_host="hapax-appendix", tool_name="Write"
    )
    assert block is True
    assert "leak" in reason.lower() or "dispatch" in reason.lower()


def test_interactive_session_on_podium_is_allowed() -> None:
    # No dispatch context == operator thin-client; must remain free on podium.
    block, _ = decide_block(current_host=PODIUM, dispatch_host=None, tool_name="Write")
    assert block is False


def test_lane_correctly_on_its_host_is_allowed() -> None:
    block, _ = decide_block(
        current_host=APPENDIX, dispatch_host="hapax-appendix", tool_name="Write"
    )
    assert block is False


def test_sanctioned_local_fallback_is_allowed() -> None:
    # The narrowed P0 codex drain fallback runs dispatch_host=local deliberately.
    block, _ = decide_block(current_host=PODIUM, dispatch_host="local", tool_name="Write")
    assert block is False


def test_non_mutation_tool_is_allowed() -> None:
    for tool in ("Read", "Bash", "Grep", "Glob"):
        block, _ = decide_block(current_host=PODIUM, dispatch_host="hapax-appendix", tool_name=tool)
        assert block is False, tool


def test_short_dispatch_alias_normalizes() -> None:
    # 'appendix' short form must equal 'hapax-appendix'.
    block, _ = decide_block(current_host=PODIUM, dispatch_host="appendix", tool_name="Edit")
    assert block is True
    # A lane dispatched to 'podium' while on podium is NOT a leak.
    block2, _ = decide_block(current_host=PODIUM, dispatch_host="podium", tool_name="Edit")
    assert block2 is False


def test_all_mutation_tools_blocked_for_leaked_lane() -> None:
    for tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        block, _ = decide_block(current_host=PODIUM, dispatch_host="appendix", tool_name=tool)
        assert block is True, tool
