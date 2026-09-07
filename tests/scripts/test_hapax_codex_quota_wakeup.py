"""The quota-reset wakeup's gates, pinned by running the script.

Every assertion comes from executing the real script against a stub sender and a
temporary state directory. Nothing is hand-computed: the script's own recorded
state is the oracle, so a test cannot agree with a mistake in the head that
produced it.

The gates, in order — a tick may only send when all of them allow it:

  1. an ACK was already recorded              -> nothing further is owed
  2. the declared reset has not arrived       -> no probe of any kind
  3. the bounded attempt budget is spent      -> record once, stay quiet
  4. the lane is not provably the expected thread -> refuse; never launch, never
     send to whoever happens to hold the name

The identity gate is the one worth stating twice. A lane NAME is not a thread
identity: another Codex thread can occupy the same tmux session, and the sender
checks for a Codex process rather than for which conversation it is continuing.
`test_a_same_named_lane_running_another_thread_is_refused` is that control.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WAKEUP = REPO_ROOT / "scripts" / "hapax-codex-quota-wakeup"


def _load_wakeup_module():
    """Import the extensionless script so tests can reuse its own identity reader."""
    spec = importlib.util.spec_from_loader(
        "hapax_codex_quota_wakeup",
        importlib.machinery.SourceFileLoader("hapax_codex_quota_wakeup", str(WAKEUP)),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_wakeup = _load_wakeup_module()
_observed_thread_uuids = _wakeup.observed_thread_uuids

#: The reset and thread this unit was built for.
DECLARED_DUE_EPOCH = 1789348894
DECLARED_THREAD = "01a06eeb-3eef-75a1-93ec-f48da5d20560"


def _stub_sender(tmp_path: Path, exit_code: int) -> Path:
    sender = tmp_path / "stub-hapax-codex-send"
    sender.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" > "{tmp_path}/sender-argv"\n'
        'printf "nudge=%s timeout=%s\\n" '
        '"${HAPAX_CODEX_SEND_ACK_NUDGE_LIMIT:-unset}" '
        f'"${{HAPAX_CODEX_SEND_ACK_TIMEOUT:-unset}}" > "{tmp_path}/sender-env"\n'
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    sender.chmod(0o755)
    return sender


class Lane:
    """A tmux session holding a rollout transcript open, like a live Codex lane.

    The script establishes identity from `/proc/<pid>/fd`, so a faithful double
    has to actually hold such a file open — which is precisely what makes the
    wrong-thread control meaningful rather than a mock agreeing with itself.
    """

    def __init__(self, tmp_path: Path, suffix: str, thread: str) -> None:
        self.session_suffix = suffix
        self.thread = thread
        self.name = f"hapax-codex-{suffix}"
        self.rollout = tmp_path / f"rollout-2026-09-04T19-15-05-{thread}.jsonl"
        self.rollout.write_text("{}\n", encoding="utf-8")

    def __enter__(self) -> Lane:
        created = subprocess.run(
            ["tmux", "new-session", "-d", "-s", self.name, f"tail -f {self.rollout}"],
            capture_output=True,
            text=True,
        )
        if created.returncode != 0:
            pytest.skip(f"no usable tmux server: {created.stderr.strip()}")
        # The double is ready exactly when the script's own reader can see it.
        for _ in range(100):
            if self._holds_rollout():
                return self
            time.sleep(0.05)
        self.__exit__()
        pytest.skip("tmux lane double never opened its rollout transcript")
        return self

    def _holds_rollout(self) -> bool:
        """Ask the script's own identity reader, so the double is ready by its rules."""
        panes = subprocess.run(
            ["tmux", "list-panes", "-t", self.name, "-F", "#{pane_pid}"],
            capture_output=True,
            text=True,
        )
        for token in panes.stdout.split():
            if not token.isdigit():
                continue
            if self.thread in _observed_thread_uuids(int(token)):
                return True
        return False

    def __exit__(self, *exc: object) -> None:
        subprocess.run(["tmux", "kill-session", "-t", self.name], capture_output=True)


