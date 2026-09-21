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


def test_unknown_binding_reports_choices_without_publication(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv",
        [
            "installer",
            "--source",
            str(ROOT),
            "--source-revision",
            "fixture",
            "--home",
            str(tmp_path),
            "--binding",
            "cdoex",
            "--apply",
        ],
    )
    assert installer.main() == 1
    error = capsys.readouterr().err
    assert "unknown --binding 'cdoex'" in error
    assert "next action: choose from" in error and "codex" in error
    assert not (tmp_path / ".config").exists()


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
    with pytest.raises(ValueError) as error:
        installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    assert str(grok) in str(error.value)
    assert "standalone [compat.claude] table" in str(error.value)
    assert "preserving other settings, then retry" in str(error.value)
    assert not (tmp_path / ".claude/CLAUDE.md").exists()


def test_invalid_existing_toml_names_its_path_and_repair_before_publication(tmp_path):
    grok = tmp_path / ".grok/config.toml"
    grok.parent.mkdir()
    body = b"not valid TOML\n"
    grok.write_bytes(body)
    with pytest.raises(ValueError) as error:
        installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    assert str(grok) in str(error.value)
    assert "repair its TOML syntax before retrying" in str(error.value)
    assert grok.read_bytes() == body
    assert not (tmp_path / ".claude/CLAUDE.md").exists()
    assert not (tmp_path / ".config/hapax/agent-instructions").exists()


@pytest.mark.parametrize("body", ["compat = false\n", "[compat]\nclaude = false\n"])
def test_invalid_native_table_types_name_path_and_repair_before_publication(tmp_path, body):
    grok = tmp_path / ".grok/config.toml"
    grok.parent.mkdir()
    grok.write_text(body)
    with pytest.raises(ValueError) as error:
        installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    assert str(grok) in str(error.value)
    assert "compat and compat.claude must be TOML tables" in str(error.value)
    assert "next action" in str(error.value)
    assert grok.read_text() == body
    assert not (tmp_path / ".config/hapax/agent-instructions").exists()


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


def test_failed_readback_retains_unknown_bytes_for_reconciliation(tmp_path, monkeypatch):
    home = tmp_path / "home"
    original = installer.atomic_write

    def faulty(path, body, mode=0o600):
        original(path, body, mode)
        if path == home / ".grok/AGENTS.md":
            path.write_bytes(b"corrupted")

    monkeypatch.setattr(installer, "atomic_write", faulty)
    with pytest.raises(OSError, match="readback failed.*reconcile.*next action"):
        installer.install(ROOT, home, revision="fixture", apply=True)
    assert (home / ".grok/AGENTS.md").read_bytes() == b"corrupted"
    assert (home / ".config/hapax/agent-instructions/pending.json").exists()


@pytest.mark.parametrize("upgrade", [False, True])
@pytest.mark.parametrize("changed", ["output", "receipt"])
def test_manual_rollback_never_adopts_edits_after_validation(
    tmp_path, monkeypatch, upgrade, changed
):
    home = tmp_path / "home"
    if upgrade:
        installer.install(ROOT, home, revision="prior", apply=True)
    current = installer.install(ROOT, home, revision="current", apply=True)
    state = home / ".config/hapax/agent-instructions"
    target = home / ".codex/AGENTS.md" if changed == "output" else state / "current.json"
    approved = target.read_bytes()
    foreign = approved + b"\n "
    backup = Path(current["rollback"])
    read_text = Path.read_text
    injected = False

    def intervene(path, *args, **kwargs):
        nonlocal injected
        body = read_text(path, *args, **kwargs)
        if path == backup / "preimages.json" and not injected:
            injected = True
            target.write_bytes(foreign)
        return body

    monkeypatch.setattr(
        "sys.argv", ["installer", "--home", str(home), "--restore-backup", str(backup)]
    )
    with monkeypatch.context() as fault:
        fault.setattr(Path, "read_text", intervene)
        status = installer.main()
    assert injected, "the edit must arrive after validation, before pending-record creation"
    assert status == 1
    assert target.read_bytes() == foreign
    pending = json.loads((state / "pending.json").read_text())
    originals = json.loads((backup / "preimages.json").read_text())
    index = next(i for i, item in enumerate(originals) if item["path"] == str(target))
    assert pending["postimages"][index] == installer.digest(approved)
    # Explicit reconciliation in this fixture permits a later guarded retry.
    target.write_bytes(approved)
    assert installer.main() == 0
    assert not (state / "pending.json").exists()


