"""Tests for the trainyard feed exporters (dossier criticals 2026-06-12:
both shipped testless; canonical datetime timestamps crashed the receipts
exporter)."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load(name: str):
    # extensionless executables need an explicit SourceFileLoader
    loader = importlib.machinery.SourceFileLoader(
        name.replace("-", "_"), str(REPO / "scripts" / name)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO))
    loader.exec_module(mod)
    return mod


class TestReceiptsExporter:
    def _run(self, tmp_path, monkeypatch):
        mod = _load("hapax-review-receipts-export")
        vault = tmp_path / "active"
        vault.mkdir()
        out = tmp_path / "review-receipts.json"
        monkeypatch.setattr(mod, "VAULT", vault)
        monkeypatch.setattr(mod, "OUT", out)
        return mod, vault, out

    def test_counts_and_verdicts(self, tmp_path, monkeypatch):
        mod, vault, out = self._run(tmp_path, monkeypatch)
        (vault / "t1.review-dossier.yaml").write_text(
            "task_id: t1\nreview_team_verdict: blocked\nhead_sha: abc123\n"
            "reviewers:\n- family: codex\n  verdict: block\n  findings:\n"
            "  - severity: critical\n    title: x\n"
        )
        (vault / "t1.acceptance.yaml").write_text("verdict: accepted\nacceptor: review-team\n")
        assert mod.main() == 0
        payload = json.loads(out.read_text())
        assert payload["counts"]["blocked"] == 1
        assert payload["counts"]["acceptances"] == 1
        assert payload["dossiers"][0]["critical_count"] == 1

    def test_unquoted_datetime_timestamp_does_not_crash(self, tmp_path, monkeypatch):
        """The crash bug: yaml parses an unquoted ISO stamp to datetime;
        json.dumps(datetime) raises. The exporter must coerce."""
        mod, vault, out = self._run(tmp_path, monkeypatch)
        (vault / "t2.acceptance.yaml").write_text(
            "verdict: accepted\nacceptor: x\ntimestamp: 2026-06-12T01:28:18+00:00\n"
        )
        assert mod.main() == 0
        payload = json.loads(out.read_text())
        assert payload["acceptances"][0]["timestamp"].startswith("2026-06-12")

    def test_unparseable_dossier_renders_honestly(self, tmp_path, monkeypatch):
        mod, vault, out = self._run(tmp_path, monkeypatch)
        (vault / "t3.review-dossier.yaml").write_text("verdict: [unclosed\n  - {{{\n")
        assert mod.main() == 0
        payload = json.loads(out.read_text())
        assert payload["dossiers"][0]["verdict"] == "unparseable"

    def test_parseable_malformed_dossier_shape_does_not_crash(self, tmp_path, monkeypatch):
        mod, vault, out = self._run(tmp_path, monkeypatch)
        (vault / "t4.review-dossier.yaml").write_text(
            "task_id: t4\nreview_team_verdict: blocked\nhead_sha: abc123\n"
            "reviewers:\n"
            "- family: codex\n  verdict: block\n  findings: scalar-not-list\n"
            "- scalar-reviewer\n"
        )
        (vault / "t5.review-dossier.yaml").write_text(
            "task_id: t5\nreview_team_verdict: blocked\nreviewers: scalar-not-list\n"
        )
        assert mod.main() == 0
        payload = json.loads(out.read_text())
        summaries = {d["task_id"]: d for d in payload["dossiers"]}
        assert summaries["t4"]["families"] == ["codex"]
        assert summaries["t4"]["critical_count"] == 0
        assert summaries["t5"]["families"] == []
        assert summaries["t5"]["critical_count"] == 0

    def test_missing_vault_fails_closed_without_replacing_feed(self, tmp_path, monkeypatch, capsys):
        mod = _load("hapax-review-receipts-export")
        vault = tmp_path / "missing-active"
        out = tmp_path / "review-receipts.json"
        previous = b'{"schema":1,"dossiers":[{"task_id":"old"}],"acceptances":[]}\n'
        out.write_bytes(previous)
        monkeypatch.setattr(mod, "VAULT", vault)
        monkeypatch.setattr(mod, "OUT", out)

        assert mod.main() == 2
        captured = capsys.readouterr()
        assert out.read_bytes() == previous
        assert "review-receipts BLOCKED" in captured.err
        assert "next:" in captured.err

    def test_unreadable_dossier_fails_closed_without_replacing_feed(
        self, tmp_path, monkeypatch, capsys
    ):
        mod, vault, out = self._run(tmp_path, monkeypatch)
        dossier = vault / "t6.review-dossier.yaml"
        dossier.write_text("task_id: t6\nreview_team_verdict: blocked\n")
        previous = b'{"schema":1,"dossiers":[{"task_id":"old"}],"acceptances":[]}\n'
        out.write_bytes(previous)
        original_read_text = Path.read_text

        def flaky_read_text(self, *args, **kwargs):
            if self == dossier:
                raise OSError("permission denied")
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", flaky_read_text)

        assert mod.main() == 2
        captured = capsys.readouterr()
        assert out.read_bytes() == previous
        assert "active cc-task review dossier unreadable" in captured.err
        assert "next:" in captured.err

    def test_unreadable_acceptance_fails_closed_without_replacing_feed(
        self, tmp_path, monkeypatch, capsys
    ):
        mod, vault, out = self._run(tmp_path, monkeypatch)
        receipt = vault / "t7.acceptance.yaml"
        receipt.write_text("verdict: accepted\nacceptor: review-team\n")
        previous = b'{"schema":1,"dossiers":[],"acceptances":[{"task_id":"old"}]}\n'
        out.write_bytes(previous)
        original_read_text = Path.read_text

        def flaky_read_text(self, *args, **kwargs):
            if self == receipt:
                raise OSError("stale mount")
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", flaky_read_text)

        assert mod.main() == 2
        captured = capsys.readouterr()
        assert out.read_bytes() == previous
        assert "active cc-task acceptance receipt unreadable" in captured.err
        assert "next:" in captured.err


class TestVocabExporter:
    def test_observed_forms_bridge_to_ladder_tokens(self, tmp_path, monkeypatch):
        mod = _load("hapax-sdlc-vocab-export")
        vault = tmp_path / "active"
        vault.mkdir()
        out = tmp_path / "sdlc-vocab.json"
        monkeypatch.setattr(mod, "VAULT", vault)
        monkeypatch.setattr(mod, "OUT", out)
        (vault / "a.md").write_text("---\nstage: S6_IMPLEMENTATION\nstatus: claimed\n---\n")
        (vault / "b.md").write_text('---\nstage: "S3.5"\nstatus: offered\n---\n')
        (vault / "c.md").write_text("---\nstage: S13_FOO\nstatus: bogus\n---\n")
        assert mod.main() == 0
        payload = json.loads(out.read_text())
        assert payload["observed_stages"]["S6_IMPLEMENTATION"]["ladder_token"] == "S6"
        assert payload["observed_stages"]["S3.5"]["ladder_token"] == "S3_5"
        assert payload["observed_stages"]["S13_FOO"]["ladder_token"] == "unknown"
        assert payload["observed_statuses"]["claimed"] == 1
        assert "ladder_tokens" in payload and "stage_re" in payload

    def test_missing_vault_fails_closed_without_replacing_feed(self, tmp_path, monkeypatch, capsys):
        mod = _load("hapax-sdlc-vocab-export")
        vault = tmp_path / "missing-active"
        out = tmp_path / "sdlc-vocab.json"
        previous = b'{"schema":1,"observed_stages":{"S6":{"count":1}}}\n'
        out.write_bytes(previous)
        monkeypatch.setattr(mod, "VAULT", vault)
        monkeypatch.setattr(mod, "OUT", out)

        assert mod.main() == 2
        captured = capsys.readouterr()
        assert out.read_bytes() == previous
        assert "sdlc-vocab BLOCKED" in captured.err
        assert "next:" in captured.err

    def test_unreadable_task_note_fails_closed_without_replacing_feed(
        self, tmp_path, monkeypatch, capsys
    ):
        mod = _load("hapax-sdlc-vocab-export")
        vault = tmp_path / "active"
        vault.mkdir()
        bad_note = vault / "bad.md"
        bad_note.write_text("---\nstage: S6_IMPLEMENTATION\n---\n")
        out = tmp_path / "sdlc-vocab.json"
        previous = b'{"schema":1,"observed_stages":{"S5":{"count":1}}}\n'
        out.write_bytes(previous)
        monkeypatch.setattr(mod, "VAULT", vault)
        monkeypatch.setattr(mod, "OUT", out)
        original_read_text = Path.read_text

        def flaky_read_text(self, *args, **kwargs):
            if self == bad_note:
                raise OSError("permission denied")
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", flaky_read_text)

        assert mod.main() == 2
        captured = capsys.readouterr()
        assert out.read_bytes() == previous
        assert "active cc-task note unreadable" in captured.err
        assert "next:" in captured.err
