"""scripts/hapax-recruit — every roster row through a stubbed CLI, plus a stubbed local endpoint."""

from __future__ import annotations

import errno
import hashlib
import http.client
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import signal
import sys
import threading
import time
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-recruit"
_LEGACY_SECRETISH = re.compile(
    r"(api[_-]?key|token|secret|password|bearer)([\s]*[:=]?[\s]*)[^\s]*",
    re.IGNORECASE,
)


def _module() -> ModuleType:
    name = "hapax_recruit_under_test"
    loader = importlib.machinery.SourceFileLoader(name, str(SCRIPT))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


def _stub(bin_dir: Path, name: str, body: str) -> Path:
    """A fake CLI that appends its argv (JSON) and whether stdin was closed to <name>.calls."""
    path = bin_dir / name
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys, os\n"
        f"calls = os.path.join({str(bin_dir)!r}, {name!r} + '.calls')\n"
        "stdin_state = 'closed' if sys.stdin.read() == '' else 'open'\n"
        "with open(calls, 'a') as fh:\n"
        "    fh.write(json.dumps({'argv': sys.argv[1:], 'cwd': os.getcwd(), 'stdin': stdin_state}) + '\\n')\n"
        + body,
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _calls(bin_dir: Path, name: str) -> list[dict]:
    return [json.loads(line) for line in (bin_dir / f"{name}.calls").read_text().splitlines()]


