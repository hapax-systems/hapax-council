from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load_exporter():
    loader = importlib.machinery.SourceFileLoader(
        "hapax_sdlc_vocab_export",
        str(REPO / "scripts" / "hapax-sdlc-vocab-export"),
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO))
    loader.exec_module(mod)
    return mod


def test_observed_forms_bridge_to_ladder_tokens(tmp_path, monkeypatch):
    mod = _load_exporter()
    vault = tmp_path / "active"
    vault.mkdir()
    out = tmp_path / "sdlc-vocab.json"
    tmp = out.with_suffix(".tmp")
    monkeypatch.setattr(mod, "VAULT", vault)
    monkeypatch.setattr(mod, "OUT", out)
    (vault / "a.md").write_text("---\nstage: S6_IMPLEMENTATION\nstatus: claimed\n---\n")
    (vault / "b.md").write_text('---\nstage: "S3.5"\nstatus: offered\n---\n')
    (vault / "c.md").write_text("---\nstage: S13_FOO\nstatus: bogus\n---\n")
    tmp.write_text("stale partial payload\n")

    assert mod.main() == 0

    payload = json.loads(out.read_text())
    assert payload["schema"] == 1
    assert payload["ladder_tokens"] == [
        stage for stage in mod.SDLC_LADDER.stages if stage not in mod.SDLC_LADDER.blocked
    ]
    assert payload["pseudo_stages"] == sorted(mod.SDLC_LADDER.blocked)
    assert payload["observed_stages"]["S6_IMPLEMENTATION"]["ladder_token"] == "S6"
    assert payload["observed_stages"]["S3.5"]["ladder_token"] == "S3_5"
    assert payload["observed_stages"]["S13_FOO"]["ladder_token"] == "unknown"
    assert payload["observed_statuses"]["claimed"] == 1
    assert "ladder_tokens" in payload and "stage_re" in payload
    assert not tmp.exists()


def test_missing_vault_fails_closed_without_replacing_feed(tmp_path, monkeypatch, capsys):
    mod = _load_exporter()
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


def test_vault_path_that_is_not_directory_fails_closed_without_replacing_feed(
    tmp_path, monkeypatch, capsys
):
    mod = _load_exporter()
    vault = tmp_path / "active-as-file"
    vault.write_text("not a directory\n")
    out = tmp_path / "sdlc-vocab.json"
    previous = b'{"schema":1,"observed_stages":{"S7":{"count":1}}}\n'
    out.write_bytes(previous)
    monkeypatch.setattr(mod, "VAULT", vault)
    monkeypatch.setattr(mod, "OUT", out)

    assert mod.main() == 2

    captured = capsys.readouterr()
    assert out.read_bytes() == previous
    assert "active cc-task vault is not a directory" in captured.err
    assert "next:" in captured.err


def test_unreadable_vault_fails_closed_without_replacing_feed(tmp_path, monkeypatch, capsys):
    mod = _load_exporter()
    vault = tmp_path / "active"
    vault.mkdir()
    out = tmp_path / "sdlc-vocab.json"
    previous = b'{"schema":1,"observed_stages":{"S4":{"count":1}}}\n'
    out.write_bytes(previous)
    monkeypatch.setattr(mod, "VAULT", vault)
    monkeypatch.setattr(mod, "OUT", out)
    original_scandir = mod.os.scandir

    def broken_scandir(path):
        if path == vault:
            raise OSError("permission denied")
        return original_scandir(path)

    monkeypatch.setattr(mod.os, "scandir", broken_scandir)

    assert mod.main() == 2

    captured = capsys.readouterr()
    assert out.read_bytes() == previous
    assert "active cc-task vault unreadable" in captured.err
    assert "next:" in captured.err


def test_unreadable_task_note_fails_closed_without_replacing_feed(tmp_path, monkeypatch, capsys):
    mod = _load_exporter()
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
