"""The capability_shape WRITER — the half a schema field cannot deliver on its own.

Review round 1 on PR #4668 landed ``CapabilityShape`` on ``RouteEnvelope`` and
nothing that populates it. glm-1 called the predicate half-delivered, correctly:
the row's item 3 asks that the estate be able to answer *which capability shape
held this claim*, and a field no writer fills leaves that answer exactly where it
was — in the transcripts.

``capability_shape_from_env`` is the producer, and cc-claim stamps its rendering
into the claim's session-log line. These pin the producer's contract; the schema
side is pinned in test_route_metadata_capability_shape.py.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from shared.route_metadata_schema import CapabilityShape  # noqa: E402
from shared.session_identity import (  # noqa: E402
    capability_shape_from_env,
    format_capability_shape,
)


class TestProducer:
    def test_reads_the_dispatched_model_and_harness(self) -> None:
        shape = capability_shape_from_env(
            {
                "HAPAX_CAPABILITY_MODEL": "claude-opus-5",
                "HAPAX_AGENT_INTERFACE": "claude",
                "HAPAX_CAPABILITY_ROUTE": "claude.review.opus",
            },
            scaffold_revision="284c8b44c",
        )
        assert shape == {
            "model_family": "claude-opus-5",
            "harness": "claude",
            "route": "claude.review.opus",
            "scaffold_revision": "284c8b44c",
        }

    def test_unknown_fields_are_none_not_guessed(self) -> None:
        """An unanswerable field is 'not recorded', never an invented default."""
        shape = capability_shape_from_env({})
        assert shape == {
            "model_family": None,
            "harness": None,
            "route": None,
            "scaffold_revision": None,
        }

    def test_a_launcher_input_is_never_read_as_a_record(self) -> None:
        """HAPAX_CLAUDE_MODEL decides an argument; it does not report an execution.

        The recorder used to read it for a claude harness. That closed the
        cross-harness hole and left the same-harness one: an operator launching a
        claude lane from inside a dispatched claude lane inherits the parent's pin,
        and hapax-claude (interactive) never hands it to anything. Recording it
        there is a fabricated measurement carrying a real model id, which is the
        worst kind. Only the launcher that passed `--model` publishes.
        """
        shape = capability_shape_from_env(
            {"HAPAX_AGENT_INTERFACE": "claude", "HAPAX_CLAUDE_MODEL": "opus"}
        )
        assert shape["model_family"] is None
        assert shape["harness"] == "claude"

    def test_blank_values_do_not_count_as_recorded(self) -> None:
        shape = capability_shape_from_env({"HAPAX_AGENT_INTERFACE": "   "})
        assert shape["harness"] is None

    def test_producer_output_validates_against_the_schema(self) -> None:
        """Producer and schema must not drift into two shapes of the same name."""
        shape = capability_shape_from_env(
            {"HAPAX_CAPABILITY_MODEL": "claude-opus-5", "HAPAX_AGENT_INTERFACE": "claude"}
        )
        model = CapabilityShape.model_validate(shape)
        assert model.model_family == "claude-opus-5"
        assert model.harness == "claude"

    def test_producer_emits_exactly_the_schema_field_set(self) -> None:
        """extra=forbid means a producer key the schema lacks is a hard failure."""
        assert set(capability_shape_from_env({})) == set(CapabilityShape.model_fields)


class TestCcClaimIntegration:
    """The producer must actually reach the note — pinned through real cc-claim.

    Round 2 found the producer suite proved nothing about integration: removing
    both `_shape_suffix` call sites in scripts/cc-claim left every assertion here
    unaffected. A producer with no demonstrated writer is the same half-delivery
    the schema-only field was.
    """

    def _claim(self, home: Path, task_id: str, cc_claim: Path | None = None, **env_extra: str):
        import os
        import subprocess

        root = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
        (root / "active").mkdir(parents=True, exist_ok=True)
        (root / "closed").mkdir(parents=True, exist_ok=True)
        (root / "active" / f"{task_id}.md").write_text(
            "\n".join(
                [
                    "---",
                    "type: cc-task",
                    f"task_id: {task_id}",
                    f'title: "{task_id}"',
                    "status: offered",
                    "assigned_to: unassigned",
                    "claimable: true",
                    "kind: build",
                    "authority_case: CASE-TEST-001",
                    "parent_spec: /tmp/isap-test.md",
                    "depends_on: []",
                    "created_at: 2026-05-09T00:00:00Z",
                    "updated_at: 2026-05-09T00:00:00Z",
                    "claimed_at: null",
                    "---",
                    "",
                    f"# {task_id}",
                    "",
                    "## Session log",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        env = {
            k: v
            for k, v in os.environ.items()
            if k
            not in (
                "HAPAX_SESSION_ID",
                "CLAUDE_CODE_SESSION_ID",
                "CODEX_SESSION",
                "CODEX_THREAD_ID",
                "CODEX_THREAD_NAME",
                "HAPAX_AGENT_INTERFACE",
                "HAPAX_CLAUDE_MODEL",
                "HAPAX_CAPABILITY_MODEL",
                "HAPAX_CAPABILITY_ROUTE",
            )
        }
        env["HOME"] = str(home)
        env["HAPAX_AGENT_ROLE"] = "epsilon"
        env["HAPAX_AGENT_NAME"] = "epsilon"
        env["HAPAX_SESSION_ID"] = "12345678-1234-4321-8765-123456789abc"
        # Legacy writer: this pins the SHAPE STAMP, not the Gate-0B publication
        # path, and the legacy branch is the one reachable without installing a
        # claim-publication root.
        env["HAPAX_GATE0B_CLAIM_PUBLICATION_OFF"] = "1"
        env.update(env_extra)
        subprocess.run(
            ["bash", str(cc_claim or REPO_ROOT / "scripts" / "cc-claim"), task_id],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        return (root / "active" / f"{task_id}.md").read_text(encoding="utf-8")

    def test_claim_stamps_the_shape_into_the_session_log(self, tmp_path: Path) -> None:
        note = self._claim(
            tmp_path / "home",
            "task-shape",
            HAPAX_AGENT_INTERFACE="claude",
            HAPAX_CAPABILITY_MODEL="claude-opus-5",
            HAPAX_CAPABILITY_ROUTE="claude.headless.opus",
        )
        assert "shape=(" in note, f"cc-claim recorded no capability shape\n{note}"
        assert "model_family=claude-opus-5" in note
        assert "harness=claude" in note
        assert "route=claude.headless.opus" in note

    def test_shape_is_appended_after_the_pinned_session_substring(self, tmp_path: Path) -> None:
        """`(cc-claim, session=…)` is a format other readers match on."""
        note = self._claim(tmp_path / "home", "task-order", HAPAX_AGENT_INTERFACE="claude")
        assert "claimed (cc-claim, session=12345678-1234-4321-8765-123456789abc)" in note

    def test_unresolvable_scaffold_revision_is_omitted_not_faked(self, tmp_path: Path) -> None:
        """_scaffold_revision's failure path: no git answer means NOT RECORDED.

        It shells `git -C <repo> rev-parse --short HEAD`. When that cannot answer —
        no git on PATH, not a repository, a permission error — the field must be
        absent rather than carry a placeholder, because a fabricated revision in a
        condition vector is worse than a missing one.
        """
        import shutil

        fakebin = tmp_path / "nogit"
        fakebin.mkdir()
        broken = fakebin / "git"
        broken.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
        broken.chmod(0o755)
        real_path = shutil.which("bash")
        assert real_path is not None

        note = self._claim(
            tmp_path / "home",
            "task-noscaffold",
            HAPAX_AGENT_INTERFACE="claude",
            PATH=f"{fakebin}:{os.environ.get('PATH', '')}",
        )
        assert "harness=claude" in note, f"the rest of the shape must still record\n{note}"
        assert "scaffold_revision" not in note, "an unresolvable revision was recorded anyway"

    def test_git_returning_nothing_also_omits_the_revision(self, tmp_path: Path) -> None:
        """_scaffold_revision's empty-stdout branch — the third of its three.

        The sibling test covers a git that exits non-zero. This covers one that
        SUCCEEDS and prints nothing, which is a different branch reaching the same
        `return None`. Both must leave the claim written with no `shape=` revision
        rather than an empty or placeholder one.

        The remaining branch (OSError — git absent entirely) is not exercised
        directly: PATH lookup skips a dangling or non-executable entry and finds
        the real git, and emptying PATH stops the shell resolving `bash` before
        cc-claim runs at all. Shadowing `git` with a file of an unexecutable FORMAT
        was tried too, on the theory that ENOEXEC would raise rather than return —
        the real revision still came back, so that is not a trigger either. The
        branch shares this one's `return None`, so the behaviour is covered even
        though the trigger is not.
        """
        shadow = tmp_path / "shadowbin"
        shadow.mkdir()
        silent = shadow / "git"
        silent.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        silent.chmod(0o755)
        note = self._claim(
            tmp_path / "home",
            "task-git-silent",
            HAPAX_AGENT_INTERFACE="claude",
            PATH=f"{shadow}:{os.environ.get('PATH', '')}",
        )
        assert "claimed (cc-claim" in note, f"the claim itself was not written\n{note}"
        assert "scaffold_revision" not in note

    def test_cc_claim_in_a_tree_that_is_not_a_git_repository(self, tmp_path: Path) -> None:
        """The branch through the REAL git, not a stub that exits non-zero.

        `_scaffold_revision` runs `git -C <repo_root> rev-parse --short HEAD`, and
        repo_root is the parent of cc-claim's own directory. Pointing a copy of the
        launcher at a tree outside any repository is the only way to reach git's
        own "not a git repository" refusal rather than a substitute for it. The
        session-log line must lose the revision and keep everything else — never
        `shape=()`, which would read as a measured emptiness.
        """
        import shutil

        fake_root = tmp_path / "not-a-repo"
        (fake_root / "scripts").mkdir(parents=True)
        (fake_root / "hooks" / "scripts").mkdir(parents=True)
        shutil.copy2(REPO_ROOT / "scripts" / "cc-claim", fake_root / "scripts" / "cc-claim")
        shutil.copy2(
            REPO_ROOT / "hooks" / "scripts" / "agent-role.sh",
            fake_root / "hooks" / "scripts" / "agent-role.sh",
        )
        shutil.copy2(
            REPO_ROOT / "hooks" / "scripts" / "cc-task-root.sh",
            fake_root / "hooks" / "scripts" / "cc-task-root.sh",
        )
        # Symlinked, not copied: the subject is where git is run, not which copy of
        # the library is imported.
        (fake_root / "shared").symlink_to(REPO_ROOT / "shared")

        note = self._claim(
            tmp_path / "home",
            "task-nonrepo",
            cc_claim=fake_root / "scripts" / "cc-claim",
            HAPAX_AGENT_INTERFACE="claude",
            HAPAX_CAPABILITY_MODEL="claude-opus-5",
        )
        assert "harness=claude" in note, f"the claim was not written at all\n{note}"
        assert "model_family=claude-opus-5" in note
        assert "scaffold_revision" not in note, (
            "a revision was recorded from a tree that is not a git repository"
        )
        assert "shape=()" not in note

    def test_nothing_recorded_stamps_no_empty_shape(self, tmp_path: Path) -> None:
        """`shape=()` would read as a measured emptiness rather than an absence."""
        note = self._claim(tmp_path / "home", "task-bare")
        assert "shape=()" not in note

    def test_a_claude_model_is_not_attributed_to_a_codex_lane(self, tmp_path: Path) -> None:
        """Dispatchers os.environ.copy(); a stale parent pin must not be recorded."""
        note = self._claim(
            tmp_path / "home",
            "task-cross",
            HAPAX_AGENT_INTERFACE="codex",
            HAPAX_CLAUDE_MODEL="claude-opus-5",
        )
        assert "harness=codex" in note
        assert "model_family" not in note, (
            "a codex lane recorded the parent claude lane's model pin"
        )

    def test_a_claude_lane_does_not_record_an_inherited_claude_pin_either(
        self, tmp_path: Path
    ) -> None:
        """The case the harness-keyed map could not see, through real cc-claim.

        Same harness on both sides, so no cross-harness rule fires; the value is
        still the parent's, and the interactive launcher that inherited it passes
        no `--model` to anything. Round 12 reported the cross-harness half of this
        (`harness=claude` beside a codex route); this is the half that survived the
        first repair.
        """
        note = self._claim(
            tmp_path / "home",
            "task-samefamily",
            HAPAX_AGENT_INTERFACE="claude",
            HAPAX_CLAUDE_MODEL="claude-opus-5",
        )
        assert "harness=claude" in note
        assert "model_family" not in note, (
            "a claude lane recorded a model pin it inherited and never executed with"
        )


class TestRendering:
    def test_renders_only_recorded_fields(self) -> None:
        rendered = format_capability_shape(
            {
                "model_family": "claude-opus-5",
                "harness": None,
                "route": "r",
                "scaffold_revision": None,
            }
        )
        assert rendered == "model_family=claude-opus-5, route=r"

    def test_nothing_known_renders_empty(self) -> None:
        """So a caller can append unconditionally without recording an absence.

        `shape=()` in a session log would read as "the shape was measured and was
        empty", which is a different claim from "nothing recorded it".
        """
        assert format_capability_shape(capability_shape_from_env({})) == ""