@pytest.mark.parametrize("upgrade", [False, True])
@pytest.mark.parametrize("foreign_kind", ["file", "symlink", "directory"])
def test_automatic_rollback_preserves_intervening_edits_and_pending_recovery(
    tmp_path, monkeypatch, upgrade, foreign_kind
):
    home = tmp_path / "home"
    state = home / ".config/hapax/agent-instructions"
    target = home / ".claude/CLAUDE.md"
    prior = installer.install(ROOT, home, revision="prior", apply=True) if upgrade else None
    prior_body = target.read_bytes() if upgrade else None
    expected_body = installer.render(ROOT)["claude"][1]
    foreign_body = b"Intervening authored instruction.\n"
    foreign_target = tmp_path / "foreign-instruction"
    foreign_target.write_bytes(foreign_body)
    atomic = installer.atomic_write

    def intervene_then_fail(path, body, mode=0o600):
        if path == home / ".codex/AGENTS.md":
            assert target.read_bytes() == expected_body
            if foreign_kind == "file":
                target.write_bytes(foreign_body)
                target.chmod(0o640)
            else:
                target.unlink()
                if foreign_kind == "symlink":
                    target.symlink_to(foreign_target)
                else:
                    target.mkdir()
            raise OSError("injected later publication failure")
        atomic(path, body, mode)

    with monkeypatch.context() as fault:
        fault.setattr(installer, "atomic_write", intervene_then_fail)
        with pytest.raises(OSError) as error:
            installer.install(ROOT, home, revision="new", apply=True)
    assert foreign_target.read_bytes() == foreign_body
    if foreign_kind == "directory":
        assert target.is_dir()
    elif foreign_kind == "symlink":
        assert target.is_symlink() and target.readlink() == foreign_target
    else:
        assert target.is_file()
        assert target.read_bytes() == foreign_body
        assert target.stat().st_mode & 0o777 == 0o640
    assert "later publication failure" in str(error.value)
    assert "next action" in str(error.value)
    pending = json.loads((state / "pending.json").read_text())
    assert Path(pending["backup"]).is_dir()
    with pytest.raises(ValueError, match="unresolved instruction transaction"):
        installer.install(ROOT, home, revision="successor", apply=True)
    monkeypatch.setattr(
        "sys.argv", ["installer", "--home", str(home), "--restore-backup", pending["backup"]]
    )
    assert installer.main() == 1
    assert (state / "pending.json").exists()

    # Explicit reconciliation to a known postimage makes guarded recovery
    # possible; the automatic path must never do this to someone else's edit.
    if target.is_dir():
        target.rmdir()
    atomic(target, expected_body)
    assert installer.main() == 0
    assert not (state / "pending.json").exists()
    assert foreign_target.read_bytes() == foreign_body
    if upgrade:
        assert target.read_bytes() == prior_body
        assert json.loads((state / "current.json").read_text()) == prior
    else:
        assert not target.exists()
        assert not (state / "current.json").exists()


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
    with pytest.raises(ValueError, match="grok.*character limit") as error:
        installer.render(tmp_path, ["grok"])
    assert "characters, limit 10000" in str(error.value)


def test_character_and_byte_limits_keep_their_units(tmp_path):
    config = tmp_path / "config/agent-instructions"
    config.mkdir(parents=True)
    (config / "AGENTS.md").write_text("é" * 10)
    binding = {"path": ".codex/AGENTS.md"}
    (config / "bindings.json").write_text(json.dumps({"codex": binding}))
    body = installer.render(tmp_path, ["codex"])["codex"][1]
    chars = len(body.decode())
    binding["max_chars"] = chars
    (config / "bindings.json").write_text(json.dumps({"codex": binding}))
    assert installer.render(tmp_path, ["codex"])["codex"][1] == body
    binding["max_bytes"] = chars
    (config / "bindings.json").write_text(json.dumps({"codex": binding}))
    with pytest.raises(ValueError, match="byte limit") as error:
        installer.render(tmp_path, ["codex"])
    assert f"{len(body)} bytes, limit {chars}" in str(error.value)


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
    with pytest.raises(ValueError, match="overlap") as error:
        installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    message = str(error.value)
    assert f"codex ({tmp_path / '.codex/AGENTS.md'})" in message
    assert f"grok ({tmp_path / '.grok/AGENTS.md'})" in message
    assert f"both resolve to {tmp_path / '.codex/AGENTS.md'}" in message
    assert "reconcile native-home overrides or directory aliases before retrying" in message
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


@pytest.mark.parametrize("contents", ["", " \n"])
def test_identical_retry_with_empty_override_retains_original_rollback(tmp_path, contents):
    override = tmp_path / ".codex/AGENTS.override.md"
    override.parent.mkdir()
    override.write_text(contents)
    first = installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    state = tmp_path / ".config/hapax/agent-instructions"
    before = (state / "current.json").stat()
    second = installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    third = installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    assert third == second == first
    after = (state / "current.json").stat()
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
    assert list((state / "backups").iterdir()) == [Path(first["rollback"])]
    installer.restore(Path(first["rollback"]))
    assert not (override.parent / "AGENTS.md").exists()
    assert override.read_text() == contents


