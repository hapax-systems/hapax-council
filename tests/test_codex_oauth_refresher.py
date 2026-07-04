"""Self-contained tests for the codex-OAuth single-writer refresher substrate.

Covers the token decode/load/expire/publish contract with a mocked refresh (the
live refresh needs the appendix refresh_token). Self-contained per the workspace
convention; never asserts on a real token.
"""

from __future__ import annotations

import base64
import json
import stat
from pathlib import Path

from shared.codex_oauth_refresher import (
    DEFAULT_REFRESH_MARGIN_S,
    AccessToken,
    decode_access_token_exp,
    load_access_token,
    needs_refresh,
    publish_access_token,
    refresh_and_publish,
    token_fingerprint,
)


def _jwt(*, exp: float | None, sub: str = "chatgpt-user") -> str:
    """Build a minimal JWT (header.payload.signature) with the given exp claim."""
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
    claims: dict[str, object] = {"sub": sub}
    if exp is not None:
        claims["exp"] = exp
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"{header}.{payload}.sig"


# -------------------------------------------------------------------- JWT decode


def test_decode_exp_well_formed() -> None:
    assert decode_access_token_exp(_jwt(exp=1000.0)) == 1000.0
    assert decode_access_token_exp(_jwt(exp=2000)) == 2000.0  # int exp coerced to float


def test_decode_exp_malformed_returns_zero() -> None:
    assert decode_access_token_exp("not-a-jwt") == 0.0
    assert decode_access_token_exp("onlyonepart") == 0.0
    assert decode_access_token_exp("hdr.@@@.sig") == 0.0  # bad base64
    assert decode_access_token_exp(_jwt(exp=None)) == 0.0  # no exp claim
    non_numeric = base64.urlsafe_b64encode(b'{"exp":"soon"}').decode().rstrip("=")
    assert decode_access_token_exp(f"h.{non_numeric}.s") == 0.0


# --------------------------------------------------------------- load auth.json


def _write_auth(path: Path, *, access_token: str | None, refresh_token: str = "rt") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tokens: dict[str, str] = {"refresh_token": refresh_token}
    if access_token is not None:
        tokens["access_token"] = access_token
    path.write_text(json.dumps({"auth_mode": "chatgpt", "tokens": tokens}), encoding="utf-8")


def test_load_access_token_present(tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    _write_auth(auth, access_token=_jwt(exp=1000.0))
    token = load_access_token(auth)
    assert token is not None
    assert token.exp == 1000.0


def test_load_access_token_absent_or_corrupt(tmp_path: Path) -> None:
    assert load_access_token(tmp_path / "missing.json") is None
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert load_access_token(corrupt) is None


def test_load_access_token_no_access_token(tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    _write_auth(auth, access_token=None)  # refresh_token only
    assert load_access_token(auth) is None


# ------------------------------------------------------------------- needs_refresh


def test_needs_refresh_none_or_unparseable() -> None:
    assert needs_refresh(None) is True
    assert needs_refresh(AccessToken(raw="t", exp=0.0)) is True


def test_needs_refresh_far_future_is_fresh() -> None:
    now = 10_000.0
    fresh = AccessToken(raw="t", exp=now + DEFAULT_REFRESH_MARGIN_S + 1.0)
    assert needs_refresh(fresh, now=now) is False


def test_needs_refresh_within_margin_is_stale() -> None:
    now = 10_000.0
    stale = AccessToken(raw="t", exp=now + DEFAULT_REFRESH_MARGIN_S - 1.0)
    assert needs_refresh(stale, now=now) is True
    boundary = AccessToken(raw="t", exp=now + DEFAULT_REFRESH_MARGIN_S)  # exactly the margin
    assert needs_refresh(boundary, now=now) is True  # <= margin -> refresh


def test_needs_refresh_custom_margin() -> None:
    now = 10_000.0
    token = AccessToken(raw="t", exp=now + 60.0)
    assert needs_refresh(token, margin_s=30.0, now=now) is False
    assert needs_refresh(token, margin_s=120.0, now=now) is True


# ------------------------------------------------------------- publish (atomic)


def test_publish_writes_0600_and_content(tmp_path: Path) -> None:
    publish_dir = tmp_path / "codex-oauth"
    target = publish_access_token("secret-access-token", publish_dir)
    assert target == publish_dir / "access_token"
    assert target.read_text(encoding="utf-8") == "secret-access-token"
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600


def test_publish_overwrites_atomically(tmp_path: Path) -> None:
    publish_dir = tmp_path / "codex-oauth"
    publish_access_token("old", publish_dir)
    publish_access_token("new", publish_dir)
    assert (publish_dir / "access_token").read_text(encoding="utf-8") == "new"
    leftovers = [p for p in publish_dir.iterdir() if p.name.startswith(".access_token.")]
    assert leftovers == []


def test_publish_cleans_temp_on_failure(tmp_path: Path) -> None:
    publish_dir = tmp_path / "codex-oauth"
    publish_dir.mkdir(parents=True)
    target = publish_dir / "access_token"
    target.mkdir()  # make os.replace fail (target is a directory)
    try:
        raised = False
        try:
            publish_access_token("x", publish_dir)
        except OSError:
            raised = True
        assert raised
    finally:
        target.rmdir()
    leftovers = [p for p in publish_dir.iterdir() if p.name.startswith(".access_token.")]
    assert leftovers == []


# ------------------------------------------------------- refresh_and_publish


def test_refresh_and_publish_invokes_refresh_and_publishes(tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    publish_dir = tmp_path / "codex-oauth"
    calls: list[Path] = []

    def mock_refresh(path: Path) -> str:
        calls.append(path)
        return _jwt(exp=9999.0)

    result = refresh_and_publish(auth, mock_refresh, publish_dir=publish_dir)
    assert calls == [auth]  # refresh called once with the auth.json path
    assert result.exp == 9999.0
    assert (publish_dir / "access_token").read_text(encoding="utf-8") == result.raw


def test_refresh_and_publish_rejects_empty_token(tmp_path: Path) -> None:
    raised = False
    try:
        refresh_and_publish(tmp_path / "auth.json", lambda _p: "", publish_dir=tmp_path / "out")
    except ValueError:
        raised = True
    assert raised


# ------------------------------------------------------------- fingerprint


def test_token_fingerprint_stable_and_not_the_token() -> None:
    token = _jwt(exp=1.0)
    fp = token_fingerprint(token)
    assert fp != token
    assert len(fp) == 12
    assert token_fingerprint(token) == fp  # stable
    assert token_fingerprint(_jwt(exp=2.0, sub="other")) != fp  # different token -> different fp
    assert token not in fp  # never the raw token
