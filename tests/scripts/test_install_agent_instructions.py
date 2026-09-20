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


@pytest.mark.parametrize("installed", [False, True])
def test_native_settings_change_between_render_and_lock_refuses(tmp_path, monkeypatch, installed):
    grok = tmp_path / ".grok/config.toml"
    grok.parent.mkdir()
    grok.write_text("[compat.claude]\nagents = true\n")
    if installed:
        installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    original = installer.fcntl.flock

    def change_then_lock(*args):
        grok.write_text("[compat.claude]\nagents = true\nrules = false\n")
        return original(*args)

    monkeypatch.setattr(installer.fcntl, "flock", change_then_lock)
    with pytest.raises(OSError, match="changed during preparation"):
        installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    assert (tmp_path / ".claude/CLAUDE.md").exists() is installed
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


@pytest.mark.parametrize("installed", [False, True])
def test_shadow_refuses_before_any_native_write(tmp_path, installed):
    if installed:
        installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    shadow = tmp_path / ".codex/AGENTS.override.md"
    shadow.parent.mkdir(exist_ok=True)
    shadow.write_text("override")
    with pytest.raises(ValueError, match="shadows"):
        installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    assert (tmp_path / ".claude/CLAUDE.md").exists() is installed


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


@pytest.mark.parametrize("upgrade", [False, True])
@pytest.mark.parametrize("foreign_edit", [False, True])
def test_cli_recovers_failed_transaction_without_current_receipt(
    tmp_path, monkeypatch, upgrade, foreign_edit
):
    home = tmp_path / "home"
    source = tmp_path / "source"
    shutil.copytree(ROOT / "config/agent-instructions", source / "config/agent-instructions")
    state = home / ".config/hapax/agent-instructions"
    prior_receipt = None
    if upgrade:
        installer.install(ROOT, home, revision="predecessor", apply=True)
        prior_receipt = (state / "current.json").read_bytes()
    target = home / ".codex/AGENTS.md"
    prior_body = target.read_bytes() if upgrade else None
    common = source / "config/agent-instructions/AGENTS.md"
    common.write_text(common.read_text() + "\nA changed instruction for upgrade.\n")
    atomic = installer.atomic_write
    unlink = Path.unlink
    published = False

    def fail_publication_and_restore(path, body, mode=0o600):
        nonlocal published
        if path == target:
            if published:
                raise OSError("injected restore failure")
            atomic(path, body, mode)
            published = True
            raise OSError("injected publication failure")
        atomic(path, body, mode)

    def fail_unlink(path, *args, **kwargs):
        if path == target:
            raise OSError("injected restore failure")
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(installer, "atomic_write", fail_publication_and_restore)
        fault.setattr(Path, "unlink", fail_unlink)
        with pytest.raises(OSError, match="publication failure.*rollback incomplete.*next action:"):
            installer.install(source, home, revision="failed-upgrade", apply=True)
    pending = json.loads((state / "pending.json").read_text())
    with pytest.raises(ValueError, match="unresolved instruction transaction"):
        installer.install(ROOT, home, revision="successor", apply=True)
    if foreign_edit:
        target.write_text("intervening authored instruction")
    monkeypatch.setattr(
        "sys.argv", ["installer", "--home", str(home), "--restore-backup", pending["backup"]]
    )
    assert installer.main() == (1 if foreign_edit else 0)
    if foreign_edit:
        assert target.read_text() == "intervening authored instruction"
        assert (state / "pending.json").exists()
    else:
        assert not (state / "pending.json").exists()
        if upgrade:
            assert target.read_bytes() == prior_body
            assert (state / "current.json").read_bytes() == prior_receipt
        else:
            assert not target.exists()
            assert not (state / "current.json").exists()


@pytest.mark.parametrize("original_symlink", [False, True])
def test_failed_manual_rollback_can_be_retried_after_current_receipt_restored(
    tmp_path, monkeypatch, original_symlink
):
    target = tmp_path / ".codex/AGENTS.md"
    if original_symlink:
        target.parent.mkdir()
        (target.parent / "original.md").write_text("Original policy")
        target.symlink_to("original.md")
    receipt = installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    unlink = Path.unlink
    replace = installer.os.replace

    def fail_symlink(source, destination):
        if destination == target and Path(source).is_symlink():
            raise OSError("symlink restore denied")
        return replace(source, destination)

    def fail_one(path, *args, **kwargs):
        if path == target:
            raise OSError("restore denied")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(
        "sys.argv", ["installer", "--home", str(tmp_path), "--restore-backup", receipt["rollback"]]
    )
    with monkeypatch.context() as fault:
        if original_symlink:
            fault.setattr(installer.os, "replace", fail_symlink)
        else:
            fault.setattr(Path, "unlink", fail_one)
        assert installer.main() == 1
    assert not (tmp_path / ".config/hapax/agent-instructions/current.json").exists()
    assert installer.main() == 0
    if original_symlink:
        assert target.is_symlink() and target.readlink() == Path("original.md")
        assert target.read_text() == "Original policy"
    else:
        assert not target.exists()


