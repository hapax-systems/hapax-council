"""Machine forge identity (operator act O2): the org-owned GitHub App's credentials.

Only the forge-send service holds the App's private key. systemd delivers it with
``LoadCredentialEncrypted=forge-app-key`` into ``$CREDENTIALS_DIRECTORY``, which is readable
by the unit's dynamic user and root and by nobody else. This module reads the key from
there and from nowhere else: not the FileStore, not the environment, not a path argument.
A lane process has no credentials directory, so it cannot load the key through this code.
Against a lane that escalates (sudo is passwordless until O5) that is class (b), and it is
labelled so in the design.

From the key the service mints a JWT (RS256, at most 10 minutes), exchanges it for a
one-hour installation token narrowed to a single repository, and creates commits through
GraphQL ``createCommitOnBranch``. GitHub attributes those commits to the App's bot and
signs them; the request carries no author a lane could set, and a result authored by
anyone else is refused.

Design: ``30-areas/hapax/frame/communication-pathway-20260925/O2-FORGE-MACHINE-IDENTITY-DESIGN-20260925.md``.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

#: The credential name in ``LoadCredentialEncrypted=`` and ``systemd-creds encrypt --name=``.
APP_KEY_CREDENTIAL = "forge-app-key"

#: GitHub: exp "no more than 10 minutes into the future"; iat "60 seconds in the past".
JWT_MAX_LIFETIME = timedelta(minutes=10)
JWT_DEFAULT_LIFETIME = timedelta(minutes=9)
JWT_CLOCK_SKEW = timedelta(seconds=60)

#: Installation tokens last one hour. One is refused this close to expiry, so a send never
#: starts on a token that can lapse mid-send.
TOKEN_SAFETY_MARGIN = timedelta(minutes=5)

#: The only permissions a send token is ever minted with. A subset of the App's grant.
SEND_PERMISSIONS: Mapping[str, str] = {"contents": "write", "pull_requests": "write"}

_REPO_NAME_RE = re.compile(r"\A[A-Za-z0-9._-]+\Z")


class ForgeIdentityRefused(RuntimeError):
    """A typed refusal. The first token of the message is the machine-readable reason."""


def load_app_key(env: Mapping[str, str]) -> str:
    """The App private key, from systemd's credentials directory only.

    ``env`` is the process environment, passed in so that tests and the service share one
    code path. Only ``CREDENTIALS_DIRECTORY`` is read from it.
    """

    creds = env.get("CREDENTIALS_DIRECTORY", "")
    if not creds:
        raise ForgeIdentityRefused(
            "credentials_directory_unset: the App key is delivered only to the forge-send unit"
            " (LoadCredentialEncrypted=forge-app-key). Send through hapax-forge-send; no other"
            " process may load the key."
        )
    root = Path(creds).resolve()
    candidate = Path(creds) / APP_KEY_CREDENTIAL
    if not candidate.exists():
        raise ForgeIdentityRefused(
            f"credential_missing: {candidate}. Install the key with the operator procedure in"
            " docs/runbooks/forge-machine-identity.md (hapax-forge-app-convert)."
        )
    resolved = candidate.resolve()
    if resolved.parent != root:
        raise ForgeIdentityRefused(
            f"credential_path_escapes: {candidate} resolves to {resolved}, outside {root}"
        )
    key = resolved.read_text(encoding="utf-8")
    if not key.strip():
        raise ForgeIdentityRefused(f"credential_empty: {candidate}")
    return key


def jwt_claims(
    client_id: str, *, now: datetime, lifetime: timedelta = JWT_DEFAULT_LIFETIME
) -> dict[str, Any]:
    """GitHub App JWT claims: iat backdated 60 s, exp at most 10 minutes out."""

    if not client_id.strip():
        raise ForgeIdentityRefused("jwt_issuer_missing: the App's client ID is required")
    if lifetime > JWT_MAX_LIFETIME:
        raise ForgeIdentityRefused(
            f"jwt_lifetime_exceeds_600s: {int(lifetime.total_seconds())}s requested"
        )
    return {
        "iat": int((now - JWT_CLOCK_SKEW).timestamp()),
        "exp": int((now + lifetime).timestamp()),
        "iss": client_id,
    }


def app_jwt(client_id: str, key: str, *, now: datetime) -> str:
    """Sign the App JWT with RS256."""

    import jwt  # pyjwt[crypto]

    return jwt.encode(jwt_claims(client_id, now=now), key, algorithm="RS256")


@dataclass(frozen=True)
class InstallationToken:
    token: str
    expires_at: datetime

    @classmethod
    def from_response(cls, body: Mapping[str, Any]) -> InstallationToken:
        token = body.get("token")
        raw_expiry = body.get("expires_at")
        if not isinstance(token, str) or not token or not isinstance(raw_expiry, str):
            raise ForgeIdentityRefused(
                "installation_token_malformed: GitHub's response lacks token or expires_at"
            )
        try:
            expires_at = datetime.fromisoformat(raw_expiry.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ForgeIdentityRefused(
                f"installation_token_malformed: expires_at {raw_expiry!r}"
            ) from exc
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return cls(token=token, expires_at=expires_at)

    def __repr__(self) -> str:  # never render the token itself
        return f"InstallationToken(expires_at={self.expires_at.isoformat()})"


def require_usable(token: InstallationToken, *, now: datetime) -> None:
    """Refuse an expired token, or one inside the safety margin, before any network call."""

    if now >= token.expires_at:
        raise ForgeIdentityRefused(
            f"installation_token_expired: expired {token.expires_at.isoformat()}; mint a new one"
        )
    if token.expires_at - now < TOKEN_SAFETY_MARGIN:
        raise ForgeIdentityRefused(
            f"installation_token_near_expiry: expires {token.expires_at.isoformat()}, inside the"
            f" {int(TOKEN_SAFETY_MARGIN.total_seconds())}s margin; mint a new one"
        )


def installation_token_request(repository: str) -> dict[str, Any]:
    """Body for ``POST /app/installations/{id}/access_tokens``, narrowed to one repository."""

    if not _REPO_NAME_RE.fullmatch(repository or ""):
        raise ForgeIdentityRefused(
            f"repository_name_invalid: {repository!r}; want the bare name (no owner), e.g."
            " 'hapax-council'"
        )
    return {"repositories": [repository], "permissions": dict(SEND_PERMISSIONS)}


@dataclass(frozen=True)
class BotIdentity:
    """The App's bot account, as GitHub renders it."""

    slug: str
    user_id: int

    @property
    def login(self) -> str:
        return f"{self.slug}[bot]"

    @property
    def email(self) -> str:
        return f"{self.user_id}+{self.login}@users.noreply.github.com"


