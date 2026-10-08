from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import github_call_observation as observation
import github_pr_status


def response(body='{"ok":true}', *, remaining=400, resource="core", status=200):
    return (
        f"HTTP/2.0 {status}\r\nX-RateLimit-Resource: {resource}\r\n"
        f"X-RateLimit-Remaining: {remaining}\r\nX-RateLimit-Limit: 5000\r\n"
        "X-RateLimit-Reset: 2000\r\nX-RateLimit-Used: 4600\r\n"
        f"Set-Cookie: NEVER_LOG_HEADER\r\n\r\n{body}"
    )


def record(capsys):
    err = capsys.readouterr().err
    return json.loads(err.split(observation.LOG_PREFIX, 1)[1])


def test_rest_observation_preserves_body_and_records_authoritative_headers(
    monkeypatch, capsys, tmp_path
):
    monkeypatch.setattr(sys, "argv", ["/installed/scripts/hapax-pr-admission"])
    monkeypatch.setattr(observation.time, "time", lambda: 1000)
    calls = []

    def runner(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, response(), "")

    cmd = ["gh", "api", "repos/owner/repo/pulls/1"]
    result = observation.run_gh_observed(runner, cmd, repo_root=tmp_path)
    assert result.stdout == '{"ok":true}'
    assert result.args == cmd
    assert len(calls) == 1, "observing a response must not issue another GitHub call"
    assert calls[0][0] == [*cmd, "--include"]
    assert calls[0][1]["cwd"] == str(tmp_path)
    event = record(capsys)
    assert event["caller"] == "hapax-pr-admission"
    assert event["http_responses_observed"] == 1
    assert event["command_started"] is True
    assert event["pool"] == "core"
    assert event["auth_identity"] is None
    assert event["readings"][0] == {
        "resource": "core",
        "remaining": 400,
        "limit": 5000,
        "reset_epoch": 2000,
        "used": 4600,
        "source": "header",
    }


@pytest.mark.parametrize("include", ["-i", "--include"])
def test_explicit_include_output_is_preserved(include, capsys, tmp_path):
    cmd = ["gh", "api", include, "rate_limit"]
    raw = response('{"resources":{"graphql":{"remaining":4990,"limit":5000,"reset":2000}}}')
    seen = []

    def runner(actual, **kwargs):
        seen.append(actual)
        return subprocess.CompletedProcess(actual, 0, raw, "")

    result = observation.run_gh_observed(runner, cmd, repo_root=tmp_path)
    assert seen == [cmd]
    assert result.stdout == raw
    event = record(capsys)
    assert event["readings"][1]["resource"] == "graphql"
    assert event["readings"][1]["source"] == "body"


def test_failure_observation_never_logs_credentials_payload_or_arbitrary_caller(
    monkeypatch, capsys, tmp_path
):
    monkeypatch.setattr(sys, "argv", ["SECRET_CALLER"])
    monkeypatch.setenv("GH_TOKEN", "SECRET_TOKEN")
    body = '{"message":"API rate limit exceeded for user ID 418460. SECRET_BODY"}'
    cmd = ["gh", "api", "graphql", "-f", "query=SECRET_QUERY", "-H", "SECRET_REQUEST_HEADER"]
    result = observation.run_gh_observed(
        lambda actual, **kw: subprocess.CompletedProcess(
            actual, 1, response(body, resource="graphql", remaining=0, status=403), "SECRET_ERROR"
        ),
        cmd,
        repo_root=tmp_path,
    )
    assert result.returncode == 1
    err = capsys.readouterr().err
    assert "SECRET" not in err and "NEVER_LOG_HEADER" not in err
    event = json.loads(err.split(observation.LOG_PREFIX, 1)[1])
    assert event["caller"] == "unknown"
    assert event["auth_identity"] == "github_user_id:418460"
    assert event["auth_identity_source"] == "error_body"
    assert event["readings"][0]["remaining"] == 0


@pytest.mark.parametrize(
    "cmd",
    [
        ["gh", "pr", "list", "--json", "number"],
        ["gh", "api", "--paginate", "repos/owner/repo/pulls"],
        ["gh", "api", "repos/owner/repo/pulls", "--jq", ".[0]"],
        ["gh", "api", "-i", "--cache", "1h", "rate_limit"],
        ["gh", "api", "repos/owner/repo/pulls", "-q.[0]"],
    ],
)
def test_compound_or_filtered_cli_is_not_counted_as_one_http_response(cmd, capsys, tmp_path):
    seen = []

    def runner(actual, **kw):
        seen.append(actual)
        return subprocess.CompletedProcess(actual, 0, "[]", "")

    observation.run_gh_observed(runner, cmd, repo_root=tmp_path)
    assert seen == [cmd]
    event = record(capsys)
    assert event["command_started"] is True
    assert event["http_responses_observed"] == 0
    assert event["request_count_exact"] is False
    assert event["readings"] == []


