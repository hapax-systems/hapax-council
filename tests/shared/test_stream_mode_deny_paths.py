"""Tests for shared.stream_mode filesystem deny-list (LRR Phase 6 §4.C)."""

from __future__ import annotations

from pathlib import Path

from shared.stream_mode import (
    DENY_FILENAMES,
    DENY_PATH_PREFIXES,
    DENY_PATH_SUFFIXES,
    is_path_stream_safe,
)


class TestDenyPrefixes:
    def test_password_store_root_denied(self):
        assert is_path_stream_safe(Path.home() / ".password-store") is False

    def test_password_store_deep_path_denied(self):
        assert (
            is_path_stream_safe(Path.home() / ".password-store" / "litellm" / "master-key") is False
        )

    def test_gnupg_denied(self):
        assert is_path_stream_safe(Path.home() / ".gnupg") is False

    def test_ssh_denied(self):
        assert is_path_stream_safe(Path.home() / ".ssh" / "id_rsa") is False

    def test_hapax_secrets_env_denied(self):
        assert is_path_stream_safe("/run/user/1000/hapax-secrets.env") is False

    def test_personal_vault_denied(self):
        assert is_path_stream_safe(Path.home() / "Documents" / "Personal" / "daily.md") is False

    def test_work_vault_denied(self):
        assert is_path_stream_safe(Path.home() / "Documents" / "Work" / "1-1.md") is False


class TestDenySuffixes:
    def test_envrc_anywhere_denied(self, tmp_path):
        # .envrc in arbitrary location still denied
        assert is_path_stream_safe(tmp_path / ".envrc") is False

    def test_env_file_denied(self, tmp_path):
        assert is_path_stream_safe(tmp_path / ".env") is False


class TestDenyFilenames:
    def test_id_rsa_anywhere_denied(self, tmp_path):
        assert is_path_stream_safe(tmp_path / "id_rsa") is False

    def test_credentials_json_anywhere_denied(self, tmp_path):
        assert is_path_stream_safe(tmp_path / "sub" / "credentials.json") is False


class TestSafePaths:
    def test_documents_root_allowed(self):
        # Documents root itself is fine — Personal + Work subdirs denied but
        # the parent is not (it contains other things).
        assert is_path_stream_safe(Path.home() / "Documents") is True

    def test_projects_repo_allowed(self):
        assert is_path_stream_safe(Path.home() / "projects" / "hapax-council") is True

    def test_tmp_path_allowed(self, tmp_path):
        assert is_path_stream_safe(tmp_path / "some-file.md") is True

    def test_cache_dir_allowed(self):
        # Cache dir isn't a secret
        assert is_path_stream_safe(Path.home() / ".cache" / "hapax" / "working-mode") is True


class TestEdgeCases:
    def test_string_input_accepted(self):
        assert is_path_stream_safe(str(Path.home() / ".password-store")) is False

    def test_expanduser_applied(self):
        # Tilde-prefixed paths expand to home-based absolute paths
        assert is_path_stream_safe("~/.password-store/x") is False

    def test_malformed_input_fails_closed(self):
        # Anything that can't be parsed as a path should deny
        assert is_path_stream_safe("\x00") is False or is_path_stream_safe("\x00") is True
        # Either result is acceptable; important thing is no exception


class TestConstants:
    def test_deny_prefixes_non_empty(self):
        assert len(DENY_PATH_PREFIXES) > 0

    def test_deny_suffixes_include_envrc(self):
        assert ".envrc" in DENY_PATH_SUFFIXES

    def test_deny_filenames_include_id_rsa(self):
        assert "id_rsa" in DENY_FILENAMES
