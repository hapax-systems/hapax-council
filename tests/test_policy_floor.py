"""Tests for the daemon-independent embedded enforcement floor (Phase 3a).

The floor is the safety-critical fallback the bash shim runs when the kernel is
down (NEW-CATCH-2): it MUST fail-closed on every irreversible-harm class and MUST
NEVER raise. Coordination reform Phase 3a.
"""

import json

import pytest

from shared.policy_decide import ToolCall, policy_decide
from shared.policy_decision import FailMode, Verdict
from shared.policy_floor import evaluate_floor, irreversible_gate, main


class TestIrreversibleHarmFailsClosed:
    @pytest.mark.parametrize(
        "tool_name,command,file_path",
        [
            ("Bash", "gh pr merge 3761", ""),
            ("mcp__github__merge_pull_request", "", ""),
            ("Bash", "gh api repos/o/r/pulls/3761/merge -X PUT", ""),
        ],
    )
    def test_merge_blocks(self, tool_name, command, file_path):
        d = evaluate_floor(tool_name, command=command, file_path=file_path)
        assert d.blocked and d.fail_mode is FailMode.FAIL_CLOSED
        assert d.gate == "floor:merge"

    @pytest.mark.parametrize(
        "tool_name,command",
        [
            ("Bash", "git push origin main"),
            ("Bash", "gh pr create --base main"),
            ("mcp__github__create_pull_request", ""),
            ("mcp__github__push_files", ""),
        ],
    )
    def test_release_blocks(self, tool_name, command):
        d = evaluate_floor(tool_name, command=command)
        assert d.blocked and d.fail_mode is FailMode.FAIL_CLOSED
        assert d.gate == "floor:release"

    @pytest.mark.parametrize(
        "file_path",
        ["axioms/registry.yaml", "shared/governance/consent.py", "/abs/repo/axioms/x.py"],
    )
    def test_axiom_path_blocks(self, file_path):
        d = evaluate_floor("Edit", file_path=file_path)
        assert d.blocked and d.fail_mode is FailMode.FAIL_CLOSED
        assert d.gate == "floor:axiom"

    def test_axiom_via_bash_blocks(self):
        d = evaluate_floor("Bash", command="sed -i s/a/b/ axioms/registry.yaml")
        # sed is not merge/release; the axiom path token trips the axiom floor.
        assert d.blocked and d.gate == "floor:axiom"

    def test_egress_path_blocks(self):
        d = evaluate_floor("Write", file_path="config/publication-hardening/known-entities.yaml")
        assert d.blocked and d.gate == "floor:egress"

    def test_egress_command_blocks(self):
        d = evaluate_floor("Bash", command="hapax-publish --surface mastodon")
        assert d.blocked and d.gate == "floor:egress"

    def test_side_effecting_app_connector_blocks(self):
        d = evaluate_floor("mcp__codex_apps__gmail___send_draft")
        assert d.blocked and d.fail_mode is FailMode.FAIL_CLOSED
        assert d.gate == "floor:connector"


class TestReversibleFailsOpenWithLedger:
    @pytest.mark.parametrize(
        "tool_name,command,file_path",
        [
            ("Edit", "", "/tmp/x"),
            ("Edit", "", "shared/config.py"),
            ("Bash", "pytest tests/ -q", ""),
            ("Bash", "git commit -m wip", ""),
            ("Write", "", "agents/foo.py"),
            ("mcp__context7__query-docs", "", ""),
        ],
    )
    def test_reversible_allows_with_ledger(self, tool_name, command, file_path):
        d = evaluate_floor(tool_name, command=command, file_path=file_path)
        assert d.allowed and d.fail_mode is FailMode.FAIL_OPEN_WITH_LEDGER
        assert d.gate == "floor:reversible"


class TestRobustness:
    @pytest.mark.parametrize(
        "command",
        ["", "   ", "git push 'unterminated", "\x00\x01", "gh", "&&&", "a" * 5000],
    )
    def test_never_raises_on_hostile_input(self, command):
        d = evaluate_floor("Bash", command=command)
        assert d.verdict in (Verdict.ALLOW, Verdict.BLOCK)

    def test_decision_carries_version_stamp(self):
        d = evaluate_floor("Edit", file_path="/tmp/x")
        assert d.policy_version  # non-empty version stamp for bisection

    def test_merge_takes_precedence_over_reversible(self):
        # A command that contains both a merge head and other tokens still blocks.
        d = evaluate_floor("Bash", command="gh pr merge 3761 --squash")
        assert d.blocked


