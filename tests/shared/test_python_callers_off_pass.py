"""The Python secret callers read the FileStore through `shared.secrets`, never pass.

Operator ruling 2026-09-16: pass and gopass are not used to manage secrets going forward.
Assertions are on INVOCATIONS against comment- and docstring-stripped source — including the
argv form `["pass", "show", name]`, which a search for the string `"pass show"` misses
entirely, one comma away from the same call.

`shared/stream_mode.py` is deliberately NOT in scope here: its DENY_PATH_PREFIXES entry names
the password store so the path never renders on a stream surface, and uninstalling pass does
not delete that directory. It has its own pin below.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import code_without_prose

REPO_ROOT = Path(__file__).resolve().parents[2]

CALLERS = (
    "shared/tavily_client.py",
    "shared/config.py",
    "agents/_config.py",
    "agents/introspect.py",
    "agents/mail_monitor/oauth.py",
    "agents/mail_monitor/pubsub_bootstrap.py",
    "agents/mail_monitor/watch_renewal.py",
    "agents/mail_monitor/webhook_gmail.py",
    "agents/payment_processors/secrets.py",
    "agents/payment_processors/lightning_receiver.py",
    "agents/payment_processors/liberapay_receiver.py",
    "agents/payment_processors/usdc_receiver.py",
    "agents/publication_bus/__main__.py",
    "agents/publication_bus/wire_status.py",
    "agents/publication_bus/bluesky_publisher.py",
    "agents/publication_bus/internet_archive_publisher.py",
    "agents/publication_bus/osf_prereg_publisher.py",
    "agents/publication_bus/philarchive_publisher.py",
    "agents/attribution/crossref_depositor.py",
    "agents/hapax_daimonion/tools.py",
    "agents/studio_compositor/scene_classifier.py",
    "agents/scout.py",
    "agents/demo_pipeline/voice.py",
    "agents/leverage_itch_bundler/__init__.py",
    "agents/leverage_itch_bundler/__main__.py",
    "agents/publication_bus/refusal_brief_daemon.py",
    "agents/publication_bus/community_submitter.py",
    "agents/publication_bus/refusal_brief_publisher.py",
    "agents/audio_processor.py",
    "agents/langfuse_sync.py",
    "agents/studio_compositor/structural_director.py",
    # agents/_google_auth.py was retired by #4625; its callers use shared/google_auth.py.
    "shared/google_auth.py",
    "scripts/mint-google-token.py",
    "agents/health_monitor/checks/credentials.py",
    "agents/health_monitor/checks/secrets.py",
    "agents/health_monitor/checks/auth.py",
    "agents/health_monitor/constants.py",
    "agents/hapax_cred_monitor/monitor.py",
    "agents/hapax_cred_monitor/registry.py",
    "agents/hapax_cred_monitor/unblocker_report.py",
    "agents/hapax_cred_monitor/__main__.py",
)

FORBIDDEN = (
    "pass show",
    "pass ls",
    "pass insert",
    "gopass",
    "PassStore",
    '"pass"',
    "'pass'",
    "PASSWORD_STORE_DIR",
    "password-store",
)


@pytest.mark.parametrize("relative", CALLERS)
def test_no_pass_invocation_or_store_path_remains(relative: str) -> None:
    code = code_without_prose((REPO_ROOT / relative).read_text(encoding="utf-8"))
    for forbidden in FORBIDDEN:
        assert forbidden not in code, f"{relative}: {forbidden}"


class TestTavilyResolution:
    def test_env_still_wins(self) -> None:
        from shared.tavily_client import load_tavily_api_key

        # Synthetic values only; the pre-push scanner's "Secret Keyword" rule fires on any
        # API_KEY-shaped name bound to a literal.
        assert (
            load_tavily_api_key({"TAVILY_API_KEY": "env-token"})  # pragma: allowlist secret
            == "env-token"
        )

    def test_it_falls_back_to_the_filestore(self, monkeypatch) -> None:
        import shared.tavily_client as tavily

        seen: list[str] = []

        def fake_get_secret(name, *, env=None, required=True):
            seen.append(name)
            return "store-token" if name == "tavily/api-key" else None

        monkeypatch.setattr(tavily, "get_secret", fake_get_secret)
        assert tavily.load_tavily_api_key({}) == "store-token"
        assert seen[0] == "tavily/api-key"

    def test_it_tries_every_declared_name(self, monkeypatch) -> None:
        import shared.tavily_client as tavily

        seen: list[str] = []

        def fake_get_secret(name, *, env=None, required=True):
            seen.append(name)
            return "second" if name == "api/tavily" else None

        monkeypatch.setattr(tavily, "get_secret", fake_get_secret)
        assert tavily.load_tavily_api_key({}) == "second"
        assert seen == list(tavily.SECRET_NAMES)

    def test_a_missing_key_is_an_empty_string_not_an_exception(self, monkeypatch) -> None:
        """The existing contract: callers branch on falsiness, they do not catch."""
        import shared.tavily_client as tavily

        monkeypatch.setattr(tavily, "get_secret", lambda name, *, env=None, required=True: None)
        assert tavily.load_tavily_api_key({}) == ""

    def test_a_tampered_blob_is_not_silently_an_empty_key(self, monkeypatch) -> None:
        """Absence returns ""; TAMPERING must not. A corrupt blob presented as "no key
        configured" sends the operator to put a secret that is already there, over a blob
        whose history nobody has audited."""
        import shared.secrets as secrets
        import shared.tavily_client as tavily

        def raiser(name, *, env=None, required=True):
            raise secrets.SecretIntegrityFailed(name)

        monkeypatch.setattr(tavily, "get_secret", raiser)
        with pytest.raises(secrets.SecretIntegrityFailed):
            tavily.load_tavily_api_key({})


class TestStreamModeDenyListSurvives:
    """The control the coordinator exempted, pinned so a later cleanup cannot quietly take it.

    Uninstalling pass does not delete `~/.password-store`; a leftover store is still secret
    material and must still never render on a stream-visible surface.
    """

    def test_the_password_store_is_still_denied(self) -> None:
        from shared.stream_mode import DENY_PATH_PREFIXES, is_path_stream_safe

        assert any(".password-store" in prefix for prefix in DENY_PATH_PREFIXES)
        assert is_path_stream_safe(Path.home() / ".password-store") is False
        assert is_path_stream_safe(Path.home() / ".password-store" / "anything") is False

    def test_the_sibling_secret_paths_are_still_denied(self) -> None:
        from shared.stream_mode import is_path_stream_safe

        assert is_path_stream_safe(Path.home() / ".gnupg") is False
        assert is_path_stream_safe(Path.home() / ".ssh") is False
        assert is_path_stream_safe("/run/user/1000/hapax-secrets.env") is False
