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
    # crossref-doi-deposit is one of the remaining CRED_BLOCKED surfaces
    # (paid-membership operator-action gated); its slug must appear in queue
    assert "crossref-doi-deposit" in text


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

    # Cred-blocked keys after PRs #1676 / #1680 / batch wiring +
    # youtube-force-ssl-token added with the chat-response-verbal-and-text
    # publisher. The fake says all cred-blocked keys have arrived.
    def fake_present(key: str) -> bool:
        return key in {
            "crossref/depositor-credentials",
            "google/youtube-force-ssl-token",
        }

    monkeypatch.setattr(m, "_key_present_in_pass", fake_present)
    rc = m.main(["--check-creds"])
    assert rc == 0
    captured = capsys.readouterr()
    # All cred-blocked keys present → no "Still cred-blocked" block renders.
    assert "MISSING:   0" in captured.out
    assert "Ready-to-wire" in captured.out
    assert "+ crossref/depositor-credentials" in captured.out
    assert "+ google/youtube-force-ssl-token" in captured.out
    assert "Still cred-blocked" not in captured.out


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
