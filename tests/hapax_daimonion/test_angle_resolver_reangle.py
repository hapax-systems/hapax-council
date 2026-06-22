"""Re-angle-then-exhaust: a dead-end topic is traversed from reframed angles before refusal.

The researcher pivot (the "then pivot" half of the reframe): when ``recruit_source_set``'s
first pass yields 0 sources, it does NOT one-shot-refuse — it re-frames the SAME matter via
LLM-generated alternative queries and re-gathers, accumulating until density is recovered or
the generated angles are spent. Only then does the existing honest refusal fire, now as
EXHAUSTION rather than first-miss. "Free to traverse, never free to collapse." Self-contained.
"""

from __future__ import annotations

from agents.hapax_daimonion import angle_resolver
from shared.source_packet import SourcePacket


def _p(ref: str, content_hash: str) -> SourcePacket:
    return SourcePacket(
        source_ref=ref, content_hash=content_hash, snippet=f"s {ref}", freshness="fresh"
    )


def test_reangle_traverses_when_first_pass_is_a_dead_end(monkeypatch) -> None:
    gathered = {
        "orig topic": [],
        "alt query": [_p("vault:a", "h0"), _p("vault:b", "h1"), _p("vault:c", "h2")],
    }
    monkeypatch.setattr(angle_resolver, "_gather_sources", lambda t, **k: list(gathered.get(t, [])))
    monkeypatch.setattr(angle_resolver, "_tavily_packets", lambda *a, **k: [])
    monkeypatch.setattr(
        angle_resolver, "_reangle_queries", lambda topic, packets, *, limit: ["alt query"]
    )
    s = angle_resolver.recruit_source_set("orig topic", use_web=False)
    assert s is not None  # the dead end was recovered by traversing a reframed angle
    assert {p.source_ref for p in s.packets} >= {"vault:a", "vault:b", "vault:c"}


def test_honest_exhaustion_after_reangles_returns_none(monkeypatch) -> None:
    calls = {"reangle": 0}

    def _re(topic, packets, *, limit):
        calls["reangle"] += 1
        return ["alt1", "alt2"]

    monkeypatch.setattr(angle_resolver, "_gather_sources", lambda t, **k: [])
    monkeypatch.setattr(angle_resolver, "_tavily_packets", lambda *a, **k: [])
    monkeypatch.setattr(angle_resolver, "_reangle_queries", _re)
    # First pass + every re-angle dry → None, but only AFTER traversal (not a first-miss).
    assert angle_resolver.recruit_source_set("dry topic", use_web=False) is None
    assert calls["reangle"] == 1


def test_no_reangle_when_first_pass_is_grounded(monkeypatch) -> None:
    grounded = [_p("vault:0", "h0"), _p("vault:1", "h1")]
    monkeypatch.setattr(angle_resolver, "_gather_sources", lambda t, **k: list(grounded))

    def _boom(*a, **k):  # pragma: no cover - must not run
        raise AssertionError("re-angle must not run when the first pass already grounded the topic")

    monkeypatch.setattr(angle_resolver, "_reangle_queries", _boom)
    s = angle_resolver.recruit_source_set("grounded topic", use_web=False)
    assert s is not None and len(s.packets) == 2  # no wasted pivot / LLM call


def test_reangle_stops_once_density_is_recovered(monkeypatch) -> None:
    gathered = {
        "t": [],
        "a1": [_p("v:0", "h0"), _p("v:1", "h1"), _p("v:2", "h2")],  # hits MIN_SOURCES_FOR_ANGLE=3
        "a2": [_p("v:3", "h3")],
    }
    queried: list[str] = []

    def _gather(t, **k):
        queried.append(t)
        return list(gathered.get(t, []))

    monkeypatch.setattr(angle_resolver, "_gather_sources", _gather)
    monkeypatch.setattr(angle_resolver, "_tavily_packets", lambda *a, **k: [])
    monkeypatch.setattr(
        angle_resolver, "_reangle_queries", lambda topic, packets, *, limit: ["a1", "a2"]
    )
    s = angle_resolver.recruit_source_set("t", use_web=False)
    assert s is not None
    assert "a1" in queried and "a2" not in queried  # stopped after density recovered


def test_reangle_queries_fail_soft_to_empty(monkeypatch) -> None:
    import litellm

    def _boom(*a, **k):
        raise RuntimeError("gateway down")

    monkeypatch.setattr(litellm, "completion", _boom)
    assert angle_resolver._reangle_queries("a topic", [], limit=2) == []


def test_reangle_queries_parses_lines_and_drops_topic_echo(monkeypatch) -> None:
    import litellm

    class _Msg:
        content = "- alt one\nalt two\nthe topic\n\n"

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    monkeypatch.setattr(litellm, "completion", lambda *a, **k: _Resp())
    out = angle_resolver._reangle_queries("the topic", [], limit=3)
    assert out == ["alt one", "alt two"]  # bullet stripped, blank dropped, topic-echo dropped