def _run(
    tmp_path: Path,
    *args: str,
    due_epoch: int = 0,
    session: str = "cx-blue",
    thread: str = DECLARED_THREAD,
    sender: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    bus = tmp_path / "bus"
    bus.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "HAPAX_CODEX_WAKEUP_DUE_EPOCH": str(due_epoch),
            "HAPAX_CODEX_WAKEUP_SESSION": session,
            "HAPAX_CODEX_WAKEUP_THREAD": thread,
            "HAPAX_CODEX_WAKEUP_STATE_DIR": str(tmp_path / "state"),
            "HAPAX_CODEX_WAKEUP_LANEBUS": str(bus),
        }
    )
    if sender is not None:
        env["HAPAX_CODEX_WAKEUP_SENDER"] = str(sender)
    return subprocess.run(
        [sys.executable, str(WAKEUP), *args],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )


def _state_files(tmp_path: Path) -> list[Path]:
    return sorted((tmp_path / "state").glob("campaign-*.json"))


def _state(tmp_path: Path) -> dict:
    files = _state_files(tmp_path)
    assert len(files) == 1, files
    return json.loads(files[0].read_text(encoding="utf-8"))


def _attempt_records(tmp_path: Path) -> list[dict]:
    records = []
    for directory in (tmp_path / "state").glob("campaign-*-attempts"):
        for path in sorted(directory.iterdir()):
            records.append(json.loads(path.read_text(encoding="utf-8")))
    return records


# --------------------------------------------------------------------------- #
# Gate 2 — the reset
# --------------------------------------------------------------------------- #
def test_a_tick_before_the_reset_touches_nothing_at_all(tmp_path: Path) -> None:
    """Checking whether a wall is still there costs the quota being conserved.

    Deliberately an assertion about the absence of every artefact: a run that
    recorded an attempt, wrote a bus file or reached the sender would have spent
    something, and spending nothing is the entire point of this gate.
    """
    sender = _stub_sender(tmp_path, 0)
    result = _run(tmp_path, due_epoch=DECLARED_DUE_EPOCH, sender=sender)

    assert result.returncode == 0, result.stderr
    assert _state_files(tmp_path) == []
    assert not (tmp_path / "sender-argv").exists()
    assert list((tmp_path / "bus").iterdir()) == []


# --------------------------------------------------------------------------- #
# Gate 4 — thread identity, not lane name
# --------------------------------------------------------------------------- #
def test_a_same_named_lane_running_another_thread_is_refused(tmp_path: Path) -> None:
    """The control the lane name cannot provide.

    The session has exactly the expected name and a live Codex-shaped process.
    Only the conversation it is continuing differs — which is the whole hazard,
    because a wakeup delivered into the wrong thread is not a continuation.
    """
    other_thread = str(uuid.uuid4())
    sender = _stub_sender(tmp_path, 0)
    with Lane(tmp_path, "cx-wrongthread", other_thread):
        result = _run(tmp_path, due_epoch=0, session="cx-wrongthread", sender=sender)

    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "sender-argv").exists(), "sent into an unverified thread"
    outcomes = [record["outcome"] for record in _attempt_records(tmp_path)]
    assert outcomes == ["wrong_thread"], outcomes


def test_the_expected_thread_is_accepted_and_sent_without_nudges(tmp_path: Path) -> None:
    """The twin of the control above: same machinery, right thread, must send."""
    sender = _stub_sender(tmp_path, 0)
    with Lane(tmp_path, "cx-rightthread", DECLARED_THREAD):
        result = _run(tmp_path, due_epoch=0, session="cx-rightthread", sender=sender)

    assert result.returncode == 0, result.stderr
    state = _state(tmp_path)
    assert state["last_outcome"] == "delivered_and_acked"
    assert state["done"] is True
    argv = (tmp_path / "sender-argv").read_text(encoding="utf-8")
    assert "--require-ack" in argv
    assert "--transport tmux" in argv
    # A quota-walled session must never be keyboard-poked into a retry storm.
    assert "nudge=0" in (tmp_path / "sender-env").read_text(encoding="utf-8")


