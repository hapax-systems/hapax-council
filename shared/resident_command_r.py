"""Resident Command-R contract for content generation paths."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from collections.abc import Sequence

RESIDENT_COMMAND_R_MODEL = "command-r-08-2024-exl3-5.0bpw"
DEFAULT_TABBY_CHAT_URL = "http://localhost:5000/v1/chat/completions"


def configured_resident_model(env_var: str, *, purpose: str) -> str:
    """Return the configured model, failing closed on non-Command-R overrides."""
    model = os.environ.get(env_var, RESIDENT_COMMAND_R_MODEL)
    if model != RESIDENT_COMMAND_R_MODEL:
        raise RuntimeError(
            f"{purpose} requires resident Command-R; {env_var}={model!r} is not allowed"
        )
    return model


def tabby_chat_url() -> str:
    return os.environ.get("HAPAX_TABBY_URL", DEFAULT_TABBY_CHAT_URL)


def tabby_model_url(chat_url: str | None = None) -> str:
    chat_url = chat_url or tabby_chat_url()
    if chat_url.endswith("/chat/completions"):
        return chat_url.removesuffix("/chat/completions") + "/model"
    if chat_url.endswith("/completions"):
        return chat_url.removesuffix("/completions") + "/model"
    return chat_url.rstrip("/") + "/model"


def loaded_tabby_model(chat_url: str | None = None) -> str | None:
    req = urllib.request.Request(tabby_model_url(chat_url), method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    loaded = data.get("id") or data.get("model_name")
    return str(loaded) if loaded else None


def assert_resident_command_r(chat_url: str | None = None) -> str:
    loaded = loaded_tabby_model(chat_url)
    if loaded != RESIDENT_COMMAND_R_MODEL:
        raise RuntimeError(
            "resident Command-R required; "
            f"TabbyAPI is serving {loaded!r}, expected {RESIDENT_COMMAND_R_MODEL!r}"
        )
    return loaded


def clean_local_model_text(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def call_resident_command_r(
    prompt: str,
    *,
    messages: list[dict] | None = None,
    chat_url: str | None = None,
    max_tokens: int = 8192,
    temperature: float = 0.7,
    timeout_s: float = 300.0,
) -> str:
    """Call TabbyAPI only after verifying resident Command-R.

    No fallback is provided here by design. Content-prep/programming artifacts
    should fail closed rather than silently route to a different model.
    """
    chat_url = chat_url or tabby_chat_url()
    assert_resident_command_r(chat_url)
    body = json.dumps(
        {
            "model": RESIDENT_COMMAND_R_MODEL,
            "messages": messages or [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
    ).encode()
    req = urllib.request.Request(chat_url, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        data = json.loads(resp.read())
    content = data["choices"][0]["message"]["content"] or ""
    content = clean_local_model_text(content)
    if not content:
        raise RuntimeError("resident Command-R returned empty content")
    return content


def main(argv: Sequence[str] | None = None) -> int:
    """CLI health check for systemd ExecStartPre and operator probes."""
    args = list(sys.argv[1:] if argv is None else argv)
    check = "--check" in args
    json_output = "--json" in args

    try:
        loaded = assert_resident_command_r() if check else loaded_tabby_model()
    except Exception as exc:
        payload = {
            "ok": False,
            "expected_model": RESIDENT_COMMAND_R_MODEL,
            "error": str(exc),
        }
        if json_output:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(
                f"resident Command-R check failed: expected {RESIDENT_COMMAND_R_MODEL}; {exc}",
                file=sys.stderr,
            )
        return 1

    payload = {
        "ok": loaded == RESIDENT_COMMAND_R_MODEL,
        "expected_model": RESIDENT_COMMAND_R_MODEL,
        "loaded_model": loaded,
    }
    if json_output:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"resident Command-R loaded: {loaded}")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
