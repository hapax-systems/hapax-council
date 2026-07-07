"""Canary fixtures for the transcript-grade scrubber (CS P0 hard gate).

Each leaking shape the privacy red-team flagged on the HKP frontmatter redactor
is a CANARY here: it MUST be caught, and the test FAILS CI on regression. The
false-positive guards assert that SOURCE pointers (git SHAs, file:line paths)
SURVIVE — over-redacting them would break the "better than naked compaction"
pointer-integrity property.

Self-contained (no conftest); env file is always a tmp fixture so the real
``/run/user/1000/hapax-secrets.env`` is never read during tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.transcript_scrubber import (
    ResidualSecretError,
    assert_clean,
    load_secret_values,
    scrub,
    scrub_structured_value,
)


def _env(tmp_path: Path, **kv: str) -> Path:
    p = tmp_path / "secrets.env"
    p.write_text("\n".join(f"{k}={v}" for k, v in kv.items()) + "\n", encoding="utf-8")
    return p


def _scrub(text: str, env: Path, **kw: object) -> str:
    return scrub(text, secret_env_path=env, **kw).text  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Canary: the 6 shapes the HKP frontmatter redactor LEAKS                      #
# --------------------------------------------------------------------------- #


def test_canary_bare_anthropic_key(tmp_path: Path) -> None:
    secret = "sk-ant-api03-AbCdEf0123456789GhIjKlMnOpQr"
    out = _scrub(f"I ran it with {secret} just now", _env(tmp_path))
    assert secret not in out
    assert "[REDACTED:provider_token]" in out


def test_canary_bare_github_pat(tmp_path: Path) -> None:
    secret = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    out = _scrub(f"export GH={secret}", _env(tmp_path))
    assert secret not in out
    assert "ghp_" not in out  # no prefix/tail remnant survives
    assert "[REDACTED:" in out


def test_canary_bare_env_secret_value(tmp_path: Path) -> None:
    # The strongest case: a value that matches NO generic pattern, caught only by
    # the live-env denylist (exact match).
    env = _env(tmp_path, ZENODO_API_TOKEN="plainishvalue1234567890")
    out = _scrub("the token is plainishvalue1234567890 fyi", env)
    assert "plainishvalue1234567890" not in out
    assert "[REDACTED:known_secret]" in out


def test_canary_spoken_password(tmp_path: Path) -> None:
    out = _scrub("when it asks, the password is Hunter2-NotReal-9x", _env(tmp_path))
    assert "Hunter2-NotReal-9x" not in out
    assert "[REDACTED:spoken_secret]" in out


def test_canary_json_value_secret(tmp_path: Path) -> None:
    out = _scrub('config: {"api_key": "jsonvaluesecret-abc123def456"}', _env(tmp_path))
    assert "jsonvaluesecret-abc123def456" not in out
    assert "[REDACTED:secret_assignment]" in out


def test_canary_bluesky_app_password(tmp_path: Path) -> None:
    secret = "abcd-efgh-ijkl-mnop"
    out = _scrub(f"bluesky app password {secret}", _env(tmp_path))
    assert secret not in out
    assert "[REDACTED:app_password]" in out


# --------------------------------------------------------------------------- #
# Additional generic shapes                                                    #
# --------------------------------------------------------------------------- #


def test_aws_key(tmp_path: Path) -> None:
    out = _scrub("key AKIAIOSFODNN7EXAMPLE here", _env(tmp_path))
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "[REDACTED:aws_key]" in out


def test_google_key(tmp_path: Path) -> None:
    secret = "AIzaSyA-1234567890abcdefghijklmnopqrstu"
    out = _scrub(f"g {secret}", _env(tmp_path))
    assert secret not in out
    assert "[REDACTED:google_key]" in out


def test_jwt(tmp_path: Path) -> None:
    jwt = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        ".eyJzdWIiOiIxMjM0NTY3ODkwIn0"
        ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV"
    )
    out = _scrub(f"bearer body {jwt}", _env(tmp_path))
    assert jwt not in out
    assert "[REDACTED:jwt]" in out


def test_pem_private_key(tmp_path: Path) -> None:
    pem = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEpAIBAAKCAQEAfakefakefake\n"
        "-----END RSA PRIVATE KEY-----"
    )
    out = _scrub(f"here it is:\n{pem}\nthanks", _env(tmp_path))
    assert "MIIEpAIBAAKCAQEAfakefakefake" not in out
    assert "[REDACTED:private_key]" in out


def test_authorization_header(tmp_path: Path) -> None:
    out = _scrub("Authorization: Bearer abc.def.ghi-token-value", _env(tmp_path))
    assert "abc.def.ghi-token-value" not in out
    assert "[REDACTED:authorization]" in out


def test_env_var_name_echo(tmp_path: Path) -> None:
    env = _env(tmp_path, LITELLM_API_KEY="realvalue-should-be-caught-too")
    out = _scrub("set LITELLM_API_KEY=realvalue-should-be-caught-too in shell", env)
    assert "realvalue-should-be-caught-too" not in out


# --------------------------------------------------------------------------- #
# Fail-closed gate                                                             #
# --------------------------------------------------------------------------- #


def test_assert_clean_raises_on_residual(tmp_path: Path) -> None:
    with pytest.raises(ResidualSecretError) as ei:
        assert_clean("leak sk-ant-api03-ZZZZ1111222233334444", secret_env_path=_env(tmp_path))
    assert "provider_token" in ei.value.categories


def test_assert_clean_passes_on_scrubbed(tmp_path: Path) -> None:
    env = _env(tmp_path)
    cleaned = scrub("token sk-ant-api03-ZZZZ1111222233334444 done", secret_env_path=env).text
    assert_clean(cleaned, secret_env_path=env)  # the fail-closed gate does not raise
    assert "sk-ant-" not in cleaned


def test_scrub_is_idempotent(tmp_path: Path) -> None:
    env = _env(tmp_path)
    first = scrub("k sk-ant-api03-ZZZZ1111222233334444", secret_env_path=env)
    # Re-scrubbing already-scrubbed text finds nothing new.
    second = scrub(first.text, secret_env_path=env)
    assert second.redactions == 0


def test_overlapping_matches_no_tail_leak(tmp_path: Path) -> None:
    # Crossing overlap (the review-caught leak class): an earlier-starting denylist
    # value and a later one that extends BEYOND it. The union must be redacted — no
    # tail may survive. Under the old "drop later overlapping match" resolver, the
    # trailing "cccc" leaked in the clear.
    env = _env(tmp_path, A="ghp_aaaabbbb", B="bbbbcccc")
    out = _scrub("leak ghp_aaaabbbbcccc end", env)
    assert "ghp_aaaabbbbcccc" not in out
    assert "cccc" not in out
    assert "bbbb" not in out
    assert "[REDACTED:" in out


# --------------------------------------------------------------------------- #
# False-positive guards — SOURCE pointers MUST survive                         #
# --------------------------------------------------------------------------- #


def test_git_sha_survives(tmp_path: Path) -> None:
    sha = "065fc65db4a1f0e9c2b7d3a8e5f6071829abcdef"  # 40-hex git SHA
    out = _scrub(f"HEAD is now at {sha} Write interview conductor state", _env(tmp_path))
    assert sha in out  # pointer integrity: not redacted


def test_file_path_survives(tmp_path: Path) -> None:
    text = "see agents/visual_layer_aggregator/aggregator.py:1165 for the hardcode"
    out = _scrub(text, _env(tmp_path))
    assert "aggregator.py:1165" in out


def test_ordinary_prose_survives(tmp_path: Path) -> None:
    text = "The operator asked me to own the throughline and make sure everything lands."
    out = _scrub(text, _env(tmp_path))
    assert out == text


def test_short_env_value_not_denylisted(tmp_path: Path) -> None:
    # Values shorter than MIN_DENYLIST_VALUE_LEN must not enter the denylist
    # (would redact "true"/ports/etc. everywhere).
    env = _env(tmp_path, PORT="8051", DEBUG="true")
    assert "8051" not in load_secret_values(env)
    out = _scrub("the api is on port 8051 in debug true mode", env)
    assert out == "the api is on port 8051 in debug true mode"


def test_structured_scrub_uses_secret_key_context() -> None:
    scrubbed = scrub_structured_value(
        {
            "nested": {
                "api_key": "hunter2",
                "X-API-Key": "hunter3",
                "access-token": "hunter4",
            }
        }
    )
    assert scrubbed == {
        "nested": {
            "api_key": "[REDACTED:secret_assignment]",
            "X-API-Key": "[REDACTED:secret_assignment]",
            "access-token": "[REDACTED:secret_assignment]",
        }
    }


def test_structured_scrub_preserves_hash_but_redacts_text() -> None:
    scrubbed = scrub_structured_value(
        {
            "utterance_hash": "abc123",
            "utterance_text": "private phrase",
        }
    )
    assert scrubbed == {
        "utterance_hash": "abc123",
        "utterance_text": "[REDACTED:private_text]",
    }


def test_structured_scrub_preserves_non_string_scalars() -> None:
    scrubbed = scrub_structured_value(
        {
            "cascade_depth": 3,
            "valence": 0.5,
            "active": True,
            "missing": None,
            "items": [1, 2.0, False, None],
        }
    )
    assert scrubbed == {
        "cascade_depth": 3,
        "valence": 0.5,
        "active": True,
        "missing": None,
        "items": [1, 2.0, False, None],
    }