class TestCliEntrypoint:
    """The shim's daemon-independent interface: JSON out + exit 0 (allow) / 2 (block)."""

    def test_cli_reversible_exits_0(self, capsys):
        rc = main(["Edit", "--file", "/tmp/x"])
        out = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert out["verdict"] == "allow"
        assert out["fail_mode"] == "fail_open_with_ledger"

    def test_cli_merge_exits_2(self, capsys):
        rc = main(["Bash", "--command", "gh pr merge 1"])
        out = json.loads(capsys.readouterr().out)
        assert rc == 2
        assert out["verdict"] == "block"
        assert out["gate"] == "floor:merge"
        assert out["policy_version"]

    def test_cli_axiom_edit_exits_2(self, capsys):
        rc = main(["Edit", "--file", "axioms/registry.yaml"])
        json.loads(capsys.readouterr().out)
        assert rc == 2


# =============================================================================
# Reform fix — floor false-negative closure (findings #5-#11). The Phase-3a floor
# classified only the command HEAD of the FIRST simple command and matched egress
# by command-name only — so a wrapped, chained, or module-target invocation slid
# straight past it with the kernel down. Each test below is a concrete bypass.
# =============================================================================


class TestWrapperStripping:
    """(a) Leading wrappers (env VAR=, env/sudo/time/nice/xargs/command, ./path)
    and `bash -c`/`sh -c` indirection must not hide an irreversible head."""

    @pytest.mark.parametrize(
        "command,gate",
        [
            ("env PUBLISH=1 hapax-publish --surface mastodon", "floor:egress"),
            ("env hapax-publish --surface x", "floor:egress"),
            ("FOO=1 BAR=2 hapax-publish", "floor:egress"),
            ("sudo gh pr merge 3761 --squash", "floor:merge"),
            ("nice -n 19 hapax-publish", "floor:egress"),
            ("time hapax-publish", "floor:egress"),
            ("nohup hapax-publish &", "floor:egress"),
            ("command hapax-publish", "floor:egress"),
            ("timeout 30 hapax-publish", "floor:egress"),
            ("./hapax-publish --surface bluesky", "floor:egress"),
            ("bash -c 'gh pr merge 3761'", "floor:merge"),
            ('sh -c "hapax-publish --surface x"', "floor:egress"),
            ("bash -lc 'git push origin main'", "floor:release"),
        ],
    )
    def test_wrapped_irreversible_blocks(self, command, gate):
        d = evaluate_floor("Bash", command=command)
        assert d.blocked and d.fail_mode is FailMode.FAIL_CLOSED
        assert d.gate == gate

    @pytest.mark.parametrize(
        "command",
        ["env FOO=1 pytest tests/ -q", "sudo systemctl status logos-api", "nice -n 5 ruff check ."],
    )
    def test_wrapped_reversible_still_allows(self, command):
        # Stripping wrappers must not over-block reversible work.
        d = evaluate_floor("Bash", command=command)
        assert d.allowed and d.gate == "floor:reversible"


class TestCompoundCommandSegments:
    """(b) EVERY simple command in a compound (split on ; && || |) is classified;
    one irreversible segment blocks the whole line."""

    @pytest.mark.parametrize(
        "command,gate",
        [
            ("echo ok && gh pr merge 3761", "floor:merge"),
            ("true; hapax-publish --surface x", "floor:egress"),
            ("make build && git push origin main", "floor:release"),
            ("cat note.md | gh pr create --base main", "floor:release"),
            ("false || git push --force origin feature", "floor:release"),
            ("cd repo && env P=1 hapax-publish", "floor:egress"),
            ("git status && echo done; gh pr merge 1", "floor:merge"),
        ],
    )
    def test_irreversible_segment_blocks(self, command, gate):
        d = evaluate_floor("Bash", command=command)
        assert d.blocked and d.gate == gate

    def test_all_reversible_segments_allow(self):
        d = evaluate_floor("Bash", command="git status -sb && pytest -q; echo done | tee /tmp/x")
        assert d.allowed and d.gate == "floor:reversible"

    def test_operator_inside_quotes_is_not_a_segment_boundary(self):
        # The && lives inside the -c script; splitting it naively would mangle it.
        d = evaluate_floor("Bash", command="bash -c 'echo a && gh pr merge 9'")
        assert d.blocked and d.gate == "floor:merge"

    @pytest.mark.parametrize(
        "command,gate",
        [
            ("gh pr \\\n  merge 9", "floor:merge"),
            ("git push --force \\\n  origin feature", "floor:release"),
        ],
    )
    def test_line_continuation_does_not_evade(self, command, gate):
        # A backslash-newline continuation must not split one simple command into
        # two innocuous-looking halves.
        d = evaluate_floor("Bash", command=command)
        assert d.blocked and d.gate == gate


