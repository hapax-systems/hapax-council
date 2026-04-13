"""Tests for agents.studio_compositor.chat_reactor (A5).

Covers the keyword match, cooldown, no-op guard on the current preset,
longest-match resolution for variants, graceful handling of missing
preset files, and the mutation-file write.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.studio_compositor import chat_reactor
from agents.studio_compositor.chat_reactor import PresetReactor, _keyword_for


def _make_preset(preset_dir: Path, name: str) -> dict:
    """Write a minimal preset graph to disk and return its dict."""
    graph = {
        "name": name,
        "nodes": {"root": {"type": "colorgrade", "params": {"brightness": 1.0}}},
        "edges": [],
    }
    (preset_dir / f"{name}.json").write_text(json.dumps(graph))
    return graph


@pytest.fixture
def reactor_env(tmp_path, monkeypatch):
    """Build an isolated PresetReactor environment with fake presets."""
    preset_dir = tmp_path / "presets"
    preset_dir.mkdir()
    _make_preset(preset_dir, "halftone_preset")
    _make_preset(preset_dir, "datamosh")
    _make_preset(preset_dir, "datamosh_heavy")
    _make_preset(preset_dir, "neon")
    _make_preset(preset_dir, "clean")  # excluded by random_mode filter
    _make_preset(preset_dir, "_default_modulations")  # leading-underscore exclusion

    mutation_file = tmp_path / "shm" / "graph-mutation.json"
    fx_current = tmp_path / "shm" / "fx-current.txt"

    # Patch the module-level constants so _read_current_preset uses tmp.
    monkeypatch.setattr(chat_reactor, "FX_CURRENT_FILE", fx_current)
    # Also redirect random_mode.load_preset_graph's PRESET_DIR lookup to tmp.
    from agents.studio_compositor import random_mode

    monkeypatch.setattr(random_mode, "PRESET_DIR", preset_dir)

    reactor = PresetReactor(
        preset_dir=preset_dir,
        mutation_file=mutation_file,
        cooldown=0.0,  # disable cooldown by default; individual tests override
    )
    return reactor, preset_dir, mutation_file, fx_current


# ---------------------------------------------------------------------------
# _keyword_for helper
# ---------------------------------------------------------------------------


def test_keyword_for_strips_preset_suffix():
    assert _keyword_for("halftone_preset") == "halftone"


def test_keyword_for_strips_fx_suffix():
    assert _keyword_for("glitch_fx") == "glitch"


def test_keyword_for_leaves_bare_names():
    assert _keyword_for("datamosh") == "datamosh"


def test_keyword_for_does_not_strip_partial_suffix():
    # "_preset" is a suffix, but only if at the end.
    assert _keyword_for("preset_thing") == "preset_thing"


# ---------------------------------------------------------------------------
# Match: pure keyword lookup
# ---------------------------------------------------------------------------


def test_match_bare_word(reactor_env):
    reactor, *_ = reactor_env
    assert reactor.match("please use halftone") == "halftone_preset"


def test_match_case_insensitive(reactor_env):
    reactor, *_ = reactor_env
    assert reactor.match("NEON plz") == "neon"


def test_match_longest_wins(reactor_env):
    """'datamosh_heavy' must win over 'datamosh' when both could match."""
    reactor, *_ = reactor_env
    assert reactor.match("let's go datamosh heavy") == "datamosh"  # not heavy — it's two words
    assert reactor.match("datamosh_heavy please") == "datamosh_heavy"


def test_match_word_boundary(reactor_env):
    """'neon' must not match 'neonight' or 'pneonatal'."""
    reactor, *_ = reactor_env
    assert reactor.match("this is neonight music") is None
    assert reactor.match("pneonatal vibes") is None
    assert reactor.match("neon vibes") == "neon"


def test_match_ignores_empty(reactor_env):
    reactor, *_ = reactor_env
    assert reactor.match("") is None


def test_match_ignores_unknown(reactor_env):
    reactor, *_ = reactor_env
    assert reactor.match("something else entirely") is None


def test_match_excludes_filtered_presets(reactor_env):
    """'clean' and presets starting with '_' must not be indexable."""
    reactor, *_ = reactor_env
    assert reactor.match("clean up") is None
    assert reactor.match("default_modulations") is None


# ---------------------------------------------------------------------------
# process_message: cooldown + write + no-op + failure guards
# ---------------------------------------------------------------------------


def test_process_message_writes_mutation(reactor_env):
    reactor, preset_dir, mutation_file, _ = reactor_env
    result = reactor.process_message("datamosh please")
    assert result == "datamosh"
    assert mutation_file.exists()
    graph = json.loads(mutation_file.read_text())
    assert graph["name"] == "datamosh"


def test_process_message_no_match_returns_none(reactor_env):
    reactor, _, mutation_file, _ = reactor_env
    assert reactor.process_message("hello world") is None
    assert not mutation_file.exists()


def test_process_message_respects_cooldown(reactor_env, monkeypatch):
    reactor, _, mutation_file, _ = reactor_env
    reactor._cooldown = 60.0
    fake_now = [1000.0]
    monkeypatch.setattr(chat_reactor.time, "monotonic", lambda: fake_now[0])

    # First match within cooldown: writes.
    assert reactor.process_message("neon") == "neon"
    assert mutation_file.exists()
    mutation_file.unlink()

    # Second match 10s later: still within cooldown, no write.
    fake_now[0] = 1010.0
    assert reactor.process_message("datamosh") is None
    assert not mutation_file.exists()

    # Third match 70s after first: cooldown expired, writes again.
    fake_now[0] = 1070.0
    assert reactor.process_message("halftone") == "halftone_preset"
    assert mutation_file.exists()


def test_process_message_skips_when_already_current(reactor_env):
    reactor, _, mutation_file, fx_current = reactor_env
    fx_current.parent.mkdir(parents=True, exist_ok=True)
    fx_current.write_text("neon")  # already on neon

    result = reactor.process_message("switch to neon please")

    assert result is None
    assert not mutation_file.exists()


def test_process_message_no_op_does_not_consume_cooldown(reactor_env, monkeypatch):
    """No-op on current preset must NOT start the cooldown timer.

    Otherwise chat spam on the active preset would lock out legitimate
    switches for 30s for no reason.
    """
    reactor, _, mutation_file, fx_current = reactor_env
    reactor._cooldown = 30.0
    fake_now = [2000.0]
    monkeypatch.setattr(chat_reactor.time, "monotonic", lambda: fake_now[0])
    fx_current.parent.mkdir(parents=True, exist_ok=True)
    fx_current.write_text("neon")

    # Spam chat about the current preset — no cooldown should accumulate.
    for _ in range(5):
        assert reactor.process_message("neon neon neon") is None
        fake_now[0] += 1.0

    # Immediately request a different preset — must succeed (cooldown unarmed).
    fx_current.write_text("neon")  # still on neon
    assert reactor.process_message("datamosh go") == "datamosh"
    assert mutation_file.exists()


def test_process_message_handles_missing_preset_file(reactor_env):
    """A match whose preset file was deleted mid-session must fail gracefully."""
    reactor, preset_dir, mutation_file, _ = reactor_env
    (preset_dir / "datamosh.json").unlink()

    result = reactor.process_message("datamosh please")

    assert result is None
    assert not mutation_file.exists()


def test_process_message_creates_mutation_parent(reactor_env):
    """The runner must mkdir parents if the SHM dir doesn't exist yet."""
    reactor, _, mutation_file, _ = reactor_env
    assert not mutation_file.parent.exists()
    reactor.process_message("datamosh")
    assert mutation_file.exists()


def test_process_message_does_not_log_author_or_text(reactor_env, caplog):
    """Consent guardrail: the log line must not contain message or author text."""
    reactor, *_ = reactor_env
    with caplog.at_level("INFO", logger="agents.studio_compositor.chat_reactor"):
        reactor.process_message("datamosh — from @alice the viewer")

    matching = [r for r in caplog.records if "preset switch" in r.message]
    assert len(matching) == 1
    msg = matching[0].message
    assert "datamosh" in msg
    assert "alice" not in msg.lower()
    assert "viewer" not in msg
