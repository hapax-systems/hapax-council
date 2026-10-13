"""Declaration and T2 render slice of #5055; no carrier or provider is executed."""

import socket
from pathlib import Path

import pytest

from shared.capability_envelope import EnvelopeDeclaration, EnvelopeRefusal, render

UNIT = {
    "memory_high": 64 * 1024 * 1024,
    "memory_max": 128 * 1024 * 1024,
    "memory_swap_max": 0,
    "runtime_max_sec": 30,
}


def declaration(**overrides):
    return EnvelopeDeclaration.model_validate(
        {
            "harness": "claude",
            "argv": ["/usr/bin/true"],
            "unit": UNIT,
            "billing_surface": "api",
            **overrides,
        }
    )


def test_missing_unit_refuses_before_writing(tmp_path):
    decl = EnvelopeDeclaration(harness="claude", argv=("/usr/bin/true",), billing_surface="api")
    with pytest.raises(EnvelopeRefusal, match="unit"):
        render(decl, run_root=tmp_path / "run")
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize(
    "field", ["memory_high", "memory_max", "memory_swap_max", "runtime_max_sec"]
)
def test_missing_hard_bound_refuses(tmp_path, field):
    unit = dict(UNIT)
    del unit[field]
    with pytest.raises((EnvelopeRefusal, ValueError), match=field):
        render(declaration(unit=unit), run_root=tmp_path / "run")
    assert not (tmp_path / "run").exists()


def test_unenforceable_network_endpoint_refuses(tmp_path):
    decl = declaration(
        channels=[{"name": "model", "kind": "network", "endpoint": "https://example.invalid"}]
    )
    with pytest.raises(EnvelopeRefusal, match="egress"):
        render(decl, run_root=tmp_path / "run")
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize("flag", ["--bare", "--bare=true", "--api-key-file=/synthetic/key"])
def test_billing_flags_need_explicit_api_declaration(tmp_path, flag):
    decl = declaration(argv=["claude", flag], billing_surface="subscription")
    with pytest.raises(EnvelopeRefusal, match="billing"):
        render(decl, run_root=tmp_path / "refused")
    render(
        decl.model_copy(update={"billing_surface": "api"}),
        run_root=tmp_path / "api",
    )


@pytest.mark.parametrize("field", ["memory_high", "memory_max", "runtime_max_sec"])
@pytest.mark.parametrize("value", [0, -1, True, "128M"])
def test_limits_are_positive_integers(field, value):
    with pytest.raises(ValueError, match=field):
        declaration(unit={**UNIT, field: value})


@pytest.mark.parametrize(
    "case",
    [
        "high-over-max",
        "home-env",
        "config-env",
        "duplicate-channel",
        "missing-source",
        "channel-endpoint",
        "non-socket",
        "root-channel",
        "home-channel",
    ],
)
def test_declaration_refusal_before_artifacts(tmp_path, case):
    from pathlib import Path

    source = tmp_path / "source"
    source.write_text("ordinary file")
    channel = {"name": "input", "kind": "mount", "source": source}
    updates = {
        "high-over-max": {"unit": {**UNIT, "memory_high": UNIT["memory_max"] + 1}},
        "home-env": {"env": {"HOME": "/private"}},
        "config-env": {"env": {"CLAUDE_CONFIG_DIR": "/private"}},
        "duplicate-channel": {"channels": [channel, channel]},
        "missing-source": {"channels": [{"name": "input", "kind": "mount"}]},
        "channel-endpoint": {"channels": [{**channel, "endpoint": "undeclared"}]},
        "non-socket": {"channels": [{**channel, "kind": "unix"}]},
        "root-channel": {"channels": [{**channel, "source": Path("/")}]},
        "home-channel": {"channels": [{**channel, "source": Path.home()}]},
    }[case]
    with pytest.raises(EnvelopeRefusal, match="next action"):
        render(declaration(**updates), run_root=tmp_path / "run")
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize(
    "key", ["XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"]
)
def test_reserved_xdg_environment_refuses_before_artifacts(tmp_path, key):
    with pytest.raises(EnvelopeRefusal, match="config environment.*next action"):
        render(declaration(env={key: "/private"}), run_root=tmp_path / "run")
    assert not (tmp_path / "run").exists()


