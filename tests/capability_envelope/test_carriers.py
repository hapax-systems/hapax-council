"""Source-only carrier checks: no harness, systemd, OCI runtime or provider is invoked."""

import copy
import importlib
import json
import socket

import pytest

from shared.capability_envelope import EnvelopeDeclaration, EnvelopeRefusal
from shared.capability_envelope import render as render_envelope

UNIT = {
    "memory_high": 64 * 1024 * 1024,
    "memory_max": 128 * 1024 * 1024,
    "memory_swap_max": 0,
    "runtime_max_sec": 30,
}


def render(*args, **kwargs):
    return render_envelope(
        *args,
        oci_uid=100000,
        oci_gid=100000,
        oci_launcher_uid=1000,
        oci_launcher_gid=1000,
        **kwargs,
    )


def declaration(**overrides):
    return EnvelopeDeclaration.model_validate(
        {"harness": "claude", "argv": ["/usr/bin/true"], "unit": UNIT, **overrides}
    )


@pytest.mark.parametrize("carrier", ["t1", "t2", "t3"])
def test_missing_unit_refuses_before_writing(tmp_path, carrier):
    decl = EnvelopeDeclaration(harness="claude", argv=("/usr/bin/true",))
    with pytest.raises(EnvelopeRefusal, match="unit"):
        render(decl, run_root=tmp_path / "run", carrier=carrier)
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize("field", ["memory_max", "runtime_max_sec"])
@pytest.mark.parametrize("carrier", ["t1", "t2", "t3"])
def test_missing_hard_bound_refuses(tmp_path, field, carrier):
    unit = dict(UNIT)
    del unit[field]
    with pytest.raises((EnvelopeRefusal, ValueError), match=field):
        render(declaration(unit=unit), run_root=tmp_path / "run", carrier=carrier)
    assert not (tmp_path / "run").exists()


def test_t1_has_exact_unit_limits_and_no_restart(tmp_path):
    result = render(declaration(), run_root=tmp_path / "run", carrier="t1")
    assert result.argv[:5] == ("systemd-run", "--user", "--wait", "--pipe", "--collect")
    assert result.unit_properties == (
        "MemoryHigh=67108864",
        "MemoryMax=134217728",
        "MemorySwapMax=0",
        "OOMPolicy=kill",
        "RuntimeMaxSec=30",
        "Restart=no",
        "KillMode=control-group",
    )
    for prop in result.unit_properties:
        assert f"--property={prop}" in result.argv
    assert "--unshare-net" in result.argv


@pytest.mark.parametrize("carrier", ["t1", "t2", "t3"])
def test_declared_mount_only_and_no_host_network(tmp_path, carrier):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    decl = declaration(channels=[{"name": "inbox", "kind": "mount", "source": inbox}])
    result = render(decl, run_root=tmp_path / "run", carrier=carrier)
    surface = json.loads(result.channel_bytes)
    assert {
        "kind": "bind",
        "source": str(inbox),
        "target": "/channels/inbox",
        "access": "ro",
    } in surface["mounts"]
    assert surface["endpoints"] == []
    assert surface["egress"] == []
    assert all(m["source"] != "/var/run/docker.sock" for m in surface["mounts"])
    if carrier == "t3":
        assert {"type": "network"} in result.oci_spec["linux"]["namespaces"]
    else:
        assert "--unshare-net" in result.argv


@pytest.mark.parametrize("carrier", ["t1", "t2", "t3"])
def test_unenforceable_network_endpoint_refuses(tmp_path, carrier):
    decl = declaration(
        channels=[{"name": "model", "kind": "network", "endpoint": "https://example.invalid"}]
    )
    with pytest.raises(EnvelopeRefusal, match="egress"):
        render(decl, run_root=tmp_path / "run", carrier=carrier)
    assert not (tmp_path / "run").exists()


def test_t3_is_rootless_and_carries_same_masks_as_t2(tmp_path):
    work = tmp_path / "checkout"
    work.mkdir()
    for name in ("AGENTS.md", ".mcp.json", "code.py"):
        (work / name).write_text("sentinel")
    (work / ".claude").mkdir()
    (work / ".claude" / "settings.json").write_text("sentinel")
    decl = declaration(workdir=work, declared_work_files=["AGENTS.md"])
    t2 = render(decl, run_root=tmp_path / "t2", carrier="t2")
    t3 = render(decl, run_root=tmp_path / "t3", carrier="t3")
    assert set(t2.masked) == set(t3.masked) == {".mcp.json", ".claude"}
    spec = t3.oci_spec
    assert spec["root"] == {"path": "rootfs", "readonly": True}
    assert spec["process"]["user"] == {"uid": 1, "gid": 1}
    assert spec["process"]["noNewPrivileges"] is True
    assert spec["process"]["capabilities"]["bounding"] == []
    assert {"type": "user"} in spec["linux"]["namespaces"]
    # Host bindings are selected at enrolment, never guessed from this renderer's host.
    assert spec["linux"]["uidMappings"][1] == {"containerID": 1, "hostID": 100000, "size": 1}
    masks = {m["destination"]: m for m in spec["mounts"]}
    assert masks["/work/.claude"]["type"] == "tmpfs"
    assert "ro" in masks["/work/.claude"]["options"]
    assert masks["/work/.mcp.json"]["source"].endswith("/empty")
    assert "/work/AGENTS.md" not in masks
    assert json.loads((tmp_path / "t3" / "config.json").read_text()) == spec


