"""Detect development phases from tool call sequences."""
from __future__ import annotations

_EXPLORE_TOOLS = {"Read", "Grep", "Glob", "LS"}
_IMPLEMENT_TOOLS = {"Edit", "Write", "MultiEdit"}
_AGENT_TOOLS = {"Agent"}
_WINDOW_SIZE = 6


def _classify_window(tools: list[str]) -> str | None:
    """Classify a window of tool calls into a phase."""
    if not tools:
        return None

    names = [t.split(":")[0] for t in tools]
    bash_args = [t.split(":", 1)[1] if ":" in t else "" for t in tools]

    explore_ratio = sum(1 for n in names if n in _EXPLORE_TOOLS) / len(names)
    implement_ratio = sum(1 for n in names if n in _IMPLEMENT_TOOLS) / len(names)
    bash_count = sum(1 for n in names if n == "Bash")
    agent_count = sum(1 for n in names if n in _AGENT_TOOLS)
    test_indicators = sum(
        1 for a in bash_args if any(k in a.lower() for k in ("pytest", "test", "uv run"))
    )

    # Debug: detect edit→bash(fail)→read→edit cycles
    if implement_ratio > 0.2 and bash_count >= 2:
        edit_bash_cycles = 0
        for i in range(len(names) - 1):
            if names[i] in _IMPLEMENT_TOOLS and names[i + 1] == "Bash":
                edit_bash_cycles += 1
        if edit_bash_cycles >= 2:
            return "debug"

    if agent_count >= len(names) * 0.4:
        return "design"
    if implement_ratio >= 0.6:
        return "implement"
    if test_indicators >= 1 and bash_count >= 1:
        return "test"
    if implement_ratio >= 0.4:
        return "implement"
    if explore_ratio >= 0.5:
        return "explore"
    if sum(1 for n in names if n == "Read") >= len(names) * 0.7:
        return "review"

    return None


def detect_phases(tools: list[str]) -> list[str]:
    """Detect all phases present in a tool sequence."""
    phases: set[str] = set()
    for i in range(0, len(tools), _WINDOW_SIZE // 2):
        window = tools[i:i + _WINDOW_SIZE]
        if not window:
            break
        phase = _classify_window(window)
        if phase:
            phases.add(phase)
    return sorted(phases)


def detect_phase_sequence(tools: list[str]) -> str:
    """Detect the ordered sequence of phases in a tool call list.

    Returns a string like 'explore>implement>test>debug'.
    """
    if not tools:
        return ""

    sequence: list[str] = []
    prev_phase: str | None = None

    for i in range(0, len(tools), _WINDOW_SIZE // 2):
        window = tools[i:i + _WINDOW_SIZE]
        if not window:
            break
        phase = _classify_window(window)
        if phase and phase != prev_phase:
            sequence.append(phase)
            prev_phase = phase

    return ">".join(sequence)