def require_bot_authored(commit: Mapping[str, Any], identity: BotIdentity) -> None:
    """Refuse a created commit whose author is not the App's bot."""

    author = commit.get("author") or {}
    user = author.get("user") if isinstance(author, Mapping) else None
    login = user.get("login") if isinstance(user, Mapping) else None
    if login != identity.login:
        raise ForgeIdentityRefused(f"commit_not_bot_authored:{login or 'unknown'}")


_CREATE_COMMIT_MUTATION = (
    "mutation($input: CreateCommitOnBranchInput!) {"
    " createCommitOnBranch(input: $input) {"
    " commit { oid url author { user { login } } } } }"
)


def create_commit_request(
    *,
    repository: str,
    branch: str,
    expected_head_oid: str,
    headline: str,
    additions: Mapping[str, bytes],
    deletions: tuple[str, ...] = (),
    body: str = "",
) -> dict[str, Any]:
    """GraphQL ``createCommitOnBranch`` request.

    The mutation has no author or committer input; GitHub attributes the commit to the
    token's App. ``expected_head_oid`` makes the write conditional on the branch head.
    """

    return {
        "query": _CREATE_COMMIT_MUTATION,
        "variables": {
            "input": {
                "branch": {"repositoryNameWithOwner": repository, "branchName": branch},
                "message": {"headline": headline, "body": body},
                "expectedHeadOid": expected_head_oid,
                "fileChanges": {
                    "additions": [
                        {"path": path, "contents": base64.b64encode(data).decode("ascii")}
                        for path, data in additions.items()
                    ],
                    "deletions": [{"path": path} for path in deletions],
                },
            }
        },
    }
