import hashlib
import json
from pathlib import Path

import pytest

from shared.capability_load_set import observe_load_set
from shared.platform_capability_registry import NativeLoadFile, NativeLoadSet


def fixture(tmp_path):
    native = tmp_path / "home/.codex"
    native.mkdir(parents=True)
    body = b"shared native policy\n"
    (native / "AGENTS.md").write_bytes(body)
    declaration = NativeLoadSet(
        native_home=".codex",
        home_env="CODEX_HOME",
        memory_scope="session",
        files=[
            NativeLoadFile(
                root="native_home",
                path="AGENTS.md",
                kind="instructions",
                sha256=hashlib.sha256(body).hexdigest(),
            )
        ],
        source_refs=["fixture"],
    )
    return native, declaration


def test_presence_never_promotes_to_native_loading(tmp_path):
    native, declaration = fixture(tmp_path)
    result = observe_load_set(declaration, home=native.parent, project=tmp_path, env={})
    assert result["files"][0]["state"] == "match"
    assert result["native_loading"] == "unobserved"
    assert result["extensions"]["plugins"] is None
    assert result["loading_flags"] is None
    assert result["may_authorize"] is False


def test_native_receipt_join_requires_exact_declared_bytes(tmp_path):
    native, declaration = fixture(tmp_path)
    receipt = {"path": str(native / "AGENTS.md"), "sha256": declaration.files[0].sha256}
    args = {"home": native.parent, "project": tmp_path, "env": {}}
    assert (
        observe_load_set(declaration, **args, native_receipts=[receipt])["native_loading"]
        == "observed"
    )
    receipt["sha256"] = "0" * 64
    result = observe_load_set(declaration, **args, native_receipts=[receipt])
    assert result["native_loading"] == "unexpected_load"
    assert len(result["unexpected_load"]) == 1


def test_override_and_missing_declared_file_are_visible_without_claiming_load(tmp_path):
    native, declaration = fixture(tmp_path)
    (native / "AGENTS.override.md").write_text("ambient policy")
    (native / "AGENTS.md").unlink()
    result = observe_load_set(declaration, home=native.parent, project=tmp_path, env={})
    assert result["problems"] == ["missing:native_home:AGENTS.md"]
    assert result["unexpected_present"] == [str(native / "AGENTS.override.md")]
    assert result["unexpected_load"] == []


def test_changed_native_home_is_observed_not_ignored(tmp_path):
    native, declaration = fixture(tmp_path)
    result = observe_load_set(
        declaration,
        home=native.parent,
        project=tmp_path,
        env={"CODEX_HOME": str(tmp_path / "other")},
    )
    assert result["files"][0]["state"] == "missing"


def test_missing_receipt_hash_never_matches_unknown_declaration(tmp_path):
    native, declaration = fixture(tmp_path)
    declaration.files[0].sha256 = None
    result = observe_load_set(
        declaration,
        home=native.parent,
        project=tmp_path,
        env={},
        native_receipts=[{"path": str(native / "AGENTS.md")}],
    )
    assert result["native_loading"] == "incomplete"


def test_configuration_only_is_not_instruction_loading(tmp_path):
    native, declaration = fixture(tmp_path)
    declaration.files[0].kind = "configuration"
    result = observe_load_set(
        declaration, home=native.parent, project=tmp_path, env={}, native_receipts=[]
    )
    assert result["native_loading"] == "incomplete"


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("alias", [False, True])
@pytest.mark.parametrize("other_digest", [None, "0" * 64])
def test_conflicting_resolved_declarations_never_collapse_to_observed(
    tmp_path, reverse, alias, other_digest
):
    native, declaration = fixture(tmp_path)
    project = native
    if alias:
        project = tmp_path / "project-alias"
        project.symlink_to(native, target_is_directory=True)
    declaration.files.append(
        NativeLoadFile(root="project", path="AGENTS.md", kind="instructions", sha256=other_digest)
    )
    witness = {"path": str(native / "AGENTS.md"), "sha256": declaration.files[0].sha256}
    if reverse:
        declaration.files.reverse()
    with pytest.raises(ValueError, match="conflicting native load declarations.*next action"):
        observe_load_set(
            declaration,
            home=native.parent,
            project=project,
            env={"CODEX_HOME": str(project)},
            native_receipts=[witness],
        )


def test_identical_expectations_for_one_resolved_file_can_share_native_witness(tmp_path):
    native, declaration = fixture(tmp_path)
    expected = declaration.files[0].sha256
    declaration.files.append(
        NativeLoadFile(root="project", path="AGENTS.md", kind="instructions", sha256=expected)
    )
    observation = observe_load_set(
        declaration,
        home=native.parent,
        project=native,
        env={},
        native_receipts=[{"path": str(native / "AGENTS.md"), "sha256": expected}],
    )
    assert observation["native_loading"] == "observed"
    assert len(observation["files"]) == 2
    assert observation["may_authorize"] is False


@pytest.mark.parametrize("path", ["/etc/AGENTS.md", "../AGENTS.md"])
def test_declaration_cannot_escape_named_root(path):
    with pytest.raises(ValueError, match="declared root"):
        NativeLoadFile(root="native_home", path=path, kind="instructions")


def test_registry_instruction_hashes_match_authored_payloads():
    import importlib.util

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "installer", root / "scripts/install-agent-instructions.py"
    )
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    rendered = installer.render(root)
    registry = json.loads((root / "config/platform-capability-registry.json").read_text())
    count = 0
    for route in registry["routes"]:
        declaration = route.get("native_load_set")
        if declaration is None:
            continue
        count += 1
        for file in declaration["files"]:
            if file["kind"] == "instructions":
                body = (
                    (root / file["path"]).read_bytes()
                    if file["root"] == "project"
                    else rendered[route["platform"]][1]
                )
                assert hashlib.sha256(body).hexdigest() == file["sha256"], route["route_id"]
    assert count == 11


def test_identical_bytes_in_different_native_homes_keep_binding_provenance(tmp_path):
    native, declaration = fixture(tmp_path)
    declaration.source_refs = ["config/platform-capability-registry.json"]
    other = tmp_path / "other"
    other.mkdir()
    (other / "AGENTS.md").write_bytes((native / "AGENTS.md").read_bytes())
    observations = [
        observe_load_set(declaration, home=native.parent, project=tmp_path, env=env)
        for env in ({}, {"CODEX_HOME": str(other)})
    ]
    assert all(o["files"][0]["state"] == "match" for o in observations)
    assert observations[0]["files"][0]["sha256"] == observations[1]["files"][0]["sha256"]
    assert [o["resolved_roots"]["native_home"] for o in observations] == [
        str(native.resolve()),
        str(other.resolve()),
    ]
    assert [o["files"][0]["observed_path"] for o in observations] == [
        str((native / "AGENTS.md").resolve()),
        str((other / "AGENTS.md").resolve()),
    ]
    assert observations[0]["declaration_sha256"] == observations[1]["declaration_sha256"]
    assert observations[0]["source_refs"] == declaration.source_refs
    declaration.source_refs = ["different-authority.md"]
    changed = observe_load_set(declaration, home=native.parent, project=tmp_path, env={})
    assert changed["declaration_sha256"] != observations[0]["declaration_sha256"]
    assert changed["source_refs"] == declaration.source_refs
    assert changed["may_authorize"] is False