def test_reserved_codex_environment_refuses_before_artifacts(tmp_path):
    with pytest.raises(EnvelopeRefusal, match="config environment.*next action"):
        render(
            declaration(harness="codex", env={"CODEX_HOME": "/private"}), run_root=tmp_path / "run"
        )
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize("value", [-1, True, "0"])
def test_swap_limit_is_a_nonnegative_integer(value):
    with pytest.raises(ValueError, match="memory_swap_max"):
        declaration(unit={**UNIT, "memory_swap_max": value})


@pytest.mark.parametrize("field,value", [("oom_policy", "continue"), ("restart", "always")])
def test_unit_lifecycle_cannot_be_overridden(field, value):
    with pytest.raises(ValueError, match=field):
        declaration(unit={**UNIT, field: value})


def test_render_revalidates_copied_declaration_before_artifacts(tmp_path):
    original = declaration()
    decl = original.model_copy(
        update={"unit": original.unit.model_copy(update={"runtime_max_sec": 0})}
    )
    with pytest.raises(ValueError, match="runtime_max_sec"):
        render(decl, run_root=tmp_path / "run")
    assert not (tmp_path / "run").exists()


def test_declared_channels_render_read_only_with_private_network(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    endpoint = tmp_path / "model.sock"
    with socket.socket(socket.AF_UNIX) as sock:
        sock.bind(str(endpoint))
        decl = declaration(
            channels=[
                {"name": "inbox", "kind": "mount", "source": inbox},
                {"name": "model", "kind": "unix", "source": endpoint},
            ]
        )
        result = render(decl, run_root=tmp_path / "run")
    argv = result.argv
    assert argv.count("--unshare-net") == 1
    assert "--share-net" not in argv
    channels = [argv[i - 2 : i + 1] for i, arg in enumerate(argv) if arg.startswith("/channels/")]
    assert channels == [
        ("--ro-bind", str(inbox), "/channels/inbox"),
        ("--ro-bind", str(endpoint), "/channels/model"),
    ]
    assert "/var/run/docker.sock" not in argv


def test_generated_home_and_masked_directories_are_read_only(tmp_path):
    work = tmp_path / "checkout"
    (work / ".claude").mkdir(parents=True)
    (work / "AGENTS.md").write_text("masked")
    (work / "CLAUDE.md").write_text("declared")
    decl = declaration(workdir=work, declared_work_files=["CLAUDE.md"])
    result = render(decl, run_root=tmp_path / "run")
    argv = result.argv
    home = argv.index(str(result.run_root / "home"))
    assert argv[home - 1 : home + 2] == ("--ro-bind", str(result.run_root / "home"), "/home/job")
    masked_dir = argv.index("/work/.claude")
    assert argv[masked_dir - 1 : masked_dir + 3] == (
        "--tmpfs",
        "/work/.claude",
        "--remount-ro",
        "/work/.claude",
    )
    assert set(result.masked) == {".claude", "AGENTS.md"}
    masked_file = argv.index("/work/AGENTS.md")
    assert argv[masked_file - 2 : masked_file + 1] == (
        "--ro-bind",
        str(result.run_root / "empty"),
        "/work/AGENTS.md",
    )
    assert "/work/CLAUDE.md" not in argv


def test_etc_bindings_are_resolved_at_render_time_without_host_resolver(tmp_path, monkeypatch):
    import importlib

    module = importlib.import_module("shared.capability_envelope.render")
    monkeypatch.setattr(module, "_ETC_ALLOW", ("hosts", "hapax-envelope-absent"))
    exists = Path.exists
    monkeypatch.setattr(
        Path,
        "exists",
        lambda path: False if str(path) == "/etc/hapax-envelope-absent" else exists(path),
    )
    argv = render(declaration(), run_root=tmp_path / "run").argv
    hosts = argv.index("/etc/hosts")
    assert argv[hosts - 1 : hosts + 2] == ("--ro-bind", "/etc/hosts", "/etc/hosts")
    assert "/etc/hapax-envelope-absent" not in argv
    assert "/run/systemd/resolve" not in argv
    assert "--ro-bind-try" not in argv


def test_relative_run_root_is_made_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = render(declaration(), run_root=Path("run"))
    assert result.run_root == tmp_path / "run"