def test_an_absent_session_is_refused_and_never_launched(tmp_path: Path) -> None:
    sender = _stub_sender(tmp_path, 0)
    result = _run(tmp_path, due_epoch=0, session="cx-definitely-not-live", sender=sender)

    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "sender-argv").exists()
    assert [r["outcome"] for r in _attempt_records(tmp_path)] == ["session_absent"]


# --------------------------------------------------------------------------- #
# Gate 1 — a delivered ACK closes the campaign
# --------------------------------------------------------------------------- #
def test_a_delivered_ack_is_never_repeated(tmp_path: Path) -> None:
    sender = _stub_sender(tmp_path, 0)
    with Lane(tmp_path, "cx-once", DECLARED_THREAD):
        first = _run(tmp_path, due_epoch=0, session="cx-once", sender=sender)
        assert first.returncode == 0, first.stderr
        assert _state(tmp_path)["done"] is True

        (tmp_path / "sender-argv").unlink()
        again = _run(tmp_path, due_epoch=0, session="cx-once", sender=sender)

    assert again.returncode == 0
    assert not (tmp_path / "sender-argv").exists(), "a delivered wakeup fired twice"


# --------------------------------------------------------------------------- #
# Gate 3 and the budget's integrity
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("{ this is not json", "state_malformed"),
        ('{"attempts": "seven"}', "state_malformed"),
        ("[]", "state_malformed"),
    ],
)
def test_damaged_state_holds_instead_of_restarting_the_budget(
    tmp_path: Path, content: str, expected: str
) -> None:
    """A ceiling that resets itself when its own record is corrupt is not a ceiling.

    This is the failure the draft had: an unreadable state read as zero attempts,
    so damaging one file silently restored an unbounded retry budget.
    """
    sender = _stub_sender(tmp_path, 0)
    with Lane(tmp_path, "cx-damaged", DECLARED_THREAD):
        # Provoke the campaign path so the state file lands at its real name.
        seed = _run(tmp_path, due_epoch=0, session="cx-damaged", sender=sender)
        assert seed.returncode == 0, seed.stderr
        state_file = _state_files(tmp_path)[0]
        state_file.write_text(content, encoding="utf-8")
        (tmp_path / "sender-argv").unlink()

        result = _run(tmp_path, due_epoch=0, session="cx-damaged", sender=sender)

    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "sender-argv").exists(), "damaged state licensed a send"
    assert expected in [r["outcome"] for r in _attempt_records(tmp_path)]


def test_the_attempt_budget_is_bounded_and_announces_once(tmp_path: Path) -> None:
    sender = _stub_sender(tmp_path, 12)
    with Lane(tmp_path, "cx-budget", DECLARED_THREAD):
        for _ in range(3):
            assert _run(tmp_path, due_epoch=0, session="cx-budget", sender=sender).returncode == 0
        state_file = _state_files(tmp_path)[0]
        state = json.loads(state_file.read_text(encoding="utf-8"))
        state["attempts"] = 8
        state_file.write_text(json.dumps(state), encoding="utf-8")

        first = _run(tmp_path, due_epoch=0, session="cx-budget", sender=sender)
        second = _run(tmp_path, due_epoch=0, session="cx-budget", sender=sender)

    assert first.returncode == 0 and second.returncode == 0
    exhausted = [p for p in (tmp_path / "bus").iterdir() if "attempts-exhausted" in p.name]
    assert len(exhausted) == 1, [p.name for p in (tmp_path / "bus").iterdir()]


