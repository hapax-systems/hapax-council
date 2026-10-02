"""Token Plan launcher checks use executable fixtures, never live credentials."""

from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/hapax-qwencloud-claude"
FIXTURE_KEY = "sk-sp-inert-fixture-only"  # pragma: allowlist secret
TASK = "qwencloud-entitlement-activation-20260914"


def load_script(path=SCRIPT):
    loader = importlib.machinery.SourceFileLoader("qwencloud_launcher", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def bench(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    capture = tmp_path / "capture.json"
    reads = tmp_path / "reads"
    (bin_dir / "hapax-secret").write_text(
        f"#!{sys.executable}\n"
        "from pathlib import Path\nimport sys\n"
        f"Path({str(reads)!r}).write_text(sys.argv[1])\n"
        f"print({FIXTURE_KEY!r})\n"
    )
    (bin_dir / "hapax-secret").chmod(0o755)
    client = bin_dir / "opencode"
    client.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\nfrom pathlib import Path\n"
        "if '--version' in sys.argv:\n print('1.17.4'); sys.exit(0)\n"
        f"Path({str(capture)!r}).write_text(json.dumps({{'argv':sys.argv,'env':dict(os.environ),'cwd':os.getcwd()}}))\n"
        "print(json.dumps({'type':'text','part':{'text':'QWENCLOUD_OK'}}))\n"
        "print(json.dumps({'type':'step_finish','part':{'reason':'stop','tokens':{'input':12,'output':4}}}))\n"
    )
    client.chmod(0o755)
    env = {
        "PATH": str(bin_dir),
        "HOME": str(tmp_path),
        "LANG": "C.UTF-8",
        "OPENAI_API_KEY": "inert-ambient-auth",  # pragma: allowlist secret
        "ANTHROPIC_AUTH_TOKEN": "inert-other-provider",
        "HTTPS_PROXY": "https://inert-proxy.invalid",
        "OPENCODE_CONFIG_CONTENT": '{"model":"other/paid-model"}',
        "NODE_OPTIONS": "inert-injection",
    }
    return env, capture, reads, client


def run(bench, *args, script=SCRIPT, fixture_bounds=False):
    command = [sys.executable, str(script)]
    if fixture_bounds:
        # Test-only injection into the in-process module; no production bypass flag.
        # The fake executable cannot retry or contact a provider.
        command = [
            sys.executable,
            "-c",
            (
                "import runpy, sys\n"
                "ns=runpy.run_path(sys.argv.pop(1))\n"
                "ns['main'].__globals__['require_single_attempt']=lambda: None\n"
                "raise SystemExit(ns['main']())\n"
            ),
            str(script),
        ]
    return subprocess.run(
        [*command, "--task", TASK, *args],
        env=bench[0],
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_client_receives_only_plan_binding_and_private_state(bench):
    proc = run(bench, "--smoke")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    receipt = json.loads(proc.stdout)
    observed = json.loads(bench[1].read_text())
    env = observed["env"]
    config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    selected = "bailian-token-plan-personal/qwen3.8-flash"
    assert config["model"] == config["small_model"] == selected
    assert config["enabled_providers"] == ["bailian-token-plan-personal"]
    provider = config["provider"]["bailian-token-plan-personal"]
    assert provider["options"]["baseURL"] == (
        "https://token-plan.ap-southeast-1.maas.aliyuncs.com/apps/anthropic/v1"
    )
    assert provider["npm"] == "@ai-sdk/anthropic"
    assert provider["options"]["apiKey"] == "{env:HAPAX_QWENCLOUD_PLAN_KEY}"
    assert env["HAPAX_QWENCLOUD_PLAN_KEY"] == FIXTURE_KEY
    assert FIXTURE_KEY not in json.dumps(observed["argv"])
    assert FIXTURE_KEY not in env["OPENCODE_CONFIG_CONTENT"]
    assert FIXTURE_KEY not in proc.stdout + proc.stderr
    assert not set(env) & {"OPENAI_API_KEY", "ANTHROPIC_AUTH_TOKEN", "HTTPS_PROXY", "NODE_OPTIONS"}
    assert env["OPENCODE_DISABLE_PROJECT_CONFIG"] == "1"
    assert env["OPENCODE_DISABLE_DEFAULT_PLUGINS"] == "1"
    assert env["OPENCODE_DISABLE_EXTERNAL_SKILLS"] == "1"
    assert env["OPENCODE_DISABLE_CLAUDE_CODE"] == "1"
    assert "--pure" in observed["argv"]
    assert config["permission"] == {"*": "deny"}
    assert config["share"] == "disabled"
    assert config["autoupdate"] is False
    assert observed["cwd"] == env["HOME"]
    assert env["HOME"].startswith("/dev/shm/hapax-qwencloud-")
    assert not Path(env["HOME"]).exists()
    for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
        assert Path(env[name]).is_relative_to(env["HOME"])
    assert receipt["served_model"] is None
    assert receipt["plan_quota_delta"] is None
    assert receipt["client_tokens"] == {"input": 12, "output": 4}
    assert bench[2].read_text() == "alibaba-cloud/plan-api-key"


def test_check_never_retrieves_credential_or_calls_model(bench):
    proc = run(bench, "--check")
    assert proc.returncode == 0
    assert not bench[2].exists()
    assert not bench[1].exists()
    assert json.loads(proc.stdout)["credential_read"] is False


@pytest.mark.parametrize(
    "credential,lookup_name",
    [("alibaba", "alibaba-cloud/plan-api-key"), ("legacy", "qwencloud/apikey")],
)
@pytest.mark.parametrize("action", ["--smoke", "--check"])
def test_stdout_omits_lookup_names_and_credential_value(bench, credential, lookup_name, action):
    proc = run(bench, action, "--credential", credential)
    assert proc.returncode == 0
    for name in ("alibaba-cloud/plan-api-key", "qwencloud/apikey"):
        assert name not in proc.stdout
    assert FIXTURE_KEY not in proc.stdout + proc.stderr
    assert "secret_name" not in json.loads(proc.stdout)
    if action == "--smoke":
        assert bench[2].read_text() == lookup_name
    else:
        assert not bench[2].exists()
        assert not bench[1].exists()


@pytest.mark.parametrize(
    "name",
    [
        "HAPAX_QWENCLOUD_ANTHROPIC_BASE_URL",
        "HAPAX_QWENCLOUD_ALLOW_BASE_URL_OVERRIDE",
        "HAPAX_QWENCLOUD_ALLOW_NON_PLAN_MODEL",
    ],
)
def test_legacy_escape_knobs_cannot_redirect_plan_key(bench, name):
    bench[0][name] = "1"
    proc = run(bench, "--smoke")
    assert proc.returncode != 0
    assert "legacy_override_refused" in proc.stdout
    assert not bench[2].exists()
    assert not bench[1].exists()


@pytest.mark.parametrize(
    "args",
    [
        ("--model", "other/paid-model"),
        ("--model", "qwen3.8-plus"),
        ("--credential", "other-key"),
        ("--share",),
        ("--attach", "http://other.invalid"),
        ("--timeout", "nan"),
        ("--timeout", "10000"),
    ],
)
def test_unreviewed_route_arguments_refuse_before_secrets(bench, args):
    proc = run(bench, "--smoke", *args)
    assert proc.returncode != 0
    assert not bench[2].exists()
    assert not bench[1].exists()


def test_legacy_credential_is_explicit_and_not_an_automatic_fallback(bench):
    proc = run(bench, "--smoke", "--credential", "legacy")
    assert proc.returncode == 0
    assert bench[2].read_text() == "qwencloud/apikey"


def test_nonzero_secret_helper_cannot_supply_nonempty_key(bench):
    helper = bench[3].parent / "hapax-secret"
    helper.write_text(helper.read_text() + "sys.exit(1)\n")
    proc = run(bench, "--smoke")
    assert proc.returncode != 0
    assert "secret_read_failed" in proc.stdout
    assert not bench[1].exists()
    assert FIXTURE_KEY not in proc.stdout + proc.stderr


def test_printable_opaque_plan_credential_reaches_client_unchanged(bench):
    opaque = "sk-sp-inert.fixture+suffix=="  # pragma: allowlist secret
    helper = bench[3].parent / "hapax-secret"
    helper.write_text(helper.read_text().replace(FIXTURE_KEY, opaque))
    proc = run(bench, "--smoke")
    assert proc.returncode == 0, proc.stdout
    assert json.loads(bench[1].read_text())["env"]["HAPAX_QWENCLOUD_PLAN_KEY"] == opaque
    assert opaque not in proc.stdout + proc.stderr


@pytest.mark.parametrize(
    "value", ["sk-other-inert", "sk-sp-", "sk-sp-inert injected", "sk-sp-inert\nheader"]
)
def test_invalid_plan_credential_never_reaches_client(bench, value):
    helper = bench[3].parent / "hapax-secret"
    helper.write_text(helper.read_text().replace(repr(FIXTURE_KEY), repr(value)))
    proc = run(bench, "--smoke")
    assert proc.returncode != 0
    assert "plan_key_shape_invalid" in proc.stdout
    assert not bench[1].exists()


def test_raw_provider_output_and_failures_cannot_leak(bench):
    client = bench[3]
    client.write_text(
        client.read_text()
        + (
            f"print({FIXTURE_KEY!r})\n"
            f"print({FIXTURE_KEY!r}, file=sys.stderr)\n"
            "print(json.dumps({'type':'text','part':{'text':os.environ['HAPAX_QWENCLOUD_PLAN_KEY']}}))\n"
            "sys.exit(1)\n"
        )
    )
    proc = run(bench, "--smoke")
    assert proc.returncode != 0
    assert FIXTURE_KEY not in proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["ok"] is False
    assert not Path(json.loads(bench[1].read_text())["env"]["HOME"]).exists()


def test_success_requires_completed_exact_synthetic_answer(bench):
    client = bench[3]
    client.write_text(client.read_text().replace("'QWENCLOUD_OK'", "'different answer'"))
    proc = run(bench, "--smoke")
    assert proc.returncode != 0
    assert json.loads(proc.stdout)["answered"] is False


def test_receipt_does_not_accept_arbitrary_token_strings():
    module = load_script()
    payload = json.dumps(
        {
            "type": "step_finish",
            "part": {
                "reason": "stop",
                "tokens": {"input": FIXTURE_KEY, "output": True, "total": -1},
            },
        }
    ).encode()
    assert module.summarize(payload, 0)["client_tokens"] == {}


def test_client_error_preserves_http_predicate_without_raw_provider_content():
    module = load_script()
    payload = json.dumps(
        {
            "type": "error",
            "error": {
                "name": "APIError",
                "data": {
                    "statusCode": 401,
                    "isRetryable": False,
                    "message": FIXTURE_KEY,
                    "responseBody": FIXTURE_KEY,
                    "responseHeaders": {"secret": FIXTURE_KEY},
                },
            },
        }
    ).encode()
    result = module.summarize(payload, 1)
    assert result["client_errors"] == [
        {"class": "APIError", "http_status": 401, "retryable": False}
    ]
    assert FIXTURE_KEY not in json.dumps(result)
    assert result["ok"] is False


def test_client_error_rejects_untyped_fields():
    module = load_script()
    payload = json.dumps(
        {
            "type": "error",
            "error": {
                "name": FIXTURE_KEY,
                "data": {"statusCode": FIXTURE_KEY, "isRetryable": FIXTURE_KEY},
            },
        }
    ).encode()
    result = module.summarize(payload, 1)
    assert result["client_errors"] == []
    assert FIXTURE_KEY not in json.dumps(result)


def test_disk_backed_scratch_is_refused(monkeypatch):
    module = load_script()
    monkeypatch.setattr(Path, "read_text", lambda self: "none /dev/shm ext4 rw 0 0\n")
    with pytest.raises(module.Refusal, match="tmpfs_missing"):
        module.require_tmpfs()


def test_timeout_kills_descendant_and_removes_client_state(bench, tmp_path):
    child_pid = tmp_path / "child-pid"
    client = bench[3]
    client.write_text(
        client.read_text()
        + (
            "import subprocess\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
            f"Path({str(child_pid)!r}).write_text(str(child.pid))\n"
        )
    )
    pid = None
    try:
        proc = run(bench, "--smoke", "--timeout", "1")
        assert proc.returncode != 0
        assert "client_timeout" in proc.stdout
        pid = int(child_pid.read_text())
        stat = Path(f"/proc/{pid}/stat")
        for _ in range(50):
            if not stat.exists() or stat.read_text().split()[2] == "Z":
                break
            time.sleep(0.01)
        assert not stat.exists() or stat.read_text().split()[2] == "Z"
        assert not Path(json.loads(bench[1].read_text())["env"]["HOME"]).exists()
    finally:
        if pid is None and child_pid.exists():
            pid = int(child_pid.read_text())
        if pid:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def useful_fixture(bench, tmp_path):
    packet = tmp_path / "public.json"
    code = "def call():\n    raise ValueError('admission_missing')\n"
    packet.write_text(
        json.dumps(
            [
                {
                    "url": "https://github.com/hapax-systems/hapax-council/blob/"
                    + "a" * 40
                    + "/shared/example.py",
                    "sha256": hashlib.sha256(code.encode()).hexdigest(),
                    "text": code,
                }
            ]
        )
    )
    artifact = useful_fixture_artifact()
    bench[3].write_text(bench[3].read_text().replace("'QWENCLOUD_OK'", repr(json.dumps(artifact))))
    return packet, tmp_path / "answer.json", artifact


def test_useful_job_delivers_bounded_context_and_validated_artifact(bench, tmp_path):
    packet, output, artifact = useful_fixture(bench, tmp_path)
    proc = run(
        bench,
        "--negative-tests",
        str(packet),
        "--output",
        str(output),
        "--timeout",
        "600",
        fixture_bounds=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(output.read_text()) == artifact
    assert output.stat().st_mode & 0o777 == 0o600
    receipt = json.loads(proc.stdout)
    assert receipt["artifact_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert receipt["input_sha256"] == hashlib.sha256(packet.read_bytes()).hexdigest()
    observed = json.loads(bench[1].read_text())
    env = observed["env"]
    cfg = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert env["OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX"] == "8192"
    assert (
        cfg["provider"]["bailian-token-plan-personal"]["models"]["qwen3.8-flash"]["limit"]["output"]
        == 8192
    )
    assert cfg["compaction"] == {"auto": False, "prune": False}
    assert all(cfg["agent"][a]["disable"] for a in ("title", "summary", "compaction"))
    assert "missing_attempt_ledger" in observed["argv"][-1]
    assert "def call():" in observed["argv"][-1]
    assert (SCRIPT.parents[1] / "AGENTS.md").read_text() in cfg["agent"]["plan-probe"]["prompt"]
    assert (SCRIPT.parents[1] / "config/agent-instructions/AGENTS.md").read_text() in cfg["agent"][
        "plan-probe"
    ]["prompt"]
    assert FIXTURE_KEY not in output.read_text() + proc.stdout + proc.stderr
    assert not Path(env["HOME"]).exists()


@pytest.mark.parametrize(
    "bad", ["oversize", "hash", "private", "output", "legacy", "model", "timeout"]
)
def test_useful_preconditions_refuse_before_credential(bench, tmp_path, bad):
    packet, output, _ = useful_fixture(bench, tmp_path)
    extra = {
        "legacy": ["--credential", "legacy"],
        "model": ["--model", "glm-5.3"],
        "timeout": ["--timeout", "601"],
    }.get(bad, [])
    if bad == "oversize":
        source = json.loads(packet.read_text())
        source[0]["text"] = "x" * 32768
        source[0]["sha256"] = hashlib.sha256(source[0]["text"].encode()).hexdigest()
        packet.write_text(json.dumps(source))
    if bad == "hash":
        packet.write_text(packet.read_text().replace("def call", "def fail"))
    if bad == "private":
        packet.write_text(packet.read_text().replace("hapax-systems", "private-owner"))
    if bad == "output":
        output.symlink_to(tmp_path / "not-created")
    proc = run(
        bench, "--negative-tests", str(packet), "--output", str(output), *extra, fixture_bounds=True
    )
    assert proc.returncode != 0
    if bad == "oversize":
        assert "input_too_large" in proc.stdout
    assert not bench[1].exists() and not bench[2].exists()


@pytest.mark.parametrize(
    "bad",
    [
        "empty",
        "partial",
        "error",
        "duplicate",
        "field",
        "field_limit",
        "count",
        "secret",
        "oversize",
        "nonzero",
        "late_text",
        "token_overrun",
        "missing_tokens",
        "malformed",
        "smoke",
    ],
)
def test_invalid_useful_output_is_not_persisted(bench, tmp_path, bad):
    packet, output, artifact = useful_fixture(bench, tmp_path)
    if bad == "duplicate":
        artifact["cases"][-1]["id"] = artifact["cases"][0]["id"]
    if bad == "field":
        artifact["cases"][0]["expected_refusal"] = ""
    if bad == "field_limit":
        artifact["cases"][0]["expected_refusal"] = "x" * 2001
    if bad == "count":
        artifact["cases"][0]["expected_transport_count"] = True
    if bad == "secret":
        artifact["cases"][0]["input_precondition"] = FIXTURE_KEY
    if bad == "oversize":
        for case in artifact["cases"]:
            case["input_precondition"] = "🙂" * 1500
    source = (
        bench[3]
        .read_text()
        .replace(repr(json.dumps(useful_fixture_artifact())), repr(json.dumps(artifact)))
    )
    if bad == "empty":
        source = source.replace(repr(json.dumps(artifact)), "''")
    if bad == "smoke":
        source = source.replace(repr(json.dumps(artifact)), "'QWENCLOUD_OK'")
    if bad == "partial":
        source = source.replace("'reason':'stop'", "'reason':'length'")
    if bad == "error":
        source += "print(json.dumps({'type':'error','error':{'name':'APIError'}}))\n"
    if bad == "nonzero":
        source += "sys.exit(1)\n"
    if bad == "late_text":
        source += "print(json.dumps({'type':'text','part':{'text':'extra'}}))\n"
    if bad == "token_overrun":
        source = source.replace("'output':4", "'output':8193")
    if bad == "missing_tokens":
        source = source.replace("'output':4", "'other':4")
    if bad == "malformed":
        source = source.replace(repr(json.dumps(artifact)), "{}")
    bench[3].write_text(source)
    proc = run(bench, "--negative-tests", str(packet), "--output", str(output), fixture_bounds=True)
    assert proc.returncode != 0, proc.stdout
    assert not output.exists()
    assert FIXTURE_KEY not in proc.stdout + proc.stderr


def test_useful_live_path_refuses_unbounded_client_retries(bench, tmp_path):
    packet, output, _ = useful_fixture(bench, tmp_path)
    proc = run(bench, "--negative-tests", str(packet), "--output", str(output))
    assert proc.returncode != 0
    assert "client_retry_control_unavailable" in proc.stdout
    assert not bench[1].exists() and not bench[2].exists() and not output.exists()


@pytest.mark.parametrize("symlink", [False, True])
def test_artifact_creation_preserves_an_existing_result(tmp_path, symlink):
    prior = tmp_path / "prior"
    prior.write_text("predecessor")
    output = tmp_path / "output" if symlink else prior
    if symlink:
        output.symlink_to(prior)
    with pytest.raises(FileExistsError):
        load_script().write_artifact(output, useful_fixture_artifact())
    assert prior.read_text() == "predecessor"


def useful_fixture_artifact():
    return {
        "cases": [
            {
                "id": case,
                "input_precondition": "Supply a refused input: " + case,
                "expected_refusal": "Refuse before delivery",
                "expected_transport_count": 0,
                "expected_persisted_evidence": "A fixed refusal receipt; no successful final row",
            }
            for case in load_script().CASE_IDS
        ]
    }
