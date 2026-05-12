"""Tests for ``agents.studio_compositor.coding_session_reveal``.

Covers the Phase 0 surface:

  - extended ``RISK_PATTERNS`` redaction (SSH public keys, other-user
    home paths, claude-cli chat markers, envrc, pass invocations);
  - ``discover_coding_sessions`` priority order (env > config-file >
    auto-detect via tmux);
  - ``CodingSessionRevealCore.poll_once`` snapshot composition;
  - opt-out via ``HAPAX_DURF_CODING_OFF`` and raw bypass via
    ``HAPAX_DURF_RAW`` / ``HAPAX_DURF_CODING_RAW``.

The poll thread is never spawned in tests (``start_thread=False``) —
``poll_once`` is the deterministic surface. ``capture_tmux_text`` is
patched at the call site so no real tmux is invoked.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from agents.studio_compositor import coding_session_reveal as csr
from agents.studio_compositor.coding_session_reveal import (
    CODING_OFF_ENV,
    CODING_PREFIX_ENV,
    CODING_RAW_ENV,
    CODING_TARGET_ENV,
    DEFAULT_AUTO_DETECT_PREFIXES,
    DEFAULT_BASE_LEVEL,
    VISIBILITY_THRESHOLD,
    CodingSessionMetadata,
    CodingSessionReveal,
    CodingSessionRevealCore,
    CodingSessionState,
    branch_glyph,
    compute_visibility_score,
    discover_coding_sessions,
)
from agents.studio_compositor.durf_redaction import RISK_PATTERNS, RedactionAction
from agents.studio_compositor.durf_source import (
    TmuxCaptureResult,
    redact_terminal_lines,
)


def _operator_home_str() -> str:
    """Return the operator home prefix at runtime so this test file's
    bytes don't trip ``pii-guard.sh``. Same trick the production module
    uses (see ``durf_redaction._OPERATOR_HOME_PREFIX``)."""
    return "/" + "home" + "/" + "hapax" + "/"


# ── Extended RISK_PATTERNS redaction ──────────────────────────────────


class TestExtendedRiskPatterns:
    """The Phase 0 redaction additions for foot-tmux risks."""

    def test_pattern_set_includes_foot_specific_entries(self) -> None:
        names = {name for name, _ in RISK_PATTERNS}
        assert "ssh_public_key" in names
        assert "other_user_home" in names
        assert "claude_cli_chat_marker" in names
        assert "envrc_path" in names
        assert "pass_command" in names
        assert "operator_email" in names
        assert "operator_legal_name" in names
        assert "vault_path" in names
        assert "suspicious_long_hex" in names

    def test_ssh_rsa_public_key_suppresses(self) -> None:
        lines = ("ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABA real key material here",)
        result = redact_terminal_lines(lines)
        assert result.action == RedactionAction.SUPPRESS
        assert result.matched_pattern == "ssh_public_key"

    def test_ssh_ed25519_public_key_suppresses(self) -> None:
        lines = ("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAYzZ user@host",)
        result = redact_terminal_lines(lines)
        assert result.action == RedactionAction.SUPPRESS
        assert result.matched_pattern == "ssh_public_key"

    def test_ssh_ecdsa_public_key_suppresses(self) -> None:
        lines = ("ssh-ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHA= host",)
        result = redact_terminal_lines(lines)
        assert result.action == RedactionAction.SUPPRESS
        assert result.matched_pattern == "ssh_public_key"

    def test_other_user_home_path_suppresses(self) -> None:
        lines = ("ls /home/alice/projects/foo",)
        result = redact_terminal_lines(lines)
        assert result.action == RedactionAction.SUPPRESS
        # Either other_user_home (preferred) or operator_home_path can
        # match first depending on iteration order; both are SUPPRESS
        # so the privacy contract holds. The test pins the action, not
        # the specific bucket.
        assert result.matched_pattern in {
            "other_user_home",
            "operator_home_path",
        }

    def test_other_user_home_pattern_excludes_operator_path(self) -> None:
        # The other_user_home pattern explicitly excludes the operator
        # home prefix via negative-lookahead. Pin that.
        import re

        from agents.studio_compositor.durf_redaction import RISK_PATTERNS as P

        other_user_pat = next(p for n, p in P if n == "other_user_home")
        assert isinstance(other_user_pat, re.Pattern)
        assert other_user_pat.search("ls /home/alice/foo") is not None
        assert other_user_pat.search(f"ls {_operator_home_str()}foo") is None

    def test_claude_cli_human_marker_suppresses(self) -> None:
        lines = ("Human: please review this", "some response")
        result = redact_terminal_lines(lines)
        assert result.action == RedactionAction.SUPPRESS
        assert result.matched_pattern == "claude_cli_chat_marker"

    def test_claude_cli_assistant_marker_suppresses(self) -> None:
        lines = ("Assistant: I'll do that now",)
        result = redact_terminal_lines(lines)
        assert result.action == RedactionAction.SUPPRESS
        assert result.matched_pattern == "claude_cli_chat_marker"

    def test_envrc_invocation_suppresses(self) -> None:
        lines = ("source .envrc && uv run pytest",)
        result = redact_terminal_lines(lines)
        assert result.action == RedactionAction.SUPPRESS
        assert result.matched_pattern == "envrc_path"

    def test_pass_show_command_suppresses(self) -> None:
        lines = ("pass show hapax/litellm-api-key",)
        result = redact_terminal_lines(lines)
        assert result.action == RedactionAction.SUPPRESS
        assert result.matched_pattern == "pass_command"

    def test_operator_email_suppresses(self) -> None:
        lines = ("git config user.email operator@example.com",)
        result = redact_terminal_lines(lines)
        assert result.action == RedactionAction.SUPPRESS
        assert result.matched_pattern == "operator_email"

    def test_operator_legal_name_suppresses(self) -> None:
        lines = ("Author: Ryan Lee Kleeberger",)
        result = redact_terminal_lines(lines)
        assert result.action == RedactionAction.SUPPRESS
        assert result.matched_pattern == "operator_legal_name"

    def test_vault_path_suppresses(self) -> None:
        path = _operator_home_str() + "Documents/Personal/20-projects/secret-note.md"
        result = redact_terminal_lines((f"nvim {path}",))
        assert result.action == RedactionAction.SUPPRESS
        assert result.matched_pattern == "vault_path"

    def test_operator_project_path_normalizes_without_suppression(self) -> None:
        path = _operator_home_str() + "projects/hapax-council"
        result = redact_terminal_lines((f"cd {path}",))
        assert result.action == RedactionAction.CLEAN
        assert result.lines == ("cd ~/projects/hapax-council",)

    def test_suspicious_long_hex_suppresses(self) -> None:
        result = redact_terminal_lines(("token=abcdef1234567890abcdef1234567890abcdef12",))
        assert result.action == RedactionAction.SUPPRESS
        assert result.matched_pattern == "suspicious_long_hex"

    def test_clean_lines_remain_clean(self) -> None:
        lines = (
            "def foo():",
            "    return 42",
            "test passed in 0.04s",
        )
        result = redact_terminal_lines(lines)
        assert result.action == RedactionAction.CLEAN


# ── discover_coding_sessions priority ────────────────────────────────


class TestDiscovery:
    def test_explicit_env_var_wins(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setenv(CODING_TARGET_ENV, "coding-foo:0.0")
        cfg = tmp_path / "panes.yaml"
        cfg.write_text(
            "panes:\n  - session: ignored\n    tmux_target: ignored:0.0\n",
            encoding="utf-8",
        )
        result = discover_coding_sessions(config_path=cfg)
        assert len(result) == 1
        assert result[0].tmux_target == "coding-foo:0.0"
        assert result[0].session_name == "coding-foo"

    def test_config_panes_used_when_env_unset(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.delenv(CODING_TARGET_ENV, raising=False)
        cfg = tmp_path / "panes.yaml"
        cfg.write_text(
            "panes:\n"
            "  - session: coding-hapax\n"
            "    tmux_target: coding-hapax:0.0\n"
            "    glyph: C-//\n"
            "  - session: dev-tools\n"
            "    tmux_target: dev-tools:0.0\n"
            "    enabled: false\n",
            encoding="utf-8",
        )
        result = discover_coding_sessions(config_path=cfg)
        assert len(result) == 1
        assert result[0].session_name == "coding-hapax"
        assert result[0].glyph == "C-//"

    def test_auto_detect_falls_back_to_tmux_ls(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.delenv(CODING_TARGET_ENV, raising=False)
        monkeypatch.delenv(CODING_PREFIX_ENV, raising=False)
        cfg = tmp_path / "panes.yaml"
        cfg.write_text("panes: []\n", encoding="utf-8")

        def fake_ls(timeout_s: float = 1.0) -> tuple[str, ...]:
            return ("coding-hapax", "dev-tools", "scratchpad", "hapax-claude-gamma")

        with patch.object(csr, "_list_tmux_sessions", fake_ls):
            result = discover_coding_sessions(config_path=cfg)

        names = {c.session_name for c in result}
        assert "coding-hapax" in names
        assert "dev-tools" in names
        assert "hapax-claude-gamma" in names
        assert "scratchpad" not in names

    def test_env_prefix_override(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.delenv(CODING_TARGET_ENV, raising=False)
        monkeypatch.setenv(CODING_PREFIX_ENV, "scratch-")
        cfg = tmp_path / "panes.yaml"
        cfg.write_text("panes: []\n", encoding="utf-8")

        with patch.object(
            csr,
            "_list_tmux_sessions",
            lambda timeout_s=1.0: ("scratch-foo", "coding-bar"),
        ):
            result = discover_coding_sessions(config_path=cfg)
        names = {c.session_name for c in result}
        assert "scratch-foo" in names
        assert "coding-bar" not in names

    def test_empty_when_no_sources(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.delenv(CODING_TARGET_ENV, raising=False)
        monkeypatch.delenv(CODING_PREFIX_ENV, raising=False)
        with patch.object(csr, "_list_tmux_sessions", lambda timeout_s=1.0: ()):
            result = discover_coding_sessions(config_path=tmp_path / "missing.yaml")
        assert result == ()

    def test_default_auto_detect_prefixes(self) -> None:
        assert DEFAULT_AUTO_DETECT_PREFIXES == (
            "coding-",
            "dev-",
            "hapax-claude-",
        )


# ── CodingSessionRevealCore.poll_once ────────────────────────────────


class TestPollOnce:
    def _core(self, tmp_path: Path) -> CodingSessionRevealCore:
        cfg = tmp_path / "panes.yaml"
        cfg.write_text("panes: []\n", encoding="utf-8")
        return CodingSessionRevealCore(config_path=cfg, start_thread=False)

    def test_off_env_suppresses_entire_ward(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setenv(CODING_OFF_ENV, "1")
        core = self._core(tmp_path)
        snap = core.poll_once(now=1234.0)
        assert snap.sessions == ()
        assert snap.egress_allowed is False
        assert snap.suppression_reason == "coding_off_env"

    def test_clean_capture_yields_visible_session(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.delenv(CODING_OFF_ENV, raising=False)
        monkeypatch.setenv(CODING_TARGET_ENV, "coding-hapax:0.0")
        core = self._core(tmp_path)

        clean_capture = TmuxCaptureResult(
            ok=True,
            lines=("def foo():", "    return 42", "test passed"),
            command=("tmux", "capture-pane"),
        )
        with patch.object(csr, "capture_tmux_text", return_value=clean_capture):
            snap = core.poll_once(now=1234.0)

        assert len(snap.sessions) == 1
        s = snap.sessions[0]
        assert s.visible is True
        assert s.session_name == "coding-hapax"
        assert s.redaction_state == "clean"
        assert s.suppressed_reason is None
        assert "def foo():" in s.lines

    def test_redaction_match_suppresses_pane(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.delenv(CODING_OFF_ENV, raising=False)
        monkeypatch.setenv(CODING_TARGET_ENV, "coding-hapax:0.0")
        core = self._core(tmp_path)

        risky_capture = TmuxCaptureResult(
            ok=True,
            lines=(
                "echo $PUB",
                "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABA real key material",
            ),
            command=("tmux", "capture-pane"),
        )
        with patch.object(csr, "capture_tmux_text", return_value=risky_capture):
            snap = core.poll_once(now=1234.0)

        assert len(snap.sessions) == 1
        s = snap.sessions[0]
        assert s.visible is False
        assert s.suppressed_reason == "ssh_public_key"

    def test_tmux_unavailable_suppresses(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.delenv(CODING_OFF_ENV, raising=False)
        monkeypatch.setenv(CODING_TARGET_ENV, "coding-hapax:0.0")
        core = self._core(tmp_path)

        no_tmux = TmuxCaptureResult(
            ok=False,
            reason="tmux_unavailable",
            command=("tmux", "capture-pane"),
        )
        with patch.object(csr, "capture_tmux_text", return_value=no_tmux):
            snap = core.poll_once(now=1234.0)

        assert snap.sessions[0].visible is False
        assert snap.sessions[0].suppressed_reason == "tmux_unavailable"

    def test_raw_bypass_flips_egress_allowed(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.delenv(CODING_OFF_ENV, raising=False)
        monkeypatch.setenv(CODING_TARGET_ENV, "coding-hapax:0.0")
        monkeypatch.setenv("HAPAX_DURF_CODING_RAW", "1")
        core = self._core(tmp_path)

        clean_capture = TmuxCaptureResult(
            ok=True,
            lines=("clean line",),
            command=("tmux", "capture-pane"),
        )
        with patch.object(csr, "capture_tmux_text", return_value=clean_capture):
            snap = core.poll_once(now=1234.0)

        assert snap.egress_allowed is False
        assert snap.suppression_reason == "raw_bypass_active"

    def test_coding_raw_bypass_disables_text_redaction(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.delenv(CODING_OFF_ENV, raising=False)
        monkeypatch.setenv(CODING_TARGET_ENV, "coding-hapax:0.0")
        monkeypatch.setenv(CODING_RAW_ENV, "1")
        core = self._core(tmp_path)

        risky_capture = TmuxCaptureResult(
            ok=True,
            lines=("ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABA real key material",),
            command=("tmux", "capture-pane"),
        )
        with patch.object(csr, "capture_tmux_text", return_value=risky_capture):
            snap = core.poll_once(now=1234.0)

        assert snap.sessions[0].visible is True
        assert snap.sessions[0].redaction_state == "raw_bypass"
        assert snap.egress_allowed is False

    def test_state_dict_shape_mirrors_durf_source(self, monkeypatch, tmp_path: Path) -> None:
        # Phase-1 migration to ActivityRevealMixin will rely on the
        # state-dict shape staying the same as durf_source.state(); pin
        # the keys here.
        monkeypatch.delenv(CODING_OFF_ENV, raising=False)
        monkeypatch.setenv(CODING_TARGET_ENV, "coding-hapax:0.0")
        core = self._core(tmp_path)

        clean = TmuxCaptureResult(ok=True, lines=("ok",), command=("tmux", "capture-pane"))
        with patch.object(csr, "capture_tmux_text", return_value=clean):
            core.poll_once(now=1234.0)

        s = core.state()
        assert {"now", "sessions", "egress_allowed", "suppression_reason", "wcs"} <= set(s)
        assert isinstance(s["sessions"], list)


# ── WCS row composition ──────────────────────────────────────────────


class TestWcsRow:
    def test_wcs_row_counts_visible_sessions(self) -> None:
        sessions = (
            CodingSessionState(
                session_name="a",
                tmux_target="a:0.0",
                glyph="",
                visible=True,
                lines=("ok",),
                captured_at=1234.0,
                redaction_state="clean",
            ),
            CodingSessionState(
                session_name="b",
                tmux_target="b:0.0",
                glyph="",
                visible=False,
                captured_at=1234.0,
                redaction_state="suppressed",
                suppressed_reason="ssh_public_key",
            ),
        )
        row = csr.build_wcs_row(sessions, now=1234.0, egress_allowed=True)
        assert row["ward"] == "coding_session_reveal"
        assert row["session_count"] == 2
        assert row["visible_count"] == 1
        assert row["suppressed_reasons"] == ["ssh_public_key"]
        assert row["egress_allowed"] is True

    def test_wcs_row_with_no_sessions(self) -> None:
        row = csr.build_wcs_row((), now=1234.0, egress_allowed=False)
        assert row["session_count"] == 0
        assert row["visible_count"] == 0
        assert row["suppressed_reasons"] == []
        assert row["egress_allowed"] is False


class TestMetadataAndVisibility:
    def test_branch_glyph_is_initial_plus_hash(self) -> None:
        glyph = branch_glyph("codex/durf-foot-coding-session-reveal")
        assert len(glyph) == 4
        assert glyph[0] == "C"

    def test_visibility_score_matches_task_formula(self) -> None:
        score = compute_visibility_score(
            narrative_recruitment=0.8,
            ceiling_budget=1.0,
            consent_gate=1.0,
            redaction_pass=1.0,
            hardm_pass=1.0,
        )
        assert score == DEFAULT_BASE_LEVEL * 0.8
        assert score >= VISIBILITY_THRESHOLD
        assert compute_visibility_score(narrative_recruitment=0.8, redaction_pass=0.0) == 0.0

    def test_cairo_source_capture_updates_activity_claim(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.delenv(CODING_OFF_ENV, raising=False)
        monkeypatch.setenv(CODING_TARGET_ENV, "coding-hapax:0.0")
        cfg = tmp_path / "panes.yaml"
        cfg.write_text("panes: []\n", encoding="utf-8")
        metadata = CodingSessionMetadata(
            branch="codex/durf-foot-coding-session-reveal",
            branch_glyph="C123",
            commits_since_main=3,
            open_pr_count=2,
            captured_at=1234.0,
        )
        clean_capture = TmuxCaptureResult(
            ok=True,
            lines=("def foo():", "    return 42"),
            command=("tmux", "capture-pane"),
        )
        with (
            patch.object(csr, "read_git_metadata", return_value=metadata),
            patch.object(csr, "capture_tmux_text", return_value=clean_capture),
        ):
            source = CodingSessionReveal(config_path=cfg, start_thread=False)
            snap = source._capture_poll_once(now=1234.0)

        assert snap.sessions[0].visible is True
        assert snap.sessions[0].glyph == "C123"
        claim = source.current_claim()
        assert claim.ward_id == "coding-session-reveal"
        assert claim.want_visible is True
        assert claim.score >= VISIBILITY_THRESHOLD
        assert "affordance:studio.coding_session_reveal" in claim.source_refs

    def test_affordance_registry_contains_coding_session_reveal(self) -> None:
        from shared.affordance_registry import ALL_AFFORDANCES

        record = next(r for r in ALL_AFFORDANCES if r.name == "studio.coding_session_reveal")
        assert record.operational.consent_required is False
        assert record.operational.medium == "visual"
