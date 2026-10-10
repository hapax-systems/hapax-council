"""Config-guard for the chatbind proxy (chatbind-featherless-verboo-proxy-build-and-probes-20261004).

chatbind is a narrowly-scoped LiteLLM instance that lets Featherless (prepaid) and Verboo
(flat) models act as builders behind the hooked harness — NEVER PAYG. CHAT-BINDING.md §6
fixes its whole configuration surface; each invariant below is a guard line. This test
fails CLOSED on any drift that would widen the surface (a third model, a fallback/alias,
an extra credential, a database/cache/master-key), so an unreviewed edit cannot quietly
turn chatbind into a general gateway.

Source-only row (container start + the P1–P5 probes are later seat runtime acts). This
test reads the committed config/compose; it starts nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CHATBIND = REPO_ROOT / "llm-stack-chatbind"
CONFIG = CHATBIND / "chatbind-config.yaml"
COMPOSE = CHATBIND / "docker-compose.chatbind.yml"

# The ONLY two credentials chatbind's environment may reference (Featherless, Verboo).
ALLOWED_ENV_SECRETS = {"FEATHERLESS_API_KEY", "VERBOO_API_KEY"}

_FORBIDDEN_LITELLM_SETTINGS = ("cache", "cache_params", "success_callback", "callbacks")
_FORBIDDEN_GENERAL_SETTINGS = (
    "master_key",
    "database_url",
    "store_model_in_db",
    "virtual_keys",
    "max_budget",
    "budget_duration",
)


def _load(path: Path) -> dict:
    assert path.is_file(), f"chatbind config missing: {path}"
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict), f"{path} did not parse to a mapping"
    return data


def _env_refs(obj) -> set[str]:
    """Every `os.environ/NAME` reference anywhere in the config tree."""
    found: set[str] = set()
    if isinstance(obj, str):
        if obj.startswith("os.environ/"):
            found.add(obj.split("/", 1)[1])
    elif isinstance(obj, dict):
        for v in obj.values():
            found |= _env_refs(v)
    elif isinstance(obj, list):
        for v in obj:
            found |= _env_refs(v)
    return found


def test_model_list_has_exactly_two_entries():
    cfg = _load(CONFIG)
    model_list = cfg.get("model_list")
    assert isinstance(model_list, list), "model_list must be a list"
    assert len(model_list) == 2, f"chatbind must pin exactly two models; found {len(model_list)}"
    names = [m.get("model_name") for m in model_list]
    assert all(names), "every model entry needs a model_name"
    # No wildcard route and no tier-alias names (fast/balanced/cheap/...).
    for n in names:
        assert "*" not in str(n), f"no wildcard model route allowed: {n!r}"
        assert str(n).lower() not in {"fast", "balanced", "cheap", "default"}, (
            f"no tier-alias model name allowed: {n!r}"
        )


# Every LiteLLM fallback/alias key form — any one opens a second route out of the two pins.
_FALLBACK_KEY_FORMS = (
    "fallbacks",
    "default_fallbacks",
    "content_policy_fallbacks",
    "context_window_fallbacks",
    "model_group_alias",
)


def test_no_fallbacks_aliases_or_wildcards():
    cfg = _load(CONFIG)
    router = cfg.get("router_settings") or {}
    for key in _FALLBACK_KEY_FORMS:
        assert key not in router, f"no router_settings.{key} allowed"
        assert key not in cfg, f"no top-level {key} allowed"


def test_litellm_params_model_has_no_wildcard_or_provider_alias():
    """The upstream route itself (litellm_params.model), not only model_name, must be a concrete
    `provider/model` — a wildcard like `openai/*` or `featherless_ai/*` opens the PAYG-leak route
    this binding exists to prevent (the fast-tier-alias leak, inverted)."""
    cfg = _load(CONFIG)
    for entry in cfg.get("model_list") or []:
        params = entry.get("litellm_params") or {}
        model = str(params.get("model") or "")
        assert model, f"every model entry needs litellm_params.model: {entry.get('model_name')!r}"
        assert "*" not in model, f"no wildcard upstream route allowed: {model!r}"
        # A concrete provider/model has a provider segment and a non-empty, non-wildcard id.
        provider, _, upstream_id = model.partition("/")
        assert provider and upstream_id and "*" not in upstream_id, (
            f"litellm_params.model must be a concrete provider/model, not an alias/wildcard: {model!r}"
        )
        assert provider.lower() not in {"fast", "balanced", "cheap", "default"}, (
            f"no tier-alias provider allowed: {model!r}"
        )


def test_no_database_cache_master_key_or_callbacks():
    cfg = _load(CONFIG)
    litellm_settings = cfg.get("litellm_settings") or {}
    for key in _FORBIDDEN_LITELLM_SETTINGS:
        assert key not in litellm_settings, f"forbidden litellm_settings.{key}"
    general = cfg.get("general_settings") or {}
    for key in _FORBIDDEN_GENERAL_SETTINGS:
        assert key not in general, f"forbidden general_settings.{key}"


def test_positive_safety_invariants():
    cfg = _load(CONFIG)
    litellm_settings = cfg.get("litellm_settings") or {}
    assert litellm_settings.get("drop_params") is True, "drop_params must be true"
    assert litellm_settings.get("modify_params") is False, "modify_params must be false"
    assert litellm_settings.get("num_retries") == 0, "num_retries must be 0"


def test_env_references_are_exactly_the_two_secrets():
    cfg = _load(CONFIG)
    refs = _env_refs(cfg)
    assert refs == ALLOWED_ENV_SECRETS, (
        f"chatbind config may reference ONLY {sorted(ALLOWED_ENV_SECRETS)}; found {sorted(refs)}"
    )


def test_compose_has_only_the_two_secrets_and_no_backing_services():
    assert COMPOSE.is_file(), f"chatbind compose missing: {COMPOSE}"
    compose = _load(COMPOSE)
    services = compose.get("services") or {}
    # Exactly one service (the chatbind litellm); no postgres/redis/langfuse/clickhouse.
    forbidden = {"postgres", "redis", "clickhouse", "langfuse", "langfuse-worker", "db", "cache"}
    assert not (set(services) & forbidden), (
        f"chatbind must add no backing services; got {sorted(services)}"
    )
    assert len(services) == 1, (
        f"chatbind compose must define exactly one service; got {sorted(services)}"
    )
    svc = next(iter(services.values()))
    # The service environment names EXACTLY the two secrets (passthrough from the
    # secret_env_from_filestore-set process env) — no third credential, no inline value.
    env = svc.get("environment") or []
    if isinstance(env, dict):
        env_names = set(env.keys())
        # No secret value is committed inline — passthrough only (null / empty).
        for k, v in env.items():
            assert v in (None, "", f"${{{k}}}"), f"compose must not inline a secret value for {k}"
    else:
        # List-style entries are passthrough only. Name-only checking would let an entry that
        # carries an inline value (NAME then "=" then a literal secret) through, so reject any
        # inline VALUE: an entry may be a bare name, `NAME=` (empty), or `NAME=${NAME}` (shell
        # passthrough) — never a committed literal after the `=`.
        for e in env:
            name, sep, value = str(e).partition("=")
            assert not sep or value in ("", f"${{{name}}}"), (
                f"compose must not inline a secret value in a list env entry: {e!r}"
            )
        env_names = {str(e).partition("=")[0] for e in env}
    assert env_names == ALLOWED_ENV_SECRETS, (
        f"chatbind service env must be exactly {sorted(ALLOWED_ENV_SECRETS)}; found {sorted(env_names)}"
    )
    # No master key / database / redis URL anywhere in the compose.
    flat = yaml.safe_dump(compose).lower()
    for banned in ("database_url", "master_key", "redis", "langfuse", "store_model_in_db"):
        assert banned not in flat, f"compose must not reference {banned}"


def _chatbind_service() -> dict:
    compose = _load(COMPOSE)
    services = compose.get("services") or {}
    svc = services.get("chatbind")
    assert isinstance(svc, dict), "compose must define the chatbind service"
    return svc


def test_ports_are_loopback_only():
    """With no master_key, the loopback port prefix is the ONLY access control; the guard must
    assert it (claude-1 major). A host-published port with no loopback prefix would expose the
    proxy to the network."""
    svc = _chatbind_service()
    ports = svc.get("ports") or []
    assert ports, "chatbind must publish its port on loopback only"
    for entry in ports:
        if isinstance(entry, dict):
            host_ip = str(entry.get("host_ip") or "")
            assert host_ip in {"127.0.0.1", "::1"}, f"port must bind loopback only: {entry!r}"
        else:
            assert str(entry).startswith(("127.0.0.1:", "::1:")), (
                f"port must bind loopback only (127.0.0.1: prefix): {entry!r}"
            )


def test_image_is_pinned_by_digest():
    """The image must be digest-pinned (`@sha256:<64hex>`), not a moving tag — the README/PR claim
    pinned-by-digest and nothing but this guard enforces it (glm-1 major). A moving `:main-stable`
    tag can change under the binding between review and start."""
    svc = _chatbind_service()
    image = str(svc.get("image") or "")
    assert re.search(r"@sha256:[0-9a-f]{64}$", image), (
        f"chatbind image must be pinned by digest (name@sha256:<64 hex>), not a moving tag: {image!r}"
    )


def test_featherless_non_default_user_agent():
    """README names the Featherless non-default User-Agent a guard invariant (claude-1 major)."""
    cfg = _load(CONFIG)
    entry = next(
        (m for m in cfg.get("model_list") or [] if m.get("model_name") == "featherless-builder"),
        None,
    )
    assert entry is not None, "the featherless-builder model entry must exist"
    headers = (entry.get("litellm_params") or {}).get("extra_headers") or {}
    assert headers.get("User-Agent") == "hapax-chatbind/1", (
        f"featherless upstream must send the non-default UA hapax-chatbind/1; got {headers!r}"
    )


def test_verboo_concurrency_cap():
    """README names the Verboo max_parallel_requests: 2 cap a guard invariant (claude-1 major)."""
    cfg = _load(CONFIG)
    entry = next(
        (m for m in cfg.get("model_list") or [] if m.get("model_name") == "verboo-builder"),
        None,
    )
    assert entry is not None, "the verboo-builder model entry must exist"
    assert (entry.get("litellm_params") or {}).get("max_parallel_requests") == 2, (
        "verboo upstream must cap concurrency at max_parallel_requests: 2 (flat-plan rate limit)"
    )
