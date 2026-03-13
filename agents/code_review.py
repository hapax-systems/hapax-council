"""code_review.py — LLM-powered code review agent.

Accepts a diff, file path, or piped input and produces structured review feedback.

Usage:
    git diff | uv run python -m agents.code_review
    git diff --staged | uv run python -m agents.code_review
    uv run python -m agents.code_review path/to/file.py
    uv run python -m agents.code_review --diff "$(git diff HEAD~1)"
"""

import asyncio
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("code_review")

from pydantic_ai import Agent

from shared.config import get_model
from shared.operator import get_system_prompt_fragment

try:
    from shared import langfuse_config  # noqa: F401
except ImportError:
    pass

from opentelemetry import trace

_tracer = trace.get_tracer(__name__)


@dataclass
class ReviewDeps:
    """Review context passed to the agent."""

    filename: str = "stdin"


SYSTEM_PROMPT = (
    get_system_prompt_fragment("code-review")
    + "\nCall lookup_constraints() for additional operator constraints.\n"
    + """\
You are a senior code reviewer. Analyze the provided code or diff and give actionable feedback.

Structure your review as:

**Summary**: One-line assessment (e.g., "Clean refactor with one potential issue")

**Issues** (if any):
- [severity: high/medium/low] Description of issue, with specific line references if available

**Suggestions** (if any):
- Concrete improvements, not style nitpicks

Focus on correctness, security, and maintainability — in that order.
Don't comment on formatting or style unless it hides a bug.
If the code looks good, say so briefly. Don't manufacture issues.
For diffs, focus on the changed lines, not surrounding context."""
)


def _make_agent(model_alias: str) -> Agent:
    a = Agent(get_model(model_alias), deps_type=ReviewDeps, system_prompt=SYSTEM_PROMPT)
    from shared.context_tools import get_context_tools

    for _tool_fn in get_context_tools():
        a.tool(_tool_fn)
    from shared.axiom_tools import get_axiom_tools

    for _tool_fn in get_axiom_tools():
        a.tool(_tool_fn)
    return a


agent = _make_agent("balanced")


async def review(code: str, filename: str = "stdin") -> str:
    """Run a code review and return the response."""
    with _tracer.start_as_current_span(
        "code_review.review",
        attributes={"review.filename": filename},
    ):
        deps = ReviewDeps(filename=filename)

        if filename != "stdin":
            prompt = f"Review this file (`{filename}`):\n\n```\n{code}\n```"
        else:
            prompt = f"Review this diff:\n\n```diff\n{code}\n```"

        try:
            result = await agent.run(prompt, deps=deps)
        except Exception as exc:
            log.error("LLM code review failed: %s", exc)
            return f"Code review failed: {exc}"
        return result.output


async def main():
    with _tracer.start_as_current_span(
        "code_review.run",
        attributes={"agent.name": "code_review", "agent.repo": "hapax-council"},
    ):
        return await _main_impl()


async def _main_impl():
    """Implementation of main, wrapped by OTel span."""
    import argparse

    parser = argparse.ArgumentParser(description="LLM code review agent")
    parser.add_argument("path", nargs="?", help="File path to review")
    parser.add_argument("--diff", help="Pass a diff string directly")
    parser.add_argument("--model", default="balanced", help="Model alias (default: balanced)")
    args = parser.parse_args()

    # Override model if specified
    if args.model != "balanced":
        global agent
        agent = _make_agent(args.model)

    if args.diff:
        code = args.diff
        filename = "stdin"
    elif args.path:
        path = Path(args.path)
        if not path.is_file():
            print(f"Error: {path} is not a file", file=sys.stderr)
            sys.exit(1)
        code = path.read_text()
        filename = str(path)
    elif not sys.stdin.isatty():
        code = sys.stdin.read()
        filename = "stdin"
    else:
        parser.print_help()
        sys.exit(1)

    if not code.strip():
        print("No input to review.", file=sys.stderr)
        sys.exit(0)

    output = await review(code, filename)
    print(output)


if __name__ == "__main__":
    asyncio.run(main())
