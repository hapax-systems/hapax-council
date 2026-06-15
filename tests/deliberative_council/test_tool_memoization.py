"""Tests for per-run tool memoization (R4).

cc-task cctv-prompt-caching-quality-neutral-20260607.

``read_source`` / ``grep_evidence`` short-circuit identical sub-calls within ONE
deliberation (a ``tool_memoization_scope``), share one cache across that
deliberation's concurrent member tasks, and stay isolated across scopes /
uncached when no scope is active.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from agents.deliberative_council import tools
from agents.deliberative_council.tools import (
    grep_evidence,
    read_source,
    tool_memoization_scope,
)


class _FakeGrepResult:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout


def _counting_subprocess_run():
    calls = {"n": 0}

    def _run(*_args, **_kwargs):
        calls["n"] += 1
        return _FakeGrepResult("x.py:1:match\n")

    return calls, _run


async def test_grep_evidence_memoized_within_scope() -> None:
    calls, fake_run = _counting_subprocess_run()
    with patch.object(tools.subprocess, "run", side_effect=fake_run):
        with tool_memoization_scope():
            r1 = await grep_evidence(None, "pattern", "agents")
            r2 = await grep_evidence(None, "pattern", "agents")
        # Second identical call short-circuited — grep ran exactly once.
        assert r1 == r2 == "x.py:1:match"
        assert calls["n"] == 1

        # A distinct (pattern, scope) is a cache miss → runs again.
        with tool_memoization_scope():
            await grep_evidence(None, "pattern", "agents")
        assert calls["n"] == 2  # fresh scope, cache reset


async def test_grep_evidence_uncached_without_scope() -> None:
    calls, fake_run = _counting_subprocess_run()
    with patch.object(tools.subprocess, "run", side_effect=fake_run):
        await grep_evidence(None, "p", "s")
        await grep_evidence(None, "p", "s")
    # No active scope → every call hits the expensive op.
    assert calls["n"] == 2


async def test_read_source_memoized_within_scope_isolated_across_scopes(tmp_path) -> None:
    f = tmp_path / "note.md"
    f.write_text("v1", encoding="utf-8")

    with tool_memoization_scope():
        r1 = await read_source(None, str(f))
        f.write_text("v2", encoding="utf-8")  # disk changes mid-scope
        r2 = await read_source(None, str(f))  # served from the per-run cache
    assert r1 == "v1"
    assert r2 == "v1"  # memoized within the deliberation

    with tool_memoization_scope():  # a new deliberation re-reads current disk
        r3 = await read_source(None, str(f))
    assert r3 == "v2"

    # Outside any scope, reads are always fresh.
    r4 = await read_source(None, str(f))
    f.write_text("v3", encoding="utf-8")
    r5 = await read_source(None, str(f))
    assert (r4, r5) == ("v2", "v3")


async def test_memoization_shared_across_gather_member_tasks() -> None:
    # The council fans members out with asyncio.gather; the ContextVar cache is
    # copied into each child task, so concurrent identical sub-calls collapse to
    # one expensive op (grep_evidence has no internal await suspension point).
    calls, fake_run = _counting_subprocess_run()
    with patch.object(tools.subprocess, "run", side_effect=fake_run):
        with tool_memoization_scope():
            results = await asyncio.gather(
                *(grep_evidence(None, "shared", "agents") for _ in range(5))
            )
    assert all(r == "x.py:1:match" for r in results)
    assert calls["n"] == 1
