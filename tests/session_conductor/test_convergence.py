"""Tests for the research convergence and finding persistence rule."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from agents.session_conductor.rules import HookEvent
from agents.session_conductor.rules.convergence import (
    ConvergenceRule,
    count_findings,
    extract_topic_slug,
)
from agents.session_conductor.state import TopicState
from agents.session_conductor.topology import TopologyConfig


def _make_agent_event(prompt: str, session_id: str = "sess-1") -> HookEvent:
    return HookEvent(
        event_type="pre_tool_use",
        tool_name="Agent",
        tool_input={"prompt": prompt},
        session_id=session_id,
        user_message=None,
    )


def _make_agent_post_event(prompt: str, output: str, session_id: str = "sess-1") -> HookEvent:
    return HookEvent(
        event_type="post_tool_use",
        tool_name="Agent",
        tool_input={"prompt": prompt},
        session_id=session_id,
        user_message=output,
    )


def test_extract_topic_slug_basic():
    slug = extract_topic_slug("research all compositor effects in the pipeline")
    assert slug != ""
    words = slug.split("-")
    assert all(w.isalpha() or w.isdigit() for w in words)
    assert len(words) <= 3


def test_extract_topic_slug_strips_stop_words():
    slug = extract_topic_slug("the quick brown fox")
    # stop words like 'the' should be excluded
    assert "the" not in slug.split("-")


def test_count_findings_with_bullets():
    text = "- finding one\n- finding two\n- finding three"
    assert count_findings(text) == 3


def test_count_findings_with_numbered():
    text = "1. First item\n2. Second item"
    assert count_findings(text) == 2


def test_count_findings_empty():
    assert count_findings("") == 0
    assert count_findings("no findings here") == 0


def test_tracks_new_topic(tmp_path: Path):
    topology = TopologyConfig()
    rule = ConvergenceRule(topology, context_dir=tmp_path)
    event = _make_agent_event("research all compositor effects touch points")
    resp = rule.on_pre_tool_use(event)
    # New topic: should allow (None or allow)
    assert resp is None or resp.action in ("allow", "rewrite")


def test_blocks_when_converging(tmp_path: Path):
    topology = TopologyConfig()
    rule = ConvergenceRule(topology, context_dir=tmp_path)
    # Pre-populate with a converging topic
    slug = "compositor-effects"
    topic = TopicState(
        slug=slug,
        rounds=3,
        findings_per_round=[10, 1, 1],
        first_seen=datetime(2026, 3, 27),
        prior_file=tmp_path / f"{slug}.md",
    )
    rule._session_topics[slug] = topic
    event = _make_agent_event("research compositor effects in depth")
    resp = rule.on_pre_tool_use(event)
    assert resp is not None
    assert resp.action == "block"


def test_blocks_at_hard_cap(tmp_path: Path):
    topology = TopologyConfig()
    rule = ConvergenceRule(topology, context_dir=tmp_path)
    slug = "voxtral-tts"
    topic = TopicState(
        slug=slug,
        rounds=5,
        findings_per_round=[10, 8, 6, 4, 2],
        first_seen=datetime(2026, 3, 27),
        prior_file=tmp_path / f"{slug}.md",
    )
    rule._session_topics[slug] = topic
    event = _make_agent_event("research voxtral tts migration approach")
    resp = rule.on_pre_tool_use(event)
    assert resp is not None
    assert resp.action == "block"


def test_injects_prior_findings(tmp_path: Path):
    topology = TopologyConfig()
    rule = ConvergenceRule(topology, context_dir=tmp_path)
    slug = "voxtral-tts"
    prior_file = tmp_path / f"{slug}.md"
    prior_file.write_text("- finding one\n- finding two\n")
    topic = TopicState(
        slug=slug,
        rounds=2,
        findings_per_round=[5, 3],
        first_seen=datetime(2026, 3, 27),
        prior_file=prior_file,
    )
    rule._session_topics[slug] = topic
    event = _make_agent_event("research voxtral tts migration approach")
    resp = rule.on_pre_tool_use(event)
    # Should rewrite with injected prior findings
    assert resp is not None
    assert resp.action == "rewrite"
    rewritten_prompt = resp.rewrite.get("prompt", "")
    assert "finding one" in rewritten_prompt or "Prior findings" in rewritten_prompt


def test_persists_findings(tmp_path: Path):
    topology = TopologyConfig()
    rule = ConvergenceRule(topology, context_dir=tmp_path)
    post_event = _make_agent_post_event(
        "research voxtral tts migration",
        "- finding one\n- finding two\n- finding three\n",
    )
    rule.on_post_tool_use(post_event)
    # Should have created a context file
    files = list(tmp_path.iterdir())
    assert len(files) >= 1


def test_allows_non_agent_tools(tmp_path: Path):
    topology = TopologyConfig()
    rule = ConvergenceRule(topology, context_dir=tmp_path)
    event = HookEvent(
        event_type="pre_tool_use",
        tool_name="Read",
        tool_input={"file_path": "/tmp/foo.py"},
        session_id="sess-1",
        user_message=None,
    )
    resp = rule.on_pre_tool_use(event)
    assert resp is None