def test_dangling_override_requires_reconciliation_before_install(tmp_path):
    override = tmp_path / ".codex/AGENTS.override.md"
    override.parent.mkdir()
    override.symlink_to("missing")
    with pytest.raises(ValueError, match="reconcile"):
        installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    assert not (tmp_path / ".claude/CLAUDE.md").exists()


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


@pytest.mark.parametrize("upgrade", [False, True])
def test_receipt_publication_preserves_intervening_edit(tmp_path, monkeypatch, upgrade):
    if upgrade:
        installer.install(ROOT, tmp_path, revision="predecessor", apply=True)
    state = tmp_path / ".config/hapax/agent-instructions"
    current = state / "current.json"
    real_write = installer.atomic_write
    edited = b'{"foreign_edit": true}\n'
    injected = False

    def write_with_intervening_receipt_edit(path, body):
        nonlocal injected
        real_write(path, body)
        if path == state / "pending.json" and not injected:
            injected = True
            current.write_bytes(edited)

    monkeypatch.setattr(installer, "atomic_write", write_with_intervening_receipt_edit)
    monkeypatch.setattr(
        "sys.argv",
        [
            "installer",
            "--source",
            str(ROOT),
            "--home",
            str(tmp_path),
            "--source-revision",
            "successor",
            "--apply",
        ],
    )
    assert installer.main() == 1
    assert injected
    assert current.read_bytes() == edited
    pending = json.loads((state / "pending.json").read_text())
    assert Path(pending["backup"]).is_dir()
    assert (Path(pending["backup"]) / "preimages.json").is_file()
    with pytest.raises(ValueError, match="transaction output changed"):
        installer.recover_pending(state, Path(pending["backup"]))
    assert current.read_bytes() == edited


@pytest.mark.parametrize("malformed", [[], None, 42, "receipt"])
def test_check_receipt_shape_reports_reconciliation_without_mutation(
    tmp_path, monkeypatch, capsys, malformed
):
    installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    current = tmp_path / ".config/hapax/agent-instructions/current.json"
    body = json.dumps(malformed).encode()
    current.write_bytes(body)
    monkeypatch.setattr(
        "sys.argv",
        [
            "installer",
            "--source",
            str(ROOT),
            "--home",
            str(tmp_path),
            "--source-revision",
            "fixture",
            "--check",
        ],
    )
    assert installer.main() == 1
    error = capsys.readouterr().err
    assert str(current) in error
    assert "receipt must be a JSON object" in error
    assert "reconcile" in error
    assert current.read_bytes() == body


@pytest.mark.parametrize("upgrade", [False, True])
def test_receipt_readback_preserves_unknown_postpublication_bytes(tmp_path, monkeypatch, upgrade):
    if upgrade:
        installer.install(ROOT, tmp_path, revision="predecessor", apply=True)
    state = tmp_path / ".config/hapax/agent-instructions"
    current = state / "current.json"
    real_write = installer.atomic_write
    foreign = b'{"unexpected_postpublication": true}\n'
    injected = False

    def corrupt_receipt(path, body):
        nonlocal injected
        real_write(path, body)
        if path == current:
            injected = True
            current.write_bytes(foreign)

    monkeypatch.setattr(installer, "atomic_write", corrupt_receipt)
    monkeypatch.setattr(
        "sys.argv",
        [
            "installer",
            "--source",
            str(ROOT),
            "--home",
            str(tmp_path),
            "--source-revision",
            "successor",
            "--apply",
        ],
    )
    assert installer.main() == 1
    assert injected
    assert current.read_bytes() == foreign
    assert (state / "pending.json").is_file()


@pytest.mark.parametrize("malformed", [[], None, 42, "receipt"])
def test_rollback_receipt_shape_reports_reconciliation(tmp_path, monkeypatch, capsys, malformed):
    receipt = installer.install(ROOT, tmp_path, revision="fixture", apply=True)
    state = tmp_path / ".config/hapax/agent-instructions"
    current = state / "current.json"
    body = json.dumps(malformed).encode()
    current.write_bytes(body)
    monkeypatch.setattr(
        "sys.argv",
        ["installer", "--home", str(tmp_path), "--restore-backup", receipt["rollback"]],
    )
    assert installer.main() == 1
    error = capsys.readouterr().err
    assert str(current) in error
    assert "receipt must be a JSON object" in error and "reconcile" in error
    assert current.read_bytes() == body
    assert not (state / "pending.json").exists()