def test_identical_retry_preserves_files_receipt_and_original_rollback(tmp_path):
    target = tmp_path / ".codex/AGENTS.md"
    target.parent.mkdir()
    target.write_bytes(b"original policy")
    target.chmod(0o640)
    first = installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    state = tmp_path / ".config/hapax/agent-instructions"

    def snapshot():
        return {
            str(path.relative_to(tmp_path)): (
                path.lstat().st_ino,
                path.lstat().st_mtime_ns,
                path.lstat().st_mode,
                path.read_bytes() if path.is_file() else None,
            )
            for path in tmp_path.rglob("*")
        }

    before = snapshot()
    for _ in range(2):
        assert installer.install(ROOT, tmp_path, revision="fixture", apply=True) == first
        assert snapshot() == before
    assert list((state / "backups").iterdir()) == [Path(first["rollback"])]
    installer.restore(Path(first["rollback"]))
    assert target.read_bytes() == b"original policy"
    assert target.stat().st_mode & 0o7777 == 0o640
    assert not (tmp_path / ".claude/CLAUDE.md").exists()
    assert not (state / "current.json").exists()


@pytest.mark.parametrize("binding", ["codex", "grok-instruction-setting"])
@pytest.mark.parametrize("drift", ["edited", "missing", "symlink", "mode"])
def test_identical_retry_repairs_local_drift(tmp_path, binding, drift):
    first = installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    item = next(item for item in first["files"] if item["binding"] == binding)
    target = Path(item["path"])
    expected = target.read_bytes()
    if drift == "edited":
        target.write_bytes(expected + b"\n# Local edit\n")
        if binding == "grok-instruction-setting":
            expected = target.read_bytes()
    elif drift == "missing":
        target.unlink()
    elif drift == "symlink":
        saved = tmp_path / "saved"
        target.rename(saved)
        target.symlink_to(saved)
    else:
        target.chmod(0o644)

    second = installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    assert second["rollback"] != first["rollback"]
    assert target.is_file() and not target.is_symlink()
    assert target.read_bytes() == expected
    assert target.stat().st_mode & 0o7777 == 0o600


def test_identical_bytes_with_changed_revision_create_new_receipt(tmp_path):
    first = installer.install(ROOT, tmp_path, revision="first", apply=True)
    second = installer.install(ROOT, tmp_path, revision="second", apply=True)
    assert second["files"] == first["files"]
    assert second["source_revision"] == "second"
    assert second["rollback"] != first["rollback"]
    state = tmp_path / ".config/hapax/agent-instructions"
    assert json.loads((state / "current.json").read_text()) == second
    installer.restore(Path(second["rollback"]))
    assert json.loads((state / "current.json").read_text()) == first


@pytest.mark.parametrize(
    ("first_names", "second_names"),
    [
        (["codex"], ["codex", "claude"]),
        (["codex", "claude"], ["codex"]),
        (["codex"], ["opencode"]),
    ],
)
def test_identical_revision_with_changed_selection_creates_new_receipt(
    tmp_path, first_names, second_names
):
    first = installer.install(ROOT, tmp_path, revision="fixture", names=first_names, apply=True)
    second = installer.install(ROOT, tmp_path, revision="fixture", names=second_names, apply=True)
    assert second["rollback"] != first["rollback"]
    assert {item["binding"] for item in second["files"]} == {"shared", *second_names}
    state = tmp_path / ".config/hapax/agent-instructions"
    assert json.loads((state / "current.json").read_text()) == second


def test_identical_revision_with_changed_destination_creates_new_receipt(tmp_path):
    first = installer.install(ROOT, tmp_path, revision="fixture", names=["codex"], apply=True)
    alternate = tmp_path / "alternate-codex"
    second = installer.install(
        ROOT,
        tmp_path,
        revision="fixture",
        names=["codex"],
        env={"CODEX_HOME": str(alternate)},
        apply=True,
    )
    assert second["rollback"] != first["rollback"]
    assert (alternate / "AGENTS.md").read_bytes() == (tmp_path / ".codex/AGENTS.md").read_bytes()