@pytest.mark.parametrize("carrier", ["t1", "t2", "t3"])
@pytest.mark.parametrize("flag", ["--bare", "--bare=true", "--api-key-file=/synthetic/key"])
def test_billing_flags_need_explicit_api_declaration(tmp_path, carrier, flag):
    decl = declaration(argv=["claude", flag])
    with pytest.raises(EnvelopeRefusal, match="billing"):
        render(decl, run_root=tmp_path / "refused", carrier=carrier)
    render(
        decl.model_copy(update={"billing_surface": "api"}),
        run_root=tmp_path / "api",
        carrier=carrier,
    )


@pytest.mark.parametrize("carrier", ["t1", "t2", "t3"])
@pytest.mark.parametrize("mutation", ["mount", "network", "access"])
def test_conformance_reads_actual_carrier_not_facts(tmp_path, carrier, mutation):
    module = importlib.import_module("shared.capability_envelope.render")
    decl = declaration()
    result = render(decl, run_root=tmp_path / "run", carrier=carrier)
    if carrier == "t3":
        spec = copy.deepcopy(result.oci_spec)
        if mutation == "mount":
            spec["mounts"].append(
                {
                    "source": "/undeclared",
                    "destination": "/leak",
                    "type": "bind",
                    "options": ["rbind", "rprivate", "ro", "rro"],
                }
            )
        elif mutation == "network":
            spec["linux"]["namespaces"] = [
                n for n in spec["linux"]["namespaces"] if n["type"] != "network"
            ]
        else:
            spec["mounts"][0]["options"] = ["rbind", "rw"]
        broken = result.model_copy(update={"oci_spec": spec})
    else:
        argv = list(result.argv)
        if mutation == "mount":
            i = len(argv) - len(decl.argv) - 1
            argv[i:i] = ["--ro-bind", "/undeclared", "/leak"]
        elif mutation == "network":
            argv.remove("--unshare-net")
        else:
            argv[argv.index("--ro-bind")] = "--bind"
        broken = result.model_copy(update={"argv": tuple(argv)})
    with pytest.raises(EnvelopeRefusal, match="conformance"):
        module.check_conformance(decl, broken)


def test_render_invokes_conformance_before_return(tmp_path, monkeypatch):
    module = importlib.import_module("shared.capability_envelope.render")

    def refuse(*args):
        raise EnvelopeRefusal("conformance injected discrepancy")

    monkeypatch.setattr(module, "check_conformance", refuse)
    with pytest.raises(EnvelopeRefusal, match="injected"):
        render(declaration(), run_root=tmp_path / "run", carrier="t3")


@pytest.mark.parametrize("carrier", ["t1", "t2", "t3"])
def test_declared_unix_endpoint_is_bound_exactly(tmp_path, carrier):
    endpoint = tmp_path / "model.sock"
    with socket.socket(socket.AF_UNIX) as sock:
        sock.bind(str(endpoint))
        decl = declaration(channels=[{"name": "model", "kind": "unix", "source": endpoint}])
        result = render(decl, run_root=tmp_path / "run", carrier=carrier)
        surface = json.loads(result.channel_bytes)
        assert surface["endpoints"] == ["unix:/channels/model"]
        assert surface["mounts"][-1] == {
            "kind": "bind",
            "source": str(endpoint),
            "target": "/channels/model",
            "access": "ro",
        }


@pytest.mark.parametrize("uid", [None, 0, -1, True, 2**32])
def test_oci_requires_explicit_valid_subordinate_id(tmp_path, uid):
    with pytest.raises(EnvelopeRefusal, match="subordinate"):
        render_envelope(
            declaration(),
            run_root=tmp_path / "run",
            carrier="t3",
            oci_uid=uid,
            oci_gid=100000,
            oci_launcher_uid=1000,
            oci_launcher_gid=1000,
        )
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize("mutation", ["root", "hook", "file", "user", "mapping"])
def test_oci_cannot_add_imports_outside_mounts(tmp_path, mutation):
    from shared.capability_envelope import check_conformance

    decl = declaration()
    result = render(decl, run_root=tmp_path / "run", carrier="t3")
    spec = copy.deepcopy(result.oci_spec)
    if mutation == "root":
        spec["root"]["path"] = "/"
    elif mutation == "hook":
        spec["hooks"] = {"prestart": [{"path": "/undeclared-hook"}]}
    elif mutation == "file":
        (result.run_root / "rootfs" / "AGENTS.md").write_text("undeclared")
    elif mutation == "user":
        spec["process"]["user"]["uid"] = 0
    else:
        spec["linux"]["uidMappings"][1]["hostID"] = 0
    with pytest.raises(EnvelopeRefusal, match="conformance"):
        check_conformance(decl, result.model_copy(update={"oci_spec": spec}))


