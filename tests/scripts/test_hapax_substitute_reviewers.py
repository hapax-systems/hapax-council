"""Substitute reviewer seats (muse, vibe, local): read-only, and every refusal is a route outage.

review-constitution-walled-family-substitution-20260924, option (a) granted 2026-09-24T21:17:12Z.
"""

from __future__ import annotations

import hashlib
import http.server
import importlib.util
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
FENCE = "```yaml\nverdict: accept\nfindings: []\nchecklist: {}\n```\n"


def _review_team():
    if "review_team" in sys.modules:
        return sys.modules["review_team"]
    spec = importlib.util.spec_from_file_location("review_team", SCRIPTS / "review_team.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["review_team"] = module
    spec.loader.exec_module(module)
    return module


def _run(wrapper: str, prompt: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    base = {k: v for k, v in os.environ.items() if k not in {"TMUX", "TMUX_PANE"}}
    return subprocess.run(
        [sys.executable, str(SCRIPTS / wrapper)],
        input=prompt,
        capture_output=True,
        text=True,
        env={**base, **env},
        cwd=REPO_ROOT,
        timeout=60,
        check=False,
    )


def _assert_route_outage(result: subprocess.CompletedProcess) -> None:
    assert result.returncode == 69
    assert result.stdout == ""
    assert _review_team().is_reviewer_route_unavailable(
        result.stderr, process_failed=True, model_stdout=result.stdout
    ), result.stderr


def _fake_cli(tmp_path: Path, name: str) -> tuple[Path, Path]:
    """A fake CLI that records its argv (and any --prompt-file body) and prints a fence."""

    record = tmp_path / f"{name}.record.json"
    script = tmp_path / name
    script.write_text(
        "#!" + sys.executable + "\n"
        "import json, os, sys\n"
        "argv = sys.argv[1:]\n"
        "body = None\n"
        "if '--prompt-file' in argv:\n"
        "    body = open(argv[argv.index('--prompt-file') + 1]).read()\n"
        f"json.dump({{'argv': argv, 'body': body, 'cwd': os.getcwd()}}, open({str(record)!r}, 'w'))\n"
        f"sys.stdout.write({FENCE!r})\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script, record


class TestMuseReviewer:
    def test_runs_read_only_in_an_empty_workspace_and_forwards_the_reply(
        self, tmp_path: Path
    ) -> None:
        fake, record = _fake_cli(tmp_path, "muse")
        result = _run("hapax-muse-reviewer", "REVIEW THIS DIFF", {"HAPAX_MUSE_BIN": str(fake)})
        assert result.returncode == 0, result.stderr
        assert result.stdout == FENCE
        seen = json.loads(record.read_text())
        argv = seen["argv"]
        assert argv[0] == "exec"
        for flag in (
            "--disable-web-tools",
            "--disable-shell",
            "--disable-write",
            "--no-session-log",
        ):
            assert flag in argv
        workspace = Path(argv[argv.index("--workspace") + 1])
        assert seen["cwd"] == str(workspace)
        assert REPO_ROOT not in workspace.parents and workspace != REPO_ROOT
        assert "REVIEW THIS DIFF" in seen["body"]
        assert "exactly one fenced yaml code block" in seen["body"]

    def test_prompt_above_the_measured_ceiling_is_a_route_outage(self, tmp_path: Path) -> None:
        fake, record = _fake_cli(tmp_path, "muse")
        result = _run("hapax-muse-reviewer", "x" * 96_001, {"HAPAX_MUSE_BIN": str(fake)})
        _assert_route_outage(result)
        assert not record.exists()

    def test_missing_binary_is_a_route_outage(self, tmp_path: Path) -> None:
        result = _run(
            "hapax-muse-reviewer",
            "REVIEW",
            {"HAPAX_MUSE_BIN": "", "PATH": str(tmp_path)},
        )
        _assert_route_outage(result)


# Fixture keys: stand-ins, not credentials. The whoami cache is keyed by the first 32 hex of
# sha256(key) (measured by the seat 2026-09-24T21:59Z against the live cache and ~/.vibe/.env).
CURRENT_KEY = "fixture-current-team-key"
STALE_KEY = "fixture-stale-api-key"


def _key_id(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def _vibe_home(
    tmp_path: Path,
    entries: dict[str, str] | None,
    *,
    configured: str | None = CURRENT_KEY,
    raw_cache: str | None = None,
) -> Path:
    """HOME with ~/.vibe/.env naming the configured key and a whoami cache of key -> plan_type."""

    home = tmp_path / "home"
    (home / ".vibe").mkdir(parents=True)
    if configured is not None:
        (home / ".vibe" / ".env").write_text(f"MISTRAL_API_KEY={configured}\n", encoding="utf-8")
    cache_path = home / ".vibe" / "whoami_cache.json"
    if raw_cache is not None:
        cache_path.write_text(raw_cache, encoding="utf-8")
    elif entries is not None:
        cache = {
            _key_id(key): {"payload": {"plan_type": plan}, "stored_at_timestamp": 1790273791}
            for key, plan in entries.items()
        }
        cache_path.write_text(json.dumps(cache), encoding="utf-8")
    return home


# Today's live shape (seat-measured 21:59Z): a stale 09-19 API entry for the old key and the
# current key's Team entry (`plan_type chat`). The configured key's entry must decide.
TODAY = {STALE_KEY: "api", CURRENT_KEY: "chat"}


class TestVibeReviewer:
    def _run_vibe(self, tmp_path: Path, home: Path, prompt: str = "REVIEW", **env: str):
        fake, record = _fake_cli(tmp_path, "vibe")
        result = _run(
            "hapax-vibe-reviewer",
            prompt,
            {"HAPAX_VIBE_BIN": str(fake), "HOME": str(home), "MISTRAL_API_KEY": "", **env},
        )
        return result, record

    def test_current_team_entry_wins_over_a_stale_api_entry(self, tmp_path: Path) -> None:
        result, record = self._run_vibe(tmp_path, _vibe_home(tmp_path, TODAY))
        assert result.returncode == 0, result.stderr
        assert result.stdout == FENCE
        argv = json.loads(record.read_text())["argv"]
        assert argv[argv.index("--enabled-tools") + 1] == "re:^$"
        assert argv[argv.index("--max-turns") + 1] == "1"
        assert "REVIEW" in argv[argv.index("-p") + 1]

    @pytest.mark.parametrize(
        "case",
        ["current_is_api", "no_matching_entry", "no_configured_key", "no_cache", "malformed_cache"],
    )
    def test_binding_other_than_the_current_team_entry_is_refused(
        self, tmp_path: Path, case: str
    ) -> None:
        home = {
            "current_is_api": lambda: _vibe_home(tmp_path, {STALE_KEY: "chat", CURRENT_KEY: "api"}),
            "no_matching_entry": lambda: _vibe_home(tmp_path, {STALE_KEY: "chat"}),
            "no_configured_key": lambda: _vibe_home(tmp_path, TODAY, configured=None),
            "no_cache": lambda: _vibe_home(tmp_path, None),
            "malformed_cache": lambda: _vibe_home(tmp_path, None, raw_cache="[not a mapping"),
        }[case]()
        result, record = self._run_vibe(tmp_path, home)
        _assert_route_outage(result)
        # A mechanical next action for the coordinator, never a question parked on the operator.
        assert "Next action (coordinator): rebind Vibe to the Team account" in result.stderr
        assert "operator" not in result.stderr
        assert not record.exists()

    def test_conflicting_process_key_is_refused(self, tmp_path: Path) -> None:
        # Both keys are Team-bound, so only the conflict itself (which key bills is not
        # established) can refuse the seat.
        both_team = {STALE_KEY: "chat", CURRENT_KEY: "chat"}
        result, record = self._run_vibe(
            tmp_path, _vibe_home(tmp_path, both_team), MISTRAL_API_KEY=STALE_KEY
        )
        _assert_route_outage(result)
        assert not record.exists()

    def test_the_key_never_reaches_output(self, tmp_path: Path) -> None:
        for home_dir, entries in (("ok", TODAY), ("refused", {STALE_KEY: "api"})):
            result, _ = self._run_vibe(
                tmp_path / home_dir, _vibe_home(tmp_path / home_dir, entries)
            )
            for key in (CURRENT_KEY, STALE_KEY):
                assert key not in result.stdout and key not in result.stderr

    def test_prompt_above_the_measured_ceiling_is_a_route_outage(self, tmp_path: Path) -> None:
        fake, record = _fake_cli(tmp_path, "vibe")
        home = _vibe_home(tmp_path, TODAY)
        result = _run(
            "hapax-vibe-reviewer", "x" * 22_001, {"HAPAX_VIBE_BIN": str(fake), "HOME": str(home)}
        )
        _assert_route_outage(result)
        assert "0 B at 45-87 KB" in result.stderr
        assert not record.exists()


class _Completions(http.server.BaseHTTPRequestHandler):
    reply: dict = {}
    seen: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802 - http.server protocol
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        type(self).seen.append({"path": self.path, "body": body})
        data = json.dumps(type(self).reply).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: object) -> None:
        return


@pytest.fixture
def completions_server():
    server = http.server.HTTPServer(("127.0.0.1", 0), _Completions)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _Completions.seen = []
    yield server, f"http://127.0.0.1:{server.server_address[1]}/v1"
    server.shutdown()


class TestLocalReviewer:
    def test_one_completion_with_the_seat_contract(self, completions_server) -> None:
        _, base = completions_server
        _Completions.reply = {"choices": [{"message": {"content": FENCE}, "finish_reason": "stop"}]}
        result = _run("hapax-local-reviewer", "REVIEW", {"HAPAX_LOCAL_REVIEW_BASE_URL": base})
        assert result.returncode == 0, result.stderr
        assert result.stdout == FENCE
        (request,) = _Completions.seen
        assert request["path"] == "/v1/chat/completions"
        assert request["body"]["model"] == "qwen3.8-flash-next"
        assert request["body"]["temperature"] == 0
        assert "tools" not in request["body"]
        assert request["body"]["messages"][1]["content"] == "REVIEW"
        assert "exactly one fenced yaml code block" in request["body"]["messages"][0]["content"]

    def test_truncated_reply_is_a_route_outage_not_a_review(self, completions_server) -> None:
        _, base = completions_server
        _Completions.reply = {
            "choices": [{"message": {"content": FENCE}, "finish_reason": "length"}]
        }
        _assert_route_outage(
            _run("hapax-local-reviewer", "REVIEW", {"HAPAX_LOCAL_REVIEW_BASE_URL": base})
        )

    def test_unreachable_endpoint_is_a_route_outage(self) -> None:
        _assert_route_outage(
            _run(
                "hapax-local-reviewer",
                "REVIEW",
                {"HAPAX_LOCAL_REVIEW_BASE_URL": "http://127.0.0.1:9/v1"},
            )
        )


@pytest.mark.parametrize(
    "wrapper", ["hapax-muse-reviewer", "hapax-vibe-reviewer", "hapax-local-reviewer"]
)
def test_empty_prompt_is_refused(wrapper: str, tmp_path: Path) -> None:
    _assert_route_outage(_run(wrapper, "  \n", {"HOME": str(tmp_path)}))
