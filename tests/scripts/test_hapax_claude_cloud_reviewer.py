"""Tests for ``scripts/hapax-claude-cloud-reviewer``.

Fail-narrow contract for the claude-cloud review seat: a missing billing
witness refuses the seat; the session must bill the promotional cloud credit
(``ccr_promotional``) and never the subscription pool or pay-as-you-go; credit
exhaustion classifies as a quota wall and never reroutes to ``claude -p``.
"""

from __future__ import annotations

import http.server
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "scripts" / "hapax-claude-cloud-reviewer"
VERDICT = "```yaml\nverdict: accept\nfindings: []\nchecklist: {}\n```\n"


@pytest.fixture(autouse=True)
def _select_test_release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAPAX_SOURCE_ACTIVATE_WORKTREE", str(REPO_ROOT))


def _fake_claude(path: Path) -> None:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "argv = sys.argv[1:]\n"
        "record = Path(os.environ['HAPAX_FAKE_CLAUDE_ARGV_LOG'])\n"
        "with record.open('a', encoding='utf-8') as fh:\n"
        "    fh.write(json.dumps(argv) + '\\n')\n"
        "if argv[:1] == ['--cloud']:\n"
        "    print('Created cloud session: fake')\n"
        "    print('View: https://claude.ai/code/session_fakeCloud01?from=cli&m=0')\n"
        "    sys.exit(0)\n"
        "if argv[:3] == ['-p', '--cloud', 'session_fakeCloud01']:\n"
        "    sys.stdin.read()\n"
        "    print(json.dumps({'ok': True, 'session_id': 'session_fakeCloud01'}))\n"
        "    sys.exit(0)\n"
        "print('unexpected argv', file=sys.stderr)\n"
        "sys.exit(13)\n",
        encoding="utf-8",
    )
    path.chmod(0o700)


class _EventsServer:
    def __init__(self, pages: list[dict]) -> None:
        self._pages = pages
        self.requests = 0
        handler = self._handler()
        self._server = http.server.HTTPServer(("127.0.0.1", 0), handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def _handler(self) -> type[http.server.BaseHTTPRequestHandler]:
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                outer.requests += 1
                page = outer._pages[min(outer.requests - 1, len(outer._pages) - 1)]
                body = json.dumps(page).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args: object) -> None:
                return

        return Handler

    def close(self) -> None:
        self._server.shutdown()
        self._thread.join(timeout=5)


def _events_page(events: list[dict]) -> dict:
    return {"data": events, "resume_cursor": None}


def _witness_event(**overrides: object) -> dict:
    info = {
        "isUsingOverage": False,
        "overageStatus": "rejected",
        "rateLimitType": "ccr_promotional",
        "status": "allowed",
        "unifiedWindows": {
            "five_hour": {"resetsAt": 1790391600, "utilization": 0.07},
            "seven_day": {"resetsAt": 1790978400, "utilization": 0.02},
        },
    }
    info.update(overrides)
    return {
        "created_at": "2026-09-25T23:11:18Z",
        "event_type": "rate_limit_event",
        "payload": {"rate_limit_info": info, "type": "rate_limit_event"},
    }


def _assistant_event(text: str, *, model: str = "claude-opus-5-5") -> dict:
    return {
        "created_at": "2026-09-25T23:11:20Z",
        "event_type": "assistant",
        "payload": {
            "message": {
                "content": [{"text": text, "type": "text"}],
                "model": model,
                "role": "assistant",
            },
            "type": "assistant",
        },
    }


def _result_event(
    *, text: str = VERDICT, is_error: bool = False, errors: list[str] | None = None
) -> dict:
    payload: dict = {
        "duration_ms": 2943,
        "is_error": is_error,
        "result": text,
        "subtype": "error_during_execution" if is_error else "success",
        "total_cost_usd": 0.16,
        "type": "result",
    }
    if errors is not None:
        payload["errors"] = errors
    return {"created_at": "2026-09-25T23:11:21Z", "event_type": "result", "payload": payload}


def _credentials(path: Path) -> Path:
    creds = path / "credentials.json"
    creds.write_text(
        json.dumps({"claudeAiOauth": {"accessToken": "fake-token-for-tests"}}),
        encoding="utf-8",
    )
    return creds


