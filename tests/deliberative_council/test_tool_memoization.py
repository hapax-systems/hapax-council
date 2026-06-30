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
from agents.deliberative_council.capability_admission import CapabilityAdmissionReceipt
from agents.deliberative_council.tools import (
    grep_evidence,
    qdrant_lookup,
    read_source,
    tool_memoization_scope,
    web_verify,
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


async def test_nested_scope_reuses_outer_cache() -> None:
    # Per-segment carryover: the OUTER scope (one segment's whole multi-pass prep)
    # must survive across the INNER per-deliberate() scopes, so research done in an
    # early pass is not re-paid in a later pass. Only the outermost scope owns the cache.
    calls, fake_run = _counting_subprocess_run()
    with patch.object(tools.subprocess, "run", side_effect=fake_run):
        with tool_memoization_scope():  # outer = per-segment
            await grep_evidence(None, "p", "s")
            with tool_memoization_scope():  # inner = one deliberate() run — reuses outer
                await grep_evidence(None, "p", "s")  # cache hit across the inner scope
            await grep_evidence(None, "p", "s")  # still the same cache after inner exits
    assert calls["n"] == 1  # one expensive op across the whole segment's passes


class _FakeWebOut:
    output = "external evidence summary"


def _admitted_web_verify() -> CapabilityAdmissionReceipt:
    return CapabilityAdmissionReceipt(
        receipt_id="cctv-test-web-verify",
        receipt_ref="cctv-capability-admission:cctv-test-web-verify",
        capability_id="cctv.tool.web_verify",
        route_id="litellm.perplexity.web-research",
        provider="perplexity",
        capacity_pool="api_paid_spend",
        admission_action="admitted",
        admitted=True,
        reason_codes=("test_admitted",),
        receipt_refs=("cctv-capability-admission:cctv-test-web-verify",),
    )


def _refused_qdrant_lookup() -> CapabilityAdmissionReceipt:
    return CapabilityAdmissionReceipt(
        receipt_id="cctv-test-qdrant-lookup",
        receipt_ref="cctv-capability-admission:cctv-test-qdrant-lookup",
        capability_id="cctv.tool.qdrant_lookup",
        route_id="local_tool.local.worker",
        provider="local",
        capacity_pool="local_compute",
        admission_action="refused",
        admitted=False,
        reason_codes=("local_resource_state:red",),
        receipt_refs=("cctv-capability-admission:cctv-test-qdrant-lookup",),
    )


def _counting_web_agent():
    calls = {"n": 0}

    class _FakeAgent:
        def __init__(self, *_a, **_k) -> None:
            pass

        async def run(self, *_a, **_k):
            calls["n"] += 1
            return _FakeWebOut()

    return calls, _FakeAgent


async def test_web_verify_memoized_within_scope() -> None:
    # web_verify is the dominant research cost (a 45s-bounded nested web agent). An
    # identical query asked twice within a deliberation/segment must short-circuit so the
    # same evidence is not re-fetched (and a slow/dead query is not re-paid).
    calls, fake_agent = _counting_web_agent()
    with (
        patch("agents.deliberative_council.tools.admit_tool", return_value=_admitted_web_verify()),
        patch("pydantic_ai.Agent", fake_agent),
        patch("shared.config.get_model", return_value="dummy-model"),
    ):
        with tool_memoization_scope():
            r1 = await web_verify(None, "is the launch-team paradox real?")
            r2 = await web_verify(None, "is the launch-team paradox real?")
        assert r1 == r2
        assert r1.endswith("external evidence summary")
        assert calls["n"] == 1  # the second identical query short-circuited
        # A distinct query is a cache miss; a fresh scope (new segment) re-pays.
        with tool_memoization_scope():
            await web_verify(None, "is the launch-team paradox real?")
        assert calls["n"] == 2


async def test_web_verify_uncached_without_scope() -> None:
    calls, fake_agent = _counting_web_agent()
    with (
        patch("agents.deliberative_council.tools.admit_tool", return_value=_admitted_web_verify()),
        patch("pydantic_ai.Agent", fake_agent),
        patch("shared.config.get_model", return_value="dummy-model"),
    ):
        await web_verify(None, "q")
        await web_verify(None, "q")
    assert calls["n"] == 2  # no active scope → every call hits the web agent


async def test_qdrant_refused_admission_memoized_within_scope() -> None:
    refused = _refused_qdrant_lookup()
    with patch("agents.deliberative_council.tools.admit_tool", return_value=refused) as admit:
        with tool_memoization_scope():
            r1 = await qdrant_lookup(None, "same query")
            r2 = await qdrant_lookup(None, "same query")

    assert r1 == r2
    assert "refused before local embedding/resource invocation" in r1
    assert admit.call_count == 1


async def test_web_verify_timeout_memoized_within_scope() -> None:
    # The dominant budget sink: an identical query that times out (45s) must NOT be
    # re-paid within the segment's scope. The per-segment window is short, so a dead/slow
    # query stays dead for that window; it is re-checked on the next segment's fresh scope.
    calls = {"n": 0}

    class _SlowAgent:
        def __init__(self, *_a, **_k) -> None:
            pass

        async def run(self, *_a, **_k):
            calls["n"] += 1
            await asyncio.sleep(0.2)
            return _FakeWebOut()

    with (
        patch("agents.deliberative_council.tools.admit_tool", return_value=_admitted_web_verify()),
        patch("pydantic_ai.Agent", _SlowAgent),
        patch("shared.config.get_model", return_value="dummy-model"),
        patch.object(tools, "_WEB_VERIFY_TIMEOUT_S", 0.01),
    ):
        with tool_memoization_scope():
            r1 = await web_verify(None, "dead query")
            r2 = await web_verify(None, "dead query")
        assert "timed out" in r1
        assert r1 == r2
        assert calls["n"] == 1  # the 45s timeout is paid once, not re-paid on retry
