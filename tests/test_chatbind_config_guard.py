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


def test_no_fallbacks_aliases_or_wildcards():
    cfg = _load(CONFIG)
    router = cfg.get("router_settings") or {}
    assert "fallbacks" not in router, "no fallbacks allowed"
    assert "default_fallbacks" not in router, "no default_fallbacks allowed"
    assert "model_group_alias" not in cfg and "model_group_alias" not in router, (
        "no model_group_alias allowed"
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
        env_names = {str(e).split("=", 1)[0] for e in env}
    assert env_names == ALLOWED_ENV_SECRETS, (
        f"chatbind service env must be exactly {sorted(ALLOWED_ENV_SECRETS)}; found {sorted(env_names)}"
    )
    # No master key / database / redis URL anywhere in the compose.
    flat = yaml.safe_dump(compose).lower()
    for banned in ("database_url", "master_key", "redis", "langfuse", "store_model_in_db"):
        assert banned not in flat, f"compose must not reference {banned}"