def test_cli_cached_headers_are_not_a_new_response_or_headroom_observation(capsys, tmp_path):
    raw = response()
    result = observation.run_gh_observed(
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, raw, ""),
        ["gh", "api", "--include", "rate_limit", "--cache", "1h"],
        repo_root=tmp_path,
    )
    assert result.stdout == raw
    event = record(capsys)
    assert event["http_responses_observed"] == 0
    assert event["readings"] == []


@pytest.mark.parametrize(
    "failure,started",
    [
        (FileNotFoundError("SECRET_ERROR"), False),
        (subprocess.TimeoutExpired(["SECRET_COMMAND"], 1), True),
    ],
)
def test_launch_failure_and_timeout_are_not_confirmed_requests(failure, started, capsys, tmp_path):
    def runner(*args, **kwargs):
        raise failure

    with pytest.raises(type(failure)):
        observation.run_gh_observed(runner, ["gh", "api", "rate_limit"], repo_root=tmp_path)
    event = record(capsys)
    assert event["command_started"] is started
    assert event["http_responses_observed"] == 0
    assert event["readings"] == []


def test_cache_hit_is_zero_calls_and_does_not_refresh_pool_evidence(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(github_pr_status, "DEFAULT_CACHE_DIR", tmp_path / "cache")
    github_pr_status._write_cached_rollup("owner/repo", "abc", [{"name": "lint"}])

    def no_call(*args, **kwargs):
        pytest.fail("cache hit issued a request")

    result = github_pr_status.fetch_status_check_rollup_rest(
        "abc", repo="owner/repo", repo_root=tmp_path, runner=no_call, use_cache=True
    )
    assert result == [{"name": "lint"}]
    event = record(capsys)
    assert event["kind"] == "cache_hit"
    assert event["command_started"] is False
    assert event["http_responses_observed"] == 0
    assert event["readings"] == []


@pytest.mark.parametrize(
    "now,reset,state",
    [
        (1020, 2000, "fresh"),
        (1061, 2000, "stale"),
        (1020, 1010, "stale"),
        (999, 2000, "unknown"),
        (1020, None, "unknown"),
    ],
)
def test_headroom_validity_expires_without_renewing_observation(now, reset, state):
    result = observation.reading_validity(observed_at=1000, reset_epoch=reset, now=now)
    assert result["freshness"] == state
    assert result["observed_at_epoch"] == 1000
    assert result["recheck"] == "python scripts/github_pr_status.py rate"
    assert result["valid_until_epoch"] == (min(1060, reset) if reset else None)


def test_summary_is_bounded_and_separates_callers_identity_provenance_and_no_calls(
    capsys, tmp_path
):
    lines = []
    for caller, identity, remaining in [
        ("hapax-pr-admission", None, 400),
        ("cc-pr-autoqueue.py", "github_user_id:418460", 0),
    ]:
        event = {
            "schema": observation.SCHEMA,
            "observed_at_epoch": 1000,
            "caller": caller,
            "transport": "rest",
            "kind": "command",
            "command_started": True,
            "http_responses_observed": 1,
            "auth_identity": identity,
            "readings": [
                {
                    "resource": "core",
                    "remaining": remaining,
                    "limit": 5000,
                    "reset_epoch": 2000,
                    "source": "header",
                    "used": None,
                }
            ],
        }
        lines.append(
            json.dumps({"MESSAGE": "prefix " + observation.LOG_PREFIX + json.dumps(event)})
        )
    # Out-of-window records and ordinary messages cannot turn into API calls.
    lines += [lines[0].replace("1000", "900"), '{"MESSAGE":"ordinary tick"}']
    result = observation.summarize_log(lines, since=990, until=1010, now=1100)
    assert len(result["callers"]) == 2
    assert sum(row["http_responses_observed"] for row in result["callers"]) == 2
    assert {row["auth_identity"] for row in result["callers"]} == {None, "github_user_id:418460"}
    assert all(
        row["latest_readings"][0]["validity"]["freshness"] == "stale" for row in result["callers"]
    )
    assert result["coverage"] == "instrumented_calls_only"


def test_existing_rest_adapter_reaches_observer_without_changing_result(capsys, tmp_path):
    result = github_pr_status.get_pull_rest(
        1,
        repo_root=tmp_path,
        runner=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, response(), ""),
    )
    assert result == {"ok": True}
    assert record(capsys)["http_responses_observed"] == 1


