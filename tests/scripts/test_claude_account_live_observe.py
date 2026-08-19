"""The account-live observer must measure, never assume — and must fail closed.

The defect it closes: `subscription_quota_headroom_observed` is documented as "a real
Claude invocation completed without a subscription quota wall", but nothing produced it,
so every receipt came from a human on a cadence nothing scheduled. On 2026-08-19 that
cadence stopped after 14:25z, both Claude and GLM seats went stale at 15:25:02z, and a
review dispatch found zero available families. Nothing reported the lapse.

These tests pin the two properties that make the observer trustworthy:
  1. Only a SERVED request counts. Presence never does.
  2. A wall that is newer than the newest served response wins.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = REPO_ROOT / "scripts" / "hapax-claude-account-live-observe"
# Explicit loader: the script is extensionless (a CLI on PATH), so suffix-based
# spec_from_file_location returns None.
_spec = importlib.util.spec_from_file_location(
    "hapax_claude_account_live_observe",
    _SCRIPT,
    loader=importlib.machinery.SourceFileLoader("hapax_claude_account_live_observe", str(_SCRIPT)),
)
assert _spec and _spec.loader
obs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(obs)

NOW = datetime(2026, 8, 19, 16, 0, 0, tzinfo=UTC)


class TestRefusesContaminatedEnvironment:
    """The probe must not measure a redirected endpoint and call it the subscription.

    /run/user/1000/hapax-secrets.env carries ANTHROPIC_BASE_URL pointing at podium's
    LiteLLM proxy, and this unit originally loaded it via EnvironmentFile=. Under systemd
    the probe would have measured that proxy while minting auth_surface=subscription.
    """

    @pytest.mark.parametrize(
        "var", ["ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"]
    )
    def test_probe_refuses_when_redirect_env_is_set(
        self, monkeypatch: pytest.MonkeyPatch, var: str
    ) -> None:
        monkeypatch.setenv(var, "https://not-the-subscription.invalid")
        called: list[object] = []
        monkeypatch.setattr(obs.subprocess, "run", lambda *a, **k: called.append(a) or None)
        assert obs.probe(NOW) is None, "must refuse, not measure the wrong endpoint"
        assert called == [], "must not even invoke the CLI"

    def test_clean_env_is_not_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
            monkeypatch.delenv(var, raising=False)
        assert obs.provider_redirect_env() == []

    def test_empty_value_is_not_a_redirect(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "")
        assert obs.provider_redirect_env() == []


class TestOnlyAnthropicServesWitnessTheSubscription:
    """1299 fugu-ultra and 167 glm-4.7 served records exist in the live corpus."""

    @pytest.mark.parametrize("model", ["fugu-ultra", "glm-4.7", "<synthetic>", "gpt-4o", None])
    def test_non_anthropic_serve_is_not_evidence(self, tmp_path: Path, model) -> None:
        rec = json.loads(_assistant(NOW - timedelta(minutes=1)))
        if model is None:
            rec["message"].pop("model", None)
        else:
            rec["message"]["model"] = model
        verdict, _ = _run(tmp_path, transcript=[json.dumps(rec)])
        assert verdict == "no_evidence", f"{model!r} must not witness the Claude subscription"

    def test_anthropic_serve_is_evidence(self, tmp_path: Path) -> None:
        verdict, ev = _run(tmp_path, transcript=[_assistant(NOW - timedelta(minutes=1))])
        assert verdict == "served"
        assert ev.model.startswith("claude-")

    def test_haiku_does_not_witness_the_opus_review_route(self, tmp_path: Path) -> None:
        """When the Opus entitlement is exhausted, cheap models keep answering."""
        ev = obs.Observation("served", NOW, "session-transcript", model="claude-haiku-4-5")
        planned = obs.mint(
            ev,
            now=NOW,
            route_ids=("claude.review.opus", "claude.headless.full"),
            stale_after_seconds=1800,
            receipt_dir=tmp_path,
            dry_run=True,
        )
        by_route = {r["route_id"]: r for r in planned}
        assert by_route["claude.review.opus"].get("skipped") == "model-family-mismatch"
        assert "would_run" in by_route["claude.headless.full"]

    def test_opus_witnesses_both(self, tmp_path: Path) -> None:
        ev = obs.Observation("served", NOW, "session-transcript", model="claude-opus-5")
        planned = obs.mint(
            ev,
            now=NOW,
            route_ids=("claude.review.opus", "claude.headless.full"),
            stale_after_seconds=1800,
            receipt_dir=tmp_path,
            dry_run=True,
        )
        assert all("would_run" in r for r in planned)


class TestFailedMintIsNotSuccess:
    def test_nonzero_writer_exit_is_a_failure(self) -> None:
        assert obs.mint_failed([{"route_id": "r", "returncode": 2, "stderr": "invalid"}])

    def test_skipped_route_is_not_a_failure(self) -> None:
        assert not obs.mint_failed([{"route_id": "r", "skipped": "model-family-mismatch"}])

    def test_dry_run_entries_are_not_failures(self) -> None:
        assert not obs.mint_failed([{"route_id": "r", "would_run": ["--observation"]}])


def _assistant(ts: datetime, *, tokens: int = 120) -> str:
    """tokens=0 means a record that proves NOTHING was served (all counters zero)."""
    return json.dumps(
        {
            "type": "assistant",
            "timestamp": ts.isoformat().replace("+00:00", "Z"),
            "message": {
                "model": "claude-opus-5",
                "usage": {
                    "input_tokens": 10 if tokens else 0,
                    "output_tokens": tokens,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
            },
        }
    )


def _result(ts: datetime, *, is_error: bool = False, result: str = "", tokens: int = 120) -> str:
    return json.dumps(
        {
            "type": "result",
            "timestamp": ts.isoformat().replace("+00:00", "Z"),
            "is_error": is_error,
            "api_error_status": None,
            "result": result,
            "model": "claude-opus-5",
            "usage": {"input_tokens": 10, "output_tokens": tokens},
        }
    )


def _run(tmp_path: Path, *, headless: list[str] = (), transcript: list[str] = (), age: int = 1800):
    hdir = tmp_path / "headless" / "lane"
    tdir = tmp_path / "projects" / "proj"
    hdir.mkdir(parents=True)
    tdir.mkdir(parents=True)
    (hdir / "output.jsonl").write_text("\n".join(headless) + "\n" if headless else "")
    (tdir / "session.jsonl").write_text("\n".join(transcript) + "\n" if transcript else "")
    return obs.observe(
        now=NOW,
        max_age_seconds=age,
        headless_glob=str(tmp_path / "headless" / "*" / "output.jsonl"),
        transcript_glob=str(tmp_path / "projects" / "*" / "*.jsonl"),
    )


class TestObservesOnlyServedRequests:
    def test_served_transcript_response_is_evidence(self, tmp_path: Path) -> None:
        verdict, ev = _run(tmp_path, transcript=[_assistant(NOW - timedelta(minutes=2))])
        assert verdict == "served"
        assert ev.source == "session-transcript"

    def test_served_headless_result_is_evidence(self, tmp_path: Path) -> None:
        verdict, ev = _run(tmp_path, headless=[_result(NOW - timedelta(minutes=3))])
        assert verdict == "served"
        assert ev.source == "headless-result"

    def test_zero_token_record_is_not_served(self, tmp_path: Path) -> None:
        """A record with no tokens proves nothing was served — that is presence."""
        verdict, _ = _run(tmp_path, transcript=[_assistant(NOW - timedelta(minutes=1), tokens=0)])
        assert verdict == "no_evidence"

    def test_evidence_outside_the_window_does_not_count(self, tmp_path: Path) -> None:
        verdict, _ = _run(tmp_path, transcript=[_assistant(NOW - timedelta(hours=9))], age=1800)
        assert verdict == "no_evidence"

    def test_no_evidence_is_not_exhaustion(self, tmp_path: Path) -> None:
        """Absence of evidence must hold the route, not mint and not declare a wall."""
        verdict, ev = _run(tmp_path)
        assert verdict == "no_evidence"
        assert ev is None


class TestFailsClosed:
    def test_wall_newer_than_served_wins(self, tmp_path: Path) -> None:
        verdict, ev = _run(
            tmp_path,
            headless=[
                _result(NOW - timedelta(minutes=20)),
                _result(
                    NOW - timedelta(minutes=2),
                    is_error=True,
                    result="You've hit your usage limit. Try again at 10:29 PM.",
                    tokens=0,
                ),
            ],
        )
        assert verdict == "walled", "a 20-minute-old success must not survive a 2-minute-old wall"
        assert ev.kind == "wall"

    def test_transcript_wall_beats_older_transcript_serve(self, tmp_path: Path) -> None:
        """The transcript scanner originally had NO wall branch at all.

        ~1093 wall-shaped records exist in the live corpus, so a 429 a minute ago losing to
        a serve nine minutes ago was the ordinary case, not an edge one.
        """
        wall = json.loads(_assistant(NOW - timedelta(minutes=1)))
        wall["message"]["usage"] = {"input_tokens": 0, "output_tokens": 0}
        wall["message"]["error"] = {"type": "rate_limit_error", "message": "rate limit exceeded"}
        verdict, ev = _run(
            tmp_path,
            transcript=[_assistant(NOW - timedelta(minutes=9)), json.dumps(wall)],
        )
        assert verdict == "walled", "a wall 1 min ago must beat a serve 9 min ago"
        assert ev.source == "session-transcript"

    def test_undated_headless_uses_only_the_last_record(self, tmp_path: Path) -> None:
        """Undated lane records all collapse to the file mtime; max() returns the FIRST
        maximal element, so a file beginning with a success would report served forever."""
        served = json.loads(_result(NOW))
        served.pop("timestamp")
        walled = json.loads(
            _result(NOW, is_error=True, result="You've hit your usage limit.", tokens=0)
        )
        walled.pop("timestamp")
        verdict, _ = _run(tmp_path, headless=[json.dumps(served), json.dumps(walled)])
        assert verdict == "walled", "the LAST undated record is the file's current state"

    def test_undated_serve_never_borrows_file_mtime_as_freshness(self, tmp_path: Path) -> None:
        """mtime is a FILE fact. A month-old success in a file touched a minute ago must
        not read as a serve a minute ago — that fabricates the exact freshness the receipt
        then vouches for."""
        served = json.loads(_result(NOW - timedelta(days=30)))
        served.pop("timestamp")
        verdict, ev = _run(tmp_path, headless=[json.dumps(served)])
        assert verdict == "no_evidence", f"undated serve must not be evidence (got {ev})"

    def test_undated_wall_is_still_honoured(self, tmp_path: Path) -> None:
        """Withholding availability on a stale signal is conservative; granting it is not."""
        walled = json.loads(
            _result(NOW, is_error=True, result="You've hit your usage limit.", tokens=0)
        )
        walled.pop("timestamp")
        verdict, _ = _run(tmp_path, headless=[json.dumps(walled)])
        assert verdict == "walled"

    def test_exact_tie_resolves_to_the_wall(self, tmp_path: Path) -> None:
        ts = NOW - timedelta(minutes=2)
        wall = json.loads(_assistant(ts))
        wall["message"]["usage"] = {"input_tokens": 0, "output_tokens": 0}
        wall["message"]["error"] = {"type": "rate_limit_error", "message": "rate limit exceeded"}
        verdict, _ = _run(tmp_path, transcript=[_assistant(ts), json.dumps(wall)])
        assert verdict == "walled", "an exact timestamp tie must fail closed"

    def test_served_newer_than_wall_recovers(self, tmp_path: Path) -> None:
        verdict, _ = _run(
            tmp_path,
            headless=[
                _result(
                    NOW - timedelta(minutes=20),
                    is_error=True,
                    result="You've hit your usage limit.",
                    tokens=0,
                ),
                _result(NOW - timedelta(minutes=2)),
            ],
        )
        assert verdict == "served"

    @pytest.mark.parametrize(
        "text",
        [
            "You've hit your usage limit. Try again at 10:29 PM.",
            "rate_limit_error",
            "429 rate limit exceeded",
            "RESOURCE_EXHAUSTED",
            "quota exceeded for this account",
        ],
    )
    def test_recognises_real_provider_refusals(self, tmp_path: Path, text: str) -> None:
        verdict, _ = _run(
            tmp_path,
            headless=[_result(NOW - timedelta(minutes=1), is_error=True, result=text, tokens=0)],
        )
        assert verdict == "walled"

    def test_auth_failure_is_not_a_quota_wall(self, tmp_path: Path) -> None:
        """The codex lesson: a quota wall reported as auth (or vice versa) sends the
        operator to re-login for a problem that is not authentication."""
        verdict, _ = _run(
            tmp_path,
            headless=[
                _result(
                    NOW - timedelta(minutes=1),
                    is_error=True,
                    result="invalid credentials: please run claude auth login",
                    tokens=0,
                )
            ],
        )
        assert verdict == "no_evidence", "auth failure is neither served nor a quota wall"

    def test_generic_error_is_not_a_quota_wall(self, tmp_path: Path) -> None:
        verdict, _ = _run(
            tmp_path,
            headless=[
                _result(
                    NOW - timedelta(minutes=1), is_error=True, result="network timeout", tokens=0
                )
            ],
        )
        assert verdict == "no_evidence"


class TestReadsMetadataOnly:
    def test_prompt_and_response_content_is_never_inspected(self, tmp_path: Path) -> None:
        """A transcript discussing rate limits must not be read as a rate limit."""
        record = json.loads(_assistant(NOW - timedelta(minutes=1)))
        record["message"]["content"] = [
            {"type": "text", "text": "We hit our usage limit yesterday; quota exceeded twice."}
        ]
        verdict, _ = _run(tmp_path, transcript=[json.dumps(record)])
        assert verdict == "served", "model output must not be scanned for wall markers"

    def test_user_records_are_not_evidence(self, tmp_path: Path) -> None:
        rec = json.dumps(
            {
                "type": "user",
                "timestamp": (NOW - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                "message": {"usage": {"input_tokens": 5, "output_tokens": 5}},
            }
        )
        verdict, _ = _run(tmp_path, transcript=[rec])
        assert verdict == "no_evidence", "only assistant responses prove the subscription served"


class TestMintDelegatesToTheValidator:
    def test_evidence_ref_matches_the_receipt_allowlist(self) -> None:
        """The witness name must satisfy the writer's regex, or the receipt is ignored."""
        import re

        allow = re.compile(
            r"\Aclaude-(?:subscription-headroom-observed|operator-confirmed-subscription-headroom)-"
            r"\d{8}t\d{4}(?:\d{2})?z\Z"
        )
        ref = f"{obs.WITNESS_PREFIX}-{NOW.strftime('%Y%m%dt%H%M%Sz')}"
        assert allow.fullmatch(ref), ref

    def test_mint_shells_out_to_the_admission_writer(self, tmp_path: Path) -> None:
        """It must not hand-write receipts — the writer owns sanitization and bounds."""
        ev = obs.Observation("served", NOW, "headless-result", model="claude-opus-5")
        planned = obs.mint(
            ev,
            now=NOW,
            route_ids=("claude.review.opus",),
            stale_after_seconds=3600,
            receipt_dir=tmp_path,
            dry_run=True,
        )
        argv = planned[0]["would_run"]
        assert "--observation" in argv
        assert obs.OBSERVATION in argv
        assert not any("lane" in str(a) or "tmux" in str(a) for a in argv)

    def test_receipt_is_anchored_to_observation_time_not_mint_time(self, tmp_path: Path) -> None:
        """Otherwise stale evidence buys a full fresh window and the two compound.

        The writer computes fresh_until = observed_at + stale_after. If mint time were
        passed, a 25-minute-old observation plus a 60-minute TTL would produce a receipt
        vouching for 85 minutes on the strength of one 25-minute-old response.
        """
        old = NOW - timedelta(minutes=25)
        planned = obs.mint(
            obs.Observation("served", old, "headless-result", model="claude-opus-5"),
            now=NOW,
            route_ids=("claude.review.opus",),
            stale_after_seconds=3600,
            receipt_dir=tmp_path,
            dry_run=True,
        )
        argv = planned[0]["would_run"]
        passed_now = argv[argv.index("--now") + 1]
        assert passed_now == old.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        assert NOW.strftime("%Y%m%dt%H%M%Sz") not in " ".join(map(str, argv))

    def test_evidence_ref_carries_no_lane_identity(self) -> None:
        """LANE_PRESENCE_RE rejects lane names; the observer must never emit one."""
        import re

        lane = re.compile(
            r"(?:hapax-claude-[a-z0-9-]+|session-present|lane-present|"
            r"(?:^|[-_.+])(?:tmux|sessions?|lanes?|dev)[0-9]*(?:$|[-_.+]))",
            re.IGNORECASE,
        )
        ref = f"{obs.WITNESS_PREFIX}-{NOW.strftime('%Y%m%dt%H%M%Sz')}"
        assert lane.search(ref) is None