@pytest.mark.parametrize(
    "damage",
    [
        "invalid-json",
        "nonobject",
        "missing-rollback",
        "invalid-rollback",
        "observation",
        "native-loading",
        "file-bytes",
        "extra-field",
        "symlink",
        "mode",
    ],
)
def test_identical_retry_does_not_preserve_invalid_current_receipt(tmp_path, damage):
    first = installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    current_path = tmp_path / ".config/hapax/agent-instructions/current.json"
    current = json.loads(current_path.read_text())
    if damage == "invalid-json":
        current_path.write_bytes(b"{")
    elif damage == "nonobject":
        current_path.write_text("[]")
    elif damage == "symlink":
        saved = tmp_path / "saved-receipt"
        current_path.rename(saved)
        current_path.symlink_to(saved)
    elif damage == "mode":
        current_path.chmod(0o644)
    else:
        if damage == "missing-rollback":
            del current["rollback"]
        elif damage == "invalid-rollback":
            current["rollback"] = None
        elif damage == "observation":
            current["observation"] = "render_only"
        elif damage == "native-loading":
            current["native_loading"] = "observed"
        elif damage == "file-bytes":
            current["files"][0]["bytes"] += 1
        else:
            current["unsupported"] = True
        current_path.write_text(json.dumps(current))
    second = installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    assert second["rollback"] != first["rollback"]
    assert second["files"] == first["files"]
    assert second["observation"] == "filesystem_readback"
    assert second["native_loading"] == "unobserved"
    assert not current_path.is_symlink()
    assert current_path.stat().st_mode & 0o7777 == 0o600
    assert json.loads(current_path.read_text()) == second


@pytest.mark.parametrize("dangling", [False, True])
def test_identical_retry_still_refuses_pending_transaction(tmp_path, dangling):
    receipt = installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    state = tmp_path / ".config/hapax/agent-instructions"
    pending = state / "pending.json"
    if dangling:
        pending.symlink_to("missing-transaction.json")
    else:
        pending.write_text(json.dumps({"backup": receipt["rollback"]}))
    current_before = (state / "current.json").read_bytes()
    with pytest.raises((OSError, ValueError)):
        installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    assert (state / "current.json").read_bytes() == current_before
    assert list((state / "backups").iterdir()) == [Path(receipt["rollback"])]
    assert pending.is_symlink() if dangling else pending.exists()


def test_identical_retry_with_empty_override_does_not_reuse_receipt(tmp_path):
    first = installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    (tmp_path / ".codex/AGENTS.override.md").touch()
    second = installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    assert second["rollback"] != first["rollback"]


def test_rollback_rejects_predecessor_backup_after_successor(tmp_path, monkeypatch):
    first = installer.install(ROOT, tmp_path, revision="first", apply=True)
    second = installer.install(ROOT, tmp_path, revision="second", apply=True)
    monkeypatch.setattr(
        "sys.argv", ["installer", "--home", str(tmp_path), "--restore-backup", first["rollback"]]
    )
    assert installer.main() == 1
    assert (
        json.loads((tmp_path / ".config/hapax/agent-instructions/current.json").read_text())
        == second
    )


@pytest.mark.parametrize("drift", ["none", "missing", "edited", "symlink", "receipt", "pending"])
def test_check_cli_reports_drift_without_mutation(tmp_path, monkeypatch, capsys, drift):
    installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    target = tmp_path / ".codex/AGENTS.md"
    if drift == "missing":
        target.unlink()
    elif drift == "edited":
        target.write_text("local edit")
    elif drift == "symlink":
        saved = tmp_path / "saved"
        target.rename(saved)
        target.symlink_to(saved)
    elif drift == "receipt":
        (tmp_path / ".config/hapax/agent-instructions/current.json").unlink()
    elif drift == "pending":
        (tmp_path / ".config/hapax/agent-instructions/pending.json").symlink_to("missing.json")
    before = {
        str(p): (p.lstat().st_mtime_ns, p.readlink() if p.is_symlink() else p.read_bytes())
        for p in tmp_path.rglob("*")
        if p.is_file() or p.is_symlink()
    }
    monkeypatch.setattr(
        "sys.argv",
        [
            "installer",
            "--home",
            str(tmp_path),
            "--source",
            str(ROOT),
            "--source-revision",
            "fixture",
            "--check",
        ],
    )
    assert installer.main() == (0 if drift == "none" else 1)
    result = json.loads(capsys.readouterr().out)
    assert result["matches"] is (drift == "none")
    assert result["native_loading"] == "unobserved"
    after = {
        str(p): (p.lstat().st_mtime_ns, p.readlink() if p.is_symlink() else p.read_bytes())
        for p in tmp_path.rglob("*")
        if p.is_file() or p.is_symlink()
    }
    assert after == before


def test_restore_refuses_dangling_pending_transaction(tmp_path, monkeypatch):
    receipt = installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    state = tmp_path / ".config/hapax/agent-instructions"
    pending = state / "pending.json"
    pending.symlink_to("missing.json")
    before = (state / "current.json").read_bytes()
    monkeypatch.setattr(
        "sys.argv", ["installer", "--home", str(tmp_path), "--restore-backup", receipt["rollback"]]
    )
    assert installer.main() == 1
    assert pending.is_symlink()
    assert (state / "current.json").read_bytes() == before