def test_existing_rate_cli_exposes_time_bound_reference_and_both_low_hold(monkeypatch, capsys):
    monkeypatch.setattr(observation.time, "time", lambda: 1000)
    body = '{"resources":{"graphql":{"remaining":0,"limit":5000,"reset":2000}}}'
    monkeypatch.setattr(
        github_pr_status.subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, response(body, remaining=0), ""),
    )
    assert github_pr_status.main(["rate"]) == github_pr_status.GRAPHQL_BACKOFF_RC
    payload = json.loads(capsys.readouterr().out)
    assert payload["transport"] is None
    assert payload["observations"]["core"]["validity"]["valid_until_epoch"] == 1060
    assert payload["observations"]["graphql"]["source"] == "body"
    assert payload["observations"]["core"]["auth_identity"] is None


@pytest.mark.parametrize(
    "script,adapter",
    [
        ("cc-pr-autoqueue.py", "_gh_api_get_json"),
        ("cc-pr-merge-watcher.py", "_run_gh_api_json"),
    ],
)
def test_direct_caller_read_adapters_deliver_observations(
    script, adapter, tmp_path, capsys, monkeypatch
):
    name = script.replace("-", "_").removesuffix(".py")
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, SCRIPTS / script)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    module = sys.modules[name]
    monkeypatch.setattr(sys, "argv", [str(SCRIPTS / script)])
    result = getattr(module, adapter)(
        "repos/owner/repo/rulesets",
        repo_root=tmp_path,
        runner=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, response(), ""),
    )
    assert result == ((True, {"ok": True}, "ok") if "autoqueue" in script else {"ok": True})
    event = record(capsys)
    assert event["caller"] == script
    assert event["http_responses_observed"] == 1


def test_usage_cli_with_uninstrumented_journal_is_unobserved_not_zero_spend(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"MESSAGE":"auto-tick open=100"}\n'))
    monkeypatch.setattr(
        github_pr_status.subprocess, "run", lambda *a, **kw: pytest.fail("GitHub call")
    )
    assert github_pr_status.main(["usage", "--since", "1", "--until", "2"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["observation_state"] == "unobserved"
    assert result["request_count_exact"] is False
    assert result["callers"] == []


def test_manual_and_service_invocations_remain_distinct(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(sys, "argv", ["cc-pr-autoqueue.py"])
    monkeypatch.setattr(observation.time, "time", lambda: 1000)
    lines = []
    for invocation in ["", "a" * 32]:
        monkeypatch.setenv("INVOCATION_ID", invocation)
        observation.run_gh_observed(
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, response(), ""),
            ["gh", "api", "rate_limit"],
            repo_root=tmp_path,
        )
        lines.append(capsys.readouterr().err)
    result = observation.summarize_log(lines, since=990, until=1010, now=1005)
    assert {row["execution_context"] for row in result["callers"]} == {
        "systemd",
        "manual_or_unknown",
    }
    assert len(result["callers"]) == 2


@pytest.mark.parametrize(
    "field,other",
    [
        ("caller", "cc-pr-autoqueue.py"),
        ("pool", "search"),
        ("auth_identity", "github_user_id:418460"),
        ("execution_context", "systemd"),
    ],
)
def test_summary_keeps_each_attribution_dimension_distinct(field, other):
    event = {
        "schema": observation.SCHEMA,
        "observed_at_epoch": 1000,
        "caller": "hapax-pr-admission",
        "transport": "rest",
        "pool": "core",
        "auth_identity": None,
        "execution_context": "manual_or_unknown",
        "readings": [],
        "command_started": True,
        "http_responses_observed": 1,
    }
    result = observation.summarize_log(
        [observation.LOG_PREFIX + json.dumps(e) for e in (event, {**event, field: other})],
        since=990,
        until=1010,
        now=1005,
    )
    assert len(result["callers"]) == 2
    assert {row[field] for row in result["callers"]} == {event[field], other}


@pytest.mark.parametrize("bad", [None, "bad", {"unexpected": True}])
def test_malformed_observation_is_ignored_without_printing_input(bad):
    event = {
        "schema": observation.SCHEMA,
        "observed_at_epoch": 1000,
        "caller": "unknown",
        "transport": "rest",
        "auth_identity": None,
        "readings": bad,
    }
    result = observation.summarize_log(
        [observation.LOG_PREFIX + json.dumps(event)], since=990, until=1010, now=1005
    )
    assert result["observation_state"] == "unobserved"
    assert result["ignored_lines"] == 1
