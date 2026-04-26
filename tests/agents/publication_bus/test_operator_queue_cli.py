"""Tests for ``agents.publication_bus.__main__`` CLI surfacing the
operator-action queue from wire_status.
"""

from __future__ import annotations

from agents.publication_bus.__main__ import main, render_operator_queue


def test_render_includes_summary_line():
    text = render_operator_queue()
    assert "WIRED:" in text
    assert "CRED_BLOCKED:" in text
    assert "DELETE:" in text


def test_render_includes_pass_insert_commands():
    text = render_operator_queue()
    assert "pass insert" in text


def test_render_includes_known_surface():
    text = render_operator_queue()
    # bluesky-atproto-multi-identity is one of the CRED_BLOCKED surfaces;
    # its slug must appear in the queue rendering
    assert "bluesky-atproto-multi-identity" in text


def test_keys_only_mode_prints_one_per_line(capsys):
    rc = main(["--keys-only"])
    assert rc == 0
    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line.strip()]
    # Each line is a pass key like "bluesky/operator-app-password"
    assert all("/" in line for line in lines)


def test_default_mode_prints_full_report(capsys):
    rc = main([])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Publication-bus wire-status" in captured.out
