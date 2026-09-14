"""The live↔declared join: runtime claim markers vs the vault SSOT.

Every other cc-hygiene check reads the vault and asks whether the DECLARED state
is self-consistent. None read the RUNTIME state — the ``cc-active-task-*``
markers the gate actually keys on — so the two could disagree indefinitely with
nothing reporting it. Measured 2026-09-13: ``cc-active-task-cx-crit`` named a
task the vault recorded CLOSED_DONE, and had for roughly eleven hours.

cc-close now retires every lease its role holds for the task it closes, which
removes the common producer. This check is the backstop for what cc-close cannot
reach: a lane that dies, is reaped, or has its note closed by hand never runs
cc-close at all.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from cc_hygiene.checks import check_stale_claim_marker, read_claim_markers  # noqa: E402
from cc_hygiene.models import TaskNote  # noqa: E402

from shared.session_identity import split_claim_marker_key  # noqa: E402


def _now() -> datetime:
    return datetime(2026, 9, 14, 1, 0, tzinfo=UTC)


def _note(task_id: str, *, status: str, assigned_to: str | None = "eta") -> TaskNote:
    return TaskNote(
        path=f"/vault/active/{task_id}.md",
        task_id=task_id,
        status=status,
        assigned_to=assigned_to,
    )


class TestDisagreementMatrix:
    def test_marker_for_a_live_task_assigned_to_that_role_is_healthy(self) -> None:
        events = check_stale_claim_marker(
            {"eta-ef3687f5-601c-4a82-9c6e-d97de6dce2c2": "t1"},
            [_note("t1", status="in_progress")],
            now=_now(),
        )
        assert events == []

    def test_marker_for_a_terminal_task_is_flagged_with_re_emit_close(self) -> None:
        events = check_stale_claim_marker(
            {"cx-crit-15c99664-780f-41c0-9c3e-daa21771bee1": "t1"},
            [_note("t1", status="done", assigned_to="cx-crit")],
            now=_now(),
        )
        assert len(events) == 1
        ev = events[0]
        assert ev.check_id == "stale_claim_marker"
        assert ev.severity == "warning"
        assert ev.metadata["next_action"] == "re-emit-close"
        assert ev.metadata["role"] == "cx-crit", (
            "the role was mis-split — a hyphenated role followed by a uuid is the "
            "exact shape this join has to read"
        )
        assert "cc-close t1" in ev.metadata["remediation"]

    def test_marker_for_a_closed_note_gets_a_remedy_that_can_actually_run(self) -> None:
        """Presence in closed/ is terminal regardless of the status string — and
        ``cc-close`` is NOT the remedy there.

        codex-1 caught the first cut prescribing ``cc-close <task>`` for every
        terminal case. cc-close resolves only active/ notes and exits 2 on one
        already in closed/, before it ever reaches marker cleanup, so the marker
        this check reported survived the action it recommended. A next_action that
        cannot run is worse than none: it looks handled.
        """
        events = check_stale_claim_marker(
            {"eta": "t1"},
            [],
            [_note("t1", status="in_progress")],
            now=_now(),
        )
        assert len(events) == 1
        assert events[0].metadata["next_action"] == "retire-orphan-marker"
        assert events[0].metadata["vault_location"] == "closed"
        assert "cc-active-task-eta" in events[0].metadata["remediation"]
        assert "cc-claim-epoch-eta" in events[0].metadata["remediation"]

    def test_terminal_note_still_in_active_preserves_its_outcome(self) -> None:
        """The emitted cc-close carries --status, so re-closing cannot rewrite it.

        cc-close defaults to `done`; a withdrawn task re-closed without --status
        would silently become done — the remedy corrupting the record it was
        meant to reconcile.
        """
        events = check_stale_claim_marker(
            {"eta": "t1"}, [_note("t1", status="withdrawn")], now=_now()
        )
        assert len(events) == 1
        assert events[0].metadata["next_action"] == "re-emit-close"
        assert events[0].metadata["vault_location"] == "active"
        assert "--status withdrawn" in events[0].metadata["remediation"]

    def test_event_reports_the_disagreement_not_an_inferred_cause(self) -> None:
        """ "the lane never ran cc-close" was an unobserved cause, and wrong.

        An interrupted close, a failed cleanup, or the cross-session sweep defect
        this ships alongside all produce the same state *after* cc-close ran.
        """
        events = check_stale_claim_marker({"eta": "t1"}, [_note("t1", status="done")], now=_now())
        assert len(events) == 1
        assert "never ran cc-close" not in events[0].message

    def test_marker_for_an_unknown_task_needs_a_person(self) -> None:
        """Nothing here can tell a deleted note from a corrupt marker."""
        events = check_stale_claim_marker(
            {"eta-ef3687f5-601c-4a82-9c6e-d97de6dce2c2": "ghost"}, [], now=_now()
        )
        assert len(events) == 1
        assert events[0].severity == "violation"
        assert events[0].metadata["next_action"] == "operator-adjudication"
        assert events[0].metadata["reason"] == "task_not_in_vault"

    def test_contested_claim_is_a_violation_not_a_cleanup(self) -> None:
        events = check_stale_claim_marker(
            {"eta-ef3687f5-601c-4a82-9c6e-d97de6dce2c2": "t1"},
            [_note("t1", status="in_progress", assigned_to="beta")],
            now=_now(),
        )
        assert len(events) == 1
        assert events[0].severity == "violation"
        assert events[0].metadata["next_action"] == "operator-adjudication"
        assert events[0].metadata["vault_assigned_to"] == "beta"

    def test_unassigned_live_task_is_not_contested(self) -> None:
        """`unassigned` is not a rival claimant."""
        events = check_stale_claim_marker(
            {"eta-ef3687f5-601c-4a82-9c6e-d97de6dce2c2": "t1"},
            [_note("t1", status="in_progress", assigned_to="unassigned")],
            now=_now(),
        )
        assert events == []

    def test_marker_whose_role_cannot_be_named_is_not_reported_as_contested(
        self,
    ) -> None:
        """A suffix too short to be claim-keyable makes the role unresolvable.

        cc-claim degrades to legacy role-keying rather than minting such a key
        (``session id … is not claim-keyable``), so a marker in this shape did not
        come from cc-claim. Naming a role anyway would send the operator to the
        wrong lane, so the event says it cannot attribute the marker instead.
        """
        events = check_stale_claim_marker(
            {"eta-sess1": "t1"},
            [_note("t1", status="in_progress", assigned_to="eta")],
            now=_now(),
        )
        assert len(events) == 1
        assert events[0].metadata["reason"] == "role_unattributable"
        assert events[0].session is None
        assert "unattributable" in events[0].metadata["role"]

    def test_every_event_carries_an_actionable_next_action(self) -> None:
        """A report without a remedy is a nag, not a reconciliation."""
        events = check_stale_claim_marker(
            {"eta": "done-task", "beta-7a9e1d91-be4a-4354-a109-482b2bd0e5e3": "ghost"},
            [_note("done-task", status="withdrawn")],
            now=_now(),
        )
        assert len(events) == 2
        assert all(e.metadata.get("next_action") for e in events)


class TestMarkerKeySplitting:
    """A marker key is ``<role>[-<session_id>]`` and BOTH halves carry hyphens."""

    def test_hyphenated_role_with_uuid_splits_correctly(self) -> None:
        got = split_claim_marker_key(
            "cx-crit-15c99664-780f-41c0-9c3e-daa21771bee1", ["cx-crit", "eta", "beta"]
        )
        assert got == ("cx-crit", "15c99664-780f-41c0-9c3e-daa21771bee1")

    def test_bare_role_has_no_session(self) -> None:
        assert split_claim_marker_key("eta", ["eta"]) == ("eta", None)

    def test_longest_role_wins_over_a_prefix_coincidence(self) -> None:
        """`cx` must not win over `cx-crit` just by being a prefix."""
        got = split_claim_marker_key(
            "cx-crit-15c99664-780f-41c0-9c3e-daa21771bee1", ["cx", "cx-crit"]
        )
        assert got == ("cx-crit", "15c99664-780f-41c0-9c3e-daa21771bee1")

    def test_remainder_that_is_not_claim_keyable_is_not_a_session(self) -> None:
        """`epsilon-12345` is the retired pid shape, not a session id."""
        assert split_claim_marker_key("epsilon-12345", ["epsilon"]) is None

    def test_unknown_role_is_unresolvable_rather_than_guessed(self) -> None:
        assert split_claim_marker_key("zzz-sess1234", ["eta"]) is None


class TestReadClaimMarkers:
    def test_reads_first_line_only_and_skips_epoch_sidecars(self, tmp_path: Path) -> None:
        (tmp_path / "cc-active-task-eta").write_text("t1\n", encoding="utf-8")
        (tmp_path / "cc-active-task-beta-s2").write_text("t2\ntrailing\n", encoding="utf-8")
        # Distinct prefix by design, so an epoch can never masquerade as a claim.
        (tmp_path / "cc-claim-epoch-eta").write_text("1780000000 t1\n", encoding="utf-8")

        assert read_claim_markers(tmp_path) == {"eta": "t1", "beta-s2": "t2"}

    def test_empty_marker_is_not_a_claim(self, tmp_path: Path) -> None:
        (tmp_path / "cc-active-task-eta").write_text("\n", encoding="utf-8")
        assert read_claim_markers(tmp_path) == {}

    def test_missing_directory_reads_as_no_markers(self, tmp_path: Path) -> None:
        assert read_claim_markers(tmp_path / "nope") == {}


class TestSweepBinding:
    """The marker source follows the sweep's configured roots, not the real $HOME.

    First cut of this check hardcoded ``Path.home()/".cache"/"hapax"`` on the
    reasoning that cc-claim and the gate hardcode it too. That reasoning was
    wrong in a way the sweeper's own suite caught immediately: every other root
    here is configurable, so a sweep pointed at a test vault reported on THIS
    host's live lanes and paged for them. cc-claim writes the markers beside the
    relay dir, so relay_root.parent is the anchor that moves with the sweep.
    """

    def test_marker_dir_defaults_to_the_relay_root_parent(self, tmp_path: Path) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "cc_hygiene_sweeper", REPO_ROOT / "scripts" / "cc-hygiene-sweeper.py"
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        cache = tmp_path / "cache" / "hapax"
        relay = cache / "relay"
        relay.mkdir(parents=True)
        # A marker that names a task the swept vault has never heard of. If the
        # check read the real $HOME this would be invisible here (and the host's
        # own live markers would show up instead).
        (cache / "cc-active-task-eta").write_text("not-in-this-vault\n", encoding="utf-8")
        vault = tmp_path / "vault"
        (vault / "active").mkdir(parents=True)
        (vault / "closed").mkdir(parents=True)

        state = mod.run_sweep(vault_root=vault, relay_root=relay, repo_root=tmp_path)

        stale = [e for e in state.events if e.check_id == "stale_claim_marker"]
        assert len(stale) == 1, f"expected the sandbox marker, got {stale}"
        assert stale[0].task_id == "not-in-this-vault"
        assert stale[0].metadata["next_action"] == "operator-adjudication"