@pytest.fixture
def bench(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, Path, Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    brief = tmp_path / "brief.md"
    brief.write_text("Reply with exactly: OK\n\nSecond line of the brief.\n", encoding="utf-8")
    out = tmp_path / "answers" / "run.md"
    module = _module()

    def no_network(*args, **kwargs):
        raise AssertionError("test attempted an unfaked endpoint call")

    monkeypatch.setattr(module.urllib.request, "urlopen", no_network)
    return module, bin_dir, brief, out


def _receipt(out: Path) -> dict:
    return json.loads(out.with_name(out.name + ".receipt.json").read_text())


def _mutate_to_legacy_redaction(module: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "_SECRETISH", _LEGACY_SECRETISH)


def _mutate_to_kill_only_child(module: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module.os, "killpg", module.os.kill)


REGISTERED_MUTATIONS = {
    "legacy-redaction-regex": _mutate_to_legacy_redaction,
    "timeout-kill-only-child": _mutate_to_kill_only_child,
}


def _assert_redacted(module: ModuleType, diagnostic: str, canary: str) -> None:
    redacted = module._redact(diagnostic)
    assert canary not in redacted
    assert "<redacted>" in redacted


def _spawn_descendant_wrapper(bin_dir: Path, pid_file: Path) -> Path:
    return _stub(
        bin_dir,
        "descendant-wrapper",
        "import subprocess, time\n"
        "child = subprocess.Popen(\n"
        "    [sys.executable, '-c', 'import time; time.sleep(30)'],\n"
        "    stdout=subprocess.DEVNULL,\n"
        "    stderr=subprocess.DEVNULL,\n"
        ")\n"
        f"with open({str(pid_file)!r}, 'w') as fh:\n"
        "    json.dump({'pid': child.pid, 'pgid': os.getpgrp()}, fh)\n"
        "print('wrapper ready', flush=True)\n"
        "time.sleep(30)\n",
    )


def _wait_for_pid_absent(pid: int, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not Path(f"/proc/{pid}").exists():
            return True
        time.sleep(0.01)
    return not Path(f"/proc/{pid}").exists()


def _assert_timeout_group_cleanup(rc: int, receipt: dict, grandchild_pid: int) -> None:
    assert rc == 4
    assert receipt["exit_code"] == "timeout"
    assert receipt["process_group_killed"] is True
    assert receipt["process_group_any_member_survived"] is False
    assert _wait_for_pid_absent(grandchild_pid), "timed-out wrapper left its grandchild alive"


def test_codex_shape_reads_the_output_file_and_closes_stdin(bench, tmp_path: Path) -> None:
    module, bin_dir, brief, out = bench
    repo = tmp_path / "repo"
    repo.mkdir()
    _stub(bin_dir, "git", "print('true')\n")
    _stub(
        bin_dir,
        "codex",
        "out = sys.argv[sys.argv.index('-o') + 1]\n"
        "open(out, 'w').write('ANSWER FROM FILE\\n')\n"
        "print('model: gpt-5.6-codex', file=sys.stderr)\n"
        "print('some stdout chatter')\n",
    )

    rc = module.main(["codex", "--brief", str(brief), "--out", str(out), "--cwd", str(repo)])

    assert rc == 0
    assert out.read_text() == "ANSWER FROM FILE\n"
    call = _calls(bin_dir, "codex")[0]
    assert call["argv"][:6] == ["exec", "--sandbox", "read-only", "-C", str(repo.resolve()), "-o"]
    assert call["argv"][-1] == brief.read_text()
    assert call["stdin"] == "closed", "codex waits on an open stdin (measured 2026-09-03)"
    receipt = _receipt(out)
    assert receipt["capacity"] == "codex"
    assert receipt["models_reported"] == ["gpt-5.6-codex"]
    assert receipt["exit_code"] == 0
    assert receipt["brief_bytes"] == len(brief.read_bytes())
    assert receipt["instrument_rev"] == module.INSTRUMENT_REV


def test_codex_refuses_a_cwd_that_is_not_a_git_checkout_and_names_the_flag(
    bench, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module, bin_dir, brief, out = bench
    _stub(
        bin_dir,
        "codex",
        "open(sys.argv[sys.argv.index('-o') + 1], 'w').write('allowed checkout answer')\n",
    )
    _stub(bin_dir, "git", "sys.exit(1)\n")
    plain = tmp_path / "plain"
    plain.mkdir()

    rc = module.main(["codex", "--brief", str(brief), "--out", str(out), "--cwd", str(plain)])

    assert rc == 2
    assert "REFUSED" in capsys.readouterr().err
    assert not (bin_dir / "codex.calls").exists()
    receipt = _receipt(out)
    assert "--allow-untrusted-cwd" in receipt["refusal"]
    assert receipt["exit_code"] is None

    rc = module.main(
        [
            "codex",
            "--brief",
            str(brief),
            "--out",
            str(out),
            "--cwd",
            str(plain),
            "--allow-untrusted-cwd",
        ]
    )
    assert rc == 0
    assert "--skip-git-repo-check" in _calls(bin_dir, "codex")[0]["argv"]


def test_grok_shape_passes_the_cwd_it_may_read(bench, tmp_path: Path) -> None:
    module, bin_dir, brief, out = bench
    _stub(bin_dir, "grok", "print('PELICAN')\n")
    work = tmp_path / "work"
    work.mkdir()

    rc = module.main(["grok", "--brief", str(brief), "--out", str(out), "--cwd", str(work)])

    assert rc == 0
    call = _calls(bin_dir, "grok")[0]
    assert call["argv"] == ["-p", brief.read_text(), "--cwd", str(work.resolve())]
    assert out.read_text() == "PELICAN\n"
    assert _receipt(out)["models_reported"] == "absent"


def test_kimi_shape_strips_banner_prompt_echo_and_session_trailer(bench) -> None:
    module, bin_dir, brief, out = bench
    _stub(
        bin_dir,
        "kimi",
        "print('kimi version 0.38.0')\n"
        "print('• Reply with exactly: OK')\n"
        "print('• OK')\n"
        "print('')\n"
        "print('To resume this session: kimi -r session_deadbeef')\n",
    )

    rc = module.main(["kimi", "--brief", str(brief), "--out", str(out)])

    assert rc == 0
    assert _calls(bin_dir, "kimi")[0]["argv"] == [
        "-p",
        brief.read_text(),
        "--output-format",
        "text",
    ]
    assert out.read_text() == "OK\n"


def test_agy_shape_is_prompt_only_with_a_print_timeout(bench) -> None:
    module, bin_dir, brief, out = bench
    _stub(bin_dir, "agy", "print('OK')\n")

    rc = module.main(["agy", "--brief", str(brief), "--out", str(out), "--timeout", "60"])

    assert rc == 0
    argv = _calls(bin_dir, "agy")[0]["argv"]
    assert argv == [f"--print={brief.read_text()}", "--print-timeout", "60s"]


def test_claude_shape_records_the_served_models_from_model_usage(bench) -> None:
    module, bin_dir, brief, out = bench
    _stub(
        bin_dir,
        "claude",
        "print(json.dumps({'type': 'result', 'result': 'OK', "
        "'modelUsage': {'claude-opus-5': {'inputTokens': 1}, 'claude-fable-5-1': {'inputTokens': 9}}}))\n",
    )

    rc = module.main(
        ["claude", "--brief", str(brief), "--out", str(out), "--model", "claude-fable-5-1"]
    )

    assert rc == 0
    argv = _calls(bin_dir, "claude")[0]["argv"]
    assert argv == [
        "-p",
        brief.read_text(),
        "--output-format",
        "json",
        "--model",
        "claude-fable-5-1",
    ]
    assert out.read_text() == "OK"
    receipt = _receipt(out)
    assert receipt["models_reported"] == ["claude-fable-5-1", "claude-opus-5"], (
        "two models served under one pin is the finding the receipt exists to show"
    )
    assert receipt["model_requested"] == "claude-fable-5-1"


def test_glmcp_shape_uses_the_wrapper_binding(bench, tmp_path: Path, monkeypatch) -> None:
    module, bin_dir, brief, out = bench
    wrapper = _stub(
        bin_dir,
        "fake-glmcp",
        "print(json.dumps({'result': 'OK', 'modelUsage': {'glm-5.2': {}}}))\n",
    )
    monkeypatch.setenv(module.GLMCP_WRAPPER_ENV, str(wrapper))

    rc = module.main(["glmcp", "--brief", str(brief), "--out", str(out)])

    assert rc == 0
    assert _calls(bin_dir, "fake-glmcp")[0]["argv"] == [
        "-p",
        brief.read_text(),
        "--output-format",
        "json",
    ]
    assert _receipt(out)["models_reported"] == ["glm-5.2"]

    monkeypatch.setenv(module.GLMCP_WRAPPER_ENV, str(tmp_path / "missing"))
    assert module.main(["glmcp", "--brief", str(brief), "--out", str(out)]) == 2
    assert "missing" in _receipt(out)["refusal"]


def test_qwencloud_shape_uses_its_own_wrapper_binding(bench, tmp_path: Path, monkeypatch) -> None:
    module, bin_dir, brief, out = bench
    wrapper = _stub(
        bin_dir,
        "fake-qwencloud",
        "print(json.dumps({'result': 'OK', 'modelUsage': {'qwen3.7-plus': {}}}))\n",
    )
    monkeypatch.setenv(module.QWENCLOUD_WRAPPER_ENV, str(wrapper))

    rc = module.main(["qwencloud", "--brief", str(brief), "--out", str(out)])

    assert rc == 0
    assert _calls(bin_dir, "fake-qwencloud")[0]["argv"] == [
        "-p",
        brief.read_text(),
        "--output-format",
        "json",
    ]
    assert _receipt(out)["models_reported"] == ["qwen3.7-plus"]


@pytest.mark.parametrize(
    ("diagnostic", "canary"),
    [
        ('{"api_key": "FAKE_JSON_CREDENTIAL"}', "FAKE_JSON_CREDENTIAL"),  # pragma: allowlist secret
        ("password: 'FAKE YAML CREDENTIAL'", "FAKE YAML CREDENTIAL"),  # pragma: allowlist secret
        ("api_key: FAKE_COLON_CREDENTIAL", "FAKE_COLON_CREDENTIAL"),
        ("API key: FAKE_SPACE_CREDENTIAL", "FAKE_SPACE_CREDENTIAL"),
        ("token=FAKE_EQUALS_CREDENTIAL", "FAKE_EQUALS_CREDENTIAL"),
        ("Bearer FAKE_BEARER_CREDENTIAL", "FAKE_BEARER_CREDENTIAL"),
        ("Authorization: Basic FAKE_AUTH_CREDENTIAL", "FAKE_AUTH_CREDENTIAL"),
    ],
    ids=[
        "json",
        "yaml",
        "key-colon-value",
        "space-separated-key",
        "key-equals-value",
        "bearer",
        "authorization",
    ],
)
def test_capacity_failure_redacts_every_diagnostic_form_from_receipt_and_terminal(
    bench,
    capsys: pytest.CaptureFixture[str],
    diagnostic: str,
    canary: str,
) -> None:
    module, bin_dir, brief, out = bench
    _stub(
        bin_dir,
        "grok",
        f"print('half an answer'); print({diagnostic!r}, file=sys.stderr); sys.exit(7)\n",
    )
    rc = module.main(["grok", "--brief", str(brief), "--out", str(out)])
    assert rc == 3
    receipt = _receipt(out)
    assert receipt["exit_code"] == 7
    assert canary not in json.dumps(receipt)
    assert "<redacted>" in receipt["stderr_tail"]
    assert canary not in capsys.readouterr().err


def test_registered_legacy_regex_mutation_turns_the_json_case_red(
    bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _bin_dir, _brief, _out = bench
    diagnostic = '{"api_key": "FAKE_JSON_MUTATION_CANARY"}'  # pragma: allowlist secret
    canary = "FAKE_JSON_MUTATION_CANARY"

    _assert_redacted(module, diagnostic, canary)
    REGISTERED_MUTATIONS["legacy-redaction-regex"](module, monkeypatch)
    with pytest.raises(AssertionError):
        _assert_redacted(module, diagnostic, canary)


def test_registered_legacy_regex_mutation_turns_the_space_separated_api_key_case_red(
    bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _bin_dir, _brief, _out = bench
    diagnostic = "API key: FAKE_SPACE_MUTATION_CANARY"
    canary = "FAKE_SPACE_MUTATION_CANARY"

    _assert_redacted(module, diagnostic, canary)
    REGISTERED_MUTATIONS["legacy-redaction-regex"](module, monkeypatch)
    with pytest.raises(AssertionError):
        _assert_redacted(module, diagnostic, canary)


def test_refusal_redacts_exception_receipt_and_terminal_at_the_guard_boundary(
    bench, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module, _bin_dir, brief, out = bench
    canary = "FAKE_REFUSAL_CREDENTIAL"

    def refuse(_name: str) -> str:
        refusal = module.Refusal(f"Authorization: Bearer {canary}")
        assert canary not in str(refusal)
        raise refusal

    monkeypatch.setattr(module, "_require_binary", refuse)
    rc = module.main(["grok", "--brief", str(brief), "--out", str(out)])

    assert rc == 2
    assert canary not in json.dumps(_receipt(out))
    assert canary not in capsys.readouterr().err


def test_timeout_kills_wrapper_process_group_and_records_no_survivor(
    bench, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, bin_dir, brief, out = bench
    pid_file = tmp_path / "descendant.json"
    wrapper = _spawn_descendant_wrapper(bin_dir, pid_file)
    monkeypatch.setenv(module.QWENCLOUD_WRAPPER_ENV, str(wrapper))

    rc = module.main(["qwencloud", "--brief", str(brief), "--out", str(out), "--timeout", "1"])

    grandchild_pid = json.loads(pid_file.read_text())["pid"]
    _assert_timeout_group_cleanup(rc, _receipt(out), grandchild_pid)


def test_registered_child_only_kill_mutation_leaves_the_grandchild_alive(
    bench, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, bin_dir, brief, out = bench
    pid_file = tmp_path / "mutated-descendant.json"
    wrapper = _spawn_descendant_wrapper(bin_dir, pid_file)
    monkeypatch.setenv(module.QWENCLOUD_WRAPPER_ENV, str(wrapper))
    real_killpg = os.killpg
    REGISTERED_MUTATIONS["timeout-kill-only-child"](module, monkeypatch)

    rc = module.main(["qwencloud", "--brief", str(brief), "--out", str(out), "--timeout", "1"])
    process = json.loads(pid_file.read_text())
    try:
        assert _receipt(out)["process_group_any_member_survived"] is True
        assert Path(f"/proc/{process['pid']}").exists()
        with pytest.raises(AssertionError):
            _assert_timeout_group_cleanup(rc, _receipt(out), process["pid"])
    finally:
        real_killpg(process["pgid"], signal.SIGKILL)
        assert _wait_for_pid_absent(process["pid"])


def test_local_endpoint_posts_an_openai_chat_completion_and_records_the_served_model(
    bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _bin_dir, brief, out = bench
    seen: list[dict] = []

    def urlopen(request, *, timeout):
        seen.append({"path": request.selector, "body": json.loads(request.data)})
        assert timeout == 900
        return io.BytesIO(
            json.dumps(
                {
                    "model": "qwen3.6-35b-a3b-q5",
                    "choices": [{"message": {"role": "assistant", "content": "OK"}}],
                }
            ).encode()
        )

    monkeypatch.setattr(module.urllib.request, "urlopen", urlopen)
    rc = module.main(["local:qwen36", "--brief", str(brief), "--out", str(out)])

    assert rc == 0
    assert out.read_text() == "OK"
    assert seen[0]["path"] == "/v1/chat/completions"
    assert seen[0]["body"]["messages"] == [{"role": "user", "content": brief.read_text()}]
    assert seen[0]["body"]["model"] == "qwen3.6-35b-a3b"
    receipt = _receipt(out)
    assert receipt["models_reported"] == ["qwen3.6-35b-a3b-q5"]
    assert receipt["cwd"] is None, "a model has no working directory"


def test_local_endpoint_unreachable_is_a_capacity_failure_with_a_receipt(
    bench, monkeypatch
) -> None:
    module, _bin_dir, brief, out = bench

    def urlopen(request, *, timeout):
        raise urllib.error.URLError("synthetic connection refused")

    monkeypatch.setattr(module.urllib.request, "urlopen", urlopen)

    rc = module.main(["local:gemma3", "--brief", str(brief), "--out", str(out), "--timeout", "2"])

    assert rc == 3
    assert "unreachable" in _receipt(out)["stderr_tail"]


def test_list_and_argument_refusals(
    bench, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    module, _bin_dir, brief, out = bench
    assert module.main(["--list"]) == 0
    listed = capsys.readouterr().out
    assert all(name in listed for name in module.CAPACITIES)
    assert module.main(["grok"]) == 2
    empty = tmp_path / "empty.md"
    empty.write_text("  \n")
    assert module.main(["grok", "--brief", str(empty), "--out", str(out)]) == 2
    assert module.main(["grok", "--brief", str(tmp_path / "nope.md"), "--out", str(out)]) == 2


@pytest.mark.parametrize("condition", ["missing-brief", "empty-brief", "invalid-cwd"])
def test_argument_validation_names_recovery(bench, monkeypatch, capsys, condition):
    module, _bin_dir, brief, out = bench
    args = ["grok", "--brief", str(brief), "--out", str(out)]
    if condition == "missing-brief":
        brief.unlink()
        path, remedy = brief, "supply an existing --brief file"
    elif condition == "empty-brief":
        brief.write_text(" \n\t")
        path, remedy = brief, "add prompt content to the brief"
    else:
        path = brief.parent / "missing-cwd"
        args += ["--cwd", str(path)]
        remedy = "select an existing --cwd directory"
    monkeypatch.setattr(module, "recruit_cli", lambda *a, **kw: pytest.fail("validation launched"))
    assert module.main(args) == 2
    captured = capsys.readouterr()
    assert str(path) in captured.err
    assert remedy in captured.err
    assert captured.out == ""
    assert not out.exists()


# Synthetic credential-shaped diagnostics: the redaction under test must remove them; none is real.
_BOUNDARY_DIAGNOSTICS = [
    '{"api_key": "VALUE"}',  # pragma: allowlist secret
    "password: 'VALUE'",  # pragma: allowlist secret
    "api_key: VALUE",  # pragma: allowlist secret
    "API key: VALUE",  # pragma: allowlist secret
    "token=VALUE",  # pragma: allowlist secret
    "Bearer VALUE",  # pragma: allowlist secret
    "Authorization: Basic VALUE",  # pragma: allowlist secret
]
_BOUNDARY_IDS = ["json", "yaml", "colon", "space", "equals", "bearer", "authorization"]


@pytest.mark.parametrize("form", _BOUNDARY_DIAGNOSTICS, ids=_BOUNDARY_IDS)
@pytest.mark.parametrize("stream", ["stderr", "stdout"])
@pytest.mark.parametrize(
    "capacity", ["codex", "grok", "kimi", "agy", "claude", "glmcp", "qwencloud"]
)
def test_cli_diagnostics_redact_before_tail(
    bench, monkeypatch, capsys, capacity: str, stream: str, form: str
) -> None:
    module, bin_dir, brief, out = bench
    canary = "SYNTHETIC_BOUNDARY_SENTINEL"
    diagnostic = form.replace("VALUE", "P" * 450 + canary) + "\ncontext after failure"
    # The raw tail starts inside the credential and still contains the complete sentinel.
    assert diagnostic[-400:].startswith("P") and canary in diagnostic[-400:]
    monkeypatch.setattr(module, "_require_binary", lambda name: str(bin_dir / name))
    monkeypatch.setattr(module, "_is_git_checkout", lambda cwd: True)
    if capacity in module.WRAPPED_CLAUDE:
        env_name, _ = module.WRAPPED_CLAUDE[capacity]
        monkeypatch.setenv(env_name, str(brief))

    def run(argv, *, cwd, timeout):
        if capacity == "codex":
            Path(argv[argv.index("-o") + 1]).write_text("ANSWER")
        return (
            7,
            diagnostic if stream == "stdout" else "",
            diagnostic if stream == "stderr" else "",
            False,
            None,
        )

    monkeypatch.setattr(module, "_run", run)
    assert module.main([capacity, "--brief", str(brief), "--out", str(out)]) == 3
    receipt = _receipt(out)
    captured = capsys.readouterr()
    assert canary not in json.dumps(receipt) + captured.out + captured.err
    assert "P" * 20 not in receipt["stderr_tail"]
    assert "<redacted>" in receipt["stderr_tail"]
    assert "context after failure" in receipt["stderr_tail"]
    assert len(receipt["stderr_tail"]) <= 400
    assert canary not in out.read_text()


@pytest.mark.parametrize("form", _BOUNDARY_DIAGNOSTICS, ids=_BOUNDARY_IDS)
@pytest.mark.parametrize("error_kind", ["url", "http"])
def test_endpoint_diagnostics_redact_before_tail(bench, monkeypatch, capsys, form, error_kind):
    module, _bin_dir, brief, out = bench
    canary = "SYNTHETIC_ENDPOINT_SENTINEL"
    diagnostic = form.replace("VALUE", "P" * 450 + canary) + "\ncontext after failure"
    assert diagnostic[-400:].startswith("P") and canary in diagnostic[-400:]

    def urlopen(request, *, timeout):
        if error_kind == "http":
            raise urllib.error.HTTPError(
                request.full_url, 503, diagnostic, {}, io.BytesIO(diagnostic.encode())
            )
        raise urllib.error.URLError(diagnostic)

    monkeypatch.setattr(module.urllib.request, "urlopen", urlopen)
    assert module.main(["local:qwen36", "--brief", str(brief), "--out", str(out)]) == 3
    receipt = _receipt(out)
    captured = capsys.readouterr()
    assert canary not in json.dumps(receipt) + captured.out + captured.err
    assert "P" * 20 not in receipt["stderr_tail"]
    assert "<redacted>" in receipt["stderr_tail"]
    assert "context after failure" in receipt["stderr_tail"]
    assert len(receipt["stderr_tail"]) <= 400


@pytest.mark.parametrize("preexisting", [False, True], ids=["absent", "unrelated-file"])
def test_codex_relative_output_uses_one_absolute_path(bench, tmp_path, monkeypatch, preexisting):
    module, _bin_dir, brief, _out = bench
    caller = tmp_path / "caller"
    checkout = tmp_path / "checkout"
    caller.mkdir()
    checkout.mkdir()
    monkeypatch.chdir(caller)
    out = caller / "answer.md"
    if preexisting:
        out.write_text("UNRELATED OLD ANSWER")
    monkeypatch.setattr(module, "_require_binary", lambda name: name)
    monkeypatch.setattr(module, "_is_git_checkout", lambda cwd: True)
    seen = []

    def run(argv, *, cwd, timeout):
        target = Path(argv[argv.index("-o") + 1])
        seen.append(target)
        # Model the client's actual resolution relative to its selected checkout.
        (cwd / target).write_text("ACTUAL CODEX ANSWER")
        return 0, "stdout chatter", "", False, None

    monkeypatch.setattr(module, "_run", run)
    assert (
        module.main(["codex", "--brief", str(brief), "--out", "answer.md", "--cwd", str(checkout)])
        == 0
    )
    assert out.read_text() == "ACTUAL CODEX ANSWER"
    assert seen == [out]
    receipt = _receipt(out)
    assert receipt["out"] == str(out)
    assert receipt["output_bytes"] == len(out.read_bytes())
    assert not (checkout / "answer.md").exists()


@pytest.mark.parametrize("capacity", ["kimi", "qwencloud"])
def test_stdout_lanes_keep_brief_side_artifacts_separate_from_recruiter_out(
    bench, tmp_path, monkeypatch, capacity
):
    module, _bin_dir, brief, _out = bench
    caller = tmp_path / "caller"
    checkout = tmp_path / "checkout"
    caller.mkdir()
    checkout.mkdir()
    monkeypatch.chdir(caller)
    artifact = brief.with_suffix(".answer.md")
    monkeypatch.setattr(module, "_require_binary", lambda name: name)
    monkeypatch.setenv(module.QWENCLOUD_WRAPPER_ENV, str(brief))

    def run(argv, *, cwd, timeout):
        assert "-o" not in argv and "--out" not in argv
        assert cwd == checkout
        artifact.write_text("CLIENT ARTIFACT BESIDE BRIEF")
        stdout = (
            "RETURNED ANSWER" if capacity == "kimi" else json.dumps({"result": "RETURNED ANSWER"})
        )
        return 0, stdout, "", False, None

    monkeypatch.setattr(module, "_run", run)
    assert (
        module.main([capacity, "--brief", str(brief), "--out", "answer.md", "--cwd", str(checkout)])
        == 0
    )
    out = caller / "answer.md"
    assert out.read_text().strip() == "RETURNED ANSWER"
    assert artifact.read_text() == "CLIENT ARTIFACT BESIDE BRIEF"
    assert _receipt(out)["out"] == str(out)
    assert not (checkout / "answer.md").exists()


@pytest.mark.parametrize(
    ("body", "failure_class", "diagnostic"),
    [
        (
            b'{"api_key": "SYNTHETIC_PROTOCOL_SENTINEL",',  # pragma: allowlist secret
            "JSONDecodeError",
            "invalid JSON",
        ),
        (b"\xffSYNTHETIC_PROTOCOL_SENTINEL", "UnicodeDecodeError", "UTF-8"),
        (b'["SYNTHETIC_PROTOCOL_SENTINEL"]', "EndpointProtocolError", "response must be an object"),
        (
            b'{"choices": {"secret": "SYNTHETIC_PROTOCOL_SENTINEL"}}',  # pragma: allowlist secret
            "EndpointProtocolError",
            "choices must be a non-empty list",
        ),
        (b'{"choices": []}', "EndpointProtocolError", "choices must be a non-empty list"),
        (
            b'{"choices": ["SYNTHETIC_PROTOCOL_SENTINEL"]}',
            "EndpointProtocolError",
            "choices[0] must be an object",
        ),
        (b'{"choices": [{}]}', "EndpointProtocolError", "message must be an object"),
        (
            b'{"choices": [{"message": "SYNTHETIC_PROTOCOL_SENTINEL"}]}',
            "EndpointProtocolError",
            "message must be an object",
        ),
        (b'{"choices": [{"message": {}}]}', "EndpointProtocolError", "content must be a string"),
        (
            b'{"choices": [{"message": {"content": ["SYNTHETIC_PROTOCOL_SENTINEL"]}}]}',
            "EndpointProtocolError",
            "content must be a string",
        ),
        (
            b'{"choices": [{"message": {"content": 42}}]}',
            "EndpointProtocolError",
            "content must be a string",
        ),
        (
            b'{"choices": [{"message": {"content": ""}}]}',
            "EndpointProtocolError",
            "content must not be empty",
        ),
        (
            b'{"choices": [{"message": {"content": "OK"}}], "model": {"secret": "SYNTHETIC_PROTOCOL_SENTINEL"}}',  # pragma: allowlist secret
            "EndpointProtocolError",
            "model must be a string",
        ),
    ],
    ids=[
        "invalid-json",
        "invalid-encoding",
        "non-object",
        "choices-object",
        "choices-empty",
        "choice-string",
        "missing-message",
        "message-string",
        "missing-content",
        "content-list",
        "content-number",
        "content-empty",
        "model-object",
    ],
)
def test_malformed_endpoint_response_is_receipted_capacity_failure(
    bench, monkeypatch, capsys, body, failure_class, diagnostic
):
    module, _bin_dir, brief, out = bench
    monkeypatch.setattr(
        module.urllib.request, "urlopen", lambda request, *, timeout: io.BytesIO(body)
    )
    assert module.main(["local:qwen36", "--brief", str(brief), "--out", str(out)]) == 3
    receipt = _receipt(out)
    assert receipt["exit_code"] == 3
    assert receipt["failure_class"] == failure_class
    assert failure_class in receipt["stderr_tail"]
    assert diagnostic in receipt["stderr_tail"]
    assert receipt["models_reported"] == "absent"
    assert out.read_text() == ""
    captured = capsys.readouterr()
    assert "SYNTHETIC_PROTOCOL_SENTINEL" not in json.dumps(receipt) + captured.out + captured.err
    assert body.decode(errors="replace") not in receipt["stderr_tail"]


@pytest.mark.parametrize(
    "capacity", ["codex", "grok", "kimi", "agy", "claude", "glmcp", "qwencloud"]
)
@pytest.mark.parametrize("code", [7, "timeout"])
def test_failed_stdout_is_redacted_at_every_destination(
    bench, monkeypatch, capsys, caplog, capacity, code
):
    module, _bin_dir, brief, out = bench
    canary = "SYNTHETIC_REVIEW_CANARY"  # pragma: allowlist secret
    diagnostic = f"api_key={canary}"  # pragma: allowlist secret
    monkeypatch.setattr(module, "_require_binary", lambda name: name)
    monkeypatch.setattr(module, "_is_git_checkout", lambda cwd: True)
    if capacity in module.WRAPPED_CLAUDE:
        monkeypatch.setenv(module.WRAPPED_CLAUDE[capacity][0], str(brief))

    def run(argv, *, cwd, timeout):
        if capacity == "codex":
            Path(argv[argv.index("-o") + 1]).write_text(diagnostic)
        return code, diagnostic, "", False, None

    monkeypatch.setattr(module, "_run", run)
    assert module.main([capacity, "--brief", str(brief), "--out", str(out)]) == (
        4 if code == "timeout" else 3
    )
    receipt = _receipt(out)
    captured = capsys.readouterr()
    # There is no journal writer: stdout/stderr are also the systemd journal boundary.
    destinations = {
        "answer": out.read_text(),
        "receipt": json.dumps(receipt),
        "terminal/journal stdout": captured.out,
        "terminal/journal stderr": captured.err,
        "logging": caplog.text,
    }
    for destination, text in destinations.items():
        assert canary not in text, f"unredacted diagnostic persisted to {destination}"
    assert "<redacted>" in out.read_text()
    assert "<redacted>" in receipt["stderr_tail"]
    assert receipt["output_bytes"] == len(out.read_bytes())
    assert receipt["answer_policy"] == "redacted_failure_output"


@pytest.mark.parametrize("code", [0, "timeout"])
@pytest.mark.parametrize("preexisting", [False, True])
def test_codex_run_without_new_output_never_attributes_an_old_answer(
    bench, monkeypatch, code, preexisting
):
    module, _bin_dir, brief, out = bench
    out.parent.mkdir()
    if preexisting:
        out.write_text("ANSWER TO AN EARLIER BRIEF")
    brief.write_text("A NEW BRIEF")
    monkeypatch.setattr(module, "_require_binary", lambda name: name)
    monkeypatch.setattr(module, "_is_git_checkout", lambda cwd: True)
    monkeypatch.setattr(
        module, "_run", lambda *args, **kwargs: (code, "only launch chatter", "", False, None)
    )

    assert module.main(["codex", "--brief", str(brief), "--out", str(out)]) == (
        4 if code == "timeout" else 3
    )
    receipt = _receipt(out)
    assert receipt["brief_sha256"] == hashlib.sha256(brief.read_bytes()).hexdigest()
    assert receipt["output_bytes"] == 0, "stale output attributed to the new brief"
    assert receipt["failure_class"] == "OutputNotProduced"
    assert "no new output" in receipt["stderr_tail"]
    assert out.read_text() == ""


@pytest.mark.parametrize(
    "failure_class", ["PermissionError", "UnicodeDecodeError", "IncompleteRead"]
)
def test_expected_launch_decode_and_transport_failures_are_receipted(
    bench, monkeypatch, capsys, failure_class
):
    module, _bin_dir, brief, out = bench
    canary = "SYNTHETIC_FAILURE_SENTINEL"  # pragma: allowlist secret
    diagnostic = f"api_key={canary}".encode()  # pragma: allowlist secret
    capacity = "qwencloud"
    monkeypatch.setenv(module.QWENCLOUD_WRAPPER_ENV, str(brief))

    def popen(*args, **kwargs):
        if failure_class == "PermissionError":
            raise PermissionError(13, diagnostic.decode(), str(brief))

        class Process:
            returncode = 0

            def communicate(self, **kwargs):
                return (diagnostic + b"\xff").decode("utf-8"), ""

        return Process()

    monkeypatch.setattr(module.subprocess, "Popen", popen)
    if failure_class == "IncompleteRead":
        capacity = "local:qwen36"

        class TruncatedResponse(io.BytesIO):
            def read(self, *args):
                raise http.client.IncompleteRead(diagnostic, 100)

            read1 = read

        monkeypatch.setattr(
            module.urllib.request, "urlopen", lambda *args, **kwargs: TruncatedResponse()
        )

    assert module.main([capacity, "--brief", str(brief), "--out", str(out)]) == 3
    receipt = _receipt(out)
    assert receipt["exit_code"] == 3
    assert receipt["failure_class"] == failure_class
    assert failure_class in receipt["stderr_tail"]
    assert receipt["output_bytes"] == 0
    assert out.read_text() == ""
    captured = capsys.readouterr()
    assert canary not in json.dumps(receipt) + captured.out + captured.err


@pytest.mark.parametrize("stage", ["connection", "body"])
def test_local_deadline_covers_connection_and_body(bench, monkeypatch, stage):
    module, _bin_dir, brief, out = bench
    clock = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])

    class DelayedResponse(io.BytesIO):
        def read(self, *args):
            if stage == "body":
                clock[0] += 1.2
            return super().read(*args)

        read1 = read

    def urlopen(*args, **kwargs):
        if stage == "connection":
            clock[0] += 1.2
        return DelayedResponse(b'{"choices": [{"message": {"content": "OK"}}]}')

    monkeypatch.setattr(module.urllib.request, "urlopen", urlopen)
    assert (
        module.main(["local:qwen36", "--brief", str(brief), "--out", str(out), "--timeout", "1"])
        == 3
    )
    receipt = _receipt(out)
    assert receipt["failure_class"] == "EndpointDeadlineExceeded"
    assert "deadline" in receipt["stderr_tail"]
    assert receipt["output_bytes"] == 0


@pytest.mark.parametrize("stage", ["headers", "body"])
def test_local_deadline_interrupts_loopback_trickle(bench, monkeypatch, stage):
    module, _bin_dir, brief, out = bench
    stop = threading.Event()
    body = b'{"choices": [{"message": {"content": "OK"}}]}'

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            try:
                if stage == "headers":
                    self.wfile.write(b"HTTP/1.0 200 OK\r\n")
                    for _ in range(10):
                        self.wfile.write(b"X-Trickle: yes\r\n")
                        self.wfile.flush()
                        if stop.wait(0.2):
                            return
                    self.wfile.write(f"Content-Length: {len(body)}\r\n\r\n".encode())
                    self.wfile.write(body)
                else:
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    for offset in range(0, len(body), 4):
                        self.wfile.write(body[offset : offset + 4])
                        self.wfile.flush()
                        if stop.wait(0.2):
                            return
            except (BrokenPipeError, ConnectionResetError):
                pass

    try:
        server = HTTPServer(("127.0.0.1", 0), Handler)
    except PermissionError as exc:
        pytest.skip(f"sandbox forbids loopback sockets: {type(exc).__name__}: {exc}")
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    # This is the sole permitted socket boundary: an ephemeral synthetic loopback server.
    monkeypatch.setitem(
        module.LOCAL_ENDPOINTS,
        "local:qwen36",
        (f"http://127.0.0.1:{server.server_port}/v1", "synthetic"),
    )
    opener = module.urllib.request.build_opener(module.urllib.request.ProxyHandler({}))
    monkeypatch.setattr(module.urllib.request, "urlopen", opener.open)
    started = time.monotonic()
    try:
        rc = module.main(
            ["local:qwen36", "--brief", str(brief), "--out", str(out), "--timeout", "1"]
        )
        elapsed = time.monotonic() - started
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
    assert rc == 3, "slowly arriving response escaped the deadline"
    assert elapsed < 1.6, "run exceeded the overall deadline"
    receipt = _receipt(out)
    assert receipt["failure_class"] == "EndpointDeadlineExceeded"
    assert "deadline" in receipt["stderr_tail"]
    assert receipt["output_bytes"] == 0


def test_runbook_has_headless_read_refusal_rechecks(request):
    doc = (SCRIPT.parents[1] / "docs/runbooks/hapax-recruit.md").read_text()
    assert 'grok -p "$recruit_read_prompt" --cwd "$recruit_probe_dir/cwd" < /dev/null' in doc
    assert 'agy --print="$recruit_read_prompt" --print-timeout 60s < /dev/null' in doc
    assert "outside cwd" in doc
    assert "read_file" in doc and "command" in doc and "auto-denied" in doc
    assert 'grok -p "$recruit_inside_prompt" --cwd "$recruit_probe_dir/cwd" < /dev/null' in doc
    assert 'cp "$recruit_probe_dir/read-target.txt" "$recruit_probe_dir/cwd/read-target.txt"' in doc
    selections = set(re.findall(r"tests/scripts/test_hapax_recruit\.py::[\w\[\]-]+", doc))
    required = {
        "test_structured_failed_output_is_redacted_at_every_destination",
        "test_nested_claude_credentials_never_reach_destinations",
        "test_undecodable_claude_envelope_cannot_claim_success",
        "test_unwritable_receipt_and_fallback_name_recovery_without_traceback",
        "test_undecodable_claude_diagnostic_stream_is_suppressed",
        "test_codex_run_without_new_output_never_attributes_an_old_answer",
        "test_expected_launch_decode_and_transport_failures_are_receipted",
        "test_local_deadline_covers_connection_and_body",
        "test_local_deadline_interrupts_blocking_io_and_restores_alarm",
        "test_timeout_kills_wrapper_process_group_and_records_no_survivor",
    }
    assert required <= {node.split("::")[1] for node in selections}
    # Collect independently so a recheck selected by node id still sees all cases.
    collector = pytest.Module.from_parent(request.session, path=Path(__file__))
    collected = {item.nodeid for item in collector.collect()}
    collected.update(node.split("[")[0] for node in tuple(collected))
    assert selections <= collected, f"runbook names uncollected tests: {selections - collected}"


@pytest.mark.parametrize("stage", ["connection", "body"])
def test_local_deadline_interrupts_blocking_io_and_restores_alarm(bench, monkeypatch, stage):
    module, _bin_dir, brief, out = bench
    previous_handler = signal.getsignal(signal.SIGALRM)
    assert signal.getitimer(signal.ITIMER_REAL) == (0, 0)

    class BlockingResponse(io.BytesIO):
        def read(self, *args):
            if stage == "body":
                time.sleep(2)
            return super().read(*args)

        read1 = read

    def urlopen(*args, **kwargs):
        if stage == "connection":
            time.sleep(2)
        return BlockingResponse(b'{"choices": [{"message": {"content": "OK"}}]}')

    monkeypatch.setattr(module.urllib.request, "urlopen", urlopen)
    started = time.monotonic()
    rc = module.main(["local:qwen36", "--brief", str(brief), "--out", str(out), "--timeout", "1"])
    assert rc == 3, "blocking I/O escaped the deadline"
    assert time.monotonic() - started < 1.6
    assert signal.getsignal(signal.SIGALRM) == previous_handler
    assert signal.getitimer(signal.ITIMER_REAL) == (0, 0)
    assert _receipt(out)["failure_class"] == "EndpointDeadlineExceeded"


def test_short_http_content_length_is_a_receipted_transport_failure(bench, monkeypatch):
    module, _bin_dir, brief, out = bench

    class FakeSocket:
        def makefile(self, *args):
            body = b'{"choices": [{"message": {"content": "OK"}}]}'
            return io.BytesIO(b"HTTP/1.0 200 OK\r\nContent-Length: 999\r\n\r\n" + body)

    response = http.client.HTTPResponse(FakeSocket())
    response.begin()
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *args, **kwargs: response)
    assert module.main(["local:qwen36", "--brief", str(brief), "--out", str(out)]) == 3
    assert _receipt(out)["failure_class"] == "IncompleteRead"
    assert _receipt(out)["output_bytes"] == 0
    assert out.read_text() == ""


@pytest.mark.parametrize(
    "diagnostic",
    [
        r'{"password": "prefix\"SYNTHETIC_STRUCTURED_CANARY"}',  # pragma: allowlist secret
        "api_key: |-\n  SYNTHETIC_STRUCTURED_CANARY\n",  # pragma: allowlist secret
        "api_key: >\n  SYNTHETIC_STRUCTURED_CANARY\n",  # pragma: allowlist secret
        "password: 'prefix''SYNTHETIC_STRUCTURED_CANARY'",  # pragma: allowlist secret
        'password: "prefix\n  SYNTHETIC_STRUCTURED_CANARY"',  # pragma: allowlist secret
        'password: "prefix\n  SYNTHETIC_STRUCTURED_CANARY',  # pragma: allowlist secret
        "password: prefix\n  SYNTHETIC_STRUCTURED_CANARY\n",  # pragma: allowlist secret
    ],
    ids=[
        "json-escape",
        "yaml-literal",
        "yaml-folded",
        "yaml-single",
        "multiline",
        "unbounded",
        "yaml-plain",
    ],
)
@pytest.mark.parametrize(
    "capacity", ["codex", "grok", "kimi", "agy", "claude", "glmcp", "qwencloud"]
)
@pytest.mark.parametrize("code", [7, "timeout"])
def test_structured_failed_output_is_redacted_at_every_destination(
    bench, monkeypatch, capsys, caplog, diagnostic, capacity, code
):
    module, _bin_dir, brief, out = bench
    monkeypatch.setattr(module, "_require_binary", lambda name: name)
    monkeypatch.setattr(module, "_is_git_checkout", lambda cwd: True)
    if capacity in module.WRAPPED_CLAUDE:
        monkeypatch.setenv(module.WRAPPED_CLAUDE[capacity][0], str(brief))

    def run(argv, *, cwd, timeout):
        if capacity == "codex":
            Path(argv[argv.index("-o") + 1]).write_text(diagnostic)
        return code, diagnostic, diagnostic, False, None

    monkeypatch.setattr(module, "_run", run)
    assert module.main([capacity, "--brief", str(brief), "--out", str(out)]) == (
        4 if code == "timeout" else 3
    )
    captured = capsys.readouterr()
    destinations = {
        "answer": out.read_text(),
        "receipt": out.with_name(out.name + ".receipt.json").read_text(),
        "stdout": captured.out,
        "stderr/journal": captured.err,
        "log": caplog.text,
    }
    for destination, text in destinations.items():
        assert "SYNTHETIC_STRUCTURED_CANARY" not in text, destination  # pragma: allowlist secret
    assert "<redacted>" in destinations["answer"]
    assert "<redacted>" in _receipt(out)["stderr_tail"]


@pytest.mark.parametrize(
    ("capacity", "stdout"),
    [
        pytest.param(capacity, value, id=f"{capacity}-{condition}")
        for capacity in ["claude", "grok", "agy", "kimi", "glmcp", "qwencloud", "codex"]
        for condition, value in [("empty", ""), ("whitespace", " \n\t")]
    ]
    + [
        pytest.param(capacity, json.dumps({"result": value}), id=f"{capacity}-json-{condition}")
        for capacity in ["claude", "glmcp", "qwencloud"]
        for condition, value in [("empty", ""), ("whitespace", " \n\t")]
    ],
)
def test_empty_cli_answer_is_receipted_failure(bench, monkeypatch, capsys, capacity, stdout):
    module, _bin_dir, brief, out = bench
    monkeypatch.setattr(module, "_require_binary", lambda name: name)
    monkeypatch.setattr(module, "_is_git_checkout", lambda cwd: True)
    if capacity in module.WRAPPED_CLAUDE:
        monkeypatch.setenv(module.WRAPPED_CLAUDE[capacity][0], str(brief))

    def run(argv, *, cwd, timeout):
        if capacity == "codex":
            Path(argv[argv.index("-o") + 1]).write_text(stdout)
        return 0, stdout, "", False, None

    monkeypatch.setattr(module, "_run", run)
    assert module.main([capacity, "--brief", str(brief), "--out", str(out)]) == 3
    receipt = _receipt(out)
    assert receipt["exit_code"] == 3
    assert receipt["failure_class"] == "OutputNotProduced"
    assert receipt["capacity"] == capacity
    assert capacity in receipt["stderr_tail"] and "empty" in receipt["stderr_tail"]
    assert receipt["output_bytes"] == 0 and out.read_bytes() == b""
    captured = capsys.readouterr()
    assert "answered" not in captured.out + captured.err


@pytest.mark.parametrize(
    ("capacity", "endpoint", "default_model"),
    [
        ("local:gptoss", "http://localhost:5001/v1/chat/completions", "gpt-oss-20b"),
        ("local:gemma3", "http://localhost:5002/v1/chat/completions", "gemma-3-4b"),
        ("local:qwen36", "http://localhost:5000/v1/chat/completions", "qwen3.6-35b-a3b"),
    ],
)
@pytest.mark.parametrize(
    "override", [None, "synthetic-local-override"], ids=["default", "override"]
)
def test_local_routes_and_model_overrides(
    bench, monkeypatch, capacity, endpoint, default_model, override
):
    module, _bin_dir, brief, out = bench
    requests = []

    def urlopen(request, *, timeout):
        requests.append(request)
        assert timeout == 5
        return io.BytesIO(
            b'{"model": "synthetic-served", "choices": [{"message": {"content": "LOCAL OK"}}]}'
        )

    monkeypatch.setattr(module.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(
        module.subprocess, "Popen", lambda *a, **kw: pytest.fail("local route launched a client")
    )
    args = [capacity, "--brief", str(brief), "--out", str(out), "--timeout", "5"]
    if override:
        args += ["--model", override]
    assert module.main(args) == 0
    assert len(requests) == 1
    assert requests[0].full_url == endpoint
    assert json.loads(requests[0].data) == {
        "model": override or default_model,
        "messages": [{"role": "user", "content": brief.read_text()}],
        "temperature": 0,
    }
    assert out.read_text() == "LOCAL OK"
    receipt = _receipt(out)
    assert receipt["capacity"] == capacity and receipt["exit_code"] == 0
    assert receipt["models_reported"] == ["synthetic-served"]
    assert receipt["model_requested"] == override and receipt["cwd"] is None


@pytest.mark.parametrize(
    "failure_class",
    [
        "PermissionError",
        "UnicodeDecodeError",
        "IncompleteRead",
        "ConnectionResetError",
        "OSError",
        "HTTPException",
        "LocalUnicodeDecodeError",
        "JSONDecodeError",
        "EndpointProtocolError",
        "EndpointTimeout",
        "EndpointDeadlineExceeded",
        "TimeoutError",
        "OutputNotProduced",
        "CLIExit",
    ],
)
def test_failure_recovery_actions_reach_diagnostic_destinations(
    bench, monkeypatch, capsys, caplog, failure_class
):
    module, _bin_dir, brief, out = bench
    capacity = (
        "grok"
        if failure_class
        in {"PermissionError", "UnicodeDecodeError", "OutputNotProduced", "CLIExit", "TimeoutError"}
        else "local:qwen36"
    )
    monkeypatch.setattr(module, "_require_binary", lambda name: name)
    canary = "SYNTHETIC_RECOVERY_CANARY"  # pragma: allowlist secret

    def fail(*args, **kwargs):
        if failure_class == "OutputNotProduced":
            return 0, "", "", False, None
        if failure_class == "CLIExit":
            return 7, "", "", False, None
        if failure_class == "TimeoutError":
            return "timeout", "", "", True, False
        if failure_class == "PermissionError":
            raise PermissionError(canary)
        if failure_class == "UnicodeDecodeError":
            raise UnicodeDecodeError("utf-8", canary.encode(), 0, 1, canary)
        if failure_class == "IncompleteRead":
            raise http.client.IncompleteRead(canary.encode(), 999)
        if failure_class == "ConnectionResetError":
            raise ConnectionResetError(canary)
        if failure_class == "OSError":
            raise OSError(canary)
        if failure_class == "HTTPException":
            raise http.client.HTTPException(canary)
        if failure_class == "LocalUnicodeDecodeError":
            return io.BytesIO(canary.encode() + b"\xff")
        if failure_class == "JSONDecodeError":
            return io.BytesIO(canary.encode())
        if failure_class == "EndpointProtocolError":
            return io.BytesIO(json.dumps({"choices": canary}).encode())
        if failure_class == "EndpointTimeout":
            raise TimeoutError(canary)
        raise module.EndpointDeadlineExceeded(canary)

    monkeypatch.setattr(module, "_run", fail)
    monkeypatch.setattr(module.urllib.request, "urlopen", fail)
    assert module.main([capacity, "--brief", str(brief), "--out", str(out), "--timeout", "5"]) == (
        4 if failure_class in {"TimeoutError", "EndpointTimeout"} else 3
    )
    receipt = _receipt(out)
    captured = capsys.readouterr()
    if failure_class == "PermissionError":
        remedy = ["executable", "mode", "PATH", "retry"]
    elif failure_class in {"TimeoutError", "EndpointTimeout", "EndpointDeadlineExceeded"}:
        remedy = ["--timeout", "retry"]
    elif failure_class == "OutputNotProduced":
        remedy = ["--out", str(out), "retry"]
    elif capacity.startswith("local:"):
        remedy = ["receipt", "endpoint", "--timeout", "retry"]
    else:
        remedy = ["receipt", "--out", "retry"]
    for destination in (receipt["stderr_tail"], captured.err):
        assert capacity in destination
        for action in remedy:
            assert action in destination, f"missing recovery action: {action}"
    assert receipt["recovery_action"]
    for action in remedy:
        assert action in receipt["recovery_action"]
    assert out.read_bytes() == b""  # Diagnostics must not turn an absent answer into an answer.
    assert captured.out == "" and caplog.text == ""
    assert canary not in json.dumps(receipt) + captured.err


@pytest.mark.parametrize(
    "diagnostic",
    [
        "password: prefix SYNTHETIC_YAML_CANARY\n",  # pragma: allowlist secret
        "password: prefix words\n  SYNTHETIC_YAML_CANARY\n",  # pragma: allowlist secret
        "password: prefix words\n\n  SYNTHETIC_YAML_CANARY\n",  # pragma: allowlist secret
        "api_key: &provider |-\n  SYNTHETIC_YAML_CANARY\n",  # pragma: allowlist secret
        "api_key: &provider >\n  SYNTHETIC_YAML_CANARY\n",  # pragma: allowlist secret
        "password: &provider prefix SYNTHETIC_YAML_CANARY\n",  # pragma: allowlist secret
        "password: !!str prefix SYNTHETIC_YAML_CANARY\n",  # pragma: allowlist secret
        "password: !custom &provider |-\n  SYNTHETIC_YAML_CANARY\n",  # pragma: allowlist secret
        'password: &provider !!str "prefix SYNTHETIC_YAML_CANARY"\n',  # pragma: allowlist secret
        "api_key: &SYNTHETIC_YAML_CANARY harmless\npassword: *SYNTHETIC_YAML_CANARY\n",  # pragma: allowlist secret
    ],
    ids=[
        "plain-tokens",
        "plain-continuation",
        "plain-blank-continuation",
        "anchored-literal",
        "anchored-folded",
        "anchored-plain",
        "tagged-plain",
        "tagged-anchored-block",
        "anchored-tagged-quoted",
        "alias",
    ],
)
@pytest.mark.parametrize(
    "capacity", ["codex", "grok", "kimi", "agy", "claude", "glmcp", "qwencloud"]
)
@pytest.mark.parametrize("code", [0, 7, "timeout"])
def test_yaml_scalars_are_redacted_at_every_destination(
    bench, monkeypatch, capsys, caplog, diagnostic, capacity, code
):
    module, _bin_dir, brief, out = bench
    monkeypatch.setattr(module, "_require_binary", lambda name: name)
    monkeypatch.setattr(module, "_is_git_checkout", lambda cwd: True)
    if capacity in module.WRAPPED_CLAUDE:
        monkeypatch.setenv(module.WRAPPED_CLAUDE[capacity][0], str(brief))

    def run(argv, *, cwd, timeout):
        if capacity == "codex":
            Path(argv[argv.index("-o") + 1]).write_text(diagnostic)
        stdout = diagnostic
        if capacity in {"claude", "glmcp", "qwencloud"}:
            stdout = json.dumps({"result": diagnostic})
        return code, stdout, diagnostic, False, None

    monkeypatch.setattr(module, "_run", run)
    rc = module.main([capacity, "--brief", str(brief), "--out", str(out)])
    assert rc == (0 if code == 0 else 4 if code == "timeout" else 3)
    captured = capsys.readouterr()
    destinations = {
        "answer": out.read_text(),
        "receipt": out.with_name(out.name + ".receipt.json").read_text(),
        "stdout": captured.out,
        "stderr/journal": captured.err,
        "log": caplog.text,
    }
    leaks = [
        destination
        for destination, text in destinations.items()
        if "SYNTHETIC_YAML_CANARY" in text  # pragma: allowlist secret
    ]
    assert not leaks, f"credential reached destinations: {', '.join(leaks)}"
    assert "<redacted>" in destinations["answer"]
    assert _receipt(out)["output_bytes"] == len(out.read_bytes())


@pytest.mark.parametrize(
    "payload",
    [{}, {"result": None}, {"result": 42}, {"result": []}, {"result": {}}, {"result": " \n\t"}],
    ids=["missing", "null", "number", "list", "object", "whitespace"],
)
@pytest.mark.parametrize("capacity", ["claude", "glmcp", "qwencloud"])
@pytest.mark.parametrize("stream_array", [False, True], ids=["object", "stream-array"])
def test_invalid_claude_result_envelope_is_receipted_failure(
    bench, monkeypatch, capsys, payload, capacity, stream_array
):
    module, _bin_dir, brief, out = bench
    monkeypatch.setattr(module, "_require_binary", lambda name: name)
    if capacity in module.WRAPPED_CLAUDE:
        monkeypatch.setenv(module.WRAPPED_CLAUDE[capacity][0], str(brief))
    payload = {"type": "result", "modelUsage": {"synthetic-served": {}}, **payload}
    stdout = json.dumps([payload] if stream_array else payload)
    monkeypatch.setattr(module, "_run", lambda *a, **kw: (0, stdout, "", False, None))
    assert module.main([capacity, "--brief", str(brief), "--out", str(out)]) == 3
    receipt = _receipt(out)
    assert receipt["exit_code"] == 3
    assert receipt["failure_class"] == "OutputNotProduced"
    assert receipt["output_bytes"] == 0 and out.read_bytes() == b""
    assert receipt["models_reported"] == ["synthetic-served"]
    captured = capsys.readouterr()
    for diagnostic in (receipt["stderr_tail"], captured.err):
        assert "invalid result envelope" in diagnostic
    assert "retry" in receipt["recovery_action"]
    assert "--out" in receipt["recovery_action"]
    assert captured.out == ""


@pytest.mark.parametrize(
    "encoding",
    [
        "object-in-object",
        "json-in-string",
        "escaped-quotes",
        "unicode-quotes",
        "sensitive-subtree",
        "string-assignment",
        "string-colon",
        "unicode-key",
        "prefixed-key",
    ],
)
@pytest.mark.parametrize("capacity", ["claude", "glmcp", "qwencloud"])
@pytest.mark.parametrize("code", [0, 7, "timeout"])
def test_nested_claude_credentials_never_reach_destinations(
    bench, monkeypatch, capsys, caplog, encoding, capacity, code
):
    module, _bin_dir, brief, out = bench
    monkeypatch.setattr(module, "_require_binary", lambda name: name)
    if capacity in module.WRAPPED_CLAUDE:
        monkeypatch.setenv(module.WRAPPED_CLAUDE[capacity][0], str(brief))
    canary = "SYNTHETIC_ENVELOPE_CANARY"  # pragma: allowlist secret
    credential = {"api_key": canary}  # pragma: allowlist secret
    if encoding == "object-in-object":
        answer = json.dumps({"outer": credential})
    elif encoding == "json-in-string":
        answer = json.dumps({"outer": json.dumps(credential)})
    elif encoding == "escaped-quotes":
        answer = json.dumps({"outer": json.dumps(json.dumps(credential))})
    elif encoding == "unicode-quotes":
        answer = json.dumps({"outer": json.dumps(credential)}).replace('\\"', r"\u0022")
    elif encoding == "sensitive-subtree":
        answer = json.dumps({"password": {"outer": [canary]}})  # pragma: allowlist secret
    elif encoding in {"string-assignment", "string-colon"}:
        separator = "=" if encoding == "string-assignment" else ": "
        assignment = f"api_key{separator}{canary}"  # pragma: allowlist secret
        answer = json.dumps({"outer": [assignment]})
    elif encoding == "prefixed-key":
        answer = json.dumps({"ANTHROPIC_API_KEY": canary})  # pragma: allowlist secret
    else:
        answer = json.dumps(credential).replace("api_key", r"\u0061pi_key")
    stdout = json.dumps({"result": answer, "modelUsage": {"synthetic-served": {}}})
    # The diagnostic stream can quote the same serialized response, even on success.
    monkeypatch.setattr(module, "_run", lambda *a, **kw: (code, stdout, stdout, False, None))
    assert module.main([capacity, "--brief", str(brief), "--out", str(out)]) == (
        0 if code == 0 else 4 if code == "timeout" else 3
    )
    captured = capsys.readouterr()
    destinations = {
        "answer": out.read_text(),
        "receipt": out.with_name(out.name + ".receipt.json").read_text(),
        "stdout": captured.out,
        "stderr/journal": captured.err,
        "log": caplog.text,
    }
    leaks = [name for name, value in destinations.items() if canary in value]
    assert not leaks, f"credential reached destinations: {', '.join(leaks)}"
    assert "<redacted>" in destinations["answer"]
    receipt = _receipt(out)
    assert receipt["output_bytes"] == len(out.read_bytes()) > 0
    assert receipt["models_reported"] == ["synthetic-served"]
    assert receipt["exit_code"] == code
    if code != 0:
        assert "retry" in receipt["recovery_action"]


@pytest.mark.parametrize("capacity", ["claude", "glmcp", "qwencloud"])
@pytest.mark.parametrize("response", ["truncated", "leading-chatter", "json-in-string", "empty"])
@pytest.mark.parametrize("code", [0, 7, "timeout"])
def test_undecodable_claude_envelope_cannot_claim_success(
    bench, monkeypatch, capsys, caplog, capacity, response, code
):
    module, _bin_dir, brief, out = bench
    monkeypatch.setattr(module, "_require_binary", lambda name: name)
    if capacity in module.WRAPPED_CLAUDE:
        monkeypatch.setenv(module.WRAPPED_CLAUDE[capacity][0], str(brief))
    canary = "SYNTHETIC_UNDECODABLE_CANARY"  # pragma: allowlist secret
    credential = json.dumps({"api_key": canary})  # pragma: allowlist secret
    envelope = json.dumps({"result": credential})
    stdout = envelope[:-1] if response == "truncated" else "startup chatter\n" + envelope
    if response == "json-in-string":
        stdout = json.dumps(envelope)[:-1]
    if response == "empty":
        stdout = ""
    monkeypatch.setattr(module, "_run", lambda *a, **kw: (code, stdout, "", False, None))
    assert module.main([capacity, "--brief", str(brief), "--out", str(out)]) == (
        4 if code == "timeout" else 3
    )
    receipt = _receipt(out)
    captured = capsys.readouterr()
    destinations = {
        "answer": out.read_text(),
        "receipt": out.with_name(out.name + ".receipt.json").read_text(),
        "stdout": captured.out,
        "stderr/journal": captured.err,
        "log": caplog.text,
    }
    leaks = [name for name, value in destinations.items() if canary in value]
    assert not leaks, f"credential reached destinations: {', '.join(leaks)}"
    assert receipt["answer_policy"] == "suppressed_undecodable_output"
    assert receipt["suppressed_streams"] == {
        "stdout": {
            "length": len(stdout),
            "first_token_class": {
                "truncated": "object",
                "leading-chatter": "text",
                "json-in-string": "string",
                "empty": "empty",
            }[response],
            "reason": "undecodable_stream_suppressed",
        }
    }
    assert receipt["exit_code"] == (3 if code == 0 else code)
    assert receipt["failure_class"] == "OutputNotProduced"
    assert receipt["output_bytes"] == 0 and out.read_bytes() == b""
    assert "startup chatter" not in receipt["stderr_tail"]
    assert "undecodable_result_envelope" in receipt["stderr_tail"]
    assert "undecodable_stream_suppressed" in receipt["stderr_tail"]
    assert "retry" in receipt["recovery_action"]
    assert ("--timeout" if code == "timeout" else "--out") in receipt["recovery_action"]
    assert "retry" in captured.err
    assert captured.out == "" and caplog.text == ""


@pytest.mark.parametrize("capacity", ["claude", "glmcp", "qwencloud"])
@pytest.mark.parametrize("code", [0, 7, "timeout"])
@pytest.mark.parametrize("stream", ["stdout", "stderr", "both"])
@pytest.mark.parametrize(
    "encoding",
    ["truncated", "leading-chatter", "json-in-string", "nested-truncated", "escaped-label"],
)
def test_undecodable_claude_diagnostic_stream_is_suppressed(
    bench, monkeypatch, capsys, caplog, capacity, code, stream, encoding
):
    module, _bin_dir, brief, out = bench
    monkeypatch.setattr(module, "_require_binary", lambda name: name)
    if capacity in module.WRAPPED_CLAUDE:
        monkeypatch.setenv(module.WRAPPED_CLAUDE[capacity][0], str(brief))
    canary = "SYNTHETIC_BROKEN_STREAM_CANARY"  # pragma: allowlist secret
    credential = json.dumps({"api_key": canary})  # pragma: allowlist secret
    envelope = json.dumps({"result": credential})
    malformed = {
        "truncated": envelope[:-1],
        "leading-chatter": "startup chatter\n" + envelope,
        "json-in-string": json.dumps(envelope)[:-1],
        "nested-truncated": json.dumps({"result": json.dumps(envelope)[:-1]}),
        "escaped-label": credential.replace('"', r"\u0022")[:-1],
    }[encoding]
    stdout = json.dumps({"result": "SAFE ANSWER"}) if stream == "stderr" else malformed
    stderr = "" if stream == "stdout" else malformed
    monkeypatch.setattr(module, "_run", lambda *a, **kw: (code, stdout, stderr, False, None))
    expected_rc = 4 if code == "timeout" else 0 if code == 0 and stream == "stderr" else 3
    assert module.main([capacity, "--brief", str(brief), "--out", str(out)]) == expected_rc
    captured = capsys.readouterr()
    destinations = {
        "answer": out.read_text(),
        "receipt": out.with_name(out.name + ".receipt.json").read_text(),
        "stdout": captured.out,
        "stderr/journal": captured.err,
        "log": caplog.text,
    }
    leaks = [name for name, value in destinations.items() if canary in value]
    assert not leaks, f"credential reached destinations: {', '.join(leaks)}"
    receipt = _receipt(out)
    assert receipt["answer_policy"] == "suppressed_undecodable_output"
    expected_streams = {"stdout", "stderr"} if stream == "both" else {stream}
    assert set(receipt["suppressed_streams"]) == expected_streams
    for shape in receipt["suppressed_streams"].values():
        assert shape == {
            "length": len(malformed),
            "first_token_class": "text"
            if encoding == "leading-chatter"
            else ("string" if encoding == "json-in-string" else "object"),
            "reason": "undecodable_stream_suppressed",
        }
    assert out.read_text() == ("SAFE ANSWER" if stream == "stderr" else "")
    assert receipt["output_bytes"] == len(out.read_bytes())
    assert "startup chatter" not in receipt["stderr_tail"]
    assert "undecodable_stream_suppressed" in receipt["stderr_tail"]
    assert caplog.text == ""


@pytest.mark.parametrize("condition", ["unwritable-directory", "directory-output", "disk-full"])
def test_answer_persistence_failure_is_receipted(bench, monkeypatch, capsys, caplog, condition):
    module, _bin_dir, brief, out = bench
    out.parent.mkdir()
    monkeypatch.setattr(module, "_require_binary", lambda name: name)
    monkeypatch.setattr(module, "_run", lambda *a, **kw: (0, "OK", "", False, None))
    original_write = Path.write_text
    if condition == "directory-output":
        out.mkdir()
    elif condition == "unwritable-directory":
        # Keep an existing receipt writable while forbidding new directory entries.
        receipt_path = out.with_name(out.name + ".receipt.json")
        receipt_path.write_text("{}")
        out.parent.chmod(0o555)

    def write(path, text, *args, **kwargs):
        if path == out and condition == "disk-full":
            original_write(path, text[:1], *args, **kwargs)
            raise OSError(errno.ENOSPC, "synthetic disk full")
        return original_write(path, text, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", write)
    try:
        rc = module.main(["grok", "--brief", str(brief), "--out", str(out)])
        receipt = _receipt(out)
        assert receipt["exit_code"] == 3, "receipt claimed success before answer persistence"
        assert rc == 3
        assert receipt["failure_class"] == "AnswerPersistenceFailed"
        assert receipt["out"] == str(out)
        actual_bytes = len(out.read_bytes()) if out.is_file() else 0
        assert receipt["output_bytes"] == actual_bytes
        captured = capsys.readouterr()
        assert captured.out == "" and caplog.text == ""
        assert "Traceback" not in captured.err
        assert "answer persistence failed" in receipt["stderr_tail"]
        for diagnostic in (receipt["recovery_action"], captured.err):
            for action in (str(out), "directory", "mode", "space", "writable --out", "retry"):
                assert action in diagnostic
    finally:
        out.parent.chmod(0o755)


def test_success_receipt_follows_verified_answer_bytes(bench, monkeypatch):
    module, _bin_dir, brief, out = bench
    monkeypatch.setattr(module, "_require_binary", lambda name: name)
    monkeypatch.setattr(module, "_run", lambda *a, **kw: (0, "réponse\n", "", False, None))
    original_receipt = module.write_receipt

    def write_receipt(path, **kwargs):
        assert out.is_file(), "success receipt preceded answer persistence"
        assert out.read_bytes() == kwargs["result"].answer.encode("utf-8")
        return original_receipt(path, **kwargs)

    monkeypatch.setattr(module, "write_receipt", write_receipt)
    assert module.main(["grok", "--brief", str(brief), "--out", str(out)]) == 0
    assert _receipt(out)["output_bytes"] == len(out.read_bytes())


@pytest.mark.parametrize("preexisting", [False, True], ids=["absent", "old-answer"])
def test_incomplete_answer_write_cannot_claim_success(bench, monkeypatch, preexisting):
    module, _bin_dir, brief, out = bench
    out.parent.mkdir()
    if preexisting:
        out.write_text("older answer")
    monkeypatch.setattr(module, "_require_binary", lambda name: name)
    monkeypatch.setattr(module, "_run", lambda *a, **kw: (0, "OK", "", False, None))
    original_write = Path.write_text

    def write(path, text, *args, **kwargs):
        if path == out:
            if not preexisting:
                original_write(path, text[:1], *args, **kwargs)
            return len(text)  # Silent short/no-op write must be caught by readback.
        return original_write(path, text, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", write)
    assert module.main(["grok", "--brief", str(brief), "--out", str(out)]) == 3
    receipt = _receipt(out)
    assert receipt["exit_code"] == 3
    assert receipt["failure_class"] == "AnswerPersistenceFailed"
    assert receipt["output_bytes"] == len(out.read_bytes())


@pytest.mark.parametrize("missing_parent", [False, True], ids=["write-answer", "create-parent"])
def test_unwritable_directory_retains_a_temporary_failure_receipt(
    bench, monkeypatch, capsys, tmp_path, missing_parent
):
    module, _bin_dir, brief, out = bench
    out.parent.mkdir()
    blocked_directory = out.parent
    if missing_parent:
        out = out.parent / "missing" / out.name
    monkeypatch.setattr(module.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(module, "_require_binary", lambda name: name)

    def run(*args, **kwargs):
        assert not missing_parent, "capacity ran before its output directory was created"
        return 0, "OK", "", False, None

    monkeypatch.setattr(module, "_run", run)
    blocked_directory.chmod(0o555)
    try:
        assert module.main(["grok", "--brief", str(brief), "--out", str(out)]) == 3
        captured = capsys.readouterr()
        (fallback,) = tmp_path.glob("hapax-recruit-*.receipt.json")
        receipt = json.loads(fallback.read_text())
        assert str(fallback) in captured.err and str(out) in captured.err
        assert fallback.stat().st_mode & 0o777 == 0o600
        assert receipt["failure_class"] == "AnswerPersistenceFailed"
        assert receipt["exit_code"] == 3 and receipt["output_bytes"] == 0
        assert "writable --out" in receipt["recovery_action"]
        assert captured.out == "" and "Traceback" not in captured.err
    finally:
        blocked_directory.chmod(0o755)


def test_unwritable_receipt_and_fallback_name_recovery_without_traceback(
    bench, monkeypatch, capsys, caplog
):
    module, _bin_dir, brief, out = bench
    monkeypatch.setattr(module, "_require_binary", lambda name: name)
    monkeypatch.setattr(module, "_run", lambda *a, **kw: (0, "OK", "", False, None))
    original_write = Path.write_text

    def write(path, text, *args, **kwargs):
        if path.name.endswith(".receipt.json"):
            raise OSError(errno.ENOSPC, "synthetic receipt disk full")
        return original_write(path, text, *args, **kwargs)

    def fallback(*args, **kwargs):
        raise OSError(errno.ENOSPC, "synthetic temporary disk full")

    monkeypatch.setattr(Path, "write_text", write)
    monkeypatch.setattr(module.tempfile, "NamedTemporaryFile", fallback)
    assert module.main(["grok", "--brief", str(brief), "--out", str(out)]) == 3
    captured = capsys.readouterr()
    assert out.read_text() == "OK"
    assert "cannot persist receipt" in captured.err
    assert "mode and space" in captured.err and "writable --out" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == "" and caplog.text == ""
