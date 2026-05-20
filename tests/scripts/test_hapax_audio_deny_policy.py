"""Tests for the WirePlumber link-time deny policy."""

from __future__ import annotations

import pathlib
import subprocess

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
POLICY_LUA = REPO_ROOT / "config" / "wireplumber" / "99-hapax-link-deny-policy.lua"
SCRIPT = REPO_ROOT / "scripts" / "hapax-audio-deny-policy"
FORBIDDEN_CONF = REPO_ROOT / "config" / "hapax" / "audio-forbidden-links.conf"


class TestPolicyScript:
    def test_script_exists_and_is_executable(self):
        assert SCRIPT.exists()
        assert SCRIPT.stat().st_mode & 0o111

    def test_script_has_strict_mode(self):
        text = SCRIPT.read_text()
        assert "set -euo pipefail" in text


class TestPolicyLua:
    def test_lua_policy_exists(self):
        assert POLICY_LUA.exists()

    def test_lua_policy_reads_env(self):
        text = POLICY_LUA.read_text()
        assert "HAPAX_AUDIO_FORBIDDEN_LINKS" in text
        assert "HAPAX_AUDIO_DENY_DRY_RUN" in text

    def test_lua_policy_has_dry_run_guard(self):
        text = POLICY_LUA.read_text()
        assert "DRY_RUN" in text
        assert "DRY-RUN" in text

    def test_lua_policy_destroys_forbidden_links(self):
        text = POLICY_LUA.read_text()
        assert "request_destroy" in text

    def test_lua_policy_loads_deny_list(self):
        text = POLICY_LUA.read_text()
        assert "load_deny_list" in text
        assert "forbidden" in text


class TestForbiddenLinksConfig:
    def test_config_exists(self):
        assert FORBIDDEN_CONF.exists()

    def test_config_has_pipe_separator(self):
        for line in FORBIDDEN_CONF.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            assert "|" in line, f"Missing pipe separator: {line}"

    def test_config_covers_private_to_l12(self):
        text = FORBIDDEN_CONF.read_text()
        assert "hapax-private-playback" in text
        assert "L-12" in text

    def test_config_covers_notification_to_l12(self):
        text = FORBIDDEN_CONF.read_text()
        assert "hapax-notification-private" in text

    def test_config_covers_tts_bypass(self):
        text = FORBIDDEN_CONF.read_text()
        assert "hapax-tts-broadcast-playback" in text
        assert "hapax-livestream-tap" in text

    def test_config_covers_pc_loudnorm_bypass(self):
        text = FORBIDDEN_CONF.read_text()
        assert "hapax-pc-loudnorm-playback" in text

    def test_config_has_minimum_rules(self):
        count = sum(
            1
            for line in FORBIDDEN_CONF.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
        assert count >= 20, f"Only {count} rules, expected >= 20"


class TestDenyPolicyStatus:
    def test_status_runs(self):
        result = subprocess.run(
            [str(SCRIPT), "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "Source: present" in result.stdout

    def test_validate_runs(self):
        result = subprocess.run(
            [str(SCRIPT), "validate"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "OK" in result.stdout
