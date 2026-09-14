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

    def test_terminal_status_cc_close_rejects_does_not_get_a_cc_close_remedy(self) -> None:
        """`refused` is terminal but cc-close's --status validator rejects it.

        TASK_TERMINAL_STATUSES is a SUPERSET of what cc-close accepts, so building
        a remedy from terminality alone emits `cc-close <task> --status refused`,
        which exits 1 before cleaning anything.
        """
        for status in ("refused", "completed", "closed_poisoned", "rejected", "deferred"):
            events = check_stale_claim_marker(
                {"eta": "t1"}, [_note("t1", status=status)], now=_now()
            )
            assert len(events) == 1, status
            assert events[0].metadata["next_action"] == "retire-orphan-marker", status
            # The explanation may NAME cc-close (saying why it is not the remedy);
            # what must not appear is a runnable `cc-close <task>` invocation.
            assert "cc-close t1" not in events[0].metadata["remediation"], status
            assert f"--status {status}" not in events[0].metadata["remediation"], status

    def test_cc_close_accepted_statuses_match_the_script(self) -> None:
        """The constant and cc-close's own validator must not drift apart."""
        from cc_hygiene.checks import CC_CLOSE_ACCEPTED_STATUSES

        script = (REPO_ROOT / "scripts" / "cc-close").read_text(encoding="utf-8")
        # scripts/cc-close:45 — `*) echo "cc-close: --status must be done, withdrawn, or superseded`
        for status in CC_CLOSE_ACCEPTED_STATUSES:
            assert status in script, f"{status} not named in cc-close"
        assert "done|withdrawn|superseded" in script, (
            "cc-close's accepted --status set changed; update CC_CLOSE_ACCEPTED_STATUSES"
        )

    def test_a_former_assignees_marker_is_not_read_as_the_new_owners(self) -> None:
        """Role discovery uses CURRENT assigned_to, which omits former assignees.

        t1 reassigned from `cx-blue-shadow` to `cx-blue`, with only the old
        `cx-blue-shadow-<uuid>` marker left: the discovered role set holds
        `cx-blue`, and a claim-keyable remainder test reads the leftover as
        cx-blue's own session — so a contested claim reported as healthy. Requiring
        a MINTED remainder makes that reading unavailable.
        """
        events = check_stale_claim_marker(
            {"cx-blue-shadow-9d4e1f77-2a3b-4c58-b0e6-1f2a3b4c5d6e": "t1"},
            [_note("t1", status="in_progress", assigned_to="cx-blue")],
            now=_now(),
        )
        assert len(events) == 1, "a former assignee's marker was silently accepted"
        assert events[0].metadata["reason"] == "role_unattributable"

    def test_remediation_names_the_cache_the_sweep_actually_read(self) -> None:
        """A sweep of another cache must not instruct deleting LOCAL files."""
        # `refused` routes to retire-orphan-marker, which is the branch that names
        # file paths at all — `re-emit-close` names a cc-close command instead.
        events = check_stale_claim_marker(
            {"eta": "t1"},
            [_note("t1", status="refused")],
            cache_dir=Path("/somewhere/else/hapax"),
            now=_now(),
        )
        assert len(events) == 1
        assert events[0].metadata["next_action"] == "retire-orphan-marker"
        remediation = events[0].metadata["remediation"]
        assert "/somewhere/else/hapax/cc-active-task-eta" in remediation
        assert ".cache/hapax/cc-active-task-eta" not in remediation

    def test_emitted_remediation_is_a_runnable_command(self) -> None:
        """The runbook says run it verbatim, so it has to parse.

        `cc-close t1 --status withdrawn (as role eta)` is rejected by `bash -n` at
        the parenthesis — and stripping the annotation would leave the closing role
        unset, so cc-close would resolve whatever role the operator's shell carried.
        """
        import shutil
        import subprocess

        events = check_stale_claim_marker(
            {"eta": "t1"}, [_note("t1", status="withdrawn")], now=_now()
        )
        assert len(events) == 1
        remediation = events[0].metadata["remediation"]

        assert "(" not in remediation and ")" not in remediation, (
            f"prose inside the command: {remediation!r}"
        )
        # HAPAX_AGENT_NAME, not HAPAX_AGENT_ROLE: agent-role.sh resolves NAME (and
        # the CODEX_* names) BEFORE ROLE, so a command setting only ROLE closes as
        # whatever lane the operator's shell already names and leaves the reported
        # markers untouched.
        assert "HAPAX_AGENT_NAME=eta" in remediation, "closing identity not selected"
        assert "HAPAX_CC_TASKS_ROOT=" in remediation, "swept vault not pinned"
        assert "HAPAX_AGENT_ROLE=" not in remediation, (
            "HAPAX_AGENT_ROLE is outranked by HAPAX_AGENT_NAME; setting it does not "
            "establish the closing identity"
        )
        bash = shutil.which("bash")
        assert bash is not None
        parsed = subprocess.run(
            [bash, "-n", "-c", remediation], capture_output=True, text=True, check=False
        )
        assert parsed.returncode == 0, (
            f"remediation does not parse: {remediation!r}\n{parsed.stderr}"
        )

    def test_identity_in_the_remediation_actually_wins_in_cc_close(self) -> None:
        """Proven against cc-close's real resolver, not by reading the command.

        The previous cut set HAPAX_AGENT_ROLE and passed a `bash -n` check while
        resolving to a completely different lane, because agent-role.sh consults
        HAPAX_AGENT_NAME first. A parse check cannot see that; running the resolver
        with a rival identity inherited can.
        """
        import os
        import subprocess

        events = check_stale_claim_marker(
            {"eta": "t1"}, [_note("t1", status="withdrawn")], now=_now()
        )
        remediation = events[0].metadata["remediation"]
        prefix = " ".join(p for p in remediation.split() if "=" in p and "cc-close" not in p)

        helper = REPO_ROOT / "hooks" / "scripts" / "agent-role.sh"
        env = {k: v for k, v in os.environ.items()}
        env["HAPAX_AGENT_NAME"] = "cx-review"  # a rival identity, inherited
        env["HAPAX_AGENT_ROLE"] = "cx-review"
        resolved = subprocess.run(
            ["bash", "-c", f"{prefix} bash -c '. \"{helper}\"; hapax_effective_role'"],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert resolved.stdout.strip() == "eta", (
            f"the emitted command resolves as {resolved.stdout.strip()!r}, not eta — "
            "it would close as the wrong lane and leave the reported markers"
        )

    def test_unattributable_owner_gets_adjudication_not_a_close_command(self) -> None:
        """`<unattributable:...>` in a command is shell redirection, and parses.

        Terminal handling ran before the unattributable branch, so an unknown owner
        beside a terminal task received
        `HAPAX_AGENT_ROLE=<unattributable:key> cc-close ...`. Bash reads the angle
        brackets as redirections; `bash -n` accepts it, so the parse test missed it.
        """
        events = check_stale_claim_marker(
            {"eta-sess1": "t1"},
            [_note("t1", status="withdrawn", assigned_to="eta")],
            now=_now(),
        )
        assert len(events) == 1
        assert events[0].metadata["next_action"] == "operator-adjudication"
        assert events[0].metadata["reason"] == "role_unattributable"
        assert "remediation" not in events[0].metadata, (
            "a close command was constructed for an owner that could not be named"
        )

    def test_a_closed_duplicate_does_not_make_a_live_claim_disposable(self) -> None:
        """A task id in BOTH collections is an inconsistency, not terminality.

        `note` came from active/ while `already_closed` went true from the closed/
        duplicate, so a LIVE in_progress claim reported vault_location=closed and
        its marker was recommended for deletion. Which record is real is not
        inferable from here.
        """
        events = check_stale_claim_marker(
            {"eta": "t1"},
            [_note("t1", status="in_progress")],
            [_note("t1", status="withdrawn")],
            now=_now(),
        )
        assert len(events) == 1
        assert events[0].severity == "violation"
        assert events[0].metadata["reason"] == "duplicate_note_active_and_closed"
        assert events[0].metadata["next_action"] == "operator-adjudication"
        assert "remediation" not in events[0].metadata, (
            "a deletion was recommended for a claim that may be live"
        )

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

    def test_an_unreadable_note_is_not_reported_as_a_nonexistent_task(self) -> None:
        """ "Exists nowhere in the vault" is a claim about the WHOLE vault.

        A sweep that could not read part of it has not established that, and the
        rejected note may be this very task. The guard sat below the vault lookup
        and the not-found branch returned past it, so the case with the least
        evidence produced the most confident event — and `task_not_in_vault` is
        what an operator acts on by deleting a marker.
        """
        events = check_stale_claim_marker(
            {"eta-ef3687f5-601c-4a82-9c6e-d97de6dce2c2": "ghost"},
            [],
            unparsed_notes=["/vault/active/renamed-work.md"],
            now=_now(),
        )
        assert len(events) == 1
        assert events[0].metadata["reason"] == "vault_view_incomplete", (
            "a marker was called nonexistent on the strength of a view that was "
            "admittedly incomplete"
        )
        assert "/vault/active/renamed-work.md" in events[0].metadata["unparsed_notes"]
        assert events[0].metadata["next_action"] == "operator-adjudication"

    def test_every_event_records_where_the_join_looked(self) -> None:
        """No result of this check is silent about its own marker directory.

        The directory is derived from relay_root, and a derivation that exists but
        points somewhere wrong cannot be detected from here — "wrong" is a fact
        about another process's configuration. What a reader CAN be given is how
        the location was chosen, so a clean or a confident result is never mistaken
        for a verified one.
        """
        events = check_stale_claim_marker(
            {"eta-ef3687f5-601c-4a82-9c6e-d97de6dce2c2": "ghost"},
            [],
            cache_dir=Path("/somewhere/.cache/hapax"),
            marker_dir_provenance="derived from relay_root /somewhere/.cache/hapax/relay",
            now=_now(),
        )
        assert events
        for event in events:
            assert event.metadata["marker_dir"] == "/somewhere/.cache/hapax"
            assert "derived from relay_root" in event.metadata["marker_dir_provenance"]

    def test_provenance_is_stated_as_unknown_rather_than_omitted(self) -> None:
        """A caller that passes none must not produce an event that looks verified."""
        events = check_stale_claim_marker(
            {"eta-ef3687f5-601c-4a82-9c6e-d97de6dce2c2": "ghost"}, [], now=_now()
        )
        assert events
        assert all(e.metadata["marker_dir_provenance"] == "unstated" for e in events)

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

        assert read_claim_markers(tmp_path).markers == {"eta": "t1", "beta-s2": "t2"}

    def test_empty_marker_is_not_a_claim(self, tmp_path: Path) -> None:
        (tmp_path / "cc-active-task-eta").write_text("\n", encoding="utf-8")
        assert read_claim_markers(tmp_path).markers == {}

    def test_missing_directory_reads_as_no_markers(self, tmp_path: Path) -> None:
        assert read_claim_markers(tmp_path / "nope").markers == {}

    def test_unreadable_marker_is_preserved_not_swallowed(self, tmp_path: Path) -> None:
        """A read failure must not look like "no drift".

        The first cut caught OSError/UnicodeDecodeError per file and `continue`d,
        so an injected PermissionError produced an empty mapping and zero events —
        a reconciliation check reporting clean precisely when it knew least.
        """
        good = tmp_path / "cc-active-task-eta"
        good.write_text("t1\n", encoding="utf-8")
        bad = tmp_path / "cc-active-task-beta"
        bad.write_bytes(b"\xff\xfe not utf-8 \xff")

        scan = read_claim_markers(tmp_path)

        assert scan.markers == {"eta": "t1"}, "readable markers must still be scanned"
        assert len(scan.unreadable) == 1
        path, reason = scan.unreadable[0]
        assert path == str(bad)
        assert "UnicodeDecodeError" in reason

    def test_unlistable_directory_is_reported_not_read_as_empty(self, tmp_path: Path) -> None:
        """A denied directory must not read as "no markers".

        The first cut wrapped ``Path.glob`` in ``except OSError``. On 3.12 glob
        swallows a directory-level PermissionError inside its own scandir walk and
        returns an empty iterator, so that except never fired and an unreadable
        cache reported a clean reconciliation. Verified against the pinned
        interpreter; the scan now enumerates with os.listdir, which propagates.
        """
        import unittest.mock as mock

        def denied(*_args: object, **_kwargs: object) -> list[str]:
            raise PermissionError(13, "Permission denied", str(tmp_path))

        with mock.patch("os.listdir", denied):
            scan = read_claim_markers(tmp_path)

        assert scan.enumeration_error is not None
        assert "PermissionError" in scan.enumeration_error

        events = check_stale_claim_marker(scan, [], cache_dir=tmp_path, now=_now())
        assert len(events) == 1
        assert events[0].metadata["reason"] == "marker_dir_unreadable"
        assert events[0].severity == "violation"

    def test_unreadable_marker_becomes_a_violation_event(self, tmp_path: Path) -> None:
        bad = tmp_path / "cc-active-task-beta"
        bad.write_bytes(b"\xff\xfe not utf-8 \xff")

        events = check_stale_claim_marker(
            read_claim_markers(tmp_path), [], cache_dir=tmp_path, now=_now()
        )

        assert len(events) == 1
        assert events[0].severity == "violation"
        assert events[0].metadata["reason"] == "marker_unreadable"
        assert str(bad) in events[0].metadata["marker"]


class TestSweepBinding:
    """The marker source follows the sweep's configured roots, not the real $HOME.

    First cut of this check hardcoded ``Path.home()/".cache"/"hapax"`` on the
    reasoning that cc-claim and the gate hardcode it too. That reasoning was
    wrong in a way the sweeper's own suite caught immediately: every other root
    here is configurable, so a sweep pointed at a test vault reported on THIS
    host's live lanes and paged for them. cc-claim writes the markers beside the
    relay dir, so relay_root.parent is the anchor that moves with the sweep.
    """

    def test_absent_marker_dir_is_reported_not_reported_clean(self, tmp_path: Path) -> None:
        """An inert reconciliation check must be visible as inert.

        read_claim_markers returns {} for "no drift" AND for "I could not read
        anything" (it swallows OSError), so without this the sweep reports a clean
        join while having checked nothing — fail-open for the one check whose whole
        job is noticing that state disagrees.
        """
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "cc_hygiene_sweeper_absent", REPO_ROOT / "scripts" / "cc-hygiene-sweeper.py"
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # relay_root exists but its parent holds no marker dir of its own.
        relay = tmp_path / "nowhere" / "relay"
        relay.mkdir(parents=True)
        vault = tmp_path / "vault"
        (vault / "active").mkdir(parents=True)
        (vault / "closed").mkdir(parents=True)

        state = mod.run_sweep(
            vault_root=vault,
            relay_root=relay,
            repo_root=tmp_path,
            claim_marker_dir=tmp_path / "definitely-absent",
        )

        stale = [e for e in state.events if e.check_id == "stale_claim_marker"]
        assert len(stale) == 1
        # Severity and next_action pinned explicitly: an inert reconciliation is a
        # warning (the sweep is misconfigured, not the claim state), and it needs a
        # person because nothing here can tell a wrong --relay-root from a cache
        # that genuinely has not been created yet.
        assert stale[0].metadata["reason"] == "marker_dir_absent"
        assert stale[0].severity == "violation"
        assert stale[0].metadata["next_action"] == "operator-adjudication"
        assert str(tmp_path / "definitely-absent") in stale[0].metadata["marker_dir"]
        assert stale[0].task_id is None and stale[0].session is None

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

    def test_the_marker_dir_can_be_corrected_without_silencing_the_check(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """A host whose cache layout differs gets a CORRECTION, not a mute.

        Review round 14 asked for an emergency bypass for this check, naming that
        misfire. A per-check mute is the wrong answer to it: it leaves the drift in
        place and removes the only thing reporting it. Both controls are pinned
        here — the flag and the env var must reach run_sweep, so the join can be
        pointed at the real directory.
        """
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "cc_hygiene_sweeper_markerdir", REPO_ROOT / "scripts" / "cc-hygiene-sweeper.py"
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        relay = tmp_path / "relay-elsewhere" / "relay"
        relay.mkdir(parents=True)
        real_cache = tmp_path / "somewhere-else"
        real_cache.mkdir()
        (real_cache / "cc-active-task-eta").write_text("not-in-this-vault\n", encoding="utf-8")
        vault = tmp_path / "vault"
        (vault / "active").mkdir(parents=True)
        (vault / "closed").mkdir(parents=True)

        seen: dict[str, object] = {}
        real_run_sweep = mod.run_sweep

        def capture(**kwargs):  # type: ignore[no-untyped-def]
            seen.update(kwargs)
            return real_run_sweep(**kwargs)

        monkeypatch.setattr(mod, "run_sweep", capture)
        monkeypatch.setenv(mod.CLAIM_MARKER_DIR_ENV, str(real_cache))
        rc = mod.main(
            [
                "--vault-root",
                str(vault),
                "--relay-root",
                str(relay),
                "--repo-root",
                str(tmp_path),
                "--no-write",
                "--no-actions",
            ]
        )
        assert rc == 0
        assert seen.get("claim_marker_dir") == real_cache, (
            f"the env override never reached run_sweep: {seen.get('claim_marker_dir')}"
        )

        seen.clear()
        monkeypatch.delenv(mod.CLAIM_MARKER_DIR_ENV)
        explicit = tmp_path / "by-flag"
        explicit.mkdir()
        rc = mod.main(
            [
                "--vault-root",
                str(vault),
                "--relay-root",
                str(relay),
                "--repo-root",
                str(tmp_path),
                "--claim-marker-dir",
                str(explicit),
                "--no-write",
                "--no-actions",
            ]
        )
        assert rc == 0
        assert seen.get("claim_marker_dir") == explicit

    def test_observational_mode_retires_no_relay(self, tmp_path: Path, monkeypatch) -> None:
        """A "diagnostic" sweep must not mutate relay state.

        `run_sweep` called `reap_dead_lanes` unconditionally, and reaping runs
        `hapax-relay-retire`. So `--no-write --no-actions` — the pair this repo's
        runbook offered as non-mutating, and which I ran to verify that runbook —
        retired a live lane (measured 2026-09-14T10:46:26Z on this host: `alpha`).
        Both flags now withhold it, and the events are still computed.
        """
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "cc_hygiene_sweeper_reap", REPO_ROOT / "scripts" / "cc-hygiene-sweeper.py"
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        called: list[Path] = []
        monkeypatch.setattr(mod, "reap_dead_lanes", lambda root: called.append(root) or [])

        relay = tmp_path / "cache" / "hapax" / "relay"
        relay.mkdir(parents=True)
        vault = tmp_path / "vault"
        (vault / "active").mkdir(parents=True)
        (vault / "closed").mkdir(parents=True)

        mod.run_sweep(vault_root=vault, relay_root=relay, repo_root=tmp_path, reap=False)
        assert not called, "observational mode retired relays anyway"

        mod.run_sweep(vault_root=vault, relay_root=relay, repo_root=tmp_path)
        assert called, (
            "the production sweep stopped reaping — withholding the action in "
            "diagnostic mode must not disable it everywhere"
        )

    def test_the_cli_withholds_reaping_for_both_diagnostic_flags(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Neither flag may leave the one mutation outside both of them."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "cc_hygiene_sweeper_reapcli", REPO_ROOT / "scripts" / "cc-hygiene-sweeper.py"
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        relay = tmp_path / "cache" / "hapax" / "relay"
        relay.mkdir(parents=True)
        vault = tmp_path / "vault"
        (vault / "active").mkdir(parents=True)
        (vault / "closed").mkdir(parents=True)
        seen: list[object] = []
        real = mod.run_sweep
        monkeypatch.setattr(
            mod, "run_sweep", lambda **kw: seen.append(kw.get("reap")) or real(**kw)
        )

        base = [
            "--vault-root",
            str(vault),
            "--relay-root",
            str(relay),
            "--repo-root",
            str(tmp_path),
        ]
        for flags in (["--no-write", "--no-actions"], ["--no-write"], ["--no-actions"]):
            seen.clear()
            assert mod.main([*base, *flags]) == 0
            assert seen == [False], f"{flags} did not withhold reaping: reap={seen}"

    def test_a_first_read_that_fails_is_not_erased_by_a_second_that_succeeds(
        self, tmp_path: Path
    ) -> None:
        """The notes and the errors must come from ONE read of the directory.

        The first repair used three scans — a note loader, a rejected-path scan, a
        closed loader — each enumerating again. A directory that failed on the
        first read and succeeded on the second then produced a notes snapshot
        missing the whole directory beside an error list saying nothing went wrong,
        and the join recommended retiring the marker of a live task it had simply
        not read. A later successful rescan cannot repair an earlier snapshot,
        because nothing joins them.

        The failure is injected once, on active/, exactly as review round 13
        described it.
        """
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "cc_hygiene_sweeper_onescan", REPO_ROOT / "scripts" / "cc-hygiene-sweeper.py"
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        cache = tmp_path / "cache" / "hapax"
        relay = cache / "relay"
        relay.mkdir(parents=True)
        vault = tmp_path / "vault"
        (vault / "active").mkdir(parents=True)
        (vault / "closed").mkdir(parents=True)

        # LIVE work in active/, an older withdrawn record for the same id in
        # closed/, and a marker naming it. Read whole, this is a duplicate-identity
        # conflict; read with active/ missing, it looks like a retirable orphan.
        (vault / "active" / "t1.md").write_text(
            "---\ntype: cc-task\ntask_id: t1\nstatus: in_progress\nassigned_to: eta\n---\n",
            encoding="utf-8",
        )
        (vault / "closed" / "t1.md").write_text(
            "---\ntype: cc-task\ntask_id: t1\nstatus: withdrawn\nassigned_to: eta\n---\n",
            encoding="utf-8",
        )
        (cache / "cc-active-task-eta").write_text("t1\n", encoding="utf-8")

        real_listdir = mod.os.listdir
        failed_once: list[str] = []

        def listdir_failing_first_on_active(target):  # type: ignore[no-untyped-def]
            if str(target).endswith("/active") and not failed_once:
                failed_once.append(str(target))
                raise PermissionError(13, "Permission denied", str(target))
            return real_listdir(target)

        mod.os.listdir = listdir_failing_first_on_active
        try:
            state = mod.run_sweep(vault_root=vault, relay_root=relay, repo_root=tmp_path)
        finally:
            mod.os.listdir = real_listdir

        assert failed_once, "the injected failure never fired — the test proves nothing"
        stale = [e for e in state.events if e.check_id == "stale_claim_marker"]
        reasons = {e.metadata.get("reason") for e in stale}
        assert "vault_view_incomplete" in reasons, (
            f"an enumeration failure left no record; events were {stale}"
        )
        actions = {e.metadata.get("next_action") for e in stale}
        assert "retire-orphan-marker" not in actions, (
            "a live task's marker was recommended for retirement from a view that "
            "failed to read active/"
        )
