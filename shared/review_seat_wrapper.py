"""Common parts of the read-only substitute reviewer wrappers (muse, vibe, local).

Each wrapper reads the dispatcher's reviewer prompt on stdin and prints the reviewer's reply
on stdout. The dispatcher parses that reply's yaml fence and owns the verdict.

When a wrapper refuses to run a seat, it prints a line containing ``UNSUPPORTED_CLIENT`` and
exits nonzero. That is the process-level signal ``review_team.is_reviewer_route_unavailable``
reads, so a refusal is classified as the route's outage. It is never read as the model's
output, and never as a vote.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROUTE_UNAVAILABLE_EXIT = 69

SEAT_PREAMBLE = """You are a blind reviewer seat invoked non-interactively. Review ONLY the text below.
Do not use tools, read files, browse, or narrate your process; reason silently.
Your entire reply must be exactly one fenced yaml code block that follows the output contract
at the end of the text, and nothing else. A verdict that contradicts your own findings (for
example accept alongside a critical finding) is wrong: a critical finding requires block."""


def render_seat_prompt(prompt: str) -> str:
    return f"{SEAT_PREAMBLE}\n\n{prompt.strip()}\n"


def reviewer_prompt_measurement(
    command: list[str], prompt: str, *, repo_root: Path
) -> dict[str, int]:
    """Count UTF-8 text at the declared wrapper boundary without invoking a reviewer.

    Use the wrappers' own renderers/constants. Unknown commands have no size proof.
    Provider/CLI hidden scaffolding is outside this measured text boundary. Claude's
    possible correction turn is reserved before its first invocation.
    """
    rendered = len(prompt.encode("utf-8"))
    retry = 0
    if command == ["codex", "exec", "--sandbox", "read-only", "-"]:
        wrapped = rendered
    else:
        if not command:
            raise ValueError("reviewer command missing prompt measurement")
        path = (repo_root / command[0]).resolve()
        name = path.name
        known = {
            "hapax-agy-reviewer",
            "hapax-claude-reviewer",
            "hapax-glmcp-reviewer",
            "hapax-muse-reviewer",
            "hapax-vibe-reviewer",
            "hapax-local-reviewer",
        }
        if name not in known or path != (repo_root / "scripts" / name).resolve():
            raise ValueError(f"reviewer command lacks prompt measurement: {command[0]}")
        # All registered wrappers expose their pure construction without executing main.
        wrapper = runpy.run_path(str(path))
        if name == "hapax-agy-reviewer":
            parts = [wrapper["render_review_dossier"](prompt), wrapper["PRINT_PROMPT"]]
        elif name == "hapax-claude-reviewer":
            parts = [wrapper["STRICT_REVIEW_SYSTEM_PROMPT"], prompt]
            retry = len(wrapper["REASK_CORRECTION"].encode("utf-8"))
        elif name == "hapax-glmcp-reviewer":
            parts = [wrapper["SYSTEM_PROMPT"], prompt]
        elif name == "hapax-local-reviewer":
            parts = [
                m["content"] for m in wrapper["request_body"](prompt, "measurement")["messages"]
            ]
        else:
            parts = [render_seat_prompt(prompt)]
        wrapped = sum(len(part.encode("utf-8")) for part in parts)
    return {
        "rendered_prompt_bytes": rendered,
        "wrapped_prompt_bytes": wrapped,
        "retry_reserve_bytes": retry,
        "max_prompt_bytes": wrapped + retry,
    }


def refuse(wrapper: str, reason: str) -> int:
    """Refuse the seat as an outage of this route, with the reason and the next action."""

    print(f"{wrapper}: UNSUPPORTED_CLIENT {reason}", file=sys.stderr)
    return ROUTE_UNAVAILABLE_EXIT
