"""Exercise publication, drift, limits and reversible native bindings."""

import importlib.util
import json
import shutil
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "instruction_install", ROOT / "scripts/install-agent-instructions.py"
)
assert spec and spec.loader
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def test_all_native_outputs_contain_one_shared_body_and_keep_native_additions(tmp_path):
    home = tmp_path / "home"
    common = (ROOT / "config/agent-instructions/AGENTS.md").read_bytes()
    receipt = installer.install(ROOT, home, revision="fixture", apply=True)
    assert len(receipt["files"]) == 10
    for item in receipt["files"]:
        body = Path(item["path"]).read_bytes()
        if not item["binding"].endswith("-instruction-setting"):
            assert body.count(common) == 1
        assert installer.digest(body) == item["sha256"]
    assert b"instruction-level" in (home / ".grok/AGENTS.md").read_bytes()
    assert b"Gate0A" in (home / ".kimi-code/AGENTS.md").read_bytes()
    assert receipt["native_loading"] == "unobserved"
    assert not (home / ".claude/settings.json").exists()


def test_foreign_instruction_controls_preserve_other_native_settings(tmp_path):
    grok = tmp_path / ".grok/config.toml"
    grok.parent.mkdir()
    grok_body = '# Keep comment\n[compat.claude]\nagents = true # named instructions\nrules = true\nskills = true\nhooks = false\n[other]\nsetting = "preserve"\n'
    grok.write_text(grok_body)
    muse = tmp_path / ".config/muse/settings.json"
    muse.parent.mkdir(parents=True)
    settings = {
        "schema_version": 1,
        "provider": "echo",
        "context": {"foreign_personal_skills": True},
    }
    muse.write_text(json.dumps(settings))
    receipt = installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    expected = tomllib.loads(grok_body)
    expected["compat"]["claude"]["agents"] = False
    assert tomllib.loads(grok.read_text()) == expected
    assert "# Keep comment" in grok.read_text()
    assert json.loads(muse.read_text()) == settings
    installer.restore(Path(receipt["rollback"]))
    assert grok.read_text() == grok_body
    assert "foreign_personal_rules" not in json.loads(muse.read_text())["context"]


def test_unhandled_native_settings_layout_refuses_before_publication(tmp_path):
    grok = tmp_path / ".grok/config.toml"
    grok.parent.mkdir()
    grok.write_text("compat = {claude = {agents = true}}\n")
    with pytest.raises(ValueError):
        installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    assert not (tmp_path / ".claude/CLAUDE.md").exists()


def test_native_settings_change_between_render_and_lock_refuses(tmp_path, monkeypatch):
    grok = tmp_path / ".grok/config.toml"
    grok.parent.mkdir()
    grok.write_text("[compat.claude]\nagents = true\n")
    original = installer.fcntl.flock

    def change_then_lock(*args):
        grok.write_text("[compat.claude]\nagents = true\nrules = false\n")
        return original(*args)

    monkeypatch.setattr(installer.fcntl, "flock", change_then_lock)
    with pytest.raises(OSError, match="changed during preparation"):
        installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    assert not (tmp_path / ".claude/CLAUDE.md").exists()
    assert tomllib.loads(grok.read_text())["compat"]["claude"]["rules"] is False


def test_restore_preserves_original_file_mode_symlink_and_absence(tmp_path):
    home = tmp_path / "home"
    claude = home / ".claude/CLAUDE.md"
    claude.parent.mkdir(parents=True)
    claude.write_bytes(b"original")
    claude.chmod(0o640)
    codex = home / ".codex/AGENTS.md"
    codex.parent.mkdir()
    codex.symlink_to("../.claude/CLAUDE.md")
    receipt = installer.install(ROOT, home, revision="fixture", apply=True)
    installer.restore(Path(receipt["rollback"]))
    assert claude.read_bytes() == b"original"
    assert claude.stat().st_mode & 0o777 == 0o640
    assert codex.is_symlink() and codex.readlink() == Path("../.claude/CLAUDE.md")
    assert not (home / ".grok/AGENTS.md").exists()
    assert not (home / ".config/hapax/agent-instructions/current.json").exists()


@pytest.mark.parametrize("changed", [False, True])
def test_rollback_cli_refuses_changed_outputs_but_restores_current_install(
    tmp_path, monkeypatch, changed
):
    receipt = installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    target = tmp_path / ".codex/AGENTS.md"
    if changed:
        target.write_text("successor instruction")
    monkeypatch.setattr(
        "sys.argv", ["installer", "--home", str(tmp_path), "--restore-backup", receipt["rollback"]]
    )
    assert installer.main() == (1 if changed else 0)
    if changed:
        assert target.read_text() == "successor instruction"
    else:
        assert not target.exists()