def _run_wrapper(
    tmp_path: Path,
    *,
    events_pages: list[dict],
    extra_args: list[str] | None = None,
    credentials: Path | None = None,
    timeout: float = 60.0,
    stdin_text: str = "review packet\n",
) -> subprocess.CompletedProcess[str]:
    fake = tmp_path / "claude"
    argv_log = tmp_path / "argv-log.jsonl"
    _fake_claude(fake)
    server = _EventsServer(events_pages)
    try:
        env = {
            **os.environ,
            "HAPAX_FAKE_CLAUDE_ARGV_LOG": str(argv_log),
            "HAPAX_CLAUDE_CLOUD_REVIEWER_POLL_SECONDS": "0.05",
        }
        cmd = [
            sys.executable,
            str(WRAPPER),
            "--claude-bin",
            str(fake),
            "--api-base",
            f"http://127.0.0.1:{server.port}",
            "--cloud-cwd",
            str(tmp_path),
        ]
        if credentials is not None:
            cmd += ["--credentials", str(credentials)]
        cmd += list(extra_args or [])
        return subprocess.run(
            cmd,
            input=stdin_text,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env=env,
        )
    finally:
        server.close()


def _recorded_argvs(tmp_path: Path) -> list[list[str]]:
    log = tmp_path / "argv-log.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def test_refuses_without_credentials_and_never_launches_claude(tmp_path: Path) -> None:
    result = _run_wrapper(
        tmp_path,
        events_pages=[_events_page([])],
        credentials=tmp_path / "absent-credentials.json",
    )
    assert result.returncode != 0
    assert "billing witness" in result.stderr
    assert _recorded_argvs(tmp_path) == []
    assert result.stdout == ""


def test_refuses_when_billing_witness_event_absent(tmp_path: Path) -> None:
    result = _run_wrapper(
        tmp_path,
        events_pages=[
            _events_page([_assistant_event(VERDICT), _result_event()]),
        ],
        credentials=_credentials(tmp_path),
    )
    assert result.returncode != 0
    assert "billing witness" in result.stderr
    assert result.stdout == ""


def test_refuses_when_witness_is_not_the_promotional_credit(tmp_path: Path) -> None:
    result = _run_wrapper(
        tmp_path,
        events_pages=[
            _events_page(
                [
                    _witness_event(rateLimitType="subscription"),
                    _assistant_event(VERDICT),
                    _result_event(),
                ]
            ),
        ],
        credentials=_credentials(tmp_path),
    )
    assert result.returncode != 0
    assert "billing witness" in result.stderr
    assert result.stdout == ""


def test_refuses_when_overage_payg_surface_is_observed(tmp_path: Path) -> None:
    result = _run_wrapper(
        tmp_path,
        events_pages=[
            _events_page(
                [
                    _witness_event(isUsingOverage=True),
                    _assistant_event(VERDICT),
                    _result_event(),
                ]
            ),
        ],
        credentials=_credentials(tmp_path),
    )
    assert result.returncode != 0
    assert "pay-as-you-go" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(
    "unsafe_witness",
    [
        {"isUsingOverage": True},
        {"rateLimitType": "subscription"},
        {"rateLimitType": "unknown"},
        {"status": "unknown"},
        {"isUsingOverage": None},
        {"overageStatus": "accepted"},
        {"overageStatus": None},
    ],
)
def test_refuses_when_any_session_billing_event_is_unsafe(
    tmp_path: Path, unsafe_witness: dict[str, object]
) -> None:
    result = _run_wrapper(
        tmp_path,
        events_pages=[
            _events_page(
                [
                    _witness_event(),
                    _witness_event(**unsafe_witness),
                    _assistant_event(VERDICT),
                    _result_event(),
                ]
            )
        ],
        credentials=_credentials(tmp_path),
    )
    assert result.returncode == 2
    assert "billing witness" in result.stderr or "pay-as-you-go" in result.stderr
    assert result.stdout == ""


