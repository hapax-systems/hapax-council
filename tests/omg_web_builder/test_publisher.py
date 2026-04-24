"""Tests for ``agents.omg_web_builder.publisher`` (ytb-OMG2 Phase 1.5).

The dry-run-by-default invariant is the safety contract: running the
publisher with no flags must not mutate the live web page. Tests pin
that explicitly.
"""

from __future__ import annotations

from unittest import mock

import pytest

from agents.omg_web_builder.publisher import (
    main,
    publish,
    read_html,
    render_dry_run_summary,
)

# ── read_html ────────────────────────────────────────────────────────


class TestReadHtml:
    def test_reads_existing_file(self, tmp_path):
        html = tmp_path / "page.html"
        html.write_text("<html><body>hi</body></html>", encoding="utf-8")
        assert "<body>" in read_html(html)

    def test_raises_on_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_html(tmp_path / "absent.html")

    def test_raises_on_empty(self, tmp_path):
        empty = tmp_path / "empty.html"
        empty.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="empty"):
            read_html(empty)

    def test_raises_on_whitespace_only(self, tmp_path):
        ws = tmp_path / "ws.html"
        ws.write_text("\n\n   \n", encoding="utf-8")
        with pytest.raises(ValueError, match="empty"):
            read_html(ws)


# ── render_dry_run_summary ───────────────────────────────────────────


class TestRenderDryRunSummary:
    def test_summary_includes_address_and_size(self):
        content = "<html>\n  <body>x</body>\n</html>\n"
        summary = render_dry_run_summary(content, address="hapax")
        assert "hapax" in summary
        assert f"bytes={len(content)}" in summary
        assert "DRY RUN" in summary

    def test_summary_mentions_publish_re_run_hint(self):
        summary = render_dry_run_summary("<html></html>", address="hapax")
        assert "--publish" in summary


# ── publish — dry-run path ───────────────────────────────────────────


class TestPublishDryRun:
    def test_dry_run_default_returns_zero(self, tmp_path, capsys):
        html = tmp_path / "page.html"
        html.write_text("<html><body>safe</body></html>", encoding="utf-8")

        rc = publish(html_path=html, address="hapax", dry_run=True)
        assert rc == 0
        captured = capsys.readouterr()
        assert "DRY RUN" in captured.out

    def test_dry_run_does_not_construct_client(self, tmp_path):
        """Pin: dry-run path must NEVER touch the client factory."""
        html = tmp_path / "page.html"
        html.write_text("<html></html>", encoding="utf-8")

        factory = mock.Mock()
        rc = publish(
            html_path=html,
            address="hapax",
            dry_run=True,
            client_factory=factory,
        )
        assert rc == 0
        factory.assert_not_called()

    def test_missing_html_returns_one(self, tmp_path, caplog):
        with caplog.at_level("ERROR"):
            rc = publish(
                html_path=tmp_path / "missing.html",
                dry_run=True,
            )
        assert rc == 1
        assert any("not found" in r.message for r in caplog.records)


# ── publish — live path ──────────────────────────────────────────────


class TestPublishLive:
    def test_live_publish_calls_set_web(self, tmp_path):
        html = tmp_path / "page.html"
        html.write_text("<html><body>live</body></html>", encoding="utf-8")

        client = mock.Mock()
        client.enabled = True
        client.set_web.return_value = {"response": {"message": "ok"}}

        rc = publish(
            html_path=html,
            address="hapax",
            dry_run=False,
            client_factory=lambda: client,
        )
        assert rc == 0
        client.set_web.assert_called_once_with(
            "hapax", content=html.read_text(encoding="utf-8"), publish=True
        )

    def test_disabled_client_returns_one(self, tmp_path, caplog):
        html = tmp_path / "page.html"
        html.write_text("<html></html>", encoding="utf-8")

        client = mock.Mock()
        client.enabled = False

        with caplog.at_level("ERROR"):
            rc = publish(
                html_path=html,
                dry_run=False,
                client_factory=lambda: client,
            )
        assert rc == 1
        assert any("disabled" in r.message for r in caplog.records)
        client.set_web.assert_not_called()

    def test_set_web_returns_none_returns_one(self, tmp_path, caplog):
        html = tmp_path / "page.html"
        html.write_text("<html></html>", encoding="utf-8")

        client = mock.Mock()
        client.enabled = True
        client.set_web.return_value = None

        with caplog.at_level("ERROR"):
            rc = publish(
                html_path=html,
                dry_run=False,
                client_factory=lambda: client,
            )
        assert rc == 1


# ── CLI entry — main() ───────────────────────────────────────────────


class TestMain:
    def test_default_argv_is_dry_run(self, tmp_path, capsys, monkeypatch):
        html = tmp_path / "page.html"
        html.write_text("<html></html>", encoding="utf-8")

        # No --publish flag → dry-run regardless of how the test
        # environment is configured. This is the safety invariant.
        rc = main(["--html-path", str(html)])
        assert rc == 0
        captured = capsys.readouterr()
        assert "DRY RUN" in captured.out

    def test_publish_flag_routes_to_live_path(self, tmp_path, monkeypatch):
        html = tmp_path / "page.html"
        html.write_text("<html></html>", encoding="utf-8")

        called = {"n": 0}

        class FakeClient:
            enabled = True

            def set_web(self, address, *, content, publish):
                called["n"] += 1
                called["address"] = address
                called["publish"] = publish
                return {"response": {"ok": True}}

        # Patch the module-level default factory so the CLI path picks
        # up our fake instead of constructing a real OmgLolClient.
        monkeypatch.setattr(
            "agents.omg_web_builder.publisher._default_client_factory",
            lambda: FakeClient(),
        )

        rc = main(["--publish", "--html-path", str(html)])
        assert rc == 0
        assert called["n"] == 1
        assert called["address"] == "hapax"
        assert called["publish"] is True

    def test_address_override(self, tmp_path, capsys):
        html = tmp_path / "page.html"
        html.write_text("<html></html>", encoding="utf-8")
        rc = main(["--html-path", str(html), "--address", "alt-addr"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "alt-addr" in captured.out
