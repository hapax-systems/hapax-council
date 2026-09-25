"""cc-claim --release / --rebind end to end: governed release, then the admitted claim."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tests.scripts.test_cc_claim import _SESSION_ID, _claim, _task_root, _write_task

NEXT_SESSION = "1f1f1f1f-2222-4333-8444-555566667777"
NEXT = {"HAPAX_AGENT_ROLE": "cx-next", "HAPAX_AGENT_NAME": "cx-next"}
THIRD_SESSION = "2e2e2e2e-3333-4444-8555-666677778888"
THIRD = {"HAPAX_AGENT_ROLE": "cx-third", "HAPAX_AGENT_NAME": "cx-third"}


@pytest.fixture(autouse=True)
def _isolated_coord(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))


def _claimed(home: Path, task_id: str = "held") -> Path:
    note = _write_task(home, "active", task_id)
    first = _claim(home, task_id, dispatch=False)
    assert first.returncode == 0, first.stderr
    return note


def _authorization(home: Path, task_id: str = "held") -> Path:
    path = home / "authorization.md"
    path.write_text(
        "---\n"
        "kind: claim-release-authorization\n"
        f"task_id: {task_id}\n"
        "incumbent_role: cx-test\n"
        f"incumbent_session_id: {_SESSION_ID}\n"
        "authorized_by: operator\n"
        "authority: coordinator dispatch for the test\n"
        "---\n",
        encoding="utf-8",
    )
    return path


def _markers(home: Path, role: str) -> list[str]:
    cache = home / ".cache" / "hapax"
    return sorted(path.name for path in cache.glob(f"cc-active-task-{role}*"))


def test_self_yield_release_then_another_role_claims_and_the_old_holder_is_fenced(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    note = _claimed(home)

    released = _claim(
        home,
        "held",
        dispatch=False,
        install_gate0b=False,
        extra_args=["--release", "--witness", "self_yield"],
    )

    assert released.returncode == 0, released.stderr
    assert "released on witness self_yield" in released.stdout
    text = note.read_text(encoding="utf-8")
    assert "status: offered" in text and "assigned_to: unassigned" in text
    assert _markers(home, "cx-test") == []
    archives = list((_task_root(home) / "_lineage" / "held").glob("governed-release-*"))
    assert len(archives) == 1

    successor = _claim(
        home, "held", dispatch=False, install_gate0b=False, session_id=NEXT_SESSION, extra_env=NEXT
    )
    assert successor.returncode == 0, successor.stderr
    assert "assigned_to: cx-next" in note.read_text(encoding="utf-8")

    # The old holder cannot resume the row it no longer holds.
    stale = _claim(home, "held", dispatch=False, install_gate0b=False)
    assert stale.returncode == 4, stale.stdout + stale.stderr
    assert "assigned_to: cx-next" in note.read_text(encoding="utf-8")


def test_rebind_on_a_recorded_operator_authorization(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _claimed(home)
    authority = _authorization(home)

    result = _claim(
        home,
        "held",
        dispatch=False,
        install_gate0b=False,
        session_id=NEXT_SESSION,
        extra_env=NEXT,
        extra_args=["--rebind", "--witness", "operator_release", "--authority-ref", str(authority)],
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "released on witness operator_release" in result.stdout
    assert "admitted publication applied" in result.stdout
    text = note.read_text(encoding="utf-8")
    assert "status: claimed" in text and "assigned_to: cx-next" in text
    assert _markers(home, "cx-test") == []
    assert _markers(home, "cx-next") == [
        "cc-active-task-cx-next",
        f"cc-active-task-cx-next-{NEXT_SESSION}",
    ]


def test_rebind_on_provider_wall_without_the_shared_readers_holds_typed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _claimed(home)
    before = note.read_bytes(), _markers(home, "cx-test")

    result = _claim(
        home,
        "held",
        dispatch=False,
        install_gate0b=False,
        session_id=NEXT_SESSION,
        extra_env=NEXT,
        extra_args=["--rebind", "--witness", "provider_wall"],
    )

    assert result.returncode == 8, result.stdout + result.stderr
    assert "claim_release_witness_verifier_unavailable" in result.stderr
    assert "Nothing was released" in result.stderr
    assert (note.read_bytes(), _markers(home, "cx-test")) == before


@pytest.mark.parametrize(
    "args",
    [
        ["--release"],
        ["--rebind"],
        ["--witness", "self_yield"],
        ["--rebind", "--witness", "self_yield", "--to", "cx-other"],
        ["--release", "--witness", "self_yield", "--recover-claim-publications"],
    ],
    ids=[
        "release_without_witness",
        "rebind_without_witness",
        "witness_alone",
        "rebind_to",
        "mixed",
    ],
)
def test_release_usage_errors_change_nothing(tmp_path: Path, args: list[str]) -> None:
    home = tmp_path / "home"
    note = _claimed(home)
    before = note.read_bytes(), _markers(home, "cx-test")
    result = _claim(home, "held", dispatch=False, install_gate0b=False, extra_args=args)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "release_usage_invalid" in result.stderr
    assert (note.read_bytes(), _markers(home, "cx-test")) == before


def test_merge_ready_release_hands_the_row_to_the_named_successor(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _claimed(home)
    note.write_text(
        note.read_text(encoding="utf-8").replace("status: claimed", "status: pr_open"),
        encoding="utf-8",
    )

    released = _claim(
        home,
        "held",
        dispatch=False,
        install_gate0b=False,
        extra_args=["--release", "--witness", "self_yield", "--to", "cx-next"],
    )
    assert released.returncode == 0, released.stderr
    text = note.read_text(encoding="utf-8")
    assert "status: pr_open" in text and "assigned_to: cx-next" in text

    resumed = _claim(
        home, "held", dispatch=False, install_gate0b=False, session_id=NEXT_SESSION, extra_env=NEXT
    )
    assert resumed.returncode == 0, resumed.stderr
    assert "status: pr_open" in note.read_text(encoding="utf-8")


def test_two_racing_rebinders_leave_exactly_one_owner(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _claimed(home)
    authority = _authorization(home)

    def rebind(session: str, env: dict[str, str]):
        return _claim(
            home,
            "held",
            dispatch=False,
            install_gate0b=False,
            session_id=session,
            extra_env=env,
            extra_args=[
                "--rebind",
                "--witness",
                "operator_release",
                "--authority-ref",
                str(authority),
            ],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda args: rebind(*args), [(NEXT_SESSION, NEXT), (THIRD_SESSION, THIRD)])
        )

    winners = [result for result in results if result.returncode == 0]
    assert len(winners) == 1, [(r.returncode, r.stdout, r.stderr) for r in results]
    loser = next(result for result in results if result.returncode != 0)
    assert loser.returncode in {4, 8}, loser.stdout + loser.stderr
    text = note.read_text(encoding="utf-8")
    owners = [role for role in ("cx-next", "cx-third") if f"assigned_to: {role}" in text]
    assert len(owners) == 1
    assert _markers(home, owners[0])
    other = "cx-third" if owners[0] == "cx-next" else "cx-next"
    assert _markers(home, other) == []
    assert _markers(home, "cx-test") == []
