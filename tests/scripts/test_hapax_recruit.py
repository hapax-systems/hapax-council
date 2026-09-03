"""scripts/hapax-recruit — every roster row through a stubbed CLI, plus a stubbed local endpoint."""

from __future__ import annotations

import http.server
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-recruit"


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
    return _module(), bin_dir, brief, out


def _receipt(out: Path) -> dict:
    return json.loads(out.with_name(out.name + ".receipt.json").read_text())


def test_codex_shape_reads_the_output_file_and_closes_stdin(bench, tmp_path: Path) -> None:
    module, bin_dir, brief, out = bench
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
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
    _stub(bin_dir, "codex", "print('should not run')\n")
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


def test_capacity_failure_and_timeout_keep_a_receipt(
    bench, capsys: pytest.CaptureFixture[str]
) -> None:
    module, bin_dir, brief, out = bench
    _stub(
        bin_dir,
        "grok",
        "print('half an answer'); print('api_key=sk-secret-value', file=sys.stderr); sys.exit(7)\n",
    )
    rc = module.main(["grok", "--brief", str(brief), "--out", str(out)])
    assert rc == 3
    receipt = _receipt(out)
    assert receipt["exit_code"] == 7
    assert (
        "sk-secret-value" not in receipt["stderr_tail"] and "<redacted>" in receipt["stderr_tail"]
    )
    assert "sk-secret-value" not in capsys.readouterr().err

    _stub(bin_dir, "kimi", "import time; print('working', flush=True); time.sleep(5)\n")
    rc = module.main(["kimi", "--brief", str(brief), "--out", str(out), "--timeout", "1"])
    assert rc == 4
    assert _receipt(out)["exit_code"] == "timeout"


def test_local_endpoint_posts_an_openai_chat_completion_and_records_the_served_model(
    bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _bin_dir, brief, out = bench
    seen: list[dict] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 — http.server's own naming
            length = int(self.headers.get("Content-Length", "0"))
            seen.append({"path": self.path, "body": json.loads(self.rfile.read(length))})
            payload = json.dumps(
                {
                    "model": "qwen3.6-35b-a3b-q5",
                    "choices": [{"message": {"role": "assistant", "content": "OK"}}],
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_: object) -> None:
            return

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setitem(
            module.LOCAL_ENDPOINTS,
            "local:qwen36",
            (f"http://127.0.0.1:{server.server_port}/v1", "qwen3.6-35b-a3b"),
        )
        rc = module.main(["local:qwen36", "--brief", str(brief), "--out", str(out)])
    finally:
        server.shutdown()

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
    monkeypatch.setitem(
        module.LOCAL_ENDPOINTS, "local:gemma3", ("http://127.0.0.1:9/v1", "gemma-3-4b")
    )

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