class TestEgressByTarget:
    """(c) Egress is classified by the executed module/script target, not just a
    command name — running a publisher IS egress however it is spelled."""

    @pytest.mark.parametrize(
        "command",
        [
            "python -m agents.publication_bus",
            "python -magents.publication_bus",
            "python3 -m agents.publication_bus.mastodon_publisher",
            "python -m agents.marketing.refusal_annex_publisher",
            "python -m agents.publish_orchestrator",
            "python scripts/publish-hn-blog-post.py",
            "python3 scripts/publish_vault_artifact.py",
            "./scripts/publish-constitutional-blog-post.py",
            "python agents/marketing/refusal_annex_publisher.py",
            "curl -X POST https://mastodon.social/api/v1/statuses -d status=hi",
            "curl --data @post.json https://bsky.social/xrpc/com.atproto.repo.createRecord",
            "wget --post-data=status=hi https://example.social/api",
        ],
    )
    def test_egress_target_blocks(self, command):
        d = evaluate_floor("Bash", command=command)
        assert d.blocked and d.fail_mode is FailMode.FAIL_CLOSED
        assert d.gate == "floor:egress"

    @pytest.mark.parametrize(
        "command",
        [
            "python -m pytest tests/",
            "python scripts/health_check.py",
            "python -m agents.ingest --bulk-only",
            "curl https://localhost:8051/health",
            "curl -s https://localhost:8051/docs -o /tmp/docs.html",
            "git add agents/publication_bus/mastodon_publisher.py",
            "cat agents/publication_bus/mastodon_publisher.py",
        ],
    )
    def test_non_egress_commands_allow(self, command):
        # Referencing or editing a publisher's source is reversible; only EXECUTING
        # the publisher (or a data-writing curl) is irreversible egress.
        d = evaluate_floor("Bash", command=command)
        assert d.allowed and d.gate == "floor:reversible"


class TestMergeReleaseCoverage:
    """(d) MERGE/RELEASE additions: direct-commit MCP tools, force/tag/->main
    pushes, and `gh release create`."""

    @pytest.mark.parametrize(
        "tool_name",
        ["mcp__github__create_or_update_file", "mcp__github__delete_file"],
    )
    def test_direct_commit_mcp_tools_block_release(self, tool_name):
        d = evaluate_floor(tool_name)
        assert d.blocked and d.gate == "floor:release"

    @pytest.mark.parametrize(
        "command",
        [
            "git push --force origin feature",
            "git push -f origin feature",
            "git push --force-with-lease origin feature",
            "git push --tags",
            "git push --follow-tags origin feature",
            "git push origin v1.2.3",
            "git push origin refs/tags/v2",
            "git push origin HEAD:main",
            "git push origin feature:refs/heads/main",
            "git push origin feature:master",
            "gh release create v1.0.0 --notes x",
            "gh release create v2 dist/file.whl",
        ],
    )
    def test_dangerous_push_and_release_block(self, command):
        d = evaluate_floor("Bash", command=command)
        assert d.blocked and d.gate == "floor:release"

    @pytest.mark.parametrize(
        "command",
        ["git push origin feature", "git push -u origin my-branch", "git push"],
    )
    def test_plain_feature_push_allows(self, command):
        # A normal feature-branch push is reversible (the branch can be deleted);
        # only protected-ref / force / tag pushes are irreversible.
        d = evaluate_floor("Bash", command=command)
        assert d.allowed and d.gate == "floor:reversible"


