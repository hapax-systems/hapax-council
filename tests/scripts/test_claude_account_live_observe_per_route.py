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


def _observe_all(tmp_path: Path, *, transcript: list[str] = (), headless: list[str] = ()):
    hdir = tmp_path / "headless" / "lane"
    tdir = tmp_path / "projects" / "proj"
    hdir.mkdir(parents=True, exist_ok=True)
    tdir.mkdir(parents=True, exist_ok=True)
    (hdir / "output.jsonl").write_text("\n".join(headless) + "\n" if headless else "")
    (tdir / "session.jsonl").write_text("\n".join(transcript) + "\n" if transcript else "")
    return obs.observe_all(
        now=NOW,
        max_age_seconds=1800,
        headless_glob=str(tmp_path / "headless" / "*" / "output.jsonl"),
        transcript_glob=str(tmp_path / "projects" / "*" / "*.jsonl"),
    )


def _plan(tmp_path: Path, evidence, found) -> dict[str, dict]:
    planned = obs.mint(
        evidence,
        now=NOW,
        route_ids=ROUTES,
        stale_after_seconds=1800,
        receipt_dir=tmp_path,
        dry_run=True,
        evidence_by_route=obs.evidence_by_route(found, ROUTES),
    )
    return {r["route_id"]: r for r in planned}


class TestEachRouteUsesItsOwnFamily:
    def test_main_probes_for_missing_review_family_without_replacing_passive_headless_evidence(
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
        assert mint_route_evidence["claude.headless.full"].source == "session-transcript"
        assert mint_route_evidence["claude.headless.full"].at == passive_at
        payload = json.loads(capsys.readouterr().out)
        assert payload["probe"]["requested_for_routes"] == ["claude.review.opus"]
        assert payload["probe"]["reason"] == (
            "requested route lacked in-model-family served evidence inside the window"
        )
        assert payload["probe"]["witnessed_routes"] == ["claude.review.opus"]
        assert payload["observed_model_by_route"] == {
            "claude.review.opus": "claude-opus-5",
            "claude.headless.full": "claude-fable-5-1",
        }

    def test_fable_serve_newer_than_opus_serve_still_mints_the_opus_review_route(
        self, tmp_path: Path
    ) -> None:
        """The measured starvation, reproduced: the newest serve is Fable, an opus serve is older."""
        verdict, newest, found = _observe_all(
            tmp_path,
            transcript=[
                _served(NOW - timedelta(minutes=9), "claude-opus-5"),
                _served(NOW - timedelta(minutes=1), "claude-fable-5-1"),
            ],
        )
        assert verdict == "served" and newest.model == "claude-fable-5-1"
        by_route = _plan(tmp_path, newest, found)
        assert "would_run" in by_route["claude.review.opus"], by_route["claude.review.opus"]
        assert "would_run" in by_route["claude.headless.full"]
        # and the review route's receipt is anchored to the OPUS serve's time, not Fable's
        argv = by_route["claude.review.opus"]["would_run"]
        assert argv[argv.index("--now") + 1] == (NOW - timedelta(minutes=9)).isoformat().replace(
            "+00:00", "Z"
        )
        argv_headless = by_route["claude.headless.full"]["would_run"]
        assert argv_headless[argv_headless.index("--now") + 1] == (
            NOW - timedelta(minutes=1)
        ).isoformat().replace("+00:00", "Z")

    def test_only_a_cheap_model_served_leaves_the_review_route_unvouched(
        self, tmp_path: Path
    ) -> None:
        verdict, newest, found = _observe_all(
            tmp_path, transcript=[_served(NOW - timedelta(minutes=2), "claude-haiku-4-5")]
        )
        assert verdict == "served"
        by_route = _plan(tmp_path, newest, found)
        assert by_route["claude.review.opus"].get("skipped") == "no-serve-in-model-family"
        assert "would_run" in by_route["claude.headless.full"]

    def test_a_wall_newer_than_every_serve_holds_the_whole_account(self, tmp_path: Path) -> None:
        verdict, newest, _found = _observe_all(
            tmp_path,
            transcript=[_served(NOW - timedelta(minutes=5), "claude-opus-5")],
            headless=[_wall(NOW - timedelta(minutes=1))],
        )
        assert verdict == "walled" and newest.kind == "wall"

    def test_a_serve_older_than_a_newer_wall_is_not_resurrected_by_another_family(
        self, tmp_path: Path
    ) -> None:
        """opus serve t0, wall t1, fable serve t2: the account is served (t2 is newest) but the
        t0 opus serve predates the wall and must not vouch for the opus review route. A Fable
        response cannot witness Opus availability after an Opus refusal (review finding, #4615)."""
        verdict, newest, found = _observe_all(
            tmp_path,
            transcript=[
                _served(NOW - timedelta(minutes=9), "claude-opus-5"),
                _served(NOW - timedelta(minutes=1), "claude-fable-5-1"),
            ],
            headless=[_wall(NOW - timedelta(minutes=5))],
        )
        assert verdict == "served" and newest.model == "claude-fable-5-1"
        by_route = obs.evidence_by_route(found, ROUTES)
        assert by_route["claude.review.opus"] is None, "pre-wall opus serve resurrected"
        assert by_route["claude.headless.full"] is not None
        assert by_route["claude.headless.full"].at == NOW - timedelta(minutes=1)
        planned = _plan(tmp_path, newest, found)
        assert "would_run" not in planned["claude.review.opus"], planned["claude.review.opus"]
        assert "would_run" in planned["claude.headless.full"]

    def test_a_serve_after_the_newest_wall_still_vouches_for_its_route(
        self, tmp_path: Path
    ) -> None:
        """Control for the test above: the same wall, but the opus serve postdates it."""
        verdict, newest, found = _observe_all(
            tmp_path,
            transcript=[
                _served(NOW - timedelta(minutes=3), "claude-opus-5"),
                _served(NOW - timedelta(minutes=1), "claude-fable-5-1"),
            ],
            headless=[_wall(NOW - timedelta(minutes=5))],
        )
        assert verdict == "served"
        by_route = obs.evidence_by_route(found, ROUTES)
        assert by_route["claude.review.opus"] is not None
        assert by_route["claude.review.opus"].at == NOW - timedelta(minutes=3)
        assert "would_run" in _plan(tmp_path, newest, found)["claude.review.opus"]

    def test_main_entry_point_mints_per_route_from_mixed_family_observations(
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
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["verdict"] == "served"
        assert payload["observed_model_by_route"]["claude.headless.full"] == "claude-fable-5-1"
        assert payload["observed_model_by_route"]["claude.review.opus"] is None
        by_route = {r["route_id"]: r for r in payload["receipts"]}
        assert "would_run" in by_route["claude.headless.full"]
        assert "would_run" not in by_route["claude.review.opus"], by_route["claude.review.opus"]

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
        ev = obs.Observation("served", NOW, "session-transcript", model="claude-fable-5-1")
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

    def test_observe_is_unchanged_for_its_existing_callers(self, tmp_path: Path) -> None:
        verdict, newest, found = _observe_all(
            tmp_path, transcript=[_served(NOW - timedelta(minutes=1), "claude-fable-5-1")]
        )
        hdir, tdir = tmp_path / "headless", tmp_path / "projects"
        verdict2, newest2 = obs.observe(
            now=NOW,
            max_age_seconds=1800,
            headless_glob=str(hdir / "*" / "output.jsonl"),
            transcript_glob=str(tdir / "*" / "*.jsonl"),
        )
        assert (verdict, newest.at, newest.model) == (verdict2, newest2.at, newest2.model)
        assert len(found) == 1