def test_every_attempt_is_retained_not_overwritten(tmp_path: Path) -> None:
    """The draft kept one `last-attempt.log`, so "preserve each error" was false."""
    sender = _stub_sender(tmp_path, 12)
    with Lane(tmp_path, "cx-retain", DECLARED_THREAD):
        for _ in range(3):
            assert _run(tmp_path, due_epoch=0, session="cx-retain", sender=sender).returncode == 0

    records = _attempt_records(tmp_path)
    assert len(records) == 3, records
    assert [r["attempt"] for r in records] == [1, 2, 3]
    assert {r["outcome"] for r in records} == {"ack_timeout"}


def test_an_unacked_send_does_not_close_the_campaign(tmp_path: Path) -> None:
    """Exit 12 means the message landed and no token came back.

    That is the outcome most easily mistaken for success, so it is the one pinned:
    delivery is not resumption, and only an ACK closes the loop.
    """
    sender = _stub_sender(tmp_path, 12)
    with Lane(tmp_path, "cx-noack", DECLARED_THREAD):
        result = _run(tmp_path, due_epoch=0, session="cx-noack", sender=sender)

    assert result.returncode == 0, result.stderr
    state = _state(tmp_path)
    assert state["last_outcome"] == "ack_timeout"
    assert state["last_exit"] == 12
    assert state.get("done") is not True
    assert "delivered_ack_at" not in state


def test_a_reserved_but_unresolved_attempt_stays_counted(tmp_path: Path) -> None:
    """A crash between reserving and resolving must cost an attempt, not license repeats.

    The uncertainty is preserved as its own record rather than resolved either way:
    the send may or may not have landed, and neither answer may be invented.
    """
    sender = _stub_sender(tmp_path, 12)
    with Lane(tmp_path, "cx-crash", DECLARED_THREAD):
        assert _run(tmp_path, due_epoch=0, session="cx-crash", sender=sender).returncode == 0
        state_file = _state_files(tmp_path)[0]
        state = json.loads(state_file.read_text(encoding="utf-8"))
        state["attempt_open"] = state["attempts"]  # as an interrupted run would leave it
        state_file.write_text(json.dumps(state), encoding="utf-8")

        result = _run(tmp_path, due_epoch=0, session="cx-crash", sender=sender)

    assert result.returncode == 0, result.stderr
    outcomes = [r["outcome"] for r in _attempt_records(tmp_path)]
    assert "unresolved_after_reserve" in outcomes, outcomes
    assert _state(tmp_path)["attempts"] >= 2


def test_an_unpersistable_reservation_refuses_to_send(tmp_path: Path) -> None:
    """A send the budget would not remember is an unbounded send."""
    # Seed with a send that does NOT close the campaign, so the second run still
    # has an attempt to reserve without any state being edited to make it so.
    sender = _stub_sender(tmp_path, 12)
    with Lane(tmp_path, "cx-nopersist", DECLARED_THREAD):
        seed = _run(tmp_path, due_epoch=0, session="cx-nopersist", sender=sender)
        assert seed.returncode == 0, seed.stderr
        assert (tmp_path / "sender-argv").exists(), "seed never reached the sender"
        (tmp_path / "sender-argv").unlink()

        state_dir = tmp_path / "state"
        state_dir.chmod(0o500)  # readable, not writable
        try:
            result = _run(tmp_path, due_epoch=0, session="cx-nopersist", sender=sender)
        finally:
            state_dir.chmod(0o700)

    assert result.returncode == 1, result.stdout + result.stderr
    assert not (tmp_path / "sender-argv").exists(), "sent without a durable attempt record"


def test_the_declared_defaults_match_the_recorded_reset_and_thread() -> None:
    """Defaults must be what was actually reported, not rounded stand-ins."""
    source = WAKEUP.read_text(encoding="utf-8")
    assert f"DEFAULT_DUE_EPOCH = {DECLARED_DUE_EPOCH}" in source
    assert f'DEFAULT_THREAD = "{DECLARED_THREAD}"' in source