def test_refuses_when_a_second_billing_event_has_unknown_shape(tmp_path: Path) -> None:
    malformed = _witness_event()
    malformed["payload"]["rate_limit_info"] = None
    result = _run_wrapper(
        tmp_path,
        events_pages=[
            _events_page([_witness_event(), malformed, _assistant_event(VERDICT), _result_event()])
        ],
        credentials=_credentials(tmp_path),
    )
    assert result.returncode == 2
    assert "billing witness" in result.stderr
    assert result.stdout == ""


def test_credit_exhaustion_classifies_quota_wall_and_never_reroutes(tmp_path: Path) -> None:
    result = _run_wrapper(
        tmp_path,
        events_pages=[
            _events_page(
                [
                    _result_event(
                        text="",
                        is_error=True,
                        errors=["HTTP 429 Too Many Requests: promotional credit exhausted"],
                    )
                ]
            ),
        ],
        credentials=_credentials(tmp_path),
    )
    assert result.returncode != 0
    assert "quota-wall" in result.stderr
    assert result.stdout == ""
    argvs = _recorded_argvs(tmp_path)
    assert argvs and argvs[0][0] == "--cloud"
    for argv in argvs:
        if "-p" in argv:
            # The only permitted -p form is the packet follow-up into the cloud
            # session; a bare claude -p reviewer fallback must never appear.
            assert "--cloud" in argv


def test_successful_review_writes_verdict_to_stdout(tmp_path: Path) -> None:
    result = _run_wrapper(
        tmp_path,
        events_pages=[
            _events_page([]),
            _events_page([_witness_event()]),
            _events_page([_witness_event(), _assistant_event(VERDICT), _result_event()]),
        ],
        credentials=_credentials(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == VERDICT
    argvs = _recorded_argvs(tmp_path)
    assert argvs[0][0] == "--cloud"
    for argv in argvs:
        if "-p" in argv:
            assert "--cloud" in argv


def test_oversized_packet_is_delivered_as_cloud_followup(tmp_path: Path) -> None:
    big_packet = "review packet\n" + ("diff context line\n" * 9000)
    assert len(big_packet) > 100_000
    result = _run_wrapper(
        tmp_path,
        stdin_text=big_packet,
        events_pages=[
            _events_page([_witness_event(), _assistant_event(VERDICT), _result_event()]),
        ],
        credentials=_credentials(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == VERDICT
    argvs = _recorded_argvs(tmp_path)
    assert argvs[0][0] == "--cloud"
    followups = [argv for argv in argvs if argv[:2] == ["-p", "--cloud"]]
    assert followups == [["-p", "--cloud", "session_fakeCloud01"]]


def test_refuses_when_verdict_model_is_not_the_route_descriptor(tmp_path: Path) -> None:
    result = _run_wrapper(
        tmp_path,
        events_pages=[
            _events_page(
                [
                    _witness_event(),
                    _assistant_event(VERDICT, model="claude-haiku-4-5"),
                    _result_event(),
                ]
            ),
        ],
        credentials=_credentials(tmp_path),
    )
    assert result.returncode != 0
    assert "descriptor" in result.stderr
    assert result.stdout == ""


def test_refuses_when_no_checkout_on_a_pushed_ref(tmp_path: Path) -> None:
    fake = tmp_path / "claude"
    _fake_claude(tmp_path / "claude")
    creds = _credentials(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "file.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "file.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"],
        check=True,
    )
    result = subprocess.run(
        [
            sys.executable,
            str(WRAPPER),
            "--claude-bin",
            str(fake),
            "--api-base",
            "http://127.0.0.1:1",
            "--credentials",
            str(creds),
            "--discover-cloud-cwd-under",
            str(repo),
        ],
        input="review packet\n",
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env={**os.environ, "HAPAX_FAKE_CLAUDE_ARGV_LOG": str(tmp_path / "argv-log.jsonl")},
    )
    assert result.returncode != 0
    assert "pushed" in result.stderr
    assert _recorded_argvs(tmp_path) == []


def test_timeout_seconds_must_be_positive_number(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(WRAPPER), "--timeout-seconds", "abc"],
        input="",
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode != 0
    assert re.search(r"positive number of seconds", result.stderr)
