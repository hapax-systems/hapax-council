"""The probe turns a one-off transcript into a command; these pin that it can fail.

A recheck that only passes is not a recheck. Every check here is driven into its
failure branch and asserted to name a next action, because the probe's whole purpose
is to be run by an operator who is not the author and who needs to be told what to do.
"""

from __future__ import annotations

import ast
import importlib.machinery
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest  # noqa: TC002 — a test module's pytest import stays at runtime

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "hapax-research-desk-probe"


def _load_module() -> types.ModuleType:
    loader = importlib.machinery.SourceFileLoader("hapax_research_desk_probe", str(_SCRIPT_PATH))
    spec = importlib.util.spec_from_loader("hapax_research_desk_probe", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec: `from __future__ import annotations` makes dataclass field
    # types strings, and @dataclass resolves them through sys.modules[cls.__module__].
    # Without this the probe's first @dataclass raises AttributeError on None at import.
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


probe = _load_module()


def test_the_probe_is_executable() -> None:
    assert _SCRIPT_PATH.stat().st_mode & 0o111, "the operator runs this directly"


def test_every_failing_check_names_a_next_action(tmp_path: Path) -> None:
    results = [
        probe.CheckResult("a", False, "broke", "do the thing"),
        probe.CheckResult("b", True, "fine"),
    ]
    rendered = probe.render(results)
    assert "FAIL a" in rendered
    assert "next action: do the thing" in rendered
    assert "1 of 2 checks FAILED" in rendered


def test_a_clean_run_renders_a_pass_count() -> None:
    rendered = probe.render([probe.CheckResult("a", True, "fine")])
    assert "1/1 checks passed" in rendered


def test_origin_listening_fails_closed_on_a_dead_port() -> None:
    result = probe.check_origin_listening(probe.ProbeConfig(port=1))
    assert result.ok is False
    assert "systemctl --user start" in result.next_action


def test_tailnet_host_is_accepted_and_local_mode_forces_loopback() -> None:
    remote = probe.ProbeConfig(remote_host="desk.example.ts.net")
    assert remote.target_base == "https://desk.example.ts.net"
    local = probe.ProbeConfig(remote_host="desk.example.ts.net", local_only=True)
    assert local.target_base == "http://127.0.0.1:8790"


def test_ledger_check_reports_a_torn_line_with_the_repair_action(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    path.write_text('{"tool": "fetch_request"}\n{"torn\n', encoding="utf-8")
    result = probe.check_ledger(probe.ProbeConfig(ledger_path=path))
    assert result.ok is False
    assert "[2]" in result.detail
    assert str(path) in result.next_action


def test_ledger_check_treats_an_absent_ledger_as_fine(tmp_path: Path) -> None:
    result = probe.check_ledger(probe.ProbeConfig(ledger_path=tmp_path / "never-written.jsonl"))
    assert result.ok is True
    assert "no call has been served" in result.detail


def test_missing_key_fails_the_spelling_checks() -> None:
    results = probe.check_key_spellings(probe.ProbeConfig(), None)
    assert [r.name for r in results] == ["bearer_accepted", "x_api_key_accepted"]
    assert all(not r.ok and not r.skipped for r in results)
    assert all("hapax-secret --where" in r.next_action for r in results)


def test_default_key_checks_only_target_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    targets: list[str] = []

    class Response:
        status_code = 200
        text = "hapax-research-desk"

    def post(url: str, **kwargs: object) -> Response:
        targets.append(url)
        return Response()

    monkeypatch.setattr(httpx, "post", post)
    results = probe.check_key_spellings(probe.ProbeConfig(), "test-only-key")
    assert all(r.ok for r in results)
    assert len(targets) == 2
    assert all(url.startswith("http://127.0.0.1:8790/") for url in targets)


def test_public_host_is_refused_before_a_key_can_be_sent() -> None:
    with pytest.raises(probe.ProbeConfigError):
        probe.ProbeConfig(remote_host="desk.hapaxrnd.com")


def test_main_refuses_public_host_before_loading_key(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden() -> None:
        raise AssertionError("key read before target validation")

    monkeypatch.setattr(probe, "load_key", forbidden)
    assert probe.main(["--tailnet-host", "desk.hapaxrnd.com"]) == 2


def test_home_cannot_substitute_the_probe_credential_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os
    import pwd
    import subprocess

    seen: list[str] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.append(argv[0])
        return subprocess.CompletedProcess(argv, 0, "test-key-with-enough-entropy", "")

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    assert probe.load_key()
    assert seen == [str(Path(pwd.getpwuid(os.getuid()).pw_dir) / ".local/bin/hapax-secret")]


def test_local_mode_runs_no_check_that_leaves_the_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """The local probe still checks auth, but every HTTP target stays on loopback."""
    targets: list[str] = []

    def target_health(config: object) -> probe.CheckResult:
        targets.append(config.target_base)
        return probe.CheckResult("target_health", True)

    def refusals(config: object) -> list[probe.CheckResult]:
        targets.append(config.target_base)
        return [probe.CheckResult("refusals", True)]

    def spellings(config: object, key: object) -> list[probe.CheckResult]:
        targets.append(config.target_base)
        return [probe.CheckResult("spellings", True)]

    monkeypatch.setattr(probe, "check_target_health", target_health)
    monkeypatch.setattr(probe, "check_refusals", refusals)
    monkeypatch.setattr(probe, "check_key_spellings", spellings)
    monkeypatch.setattr(probe, "check_units_installed", lambda: probe.CheckResult("u", True))
    monkeypatch.setattr(probe, "check_units_active", lambda: probe.CheckResult("a", True))

    results = probe.run_checks(probe.ProbeConfig(port=1, local_only=True), key="test-key")

    assert targets == ["http://127.0.0.1:1"] * 3
    assert {"origin_listening", "origin_health", "ledger_readable", "spellings"} <= {
        r.name for r in results
    }


def test_json_output_is_machine_readable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        probe, "run_checks", lambda config, key: [probe.CheckResult("x", True, "d")]
    )
    monkeypatch.setattr(probe, "load_key", lambda: None)
    assert probe.main(["--json", "--local"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == [
        {"check": "x", "ok": True, "skipped": False, "detail": "d", "next_action": ""}
    ]


def test_exit_code_is_nonzero_when_any_check_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        probe, "run_checks", lambda config, key: [probe.CheckResult("x", False, "d", "fix it")]
    )
    monkeypatch.setattr(probe, "load_key", lambda: None)
    assert probe.main(["--local"]) == 1


def test_a_skipped_failed_check_still_fails_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        probe,
        "run_checks",
        lambda config, key: [probe.CheckResult("x", False, "d", "a", skipped=True)],
    )
    monkeypatch.setattr(probe, "load_key", lambda: None)
    assert probe.main(["--local"]) == 1


def _executable_string_constants(path: Path) -> list[str]:
    """Every string literal the module would actually evaluate, docstrings excluded.

    A grep over the source matches this file's own prose and the probe's docstring,
    which both name ``deliver_result`` precisely to say it is never called — so a grep
    proves nothing. Walking the AST and dropping docstring nodes asserts the shape of
    what the code DOES rather than what it says about itself.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def test_the_probe_never_calls_deliver_result() -> None:
    """Non-mutating by design: a recheck an operator can run at any time must not
    write into the vault or spend Computer credits."""
    literals = _executable_string_constants(_SCRIPT_PATH)
    assert not [text for text in literals if "deliver_result" in text]
    assert not [text for text in literals if "tools/call" in text]
    assert [text for text in literals if text == "initialize"], (
        "the probe must still exercise the authenticated path"
    )
