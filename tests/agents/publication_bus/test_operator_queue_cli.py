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


def test_check_creds_mode_lists_per_key(capsys, monkeypatch):
    # Stub `pass` lookup to deterministic results without touching the
    # operator's actual pass-store.
    from agents.publication_bus import __main__ as m

    def fake_present(key: str) -> bool:
        # bluesky app-password "arrived"; everything else still missing
        # (test uses an in-the-list key — zenodo/api-token was removed
        # from cred_blocked_pass_keys when refusal_brief_publisher
        # flipped to WIRED in #1672)
        return key == "bluesky/operator-app-password"

    monkeypatch.setattr(m, "_key_present_in_pass", fake_present)
    rc = m.main(["--check-creds"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "PRESENT:   1" in captured.out
    assert "Ready-to-wire" in captured.out
    assert "+ bluesky/operator-app-password" in captured.out
    assert "Still cred-blocked" in captured.out
    assert "- bluesky/operator-did" in captured.out


def test_check_creds_all_missing_renders_correctly(capsys, monkeypatch):
    from agents.publication_bus import __main__ as m

    monkeypatch.setattr(m, "_key_present_in_pass", lambda _k: False)
    rc = m.main(["--check-creds"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "PRESENT:   0" in captured.out
    assert "MISSING:" in captured.out
    assert "Ready-to-wire" not in captured.out  # no PRESENT block
    assert "Run scripts/bootstrap_cred_tokens.py" in captured.out


def test_check_creds_all_present_renders_correctly(capsys, monkeypatch):
    from agents.publication_bus import __main__ as m

    monkeypatch.setattr(m, "_key_present_in_pass", lambda _k: True)
    rc = m.main(["--check-creds"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "MISSING:   0" in captured.out
    assert "Ready-to-wire" in captured.out
    assert "Still cred-blocked" not in captured.out
