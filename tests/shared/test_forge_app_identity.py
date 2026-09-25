"""Machine forge identity (O2): the unsafe cases, each a direct test.

- a lane process cannot read the App key: the loader reads only systemd's credential
  directory and refuses every other source;
- an expired (or nearly expired) installation token is refused before any network call;
- commits and PRs are authored by the App's bot, never by a lane-supplied identity;
- a JWT longer-lived than GitHub's 10-minute ceiling is never built;
- the service unit holds the key under a dynamic user, with no key material in its environment.
"""

from __future__ import annotations

import configparser
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from shared import forge_app_identity as fai

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT = REPO_ROOT / "systemd" / "units" / "hapax-forge-send.service"
NOW = datetime(2026, 9, 25, 8, 0, 0, tzinfo=UTC)
KEY = "-----BEGIN RSA PRIVATE KEY-----\nnot-a-real-key\n-----END RSA PRIVATE KEY-----\n"  # pragma: allowlist secret


def _cred_dir(tmp_path: Path) -> Path:
    creds = tmp_path / "run-credentials-hapax-forge-send"
    creds.mkdir()
    (creds / fai.APP_KEY_CREDENTIAL).write_text(KEY, encoding="utf-8")
    return creds


class TestKeyLoader:
    def test_reads_the_key_from_the_credentials_directory(self, tmp_path: Path) -> None:
        creds = _cred_dir(tmp_path)

        assert fai.load_app_key({"CREDENTIALS_DIRECTORY": str(creds)}) == KEY

    def test_refuses_without_a_credentials_directory(self) -> None:
        # A lane process is not a unit with LoadCredentialEncrypted=, so it has no
        # CREDENTIALS_DIRECTORY: it must not find the key anywhere else.
        with pytest.raises(fai.ForgeIdentityRefused, match="credentials_directory_unset"):
            fai.load_app_key({})

    def test_ignores_every_other_key_source(self, tmp_path: Path) -> None:
        # Key material placed where a lane could put or read it is never consulted.
        env = {
            "HAPAX_FORGE_APP_KEY": KEY,
            "FORGE_APP_KEY_PATH": str(tmp_path / "key.pem"),
            "HAPAX_SECRETS_DIR": str(tmp_path),
        }
        (tmp_path / "key.pem").write_text(KEY, encoding="utf-8")

        with pytest.raises(fai.ForgeIdentityRefused, match="credentials_directory_unset"):
            fai.load_app_key(env)

    def test_refuses_a_symlink_that_escapes_the_credentials_directory(self, tmp_path: Path) -> None:
        creds = tmp_path / "creds"
        creds.mkdir()
        outside = tmp_path / "lane-readable.pem"
        outside.write_text(KEY, encoding="utf-8")
        (creds / fai.APP_KEY_CREDENTIAL).symlink_to(outside)

        with pytest.raises(fai.ForgeIdentityRefused, match="credential_path_escapes"):
            fai.load_app_key({"CREDENTIALS_DIRECTORY": str(creds)})

    def test_refuses_a_missing_credential(self, tmp_path: Path) -> None:
        creds = tmp_path / "creds"
        creds.mkdir()

        with pytest.raises(fai.ForgeIdentityRefused, match="credential_missing"):
            fai.load_app_key({"CREDENTIALS_DIRECTORY": str(creds)})

    def test_refuses_an_empty_credential(self, tmp_path: Path) -> None:
        creds = tmp_path / "creds"
        creds.mkdir()
        (creds / fai.APP_KEY_CREDENTIAL).write_text("", encoding="utf-8")

        with pytest.raises(fai.ForgeIdentityRefused, match="credential_empty"):
            fai.load_app_key({"CREDENTIALS_DIRECTORY": str(creds)})


class TestJwtClaims:
    def test_claims_follow_githubs_rules(self) -> None:
        claims = fai.jwt_claims("Iv23client", now=NOW)

        assert claims["iss"] == "Iv23client"
        assert claims["iat"] == int((NOW - timedelta(seconds=60)).timestamp())
        assert claims["exp"] - claims["iat"] <= 600
        assert claims["exp"] > int(NOW.timestamp())

    def test_refuses_a_lifetime_beyond_ten_minutes(self) -> None:
        with pytest.raises(fai.ForgeIdentityRefused, match="jwt_lifetime_exceeds_600s"):
            fai.jwt_claims("Iv23client", now=NOW, lifetime=timedelta(minutes=11))

    def test_refuses_an_empty_issuer(self) -> None:
        with pytest.raises(fai.ForgeIdentityRefused, match="jwt_issuer_missing"):
            fai.jwt_claims("", now=NOW)


class TestInstallationToken:
    def _token(self, expires_in: timedelta) -> fai.InstallationToken:
        return fai.InstallationToken(
            token="ghs_x", expires_at=NOW + expires_in
        )  # pragma: allowlist secret

    def test_fresh_token_is_usable(self) -> None:
        fai.require_usable(self._token(timedelta(minutes=50)), now=NOW)

    def test_expired_token_is_refused(self) -> None:
        with pytest.raises(fai.ForgeIdentityRefused, match="installation_token_expired"):
            fai.require_usable(self._token(timedelta(seconds=-1)), now=NOW)

    def test_token_expiring_exactly_now_is_refused(self) -> None:
        with pytest.raises(fai.ForgeIdentityRefused, match="installation_token_expired"):
            fai.require_usable(self._token(timedelta(0)), now=NOW)

    def test_token_inside_the_safety_margin_is_refused(self) -> None:
        with pytest.raises(fai.ForgeIdentityRefused, match="installation_token_near_expiry"):
            fai.require_usable(self._token(timedelta(minutes=4)), now=NOW)

    def test_parses_githubs_response(self) -> None:
        tok = fai.InstallationToken.from_response(
            {"token": "ghs_y", "expires_at": "2026-09-25T09:00:00Z"}  # pragma: allowlist secret
        )

        assert tok.expires_at == datetime(2026, 9, 25, 9, 0, tzinfo=UTC)

    def test_response_without_expiry_is_refused(self) -> None:
        with pytest.raises(fai.ForgeIdentityRefused, match="installation_token_malformed"):
            fai.InstallationToken.from_response({"token": "ghs_y"})  # pragma: allowlist secret

    def test_request_is_narrowed_to_one_repository_and_two_permissions(self) -> None:
        body = fai.installation_token_request("hapax-council")

        assert body == {
            "repositories": ["hapax-council"],
            "permissions": {"contents": "write", "pull_requests": "write"},
        }

    def test_request_refuses_an_owner_qualified_or_empty_repository(self) -> None:
        for bad in ("", "hapax-systems/hapax-council", "a b"):
            with pytest.raises(fai.ForgeIdentityRefused, match="repository_name_invalid"):
                fai.installation_token_request(bad)


