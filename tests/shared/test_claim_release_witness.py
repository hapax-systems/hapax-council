"""provider_wall witness: incumbent -> relay -> native trace -> shared wall/turn readers."""

from __future__ import annotations

import json
import sys
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from shared.claim_release_witness import verify_provider_wall
from shared.sdlc_claim import ClaimLeaseIncumbent, ClaimPublicationError

ROLE = "cx-walled"
SESSION = "6fe9afe8-84e2-4093-a09d-6ce5e387eddb"
THREAD = "01a0d3a0-4860-7e90-9f6e-6d46971f9ff7"
NOW = datetime(2026, 9, 24, 20, 0, tzinfo=UTC)
LAST_TURN = datetime(2026, 9, 24, 13, 38, 24, tzinfo=UTC)


def _incumbent(session: str | None = SESSION) -> ClaimLeaseIncumbent:
    return ClaimLeaseIncumbent(
        task_id="held-task",
        role=ROLE,
        session_id=session,
        claim_epoch=1790224731,
        note_path=Path("/vault/active/held-task.md"),
        note_state="active",
        note_status="claimed",
        sidecars=(),
    )


def _home(tmp_path: Path, *, relay: dict | None = None, provider: str = "openai") -> Path:
    home = tmp_path / "home"
    relay_dir = home / ".cache/hapax/relay"
    relay_dir.mkdir(parents=True)
    record = (
        relay
        if relay is not None
        else {
            "schema": "hapax.relay.status.v1",
            "lane": ROLE,
            "platform": "codex",
            "session_id": SESSION,
            "native_thread_id": THREAD,
        }
    )
    # The live relay format is a JSON object followed by YAML status lines.
    (relay_dir / f"{ROLE}.yaml").write_text(
        json.dumps(record, indent=2) + "\nstatus: retired\nretired_at: '2026-09-24T13:38:24Z'\n",
        encoding="utf-8",
    )
    sessions = home / ".codex/sessions/2026/09/24"
    sessions.mkdir(parents=True)
    (sessions / f"rollout-2026-09-24T08-34-52-{THREAD}.jsonl").write_text(
        json.dumps({"type": "session_meta", "payload": {"id": THREAD, "model_provider": provider}})
        + "\n",
        encoding="utf-8",
    )
    return home


def _wall(earliest: datetime | None, *, provider: str | None = "openai", live: bool = True):
    details: dict[str, object] = {}
    if earliest is not None:
        details["earliest_at"] = earliest.isoformat()
    if provider is not None:
        details["model_provider"] = provider
    return SimpleNamespace(
        capacity_id="codex.subscription.weekly",
        label="wall-signal",
        observed_at=(earliest or NOW) + timedelta(minutes=5),
        resets_at=datetime(2026, 9, 30, 14, 25, tzinfo=UTC),
        window="10080m",
        source="local-trace:sha256:abc",
        details=details,
        live=live,
    )


def _readers(walls, *, last_turn: datetime | None = LAST_TURN):
    seen: dict[str, object] = {}

    def read_wall_signals(family, *, now):
        seen["family"], seen["now"] = family, now
        return list(walls)

    def wall_is_live(wall, rows, *, now):
        return wall.live

    def last_served_turn(trace_path):
        seen["trace"] = trace_path
        return last_turn

    return SimpleNamespace(
        read_wall_signals=read_wall_signals,
        wall_is_live=wall_is_live,
        last_served_turn=last_served_turn,
        seen=seen,
    )


def test_a_live_wall_certainly_after_the_last_turn_is_proof(tmp_path: Path) -> None:
    home = _home(tmp_path)
    early = _wall(datetime(2026, 9, 24, 17, 38, 50, tzinfo=UTC))
    later = _wall(datetime(2026, 9, 24, 18, 0, tzinfo=UTC))
    readers = _readers([early, later])
    evidence = verify_provider_wall(_incumbent(), NOW, home=home, readers=readers)
    assert readers.seen["family"] == "codex"
    assert Path(str(readers.seen["trace"])).name.endswith(f"{THREAD}.jsonl")
    assert evidence["family"] == "codex"
    assert evidence["last_served_turn"] == LAST_TURN.isoformat()
    assert evidence["wall_earliest_at"] == early.details["earliest_at"]
    assert evidence["model_provider"] == "openai"
    assert "trace_sha256" in evidence and str(home) not in json.dumps(evidence)


