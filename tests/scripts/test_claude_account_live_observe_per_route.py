"""Each route is vouched for by the freshest serve in its OWN model family.

Measured 2026-09-02: for ~24h every 10-minute observer cycle logged
``claude.review.opus: skipped model-family-mismatch, observed_model: claude-fable-5-1``. The
account's newest serve was a Fable run, so the opus review route was never minted although
opus serves sat minutes older inside the same window — a new model family arriving starved a
route. The observer used to judge every route against the single newest observation; now
``evidence_by_route`` picks per family, and a wall still holds the whole account.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = REPO_ROOT / "scripts" / "hapax-claude-account-live-observe"
_spec = importlib.util.spec_from_file_location(
    "hapax_claude_account_live_observe_per_route",
    _SCRIPT,
    loader=importlib.machinery.SourceFileLoader(
        "hapax_claude_account_live_observe_per_route", str(_SCRIPT)
    ),
)
assert _spec and _spec.loader
obs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(obs)

NOW = datetime(2026, 9, 2, 2, 0, 0, tzinfo=UTC)
ROUTES = ("claude.review.opus", "claude.headless.full")


def _served(ts: datetime, model: str) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "timestamp": ts.isoformat().replace("+00:00", "Z"),
            "message": {
                "model": model,
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 120,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
            },
        }
    )


def _wall(ts: datetime) -> str:
    return json.dumps(
        {
            "type": "result",
            "timestamp": ts.isoformat().replace("+00:00", "Z"),
            "is_error": True,
            "api_error_status": 429,
            "result": "You have hit your usage limit",
            "model": "claude-opus-5",
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }
    )


def _observations(tmp_path: Path, *, transcript=(), headless=()):
    """Exercise the real passive scanners before the per-route selector."""
    transcript_path = tmp_path / "session.jsonl"
    headless_path = tmp_path / "output.jsonl"
    transcript_path.write_text("\n".join(transcript) + "\n")
    headless_path.write_text("\n".join(headless) + "\n")
    result = obs.observe_all(
        now=NOW,
        max_age_seconds=1800,
        transcript_glob=str(transcript_path),
        headless_glob=str(headless_path),
    )
    assert all(item.source in {"session-transcript", "headless-result"} for item in result[2])
    return result


class TestEachRouteUsesItsOwnFamily:
    def test_unbound_passive_serve_does_not_suppress_subscription_probe(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """Measured defect: a continuous Fable serve must not suppress the Opus probe."""
        hdir = tmp_path / "headless" / "lane"
        tdir = tmp_path / "projects" / "proj"
        hdir.mkdir(parents=True)
        tdir.mkdir(parents=True)
        passive_at = NOW - timedelta(minutes=1)
        (hdir / "output.jsonl").write_text("")
        (tdir / "session.jsonl").write_text(_served(passive_at, "claude-fable-5-1") + "\n")
        probe_calls: list[datetime] = []
        mint_route_evidence: dict[str, object] = {}

        def fake_probe(now: datetime):
            probe_calls.append(now)
            return obs.Observation(
                "served",
                now,
                "active-probe",
                model="claude-opus-5",
                scrubbed_env=obs.PROBE_ENV_SCRUBBED,
            )

        def fake_mint(evidence, **kwargs):
            mint_route_evidence.update(kwargs["evidence_by_route"])
            return [{"route_id": route_id, "returncode": 0} for route_id in kwargs["route_ids"]]

        monkeypatch.setattr(obs, "probe", fake_probe)
        monkeypatch.setattr(obs, "mint", fake_mint)

        rc = obs.main(
            [
                "--transcript-glob",
                str(tmp_path / "projects" / "*" / "*.jsonl"),
                "--headless-glob",
                str(tmp_path / "headless" / "*" / "output.jsonl"),
                "--now",
                NOW.isoformat().replace("+00:00", "Z"),
                "--max-age-seconds",
                "1800",
                "--route-id",
                "claude.review.opus",
                "--route-id",
                "claude.headless.full",
                "--receipt-dir",
                str(tmp_path / "receipts"),
                "--probe",
                "--json",
            ]
        )

        assert rc == 0
        assert probe_calls == [NOW], "passive Fable evidence must not suppress the Opus probe"
        assert mint_route_evidence["claude.review.opus"].source == "active-probe"
        assert mint_route_evidence["claude.headless.full"].source == "active-probe"
        assert mint_route_evidence["claude.headless.full"].at == NOW
        payload = json.loads(capsys.readouterr().out)
        assert payload["probe"]["requested_for_routes"] == list(ROUTES)
        assert payload["probe"]["reason"] == (
            "requested route lacked in-model-family served evidence inside the window"
        )
        assert payload["probe"]["witnessed_routes"] == list(ROUTES)
        assert payload["observed_model_by_route"] == {
            "claude.review.opus": "claude-opus-5",
            "claude.headless.full": "claude-opus-5",
        }

    def test_fable_serve_newer_than_opus_serve_still_mints_the_opus_review_route(
        self, tmp_path: Path
    ) -> None:
        """Neither unbound passive serve can vouch for subscription routes."""
        verdict, newest, found = _observations(
            tmp_path,
            transcript=[
                _served(NOW - timedelta(minutes=9), "claude-opus-5"),
                _served(NOW - timedelta(minutes=1), "claude-fable-5-1"),
            ],
        )
        assert (verdict, newest, found) == ("no_evidence", None, [])

    def test_only_a_cheap_model_served_leaves_the_review_route_unvouched(
        self, tmp_path: Path
    ) -> None:
        verdict, newest, found = _observations(
            tmp_path, transcript=[_served(NOW - timedelta(minutes=2), "claude-haiku-4-5")]
        )
        assert (verdict, newest, found) == ("no_evidence", None, [])

    def test_a_wall_newer_than_every_serve_holds_the_whole_account(self, tmp_path: Path) -> None:
        verdict, newest, _found = _observations(
            tmp_path,
            transcript=[_served(NOW - timedelta(minutes=5), "claude-opus-5")],
            headless=[_wall(NOW - timedelta(minutes=1))],
        )
        assert verdict == "walled" and newest.kind == "wall"

    def test_a_serve_older_than_a_newer_wall_is_not_resurrected_by_another_family(
        self, tmp_path: Path
    ) -> None:
        """An unbound passive serve cannot override a measured quota wall."""
        verdict, newest, found = _observations(
            tmp_path,
            transcript=[
                _served(NOW - timedelta(minutes=9), "claude-opus-5"),
                _served(NOW - timedelta(minutes=1), "claude-fable-5-1"),
            ],
            headless=[_wall(NOW - timedelta(minutes=5))],
        )
        assert verdict == "walled" and newest.source == "headless-result"
        by_route = obs.evidence_by_route(found, ROUTES)
        assert by_route == dict.fromkeys(ROUTES)

    def test_a_serve_after_the_newest_wall_still_vouches_for_its_route(
        self, tmp_path: Path
    ) -> None:
        """Even a later passive Opus serve cannot clear a bound subscription wall."""
        verdict, newest, found = _observations(
            tmp_path,
            transcript=[
                _served(NOW - timedelta(minutes=3), "claude-opus-5"),
                _served(NOW - timedelta(minutes=1), "claude-fable-5-1"),
            ],
            headless=[_wall(NOW - timedelta(minutes=5))],
        )
        assert verdict == "walled" and newest.source == "headless-result"
        by_route = obs.evidence_by_route(found, ROUTES)
        assert by_route == dict.fromkeys(ROUTES)

    def test_main_unbound_mixed_family_serves_cannot_clear_wall(
        self, tmp_path: Path, capsys
    ) -> None:
        """Review finding: every regression test composed observe_all/evidence_by_route/mint by
        hand, so main() could stop passing route-specific evidence and stay green. This runs the
        deployed entry point on the interleaving case and reads its JSON."""
        hdir = tmp_path / "headless" / "lane"
        tdir = tmp_path / "projects" / "proj"
        hdir.mkdir(parents=True)
        tdir.mkdir(parents=True)
        (tdir / "session.jsonl").write_text(
            "\n".join(
                [
                    _served(NOW - timedelta(minutes=9), "claude-opus-5"),
                    _served(NOW - timedelta(minutes=1), "claude-fable-5-1"),
                ]
            )
            + "\n"
        )
        (hdir / "output.jsonl").write_text(_wall(NOW - timedelta(minutes=5)) + "\n")
        rc = obs.main(
            [
                "--transcript-glob",
                str(tmp_path / "projects" / "*" / "*.jsonl"),
                "--headless-glob",
                str(tmp_path / "headless" / "*" / "output.jsonl"),
                "--now",
                NOW.isoformat().replace("+00:00", "Z"),
                "--max-age-seconds",
                "1800",
                "--route-id",
                "claude.review.opus",
                "--route-id",
                "claude.headless.full",
                "--receipt-dir",
                str(tmp_path / "receipts"),
                "--no-probe",
                "--dry-run",
                "--json",
            ]
        )
        assert rc == 3
        payload = json.loads(capsys.readouterr().out)
        assert payload["verdict"] == "walled"
        assert not payload.get("receipts")

    def test_evidence_by_route_picks_the_freshest_in_family_not_the_first(
        self, tmp_path: Path
    ) -> None:
        older = obs.Observation(
            "served", NOW - timedelta(minutes=20), "session-transcript", model="claude-opus-5"
        )
        newer = obs.Observation(
            "served", NOW - timedelta(minutes=3), "session-transcript", model="claude-opus-5"
        )
        fable = obs.Observation(
            "served", NOW - timedelta(minutes=1), "session-transcript", model="claude-fable-5-1"
        )
        by_route = obs.evidence_by_route([older, fable, newer], ROUTES)
        assert by_route["claude.review.opus"] is newer
        assert by_route["claude.headless.full"] is fable

    def test_mint_without_the_selector_behaves_as_before(self, tmp_path: Path) -> None:
        """Existing callers pass one observation; the family guard is unchanged for them."""
        ev = obs.Observation("served", NOW, "active-probe", model="claude-fable-5-1")
        planned = obs.mint(
            ev,
            now=NOW,
            route_ids=ROUTES,
            stale_after_seconds=1800,
            receipt_dir=tmp_path,
            dry_run=True,
        )
        by_route = {r["route_id"]: r for r in planned}
        assert by_route["claude.review.opus"].get("skipped") == "model-family-mismatch"
        assert "would_run" in by_route["claude.headless.full"]

    def test_observe_and_observe_all_agree_on_unbound_passive_input(self, tmp_path: Path) -> None:
        transcript = tmp_path / "session.jsonl"
        transcript.write_text(_served(NOW - timedelta(minutes=1), "claude-opus-5") + "\n")
        kwargs = dict(
            now=NOW,
            max_age_seconds=1800,
            headless_glob=str(tmp_path / "absent"),
            transcript_glob=str(transcript),
        )
        assert obs.observe(**kwargs) == ("no_evidence", None)
        assert obs.observe_all(**kwargs) == ("no_evidence", None, [])