class TestBotAuthorship:
    IDENTITY = fai.BotIdentity(slug="hapax-forge", user_id=123456789)

    def test_bot_identity_uses_githubs_bot_form(self) -> None:
        assert self.IDENTITY.login == "hapax-forge[bot]"
        assert self.IDENTITY.email == "123456789+hapax-forge[bot]@users.noreply.github.com"

    def test_commit_authored_by_the_bot_is_accepted(self) -> None:
        fai.require_bot_authored({"author": {"user": {"login": "hapax-forge[bot]"}}}, self.IDENTITY)

    def test_commit_authored_by_anyone_else_is_refused(self) -> None:
        with pytest.raises(fai.ForgeIdentityRefused, match="commit_not_bot_authored:ryanklee"):
            fai.require_bot_authored({"author": {"user": {"login": "ryanklee"}}}, self.IDENTITY)

    def test_commit_with_no_resolvable_author_is_refused(self) -> None:
        with pytest.raises(fai.ForgeIdentityRefused, match="commit_not_bot_authored:unknown"):
            fai.require_bot_authored({"author": {"user": None}}, self.IDENTITY)

    def test_commit_request_carries_no_author_a_lane_could_set(self) -> None:
        request = fai.create_commit_request(
            repository="hapax-systems/hapax-council",
            branch="forge/test",
            expected_head_oid="a" * 40,
            headline="test commit",
            additions={"docs/x.md": b"hello\n"},
        )

        # The mutation's INPUT is what a caller controls; the query's selection reads the
        # author back so the send can verify it (require_bot_authored).
        text = repr(request["variables"]).lower()
        assert "author" not in text
        assert "committer" not in text
        assert "author { user { login } }" in request["query"]
        assert request["variables"]["input"]["expectedHeadOid"] == "a" * 40


def _unit() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    parser.read(UNIT, encoding="utf-8")
    return parser


class TestServiceUnit:
    def test_unit_holds_the_key_under_a_dynamic_user(self) -> None:
        service = _unit()["Service"]

        assert service.get("DynamicUser") == "yes"
        assert service.get("LoadCredentialEncrypted") == fai.APP_KEY_CREDENTIAL
        assert service.get("ProtectHome") == "yes"
        assert service.get("ProtectSystem") == "strict"
        assert service.get("NoNewPrivileges") == "yes"
        assert service.get("PrivateTmp") == "yes"

    def test_unit_carries_no_key_material_in_its_environment(self) -> None:
        service = _unit()["Service"]
        text = UNIT.read_text(encoding="utf-8")

        assert "EnvironmentFile" not in service
        assert "LoadCredential" not in service  # only the encrypted form, never a plain path
        assert "SetCredential" not in service
        assert "BEGIN" not in text and ".pem" not in text
        assert "hapax-secrets" not in text

    def test_unit_does_not_run_as_the_lane_user(self) -> None:
        service = _unit()["Service"]

        assert "User" not in service
        assert service.get("DynamicUser") == "yes"


def test_module_never_reads_the_filestore_or_environment_for_the_key() -> None:
    source = (REPO_ROOT / "shared" / "forge_app_identity.py").read_text(encoding="utf-8")

    assert "get_secret" not in source
    assert "shared.secrets" not in source
    assert "os.environ" not in source


def test_app_jwt_is_rs256_and_verifies_with_the_public_key() -> None:
    import jwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode("ascii")

    token = fai.app_jwt("Iv23client", pem, now=datetime.now(UTC))

    assert jwt.get_unverified_header(token)["alg"] == "RS256"
    claims = jwt.decode(token, private.public_key(), algorithms=["RS256"])
    assert claims["iss"] == "Iv23client"
    assert claims["exp"] - claims["iat"] <= 600


MANIFEST = REPO_ROOT / "docs" / "runbooks" / "forge-machine-identity-app-manifest.json"


class TestManifest:
    def _manifest(self) -> dict[str, object]:
        import json

        return json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_permissions_are_exactly_the_minimum(self) -> None:
        assert self._manifest()["default_permissions"] == {
            "contents": "write",
            "pull_requests": "write",
            "metadata": "read",
        }

    def test_app_is_private_with_no_webhook_and_no_events(self) -> None:
        manifest = self._manifest()

        assert manifest["public"] is False
        assert "hook_attributes" not in manifest
        assert manifest.get("default_events", []) == []
        assert manifest.get("request_oauth_on_install", False) is False

    def test_urls_point_at_the_org_not_a_personal_account(self) -> None:
        manifest = self._manifest()

        for key in ("url", "redirect_url"):
            assert str(manifest[key]).startswith("https://github.com/hapax-systems"), key