def test_actual_rendered_mount_mismatch_refuses_before_spec_is_published(tmp_path, monkeypatch):
    module = importlib.import_module("shared.capability_envelope.carriers")
    original = module.make_oci_spec

    def extra_mount(*args, **kwargs):
        spec = original(*args, **kwargs)
        spec["mounts"].append(
            {
                "source": "/undeclared",
                "destination": "/leak",
                "type": "bind",
                "options": ["rbind", "rprivate", "ro", "rro"],
            }
        )
        return spec

    monkeypatch.setattr(module, "make_oci_spec", extra_mount)
    with pytest.raises(EnvelopeRefusal, match="conformance"):
        render(declaration(), run_root=tmp_path / "run", carrier="t3")
    assert not (tmp_path / "run" / "config.json").exists()


def test_published_hashes_cover_final_carrier(tmp_path):
    import hashlib

    for carrier in ("t1", "t2", "t3"):
        result = render(declaration(), run_root=tmp_path / carrier, carrier=carrier)
        assert (
            result.facts["argv_sha256"]
            == hashlib.sha256("\0".join(result.argv).encode()).hexdigest()
        )
        if carrier == "t3":
            raw = (result.run_root / "config.json").read_bytes()
            assert result.facts["oci_spec_sha256"] == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("field", ["memory_high", "memory_max", "runtime_max_sec"])
@pytest.mark.parametrize("value", [0, -1, True, "128M"])
def test_limits_are_positive_integers(field, value):
    with pytest.raises(ValueError, match=field):
        declaration(unit={**UNIT, field: value})


def test_t1_t3_execute_remains_outside_this_source_carrier(tmp_path, monkeypatch):
    from shared.capability_envelope import EnvelopeCarrierError, execute

    module = importlib.import_module("shared.capability_envelope.render")

    def unexpected(*args, **kwargs):
        pytest.fail("source carrier attempted activation")

    monkeypatch.setattr(module.subprocess, "run", unexpected)
    for carrier in ("t1", "t3"):
        result = render(declaration(), run_root=tmp_path / carrier, carrier=carrier)
        with pytest.raises(EnvelopeCarrierError, match="governed"):
            execute(result, timeout=30)


def test_oci_read_only_binds_cover_submounts(tmp_path):
    result = render(declaration(), run_root=tmp_path / "run", carrier="t3")
    for mount in result.oci_spec["mounts"]:
        if mount["type"] == "bind" and "ro" in mount["options"]:
            assert "rro" in mount["options"]


def test_oci_mount_cannot_smuggle_extra_bindings(tmp_path):
    from shared.capability_envelope import check_conformance

    decl = declaration()
    result = render(decl, run_root=tmp_path / "run", carrier="t3")
    spec = copy.deepcopy(result.oci_spec)
    spec["mounts"][0]["uidMappings"] = [{"containerID": 0, "hostID": 0, "size": 1000000}]
    with pytest.raises(EnvelopeRefusal, match="conformance"):
        check_conformance(decl, result.model_copy(update={"oci_spec": spec}))


def test_a_changed_declaration_fails_channel_comparison(tmp_path):
    from shared.capability_envelope import DeclaredChannel, check_conformance

    decl = declaration()
    result = render(decl, run_root=tmp_path / "run")
    changed = decl.model_copy(
        update={"channels": (DeclaredChannel(name="new", kind="mount", source=tmp_path),)}
    )
    with pytest.raises(EnvelopeRefusal, match="conformance"):
        check_conformance(changed, result)


def test_bwrap_readback_requires_environment_clear(tmp_path):
    from shared.capability_envelope import check_conformance

    decl = declaration()
    result = render(decl, run_root=tmp_path / "run")
    argv = tuple(a for a in result.argv if a != "--clearenv")
    with pytest.raises(EnvelopeRefusal, match="conformance"):
        check_conformance(decl, result.model_copy(update={"argv": argv}))


@pytest.mark.parametrize(
    "config", [".claude.json", ".claude/.claude.json", ".claude/settings.json"]
)
def test_generated_config_cannot_add_undeclared_endpoints_or_hooks(tmp_path, config):
    from shared.capability_envelope import check_conformance

    decl = declaration()
    result = render(decl, run_root=tmp_path / "run", carrier="t3")
    path = result.run_root / "home" / config
    value = json.loads(path.read_text())
    value["hooks" if "settings" in config else "mcpServers"] = {"undeclared": {"command": "leak"}}
    path.write_text(json.dumps(value))
    with pytest.raises(EnvelopeRefusal, match="conformance"):
        check_conformance(decl, result)