class TestAxiomDefenseInDepth:
    """(e) Defense-in-depth governance surfaces: CODEOWNERS, CLAUDE.md, pipewire."""

    @pytest.mark.parametrize(
        "file_path",
        [
            "CODEOWNERS",
            ".github/CODEOWNERS",
            "CLAUDE.md",
            "agents/CLAUDE.md",
            "config/pipewire/voice-fx-warm.conf",
        ],
    )
    def test_governance_paths_block_axiom(self, file_path):
        d = evaluate_floor("Edit", file_path=file_path)
        assert d.blocked and d.gate == "floor:axiom"

    def test_pipewire_user_config_blocks_axiom(self):
        d = evaluate_floor("Write", file_path="~/.config/pipewire/pipewire.conf.d/x.conf")
        assert d.blocked and d.gate == "floor:axiom"

    def test_axiom_via_bash_path_token_blocks(self):
        d = evaluate_floor("Bash", command="sed -i s/a/b/ .github/CODEOWNERS")
        assert d.blocked and d.gate == "floor:axiom"

    @pytest.mark.parametrize("file_path", ["docs/foo.md", "shared/config.py", "agents/foo.py"])
    def test_ordinary_source_and_docs_still_reversible(self, file_path):
        d = evaluate_floor("Edit", file_path=file_path)
        assert d.allowed and d.gate == "floor:reversible"


class TestIrreversibleGateContract:
    """``irreversible_gate`` is the single classifier shared by the floor and the
    kernel-up mirror — lock its public contract."""

    @pytest.mark.parametrize(
        "tool_name,command,file_path,expected",
        [
            ("Bash", "gh pr merge 1", "", "floor:merge"),
            ("Bash", "env P=1 hapax-publish", "", "floor:egress"),
            ("Bash", "true && git push --force origin x", "", "floor:release"),
            ("mcp__github__delete_file", "", "", "floor:release"),
            ("Edit", "", "CODEOWNERS", "floor:axiom"),
            ("Bash", "pytest tests/ -q", "", None),
            ("Edit", "", "shared/config.py", None),
        ],
    )
    def test_gate_string_or_none(self, tool_name, command, file_path, expected):
        assert irreversible_gate(tool_name, command=command, file_path=file_path) == expected


class TestPolicyDecideMirror:
    """The kernel-up/kernel-down mirror: ``policy_decide`` must route the same
    irreversible commands the floor blocks through ``evaluate_floor`` instead of
    short-circuiting them as 'non-mutating'. Pre-fix, ``_is_gated_mutation`` missed
    module-target egress, so an egress command slipped past the floor entirely."""

    @staticmethod
    def _bash(cmd: str) -> ToolCall:
        return ToolCall(tool_name="Bash", command=cmd)

    def test_kernel_down_blocks_module_egress(self):
        d = policy_decide(
            self._bash("python -m agents.publication_bus"), None, "beta", kernel_up=False
        )
        assert d.blocked and d.gate == "floor:egress"

    def test_kernel_down_blocks_force_push(self):
        d = policy_decide(
            self._bash("git push --force origin feature"), None, "beta", kernel_up=False
        )
        assert d.blocked and d.gate == "floor:release"

    def test_kernel_down_blocks_wrapped_egress(self):
        d = policy_decide(
            self._bash("env P=1 hapax-publish --surface x"), None, "beta", kernel_up=False
        )
        assert d.blocked and d.gate == "floor:egress"

    def test_module_egress_is_gated_not_passthrough(self):
        # kernel UP, no role: an egress command is now GATED, so it cannot slip
        # through as 'non-mutating' (pre-fix it returned gate=='non-mutating').
        d = policy_decide(self._bash("python -m agents.publication_bus"), None, None)
        assert d.gate != "non-mutating"

    def test_reversible_bash_still_passthrough(self):
        d = policy_decide(self._bash("pytest tests/ -q"), None, "beta")
        assert d.allowed and d.gate == "non-mutating"

    def test_read_only_git_still_passthrough(self):
        d = policy_decide(self._bash("git status -sb"), None, "beta")
        assert d.allowed and d.gate == "non-mutating"