@pytest.mark.parametrize(
    "wall",
    [
        _wall(datetime(2026, 9, 24, 13, 0, tzinfo=UTC)),  # before the last turn
        _wall(LAST_TURN),  # not strictly after
        _wall(None),  # no earliest bound: only a late bound is known
        _wall(datetime(2026, 9, 24, 17, 38, 50, tzinfo=UTC), live=False),  # lifted
        _wall(datetime(2026, 9, 24, 17, 38, 50, tzinfo=UTC), provider="sakana"),  # other pool
        _wall(datetime(2026, 9, 24, 17, 38, 50, tzinfo=UTC), provider=None),  # pool unbound
    ],
    ids=["before", "equal", "no_earliest", "lifted", "other_provider", "no_provider"],
)
def test_a_wall_that_does_not_prove_the_holder_walled_refuses(tmp_path: Path, wall) -> None:
    home = _home(tmp_path)
    with pytest.raises(ClaimPublicationError) as raised:
        verify_provider_wall(_incumbent(), NOW, home=home, readers=_readers([wall]))
    assert raised.value.reason_code == "claim_release_wall_not_proven"


def test_no_served_turn_is_unknown(tmp_path: Path) -> None:
    home = _home(tmp_path)
    readers = _readers([_wall(datetime(2026, 9, 24, 17, 38, 50, tzinfo=UTC))], last_turn=None)
    with pytest.raises(ClaimPublicationError) as raised:
        verify_provider_wall(_incumbent(), NOW, home=home, readers=readers)
    assert raised.value.reason_code == "claim_release_wall_unknown"


@pytest.mark.parametrize(
    "relay",
    [
        None,  # no relay record at all
        {"lane": ROLE, "platform": "codex", "session_id": "other", "native_thread_id": THREAD},
        {"lane": ROLE, "platform": "codex", "session_id": SESSION},  # no native thread
        {
            "lane": ROLE,
            "platform": "podium-remote",
            "session_id": SESSION,
            "native_thread_id": THREAD,
        },
    ],
    ids=["missing", "session_mismatch", "no_thread", "unknown_platform"],
)
def test_an_incumbent_that_cannot_be_bound_to_its_trace_is_unknown(tmp_path: Path, relay) -> None:
    home = _home(tmp_path, relay=relay or {})
    if relay is None:
        (home / ".cache/hapax/relay" / f"{ROLE}.yaml").unlink()
    wall = _wall(datetime(2026, 9, 24, 17, 38, 50, tzinfo=UTC))
    with pytest.raises(ClaimPublicationError) as raised:
        verify_provider_wall(_incumbent(), NOW, home=home, readers=_readers([wall]))
    assert raised.value.reason_code == "claim_release_wall_unknown"


def test_an_incumbent_without_a_session_is_unknown(tmp_path: Path) -> None:
    home = _home(tmp_path)
    wall = _wall(datetime(2026, 9, 24, 17, 38, 50, tzinfo=UTC))
    with pytest.raises(ClaimPublicationError) as raised:
        verify_provider_wall(_incumbent(session=None), NOW, home=home, readers=_readers([wall]))
    assert raised.value.reason_code == "claim_release_wall_unknown"


def test_missing_shared_readers_are_typed_unavailable(tmp_path: Path, monkeypatch) -> None:
    home = _home(tmp_path)
    partial = types.ModuleType("shared.quota_headroom")
    partial.wall_is_live = lambda wall, rows, *, now: True  # the other two are not there yet
    monkeypatch.setitem(sys.modules, "shared.quota_headroom", partial)
    with pytest.raises(ClaimPublicationError) as raised:
        verify_provider_wall(_incumbent(), NOW, home=home)
    assert raised.value.reason_code == "claim_release_witness_verifier_unavailable"
    assert "read_wall_signals" in (raised.value.detail or "")
    assert "last_served_turn" in (raised.value.detail or "")