def test_failed_readback_rolls_back_entire_publication(tmp_path, monkeypatch):
    home = tmp_path / "home"
    original = installer.atomic_write

    def faulty(path, body, mode=0o600):
        original(path, body, mode)
        if path == home / ".grok/AGENTS.md":
            path.write_bytes(b"corrupted")

    monkeypatch.setattr(installer, "atomic_write", faulty)
    with pytest.raises(OSError, match="readback failed"):
        installer.install(ROOT, home, revision="fixture", apply=True)
    assert not (home / ".claude/CLAUDE.md").exists()
    assert not (home / ".codex/AGENTS.md").exists()
    assert not (home / ".grok/AGENTS.md").exists()


def test_shadow_refuses_before_any_native_write(tmp_path):
    shadow = tmp_path / ".codex/AGENTS.override.md"
    shadow.parent.mkdir()
    shadow.write_text("override")
    with pytest.raises(ValueError, match="shadows"):
        installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    assert not (tmp_path / ".claude/CLAUDE.md").exists()


def test_oversize_refuses_instead_of_truncating(tmp_path):
    shutil.copytree(ROOT / "config/agent-instructions", tmp_path / "config/agent-instructions")
    (tmp_path / "config/agent-instructions/AGENTS.md").write_text("x" * 10001)
    with pytest.raises(ValueError, match="grok.*character limit"):
        installer.render(tmp_path, ["grok"])


def test_explicit_home_does_not_inherit_process_native_homes(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "ambient"))
    receipt = installer.install(ROOT, tmp_path / "home", revision="fixture", apply=True)
    assert not (tmp_path / "ambient").exists()
    assert any(f["path"].endswith("home/.codex/AGENTS.md") for f in receipt["files"])
    binding, _ = installer.render(ROOT)["codex"]
    assert installer.destination(binding, tmp_path, {"CODEX_HOME": "/explicit"}) == Path(
        "/explicit/AGENTS.md"
    )


def test_dry_render_is_non_mutating(tmp_path):
    installer.install(ROOT, tmp_path, revision="fixture")
    assert list(tmp_path.iterdir()) == []


def test_grok_and_codex_complete_payload_budgets():
    rendered = installer.render(ROOT)
    assert len(rendered["grok"][1].decode()) <= 10000
    assert len(rendered["codex"][1]) + len((ROOT / "AGENTS.md").read_bytes()) < 32768
    bindings = json.loads((ROOT / "config/agent-instructions/bindings.json").read_text())
    assert bindings["muse"]["path"] == ".config/muse/AGENTS.md"
    assert len((ROOT / "AGENTS.md").read_text()) <= 10000


def test_unwritable_unchanged_destination_does_not_interrupt_rollback(tmp_path):
    directory = tmp_path / ".grok"
    directory.mkdir()
    target = directory / "AGENTS.md"
    target.write_text("existing grok rules")
    directory.chmod(0o500)
    try:
        with pytest.raises(PermissionError):
            installer.install(ROOT, tmp_path, revision="fixture", apply=True)
        assert target.read_text() == "existing grok rules"
        assert not (tmp_path / ".claude/CLAUDE.md").exists()
        assert not (tmp_path / ".codex/AGENTS.md").exists()
    finally:
        directory.chmod(0o700)


def test_parent_symlink_aliases_are_rejected_before_publication(tmp_path):
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".grok").symlink_to(".codex", target_is_directory=True)
    with pytest.raises(ValueError, match="overlap"):
        installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    assert not (tmp_path / ".codex/AGENTS.md").exists()


def test_rollback_failure_continues_other_restores_and_retains_both_errors(tmp_path, monkeypatch):
    target = tmp_path / ".codex/AGENTS.md"
    original = installer.atomic_write

    def fail_after_publish(path, body, mode=0o600):
        original(path, body, mode)
        if path == target:
            raise OSError("injected publication failure")

    unlink = Path.unlink

    def fail_one_restore(path, *args, **kwargs):
        if path == target:
            raise OSError("injected rollback failure")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(installer, "atomic_write", fail_after_publish)
    monkeypatch.setattr(Path, "unlink", fail_one_restore)
    with pytest.raises(OSError, match="publication failure.*rollback incomplete.*rollback failure"):
        installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    assert not (tmp_path / ".claude/CLAUDE.md").exists()
    assert not (tmp_path / ".config/hapax/agent-instructions/AGENTS.md").exists()
    assert list((tmp_path / ".config/hapax/agent-instructions/backups").glob("*/preimages.json"))
