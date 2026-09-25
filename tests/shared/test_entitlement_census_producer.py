"""The entitlement census producer: held x holds-now x declared, one view, no spend, no secret.

Every unsafe case in the parent spec (``frame/ENTITLEMENT-CENSUS-20260924.md`` section 10, and the
build row's list) has a test here, written before the producer. Each was mutation-verified: the
guard was broken, the test went red, the exact bytes were restored, and it went green again.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import shared.entitlement_census as census
from shared.capability_surface_delta import DeltaKind
from shared.entitlement_census import (
    ENTITLEMENT_CENSUS_CONFIG,
    READBACKS,
    CensusConfig,
    CensusConfigError,
    CostClass,
    EntitlementState,
    EvidenceClass,
    HostBinding,
    HostHoldings,
    HttpResponse,
    SecretLeakError,
    SecretRegister,
    attach_history,
    compute_trend,
    default_http_get,
    holdings_command,
    load_census_config,
    load_history,
    load_registry,
    parse_holdings,
    read_dispatched_demand,
    read_queued_demand,
    read_wall_witness,
    render_markdown,
    render_view,
    run_census,
    write_outputs,
)

NOW = datetime(2026, 9, 25, 1, 0, tzinfo=UTC)
# A fake value, never a real credential: the tests need one to prove it never reaches output.
SECRET = "kq-7f3a9c1e5b2d8f4a6c0e9b1d3f5a7c9e"  # pragma: allowlist secret


def _config(entitlements: list[dict[str, Any]], **extra: Any) -> CensusConfig:
    payload: dict[str, Any] = {
        "schema": "hapax.entitlement_census.v1",
        "hosts": [
            {"host_id": "appendix", "transport": "local"},
            {"host_id": "podium", "transport": "ssh_batch", "target": "podium.example"},
        ],
        "vendor_cache_max_age_seconds": 86400,
        "withheld_name_tokens": ["ssn"],
        "entitlements": entitlements,
    }
    payload.update(extra)
    return CensusConfig.model_validate(payload)


def _decl(entitlement_id: str = "kimi", **fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "entitlement_id": entitlement_id,
        "provider": "moonshot",
        "kind": "cognition",
        "cost_class": "subscription",
    }
    base.update(fields)
    return base


def _holdings(
    host_id: str = "appendix",
    *,
    filestore: tuple[str, ...] = (),
    login: dict[str, datetime] | None = None,
    bins: tuple[str, ...] = (),
    env: tuple[str, ...] = (),
    reachable: bool = True,
) -> HostHoldings:
    return HostHoldings(
        host_id=host_id,
        reachable=reachable,
        observed_at=NOW if reachable else None,
        error=None if reachable else "ssh_exit_255",
        filestore_names=filestore,
        pass_names=(),
        env_names=env,
        login_files=login or {},
        harness_bins=bins,
    )


class FakeHttp:
    def __init__(self, responses: dict[str, HttpResponse] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
        self.calls.append((url, dict(headers)))
        return self.responses.get(url, HttpResponse(status=None, body=b"", error="refused"))


class FakeSecrets:
    def __init__(self, value: str = SECRET) -> None:
        self.value = value
        self.asked: list[str] = []

    def __call__(self, name: str) -> str | None:
        self.asked.append(name)
        return self.value


def _ok(payload: Any) -> HttpResponse:
    return HttpResponse(status=200, body=json.dumps(payload).encode(), error=None)


KIMI_USAGES = {
    "usage": {
        "limit": "100",
        "used": "5",
        "remaining": "95",
        "resetTime": "2026-10-01T00:57:28.457Z",
    },
    "limits": [
        {
            "window": {"duration": 300, "timeUnit": "TIME_UNIT_MINUTE"},
            "detail": {
                "limit": "100",
                "used": "23",
                "remaining": "77",
                "resetTime": "2026-09-25T02:57:28Z",
            },
        }
    ],
    "booster_wallet": {
        "id": "19fcbd85-4ea2-8537-8000-00001fbcf1a6",
        "userId": "d9c2uj5kbg78kh6kqgcg",
        "balance": {"type": "BOOSTER", "amount": "32000000000", "unit": "UNIT_CURRENCY"},
    },
}


def _run(
    config: CensusConfig,
    *,
    holdings: list[HostHoldings] | None = None,
    http: FakeHttp | None = None,
    secrets: FakeSecrets | None = None,
    registry: dict[str, Any] | None = None,
    ledger: dict[str, Any] | None = None,
    prior_view: dict[str, Any] | None = None,
    home_files: dict[str, bytes] | None = None,
    scout_report: dict[str, Any] | None = None,
    gpu_probe=None,
    now: datetime = NOW,
    **timing: Any,
):
    files = home_files or {}
    return run_census(
        config,
        now=now,
        holdings=holdings if holdings is not None else [_holdings()],
        registry=registry or {"routes": [], "omitted_capability_shapes": []},
        ledger=ledger,
        prior_view=prior_view,
        resolve_secret=secrets or FakeSecrets(),
        http_get=http or FakeHttp(),
        read_home_file=files.get,
        scout_report=scout_report,
        gpu_probe=gpu_probe,
        **timing,
    )


def _row(run, entitlement_id: str):
    matches = [row for row in run.rows if row.entitlement_id == entitlement_id]
    assert len(matches) == 1, [row.entitlement_id for row in run.rows]
    return matches[0]


# --- unsafe case 1: a secret value reaches output -> the rendered view's scan fails closed -----------


def test_secret_value_echoed_by_a_provider_fails_closed_and_writes_nothing(tmp_path: Path) -> None:
    config = _config(
        [
            _decl(
                "tavily",
                provider="tavily",
                kind="grounding",
                credential_names=["tavily-api-key"],
                readbacks=[{"readback_id": "tavily_usage", "secret": "tavily-api-key"}],
            )
        ]
    )
    # A provider that echoes the key back in a categorical field the extractor keeps.
    body = {
        "account": {"current_plan": SECRET, "plan_usage": 1, "plan_limit": 10, "paygo_usage": 0}
    }
    http = FakeHttp({READBACKS["tavily_usage"].url: _ok(body)})
    run = _run(config, holdings=[_holdings(filestore=("tavily-api-key",))], http=http)

    out = tmp_path / "out"
    with pytest.raises(SecretLeakError) as excinfo:
        write_outputs(run, output_root=out, projection_md=tmp_path / "VIEW.md", now=NOW)
    assert SECRET not in str(excinfo.value)
    assert not out.exists() or not any(out.iterdir())
    assert not (tmp_path / "VIEW.md").exists()


def test_secret_shaped_token_in_any_output_fails_closed() -> None:
    register = SecretRegister()
    with pytest.raises(SecretLeakError):
        register.require_clean("plan: sk-" + "A1b2C3d4" * 5, label="view.json")
    with pytest.raises(SecretLeakError):
        register.require_clean("Authorization: Bearer " + "x9" * 20, label="view.json")
    # Credential NAMES are the census's subject and must pass.
    register.require_clean(
        "research-desk-connector-key sakana-fugu-apikey api-key", label="view.json"
    )


def test_provider_identifiers_are_never_projected() -> None:
    config = _config(
        [
            _decl(
                credential_names=["kimi-api-key"],
                readbacks=[{"readback_id": "kimi_usages", "secret": "kimi-api-key"}],
            )
        ]
    )
    http = FakeHttp({READBACKS["kimi_usages"].url: _ok(KIMI_USAGES)})
    run = _run(config, holdings=[_holdings(filestore=("kimi-api-key",))], http=http)
    text = json.dumps(render_view(run, now=NOW)) + render_markdown(render_view(run, now=NOW))
    assert "d9c2uj5kbg78kh6kqgcg" not in text
    assert "19fcbd85-4ea2-8537-8000-00001fbcf1a6" not in text


# --- unsafe case 2: a probe that spends -> allow-listed GETs only, no completion, no Claude probe ----


def test_readback_allow_list_contains_no_completion_or_write_endpoint() -> None:
    forbidden = (
        "completion",
        "/messages",
        "/responses",
        "/generate",
        "/embed",
        "/chat",
        "/audio",
        "/images",
        "/rerank",
        "/text-to-speech",
        "/search",
        "/fetch",
        "/crawl",
        "/scrape",
    )
    for spec in READBACKS.values():
        assert spec.url.startswith("https://"), spec
        path = spec.url.split("://", 1)[1].partition("/")[2].lower()
        assert not any(token in "/" + path for token in forbidden), spec.url


def test_config_cannot_name_a_readback_outside_the_allow_list() -> None:
    with pytest.raises(ValidationError):
        _config([_decl(readbacks=[{"readback_id": "chat_completions", "secret": "kimi-api-key"}])])


def test_config_cannot_declare_a_method() -> None:
    with pytest.raises(ValidationError):
        _config(
            [
                _decl(
                    readbacks=[
                        {"readback_id": "kimi_usages", "secret": "kimi-api-key", "method": "POST"}
                    ]
                )
            ]
        )


def test_serving_endpoint_path_is_fixed_by_code() -> None:
    with pytest.raises(ValidationError):
        _config(
            [],
            serving_endpoints=[
                {
                    "endpoint_id": "x",
                    "host_id": "appendix",
                    "base_url": "http://127.0.0.1:5000",
                    "models_path": "/v1/chat/completions",
                }
            ],
        )


def test_transport_sends_get_with_no_body(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[urllib.request.Request] = []

    class _Resp:
        status = 200

        def read(self, _n: int = -1) -> bytes:
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *_a: object) -> None:
            return None

    def fake_open(request: urllib.request.Request, timeout: float = 0):
        seen.append(request)
        return _Resp()

    monkeypatch.setattr(census._OPENER, "open", fake_open)
    response = default_http_get("https://api.example/v1/usage", {"Authorization": "Bearer x"}, 5)
    assert response.status == 200
    assert seen[0].get_method() == "GET"
    assert seen[0].data is None


def test_no_readback_probes_the_claude_subscription() -> None:
    shipped = load_census_config(ENTITLEMENT_CENSUS_CONFIG)
    claude = [e for e in shipped.entitlements if e.entitlement_id == "anthropic-claude-max"]
    assert claude and not claude[0].readbacks
    for spec in READBACKS.values():
        parts = urllib.parse.urlsplit(spec.url)
        host = parts.hostname or ""
        if host == "anthropic.com" or host.endswith(".anthropic.com"):
            assert parts.path == "/v1/models", spec.url


# --- unsafe case 3: HTTP 401 rendered as held -> state dead ------------------------------------------


def _anthropic_api_row(status: int):
    config = _config(
        [
            _decl(
                "anthropic-api",
                provider="anthropic",
                cost_class="payg",
                credential_names=["api-anthropic"],
                readbacks=[{"readback_id": "anthropic_models", "secret": "api-anthropic"}],
            )
        ]
    )
    http = FakeHttp(
        {READBACKS["anthropic_models"].url: HttpResponse(status=status, body=b"", error=None)}
    )
    run = _run(config, holdings=[_holdings(filestore=("api-anthropic",))], http=http)
    return _row(run, "anthropic-api")


def test_forbidden_is_never_dead_and_never_live() -> None:
    """Measured 2026-09-25T00:31Z: Featherless answers 403 to urllib's default User-Agent and 200
    to curl's with the same key, so a 403 does not prove the credential was rejected. The name is
    still held; the readback is unobserved, and the row says why."""
    row = _anthropic_api_row(403)
    assert row.state is EntitlementState.HELD
    assert row.evidence_class is EvidenceClass.NAME_ONLY
    assert row.readbacks[0]["outcome"] == "unobserved"
    assert any("403" in reason for reason in row.reasons)


def test_transport_sends_an_explicit_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[urllib.request.Request] = []

    def fake_open(request: urllib.request.Request, timeout: float = 0):
        seen.append(request)
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(census._OPENER, "open", fake_open)
    default_http_get("https://api.example/v1/usage", {}, 5)
    agent = seen[0].get_header("User-agent") or ""
    assert agent.startswith("hapax-entitlement-census/")


def test_rejected_key_is_dead_not_held() -> None:
    status = 401
    config = _config(
        [
            _decl(
                "anthropic-api",
                provider="anthropic",
                cost_class="payg",
                credential_names=["api-anthropic"],
                readbacks=[{"readback_id": "anthropic_models", "secret": "api-anthropic"}],
            )
        ]
    )
    http = FakeHttp(
        {READBACKS["anthropic_models"].url: HttpResponse(status=status, body=b"", error=None)}
    )
    run = _run(config, holdings=[_holdings(filestore=("api-anthropic",))], http=http)
    row = _row(run, "anthropic-api")
    assert row.state is EntitlementState.DEAD
    assert "api-anthropic" in row.credential_names


# --- unsafe case 4: PAYG rendered as subscription -> cost_class required, unknown is unobserved -------


def test_cost_class_is_required_on_every_declaration() -> None:
    decl = _decl()
    del decl["cost_class"]
    with pytest.raises(ValidationError):
        _config([decl])


def test_unidentified_names_carry_unobserved_cost_never_subscription() -> None:
    run = _run(_config([]), holdings=[_holdings(filestore=("mastadon-access-token",))])
    rows = [row for row in run.rows if not row.identified]
    assert rows and all(row.cost_class is CostClass.UNOBSERVED for row in rows)


# --- unsafe case 5: an entitlement disappears -> row retained with last_seen -------------------------


def test_vanished_entitlement_is_retained_with_last_seen() -> None:
    config = _config([_decl(credential_names=["kimi-api-key"])])
    earlier = NOW - timedelta(days=3)
    first = _run(config, holdings=[_holdings(filestore=("kimi-api-key",))], now=earlier)
    prior = render_view(first, now=earlier)

    later = _run(config, holdings=[_holdings(filestore=())], prior_view=prior)
    row = _row(later, "kimi")
    assert row.state is EntitlementState.ABSENT
    assert row.last_seen == earlier
    assert row.first_seen == earlier


def test_vanished_unidentified_name_is_retained() -> None:
    config = _config([])
    earlier = NOW - timedelta(hours=2)
    first = _run(
        config, holdings=[_holdings(filestore=("bluesky-operator-app-password",))], now=earlier
    )
    later = _run(config, holdings=[_holdings()], prior_view=render_view(first, now=earlier))
    gone = [
        row
        for row in later.rows
        if row.entitlement_id == "unidentified.bluesky-operator-app-password"
    ]
    assert gone and gone[0].state is EntitlementState.ABSENT and gone[0].last_seen == earlier


# --- unsafe case 6: terms-restricted provider probed -> never -----------------------------------------


def test_terms_restricted_declaration_cannot_carry_a_readback() -> None:
    with pytest.raises(ValidationError):
        _config(
            [
                _decl(
                    "qwen",
                    terms_restricted=True,
                    readbacks=[{"readback_id": "kimi_usages", "secret": "qwencloud-apikey"}],
                )
            ]
        )


def test_terms_restricted_provider_is_never_probed() -> None:
    config = _config(
        [
            _decl(
                "qwen",
                provider="alibaba",
                terms_restricted=True,
                credential_names=["qwencloud-apikey"],
            )
        ]
    )
    http, secrets = FakeHttp(), FakeSecrets()
    run = _run(
        config, holdings=[_holdings(filestore=("qwencloud-apikey",))], http=http, secrets=secrets
    )
    assert http.calls == []
    assert "qwencloud-apikey" not in secrets.asked
    assert _row(run, "qwen").state is EntitlementState.TERMS_RESTRICTED


# --- unsafe case 7: a vendor cache read as current -> carry fetched_at, stale past a bound -----------


def _grok_cache(fetched_at: datetime) -> bytes:
    payload = {
        "fetched_at": fetched_at.isoformat().replace("+00:00", "Z"),
        "settings": {"subscription_tier_display": "SuperGrok Heavy"},
    }
    return json.dumps({"payload": json.dumps(payload), "signature": [1, 2, 3]}).encode()


def test_vendor_cache_past_its_bound_is_stale_and_carries_fetched_at() -> None:
    config = _config([_decl("grok", provider="xai", vendor_cache="grok_settings_cache")])
    fetched = NOW - timedelta(days=2)
    run = _run(config, home_files={".grok/settings_cache.json": _grok_cache(fetched)})
    row = _row(run, "grok")
    assert row.state is EntitlementState.STALE
    assert row.evidence_class is EvidenceClass.VENDOR_CACHE
    assert row.observed_at == fetched


def test_fresh_vendor_cache_is_cache_evidence_never_live() -> None:
    config = _config([_decl("grok", provider="xai", vendor_cache="grok_settings_cache")])
    fetched = NOW - timedelta(minutes=30)
    run = _run(config, home_files={".grok/settings_cache.json": _grok_cache(fetched)})
    row = _row(run, "grok")
    assert row.state is EntitlementState.HELD
    assert row.evidence_class is EvidenceClass.VENDOR_CACHE
    assert row.observed_at == fetched
    assert row.facts.get("tier") == "SuperGrok Heavy"


def test_expired_declared_reference_is_stale() -> None:
    ref = {
        "fact": "subscription recorded",
        "source": "record",
        "recorded_at": "2026-07-02T00:00:00Z",
        "expires_at": "2026-08-02T00:00:00Z",
    }
    run = _run(_config([_decl("epidemic", provider="epidemic", declared_refs=[ref])]))
    row = _row(run, "epidemic")
    assert row.state is EntitlementState.STALE
    assert row.evidence_class is EvidenceClass.RECORDED


# --- unsafe case 8: podium needs a remote read -> declared binding, never an interactive login --------


def test_remote_holdings_run_in_batch_mode_without_a_tty() -> None:
    binding = HostBinding(host_id="podium", transport="ssh_batch", target="podium.example")
    argv = holdings_command(binding, login_files=(".codex/auth.json",), harness_bins=("codex",))
    assert argv[0] == "ssh"
    assert "BatchMode=yes" in argv
    assert "-t" not in argv and "-tt" not in argv
    assert "podium.example" in argv
    assert not any("hapax-secret" in part for part in argv)


def test_unreachable_host_leaves_its_rows_unobserved_not_absent_or_dead() -> None:
    config = _config([_decl("verboo", provider="verboo", credential_names=["verboo-api-key"])])
    earlier = NOW - timedelta(hours=1)
    first = _run(
        config,
        holdings=[_holdings(), _holdings("podium", filestore=("verboo-api-key",))],
        now=earlier,
    )
    later = _run(
        config,
        holdings=[_holdings(), _holdings("podium", reachable=False)],
        prior_view=render_view(first, now=earlier),
    )
    row = _row(later, "verboo")
    assert row.state is EntitlementState.UNOBSERVED
    assert row.last_seen == earlier
    assert any("podium" in reason for reason in row.reasons)


def test_holdings_parser_keeps_names_and_mtimes_only() -> None:
    text = "\n".join(
        [
            "F\tkimi-api-key",
            "F\tnot a name; rm -rf",
            "P\tapi/anthropic",
            "E\tGLM_API_KEY",
            "L\t.codex/auth.json\t1790000000",
            "B\tcodex",
        ]
    )
    holdings = parse_holdings("podium", text, now=NOW)
    assert holdings.filestore_names == ("kimi-api-key",)
    assert holdings.pass_names == ("api/anthropic",)
    assert holdings.env_names == ("GLM_API_KEY",)
    assert holdings.login_files[".codex/auth.json"] == datetime.fromtimestamp(1790000000, UTC)
    assert holdings.harness_bins == ("codex",)


# --- the seat's additions: one surface, every row, freshness per row, stale shows as stale ------------


def test_every_declared_entitlement_has_a_row_even_without_evidence() -> None:
    run = _run(
        _config(
            [_decl("copilot", provider="github", cost_class="unobserved", harness_bins=["copilot"])]
        )
    )
    row = _row(run, "copilot")
    assert row.state is EntitlementState.UNOBSERVED
    assert row.freshness is not None


def test_determine_row_holds_the_intake_until_the_registry_declarations_merge() -> None:
    """Seat decision 2026-09-25T01:46Z (option a). The flip is exit-predicate item (7) of
    entitlement-census-producer-20260924: once grok-registry's provider declarations merge, the
    flip PR removes --no-intake and must change this pin on purpose, so the flip is never silent."""
    registry = json.loads(
        (Path(census.REPO_ROOT) / "config" / "determination-producers.json").read_text()
    )
    row = next(p for p in registry["producers"] if p["id"] == "entitlement-census")
    assert "--no-intake" in row["command"]
    assert row["cadence_seconds"] < row["evidence_ttl_seconds"]
    # hapax-determine runs on every host; the census runs only where its bindings hold.
    command = row["command"]
    assert command[command.index("--run-on-host") + 1] == "hapax-appendix"


def test_duplicate_free_config_validates_and_duplicate_ids_are_refused() -> None:
    """Review round 2 (claude-1 on 031c400e) claimed ``_unique`` ends in ``return s``. It ends in
    ``return self``; this pins it: a duplicate-free declaration validates, a duplicate is refused."""
    config = _config([_decl("a"), _decl("b")])
    assert [e.entitlement_id for e in config.entitlements] == ["a", "b"]
    with pytest.raises(ValidationError, match="duplicate entitlement_id"):
        _config([_decl("a"), _decl("a")])


_REF = {
    "fact": "f",
    "source": "s",
    "recorded_at": "2026-09-01T00:00:00Z",
    "expires_at": "2026-10-01T00:00:00Z",
}


@pytest.mark.parametrize(
    ("entitlements", "extra"),
    [
        ([_decl(readbacks=[{"readback_id": "kimi_usages", "secret": None}])], {}),
        ([_decl(readbacks=[{"readback_id": "chat_completions", "secret": "k"}])], {}),
        ([_decl(declared_refs=[{**_REF, "expires_at": "2026-08-01T00:00:00Z"}])], {}),
        ([_decl(declared_refs=[{**_REF, "recorded_at": "2026-09-01T00:00:00"}])], {}),
        ([], {"hosts": [{"host_id": "x", "transport": "ssh_batch"}]}),
        ([], {"hosts": [{"host_id": "x", "transport": "local", "target": "h"}]}),
        (
            [],
            {
                "serving_endpoints": [
                    {
                        "endpoint_id": "e",
                        "host_id": "h",
                        "base_url": "http://h:1/path",
                        "models_path": "/v1/models",
                    }
                ]
            },
        ),
        (
            [
                _decl(
                    terms_restricted=True, readbacks=[{"readback_id": "kimi_usages", "secret": "k"}]
                )
            ],
            {},
        ),
        ([_decl(vendor_cache="nope")], {}),
        ([_decl(login_files=["/etc/passwd"])], {}),
        ([_decl("a"), _decl("a")], {}),
    ],
)
def test_every_declaration_error_names_a_next_action(
    entitlements: list[dict[str, Any]], extra: dict[str, Any]
) -> None:
    """Axiom executive_function: errors must include next actions (review round 2, gemini-1)."""
    with pytest.raises(ValidationError) as excinfo:
        _config(entitlements, **extra)
    assert "next action" in str(excinfo.value).lower()


def test_shipped_config_loads_and_names_every_census_provider() -> None:
    shipped = load_census_config(ENTITLEMENT_CENSUS_CONFIG)
    ids = [e.entitlement_id for e in shipped.entitlements]
    assert len(ids) == len(set(ids))
    providers = {e.provider for e in shipped.entitlements}
    # The 17 cognition providers of E0 section 2, plus the owned fleet.
    for provider in (
        "anthropic",
        "openai",
        "moonshot",
        "z.ai",
        "sakana",
        "mistral",
        "xai",
        "google",
        "meta",
        "xiaomi",
        "alibaba",
        "verboo",
        "featherless",
        "perplexity",
        "openrouter",
        "huggingface",
        "cohere",
        "owned",
    ):
        assert provider in providers, provider


def test_serving_endpoint_is_a_row_with_models_and_freshness() -> None:
    config = _config(
        [],
        serving_endpoints=[
            {
                "endpoint_id": "appendix-5000",
                "host_id": "appendix",
                "base_url": "http://127.0.0.1:5000",
                "models_path": "/v1/models",
            }
        ],
    )
    http = FakeHttp({"http://127.0.0.1:5000/v1/models": _ok({"data": [{"id": "qwen3.6-35b-a3b"}]})})
    run = _run(config, http=http)
    row = _row(run, "serving.appendix-5000")
    assert row.state is EntitlementState.LIVE
    assert row.facts["models"] == "qwen3.6-35b-a3b"
    assert row.fresh_until is not None and row.fresh_until > NOW
    assert http.calls[0][1] == {}


# --- recruitment ladder (anchor 1): align with the routing table and the ledger, never "admitted" -----


def test_recruitment_stage_follows_the_ladder_and_never_claims_admission() -> None:
    registry = {
        "routes": [
            {"route_id": "kimi.interactive.lane", "platform": "kimi", "route_state": "blocked"}
        ],
        "omitted_capability_shapes": [],
    }
    config = _config(
        [
            _decl(
                "kimi",
                credential_names=["kimi-api-key"],
                registry_platforms=["kimi"],
                readbacks=[{"readback_id": "kimi_usages", "secret": "kimi-api-key"}],
            ),
            _decl(
                "featherless",
                provider="featherless",
                cost_class="prepaid",
                credential_names=["featherless-api-key"],
            ),
            _decl(
                "anthropic-api",
                provider="anthropic",
                cost_class="payg",
                credential_names=["api-anthropic"],
                readbacks=[{"readback_id": "anthropic_models", "secret": "api-anthropic"}],
            ),
        ]
    )
    http = FakeHttp(
        {
            READBACKS["kimi_usages"].url: _ok(KIMI_USAGES),
            READBACKS["anthropic_models"].url: HttpResponse(status=401, body=b"", error=None),
        }
    )
    run = _run(
        config,
        holdings=[_holdings(filestore=("kimi-api-key", "featherless-api-key", "api-anthropic"))],
        http=http,
        registry=registry,
    )
    # Declared and measured, but its only route is blocked in the registry: never "routable".
    assert _row(run, "kimi").recruitment_stage == "declared-measured"
    assert _row(run, "featherless").recruitment_stage == "usable-undeclared"
    assert _row(run, "anthropic-api").recruitment_stage == "unusable"
    assert "admitted" not in json.dumps(render_view(run, now=NOW)["rows"])


# --- deltas through the existing intake --------------------------------------------------------------


def _registry() -> dict[str, Any]:
    return {
        "routes": [
            {"route_id": "api.headless.api_frontier", "platform": "api", "route_state": "blocked"},
            {"route_id": "kimi.interactive.lane", "platform": "kimi", "route_state": "blocked"},
        ],
        "omitted_capability_shapes": [
            {
                "shape_id": "local_compute.fugu_surface",
                "shape_class": "local_compute",
                "shape_state": "intake_required",
            },
        ],
    }


def test_held_but_undeclared_emits_new_capability() -> None:
    config = _config(
        [
            _decl(
                "featherless",
                provider="featherless",
                cost_class="prepaid",
                credential_names=["featherless-api-key"],
            )
        ]
    )
    run = _run(
        config, holdings=[_holdings(filestore=("featherless-api-key",))], registry=_registry()
    )
    kinds = {(d.surface_id, d.delta_kind) for d in run.deltas}
    assert ("entitlement.featherless", DeltaKind.NEW_CAPABILITY) in kinds


def test_declared_but_dead_emits_absent_determination() -> None:
    config = _config(
        [
            _decl(
                "anthropic-api",
                provider="anthropic",
                cost_class="payg",
                credential_names=["api-anthropic"],
                readbacks=[{"readback_id": "anthropic_models", "secret": "api-anthropic"}],
                registry_route_ids=["api.headless.api_frontier"],
            )
        ]
    )
    http = FakeHttp(
        {READBACKS["anthropic_models"].url: HttpResponse(status=401, body=b"", error=None)}
    )
    run = _run(
        config, holdings=[_holdings(filestore=("api-anthropic",))], http=http, registry=_registry()
    )
    kinds = {(d.surface_id, d.delta_kind) for d in run.deltas}
    assert ("api.headless.api_frontier", DeltaKind.ABSENT_DETERMINATION) in kinds


def test_misclassified_shape_emits_resource_pool_change() -> None:
    config = _config(
        [
            _decl(
                "fugu",
                provider="sakana",
                credential_names=["sakana-fugu-apikey"],
                registry_shape_ids=["local_compute.fugu_surface"],
                expected_shape_class="model_provider",
            )
        ]
    )
    run = _run(
        config, holdings=[_holdings(filestore=("sakana-fugu-apikey",))], registry=_registry()
    )
    kinds = {(d.surface_id, d.delta_kind) for d in run.deltas}
    assert ("local_compute.fugu_surface", DeltaKind.RESOURCE_POOL_CHANGED) in kinds


def test_reclassified_shape_clears_the_misclassification_without_a_new_capability() -> None:
    """The registry owner replaces the misfiled shape with a model_provider one. Binding both ids
    ahead of that edit means the delta clears by itself, and nothing reads as undeclared."""
    config = _config(
        [
            _decl(
                "fugu",
                provider="sakana",
                credential_names=["sakana-fugu-apikey"],
                registry_shape_ids=["local_compute.fugu_surface", "model_provider.fugu"],
                expected_shape_class="model_provider",
            )
        ]
    )
    after = {
        "routes": [],
        "omitted_capability_shapes": [
            {"shape_id": "model_provider.fugu", "shape_class": "model_provider"}
        ],
    }
    run = _run(config, holdings=[_holdings(filestore=("sakana-fugu-apikey",))], registry=after)
    assert run.deltas == []
    assert _row(run, "fugu").declared_shapes == ("model_provider.fugu",)


def test_delta_ids_are_stable_across_runs_so_intake_never_remints() -> None:
    config = _config(
        [
            _decl(
                "featherless",
                provider="featherless",
                cost_class="prepaid",
                credential_names=["featherless-api-key"],
            )
        ]
    )
    holdings = [_holdings(filestore=("featherless-api-key",))]
    first = _run(config, holdings=holdings, registry=_registry())
    second = _run(config, holdings=holdings, registry=_registry(), now=NOW + timedelta(hours=5))
    assert [d.delta_id for d in first.deltas] == [d.delta_id for d in second.deltas]


# --- quantities are handed to the quota ledger in its measurement shape ------------------------------


def test_kimi_quantities_are_ledger_measurements() -> None:
    config = _config(
        [
            _decl(
                credential_names=["kimi-api-key"],
                measurement_prefixes=["kimi.subscription."],
                readbacks=[{"readback_id": "kimi_usages", "secret": "kimi-api-key"}],
            ),
            _decl(
                "booster",
                cost_class="prepaid",
                credential_names=["kimi-api-key"],
                measurement_prefixes=["kimi.booster."],
                readbacks=[{"readback_id": "kimi_usages", "secret": "kimi-api-key"}],
            ),
        ]
    )
    http = FakeHttp({READBACKS["kimi_usages"].url: _ok(KIMI_USAGES)})
    run = _run(config, holdings=[_holdings(filestore=("kimi-api-key",))], http=http)
    assert len(http.calls) == 1  # one readback shared by both rows
    weekly = [m for m in run.measurements if m["capacity_id"] == "kimi.subscription.weekly"]
    assert weekly and weekly[0]["quantity"] == 5.0 and weekly[0]["unit"] == "percent_used"
    assert weekly[0]["label"] == "observed" and weekly[0]["observed_at"] is not None
    booster = _row(run, "booster")
    assert booster.measurements and all(
        m["capacity_id"].startswith("kimi.booster.") for m in booster.measurements
    )


def test_glm_and_sakana_walls_are_read_with_their_resets() -> None:
    glm = {
        "code": 200,
        "data": {
            "level": "max",
            "limits": [
                {"type": "TOKENS_LIMIT", "unit": 3, "number": 5, "percentage": 0},
                {
                    "type": "TOKENS_LIMIT",
                    "unit": 6,
                    "number": 1,
                    "percentage": 100,
                    "nextResetTime": 1790480184984,
                },
            ],
        },
    }
    sakana = {
        "billing_mode": "subscription",
        "plan": "max",
        "window_usage": {"usage_percent": 5.03, "reset_at": "2026-09-25T02:37:10Z"},
        "weekly_usage": {"usage_percent": 1.75, "reset_at": "2026-09-28T00:00:00Z"},
        "pay_as_you_go": {"available_amount_micro_usd": 0},
    }
    config = _config(
        [
            _decl(
                "glm",
                provider="z.ai",
                credential_names=["glmcp-api-key"],
                readbacks=[{"readback_id": "glm_quota_limit", "secret": "glmcp-api-key"}],
            ),
            _decl(
                "fugu",
                provider="sakana",
                credential_names=["sakana-fugu-apikey"],
                readbacks=[{"readback_id": "sakana_usage", "secret": "sakana-fugu-apikey"}],
            ),
        ]
    )
    http = FakeHttp(
        {READBACKS["glm_quota_limit"].url: _ok(glm), READBACKS["sakana_usage"].url: _ok(sakana)}
    )
    run = _run(
        config, holdings=[_holdings(filestore=("glmcp-api-key", "sakana-fugu-apikey"))], http=http
    )
    by_id = {m["capacity_id"]: m for m in run.measurements}
    assert by_id["glm.subscription.weekly"]["quantity"] == 100.0
    assert by_id["glm.subscription.weekly"]["resets_at"] == "2026-09-27T03:36:24Z"
    assert by_id["fugu.subscription.weekly"]["quantity"] == 1.75
    # The GLM header is the raw key (no Bearer), exactly as E0 measured.
    glm_call = [h for url, h in http.calls if url == READBACKS["glm_quota_limit"].url][0]
    assert glm_call["Authorization"] == SECRET


# --- the potential face: our own metal, never dispatch supply -----------------------------------------


def test_disconnected_egpu_is_potential_and_never_supply() -> None:
    hardware = [
        {
            "host_id": "beelink1",
            "device": "RTX 5060 Ti 16 GB eGPU",
            "memory_gb": 16,
            "availability": "unavailable",
            "until": "a readback shows it enumerated",
            "source": "operator",
            "recorded_at": "2026-09-25T00:03:00Z",
            "expires_at": "2026-10-25T00:03:00Z",
        },
        {
            "host_id": "beelink1",
            "device": "unified host memory",
            "memory_gb": 124,
            "availability": "available",
            "source": "fleet",
            "recorded_at": "2026-09-25T00:03:00Z",
            "expires_at": "2026-10-25T00:03:00Z",
        },
    ]
    run = _run(_config([], metal={"hardware": hardware}))
    view = render_view(run, now=NOW)
    supply_text = json.dumps(view["rows"])
    assert "eGPU" not in supply_text
    egpu = [item for item in view["potential"]["hardware"] if "eGPU" in item["device"]]
    assert egpu and egpu[0]["availability"] == "unavailable"
    assert any(item["memory_gb"] == 124 for item in view["potential"]["hardware"])


def test_scout_candidates_enter_the_experiment_stage_with_safe_fields_only() -> None:
    report = {
        "generated_at": "2026-09-23T15:13:05Z",
        "recommendations": [
            {
                "component": "local-llm-coding",
                "tier": "adopt",
                "current": "qwen3.5:27b via Ollama",
                "confidence": "high",
                "summary": "long model prose " * 20,
                "findings": [{"name": "Qwen3-Coder 30B-A3B-Instruct", "url": "https://x"}],
            },
            {"component": "vector-database", "tier": "adopt", "findings": [{"name": "Other"}]},
        ],
    }
    run = _run(
        _config(
            [],
            metal={
                "scout_report": {
                    "host_id": "podium",
                    "path": "p.json",
                    "components": ["local-llm-coding"],
                }
            },
        ),
        scout_report=report,
    )
    stages = render_view(run, now=NOW)["potential"]["stages"]
    experiment = stages["candidate_to_experiment"]
    assert [item["component"] for item in experiment] == ["local-llm-coding"]
    assert experiment[0]["candidates"] == ["Qwen3-Coder 30B-A3B-Instruct"]
    assert "long model prose" not in json.dumps(stages)


@pytest.mark.parametrize(
    ("probe", "expected"),
    [
        (None, "unavailable"),  # no readback this run: stays as declared
        (lambda host: (False, []), "unavailable"),  # host unreachable
        (
            lambda host: (True, ["NVIDIA GeForce RTX 3090, 24576 MiB"]),
            "unavailable",
        ),  # other GPU only
        (lambda host: (True, ["NVIDIA GeForce RTX 5060 Ti, 16311 MiB"]), "enumerated"),
    ],
)
def test_egpu_is_unavailable_until_a_readback_shows_it_enumerated(probe, expected: str) -> None:
    hardware = [
        {
            "host_id": "beelink1",
            "device": "RTX 5060 Ti 16 GB eGPU",
            "memory_gb": 16,
            "availability": "unavailable",
            "enumerate_gpu": "5060 Ti",
            "source": "operator",
            "recorded_at": "2026-09-25T00:03:00Z",
            "expires_at": "2026-10-25T00:03:00Z",
        }
    ]
    run = _run(_config([], metal={"hardware": hardware}), gpu_probe=probe)
    view = render_view(run, now=NOW)
    assert view["potential"]["hardware"][0]["availability"] == expected
    assert view["rows"] == []  # potential, never supply, even once enumerated


# --- review round 1 (CodeRabbit on #4743): redirects, registry, timezones, run deadline ---------------


def test_a_redirect_never_carries_the_credential_to_another_host() -> None:
    """urllib's default redirect handler copies Authorization onto the redirected request, even
    across hosts. Two real loopback servers: the first redirects, the second must see nothing."""
    import http.server
    import threading

    received: list[str | None] = []

    class Sink(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server API
            received.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *_args: object) -> None:
            return None

    sink = http.server.HTTPServer(("127.0.0.1", 0), Sink)

    class Redirector(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server API
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{sink.server_port}/steal")
            self.end_headers()

        def log_message(self, *_args: object) -> None:
            return None

    redirector = http.server.HTTPServer(("127.0.0.1", 0), Redirector)
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (sink, redirector)]
    for thread in threads:
        thread.start()
    try:
        response = default_http_get(
            f"http://127.0.0.1:{redirector.server_port}/v1/usage",
            {"Authorization": f"Bearer {SECRET}"},
            5,
        )
    finally:
        for server in (sink, redirector):
            server.shutdown()
            server.server_close()
    assert received == []
    assert response.status == 302


def test_redirect_status_is_unobserved_never_live() -> None:
    row = _anthropic_api_row(302)
    assert row.readbacks[0]["outcome"] == "unobserved"
    assert row.state is not EntitlementState.LIVE


def test_registry_that_cannot_be_read_fails_the_run(tmp_path: Path) -> None:
    missing = tmp_path / "absent.json"
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{not json", encoding="utf-8")
    not_object = tmp_path / "list.json"
    not_object.write_text("[]", encoding="utf-8")
    bad_routes = tmp_path / "bad-routes.json"
    bad_routes.write_text('{"routes": {}}', encoding="utf-8")
    for path in (missing, malformed, not_object, bad_routes):
        with pytest.raises(CensusConfigError):
            load_registry(path)
    empty = tmp_path / "empty.json"
    empty.write_text("{}", encoding="utf-8")
    assert load_registry(empty) == {}


@pytest.mark.parametrize("section", ["hardware", "trial_records"])
def test_potential_face_dates_must_carry_a_timezone(section: str) -> None:
    item: dict[str, Any] = (
        {"host_id": "h", "device": "d", "memory_gb": 1, "availability": "available", "source": "s"}
        if section == "hardware"
        else {"model": "m", "stage": "deployed", "evidence": "e"}
    )
    item.update(recorded_at="2026-09-25T00:00:00", expires_at="2026-10-25T00:00:00Z")
    with pytest.raises(ValidationError):
        _config([], metal={section: [item]})


def test_past_the_run_deadline_nothing_more_is_probed() -> None:
    config = _config(
        [
            _decl(
                credential_names=["kimi-api-key"],
                readbacks=[{"readback_id": "kimi_usages", "secret": "kimi-api-key"}],
            )
        ],
        serving_endpoints=[
            {
                "endpoint_id": "appendix-5000",
                "host_id": "appendix",
                "base_url": "http://127.0.0.1:5000",
                "models_path": "/v1/models",
            }
        ],
        metal={
            "hardware": [
                {
                    "host_id": "beelink1",
                    "device": "RTX 5060 Ti 16 GB eGPU",
                    "memory_gb": 16,
                    "availability": "unavailable",
                    "enumerate_gpu": "5060 Ti",
                    "source": "s",
                    "recorded_at": "2026-09-25T00:03:00Z",
                    "expires_at": "2026-10-25T00:03:00Z",
                }
            ]
        },
    )
    http, secrets, probed = FakeHttp(), FakeSecrets(), []
    run = _run(
        config,
        holdings=[_holdings(filestore=("kimi-api-key",))],
        http=http,
        secrets=secrets,
        gpu_probe=lambda host: probed.append(host) or (True, []),
        deadline=100.0,
        clock=lambda: 200.0,
    )
    assert http.calls == [] and secrets.asked == [] and probed == []
    assert _row(run, "kimi").readbacks[0]["outcome"] == "unobserved"
    assert any("deadline" in reason for reason in _row(run, "kimi").reasons)
    assert _row(run, "serving.appendix-5000").state is EntitlementState.UNOBSERVED
    assert any("deadline" in r for r in _row(run, "serving.appendix-5000").reasons)


# --- clause (8): the trend face ("are we ratcheting up our capability usage and availability for
# demand?", operator 2026-09-24T23:33:04Z), with wall events per pool (seat 2026-09-25T05:12Z) -----


def _record(
    ts: datetime,
    *,
    windows: dict[str, float],
    live: int = 1,
    queued: int = 10,
    dispatched: int = 0,
    witness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    states = {f"e{i}": "live" for i in range(live)}
    return {
        "ts": ts.isoformat().replace("+00:00", "Z"),
        "states": states,
        "windows": [[cid, q, "percent_used", "300m", None] for cid, q in windows.items()],
        "demand": {
            "queued": {"queued": queued, "by_status": {"offered": queued}},
            "dispatched": {
                "total": dispatched,
                "by_platform": {},
                "stale": False,
                "last_record_at": None,
            },
        },
        "witness": witness or {},
    }


def test_trend_reads_ratchet_direction_on_every_axis() -> None:
    history = [
        _record(
            NOW - timedelta(hours=6), windows={"kimi.subscription.weekly": 5.0}, live=20, queued=800
        ),
        _record(
            NOW - timedelta(hours=3),
            windows={"kimi.subscription.weekly": 10.0},
            live=20,
            queued=850,
        ),
        _record(NOW, windows={"kimi.subscription.weekly": 20.0}, live=21, queued=900),
    ]
    trend = compute_trend(history, now=NOW)
    assert trend["usage"]["direction"] == "up"
    assert trend["availability"]["direction"] == "up"
    assert trend["demand"]["queued_direction"] == "up"
    assert trend["windows"]["kimi.subscription.weekly"]["first"] == 5.0
    assert trend["windows"]["kimi.subscription.weekly"]["last"] == 20.0


def test_a_snapshot_is_insufficient_history_never_a_direction() -> None:
    trend = compute_trend([_record(NOW, windows={"glm.subscription.weekly": 100.0})], now=NOW)
    assert trend["usage"]["direction"] == "insufficient_history"
    assert trend["availability"]["direction"] == "insufficient_history"


def test_wall_events_are_counted_per_pool_as_episodes() -> None:
    k5, gw = "kimi.subscription.five_hour", "glm.subscription.weekly"
    history = [
        _record(NOW - timedelta(hours=4), windows={k5: 40.0, gw: 100.0}),
        _record(NOW - timedelta(hours=3), windows={k5: 100.0, gw: 100.0}),
        _record(NOW - timedelta(hours=2), windows={k5: 100.0, gw: 100.0}),
        _record(NOW - timedelta(hours=1), windows={k5: 30.0, gw: 100.0}),
        _record(
            NOW,
            windows={k5: 100.0, gw: 100.0},
            witness={"codex": {"cause": "quota_wall", "outage_started_at": "2026-09-25T03:21:11Z"}},
        ),
    ]
    walls = compute_trend(history, now=NOW)["walls"]
    assert walls["by_window"][k5]["episodes"] == 2
    assert walls["by_window"][k5]["at_wall_now"] is True
    assert walls["by_window"][gw]["episodes"] == 1
    assert walls["by_pool"]["kimi.subscription"] == 2
    assert walls["witness"]["codex"]["cause"] == "quota_wall"


def test_trend_ignores_history_outside_its_window() -> None:
    old = _record(NOW - timedelta(days=30), windows={"kimi.subscription.weekly": 90.0})
    recent = [
        _record(NOW - timedelta(hours=2), windows={"kimi.subscription.weekly": 10.0}),
        _record(NOW, windows={"kimi.subscription.weekly": 10.0}),
    ]
    trend = compute_trend([old, *recent], now=NOW)
    assert trend["windows"]["kimi.subscription.weekly"]["first"] == 10.0
    assert trend["usage"]["direction"] == "flat"


def test_history_is_a_chained_durable_stream_append_only_and_secret_scanned(tmp_path: Path) -> None:
    """The series lives on the estate's durable append-only primitive (shared/durable_jsonl_sink.py,
    per-stream SHA-256 chain), not a bespoke file: align, per frame/append-only-logs-20260925."""
    from shared.durable_jsonl_sink import DurableJsonlSink, validate_chain

    config = _config([_decl(credential_names=["kimi-api-key"])])
    out, sink_root = tmp_path / "out", tmp_path / "sink"
    sink_root.mkdir()
    stream = DurableJsonlSink(sink_root).path_for_stream(census.HISTORY_STREAM)
    first = _run(
        config, holdings=[_holdings(filestore=("kimi-api-key",))], now=NOW - timedelta(hours=1)
    )
    attach_history(first, now=NOW - timedelta(hours=1), prior=[], demand={}, witness={})
    write_outputs(
        first,
        output_root=out,
        projection_md=None,
        now=NOW - timedelta(hours=1),
        history_sink_root=sink_root,
    )
    line_one = stream.read_text(encoding="utf-8")

    second = _run(config, holdings=[_holdings(filestore=("kimi-api-key",))])
    attach_history(second, now=NOW, prior=load_history(stream, now=NOW), demand={}, witness={})
    write_outputs(second, output_root=out, projection_md=None, now=NOW, history_sink_root=sink_root)
    text = stream.read_text(encoding="utf-8")
    assert text.startswith(line_one) and len(text.splitlines()) == 2
    assert not validate_chain(stream, stream_id=census.HISTORY_STREAM).issues
    assert render_view(second, now=NOW)["trend"]["points"] == 2

    leaky = _run(config, holdings=[_holdings(filestore=("kimi-api-key",))])
    leaky.secrets.remember(SECRET)
    attach_history(leaky, now=NOW, prior=[], demand={"queued": {"note": SECRET}}, witness={})
    with pytest.raises(SecretLeakError):
        write_outputs(
            leaky, output_root=out, projection_md=None, now=NOW, history_sink_root=sink_root
        )
    assert stream.read_text(encoding="utf-8") == text


def test_history_reader_accepts_the_pre_sink_plain_records(tmp_path: Path) -> None:
    plain = tmp_path / "history.jsonl"
    plain.write_text(
        json.dumps(_record(NOW, windows={"kimi.subscription.weekly": 45.0})) + "\n",
        encoding="utf-8",
    )
    assert load_history(plain, now=NOW)[0]["windows"][0][1] == 45.0


# --- utilization per entitlement (operator-accepted 2026-09-25T10:15Z: "underuse is the failure to
# surface"; Featherless $200/month prepaid, Verboo flat-price) -----------------------------------------


def _kimi_weekly(used: float, elapsed_pct: float) -> dict[str, Any]:
    reset = NOW + timedelta(minutes=10080 * (1 - elapsed_pct / 100))
    return {
        "usage": {
            "limit": "100",
            "used": str(used),
            "remaining": "0",
            "resetTime": reset.isoformat().replace("+00:00", "Z"),
        }
    }


def _kimi_run(used: float, elapsed_pct: float):
    config = _config(
        [
            _decl(
                credential_names=["kimi-api-key"],
                monthly_cost_usd=39.0,
                readbacks=[{"readback_id": "kimi_usages", "secret": "kimi-api-key"}],
            )
        ]
    )
    http = FakeHttp({READBACKS["kimi_usages"].url: _ok(_kimi_weekly(used, elapsed_pct))})
    return _run(config, holdings=[_holdings(filestore=("kimi-api-key",))], http=http)


def test_window_well_below_pace_is_underuse() -> None:
    utilization = _row(_kimi_run(used=5, elapsed_pct=80), "kimi").utilization
    assert utilization["basis"] == "window_pace"
    assert utilization["underuse"] is True
    assert utilization["pace_ratio"] == pytest.approx(5 / 80, abs=0.01)


def test_window_on_pace_is_not_underuse() -> None:
    assert _row(_kimi_run(used=45, elapsed_pct=30), "kimi").utilization["underuse"] is False


def test_early_window_is_not_judged() -> None:
    utilization = _row(_kimi_run(used=1, elapsed_pct=10), "kimi").utilization
    assert utilization["underuse"] is None


def test_no_usage_evidence_is_unjudged_never_silently_fine() -> None:
    run = _run(
        _config(
            [
                _decl(
                    "cohere",
                    provider="cohere",
                    cost_class="unobserved",
                    credential_names=["cohere-api-key"],
                )
            ]
        ),
        holdings=[_holdings(filestore=("cohere-api-key",))],
    )
    utilization = _row(run, "cohere").utilization
    assert utilization["basis"] == "none" and utilization["underuse"] is None


def _ledger_decl(entitlement_id: str, **fields: Any) -> dict[str, Any]:
    return _decl(
        entitlement_id, provider=entitlement_id, usage_ledger=True, renewal_day=19, **fields
    )


def test_prepaid_with_zero_recorded_calls_is_underuse() -> None:
    config = _config([_ledger_decl("featherless", cost_class="prepaid", monthly_cost_usd=200.0)])
    run = _run(config, provider_calls={})
    utilization = _row(run, "featherless").utilization
    assert utilization["basis"] == "per_call_ledger"
    assert utilization["calls"] == 0 and utilization["underuse"] is True
    assert "0 calls recorded" in utilization["reason"]


def test_unreadable_ledger_is_unjudged_never_zero_calls() -> None:
    """Zero calls is a finding; a ledger that could not be read is not. Keep them apart."""
    config = _config([_ledger_decl("featherless", cost_class="prepaid", monthly_cost_usd=200.0)])
    utilization = _row(_run(config, provider_calls=None), "featherless").utilization
    assert utilization["underuse"] is None
    assert "not read" in utilization["reason"]


def test_flat_price_slots_utilization_is_busy_time_over_slot_capacity() -> None:
    config = _config([_ledger_decl("verboo", monthly_cost_usd=269.0, concurrency_slots=2)])
    # Period renews on the 19th: 2026-09-19T00:00Z to NOW is 6 d 1 h.
    elapsed = (NOW - datetime(2026, 9, 19, tzinfo=UTC)).total_seconds()
    light = _run(
        config, provider_calls={"verboo": {"calls": 3, "tokens": 900, "busy_seconds": 3600.0}}
    )
    heavy_busy = 0.25 * 2 * elapsed
    heavy = _run(
        config, provider_calls={"verboo": {"calls": 400, "tokens": 9e5, "busy_seconds": heavy_busy}}
    )
    assert _row(light, "verboo").utilization["used_pct"] == pytest.approx(
        3600 / (2 * elapsed) * 100, abs=0.01
    )
    assert _row(light, "verboo").utilization["underuse"] is True
    assert _row(heavy, "verboo").utilization["used_pct"] == pytest.approx(25.0, abs=0.01)
    assert _row(heavy, "verboo").utilization["underuse"] is False


def test_underuse_is_surfaced_first_ranked_by_monthly_cost() -> None:
    config = _config(
        [
            _ledger_decl("featherless", cost_class="prepaid", monthly_cost_usd=200.0),
            _ledger_decl("verboo", monthly_cost_usd=269.0, concurrency_slots=2),
            _decl(
                "cohere",
                provider="cohere",
                cost_class="unobserved",
                credential_names=["cohere-api-key"],
            ),
        ]
    )
    view = render_view(_run(config, provider_calls={}), now=NOW)
    assert [u["entitlement_id"] for u in view["underuse"]] == ["verboo", "featherless"]
    assert view["utilization_unjudged"] >= 1
    md = render_markdown(view)
    assert md.index("## Underuse") < md.index("## Cognition")


def test_paid_capacity_nobody_can_judge_is_named_not_counted() -> None:
    """A paid entitlement with no usage evidence is a surfacing failure too: name it, with its cost."""
    config = _config(
        [
            _decl(
                "mimo",
                provider="mimo",
                cost_class="subscription",
                monthly_cost_usd=200.0,
                credential_names=["mimo-api-key"],
            ),
            _decl(
                "cohere",
                provider="cohere",
                cost_class="unobserved",
                credential_names=["cohere-api-key"],
            ),
        ]
    )
    run = _run(config, holdings=[_holdings(filestore=("mimo-api-key", "cohere-api-key"))])
    view = render_view(run, now=NOW)
    assert [(u["entitlement_id"], u["monthly_cost_usd"]) for u in view["paid_unjudged"]] == [
        ("mimo", 200.0)
    ]
    assert view["underuse"] == []
    underuse_section = render_markdown(view).split("## Underuse", 1)[1].split("## Hosts", 1)[0]
    assert "mimo" in underuse_section and "cohere" not in underuse_section


def test_provider_call_ledger_reads_counts_only(tmp_path: Path) -> None:
    from shared.durable_jsonl_sink import DurableJsonlSink

    root = tmp_path / "sink"
    root.mkdir()
    sink = DurableJsonlSink(root)

    def row(call_id: str, phase: str, started: str, **final: Any) -> None:
        # dev22's contract (lanebus/dev16/20260925T102149Z): a write-ahead pair per call, the
        # "attempted" row before egress and the "final" row after, sharing call_id.
        sink.append(
            stream_id=census.PROVIDER_CALLS_STREAM,
            data_class="provider_call",
            source_receipt_ref="test",
            payload={
                "provider": "verboo",
                "entitlement_id": "verboo",
                "call_id": call_id,
                "phase": phase,
                "started_at": started,
                "status": None,
                "http_status": None,
                "ended_at": None,
                "tokens_in": None,
                "tokens_out": None,
                "prompt": "private prose " + SECRET,
                **final,
            },
        )

    row("a", "attempted", "2026-09-24T10:00:00Z")
    row(
        "a",
        "final",
        "2026-09-24T10:00:00Z",
        status="ok",
        http_status=200,
        ended_at="2026-09-24T10:00:30Z",
        tokens_in=100,
        tokens_out=50,
    )
    row("b", "attempted", "2026-09-24T11:00:00Z")  # crashed mid-call: no final row
    row("c", "attempted", "2026-09-18T10:00:00Z")  # before the period
    row(
        "c",
        "final",
        "2026-09-18T10:00:00Z",
        status="ok",
        ended_at="2026-09-18T10:05:00Z",
        tokens_in=1,
        tokens_out=1,
    )
    calls = census.read_provider_calls(
        sink.path_for_stream(census.PROVIDER_CALLS_STREAM),
        since=datetime(2026, 9, 19, tzinfo=UTC),
        until=NOW,
    )
    # An attempted call with no final still counts, so utilization never under-reports.
    assert calls == {
        "verboo": {
            "calls": 2,
            "tokens": 150,
            "busy_seconds": 30.0,
            "errors": 0,
            "incomplete": 1,
            "last_at": "2026-09-24T11:00:00Z",
        }
    }
    assert SECRET not in json.dumps(calls)


def test_queued_demand_counts_task_row_status(tmp_path: Path) -> None:
    for name, status in (("a", "offered"), ("b", "ready"), ("c", "in_progress"), ("d", "offered")):
        (tmp_path / f"{name}.md").write_text(
            f"---\nstatus: {status}\n---\n# x\nstatus: done\n", "utf-8"
        )
    demand = read_queued_demand(tmp_path)
    assert demand["by_status"] == {"offered": 2, "ready": 1, "in_progress": 1}
    assert demand["queued"] == 3 and demand["in_flight"] == 1


def test_dispatched_demand_carries_its_own_staleness(tmp_path: Path) -> None:
    path = tmp_path / "route-decisions.jsonl"
    rows = [
        {
            "created_at": "2026-09-23T14:07:49Z",
            "platform": "codex",
            "route_id": "codex.headless.full",
        },
        {
            "created_at": "2026-09-25T00:30:00Z",
            "platform": "claude",
            "route_id": "claude.headless.full",
        },
        {
            "created_at": "2026-09-25T00:40:00Z",
            "platform": "claude",
            "route_id": "claude.headless.full",
        },
    ]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    fresh = read_dispatched_demand(path, now=NOW)
    assert fresh["by_platform"] == {"claude": 2} and fresh["stale"] is False
    later = read_dispatched_demand(path, now=NOW + timedelta(days=3))
    assert later["total"] == 0 and later["stale"] is True
    assert later["last_record_at"] == "2026-09-25T00:40:00Z"
    assert read_dispatched_demand(tmp_path / "absent.jsonl", now=NOW)["stale"] is True
    # Measured live 2026-09-25T05:23Z: the last decision was 15 h old, inside the 24 h counting
    # window, while every lane was being dispatched by hand. A recorder that ran at ~27 decisions/h
    # and has been silent for over an hour is not recording: stale, whatever the window holds.
    quiet = read_dispatched_demand(path, now=datetime(2026, 9, 25, 2, 0, tzinfo=UTC))
    assert quiet["stale"] is True and quiet["total"] == 2
    assert quiet["last_record_age_hours"] == pytest.approx(1.33, abs=0.01)


def test_wall_witness_projects_timestamps_and_cause_only(tmp_path: Path) -> None:
    path = tmp_path / "family-outage.json"
    path.write_text(
        json.dumps(
            {
                "codex": {
                    "observed_at": "2026-09-25T04:41:52+00:00",
                    "outage_started_at": "2026-09-25T03:21:11+00:00",
                    "cause": "quota_wall",
                    "note": "free prose " + SECRET,
                    "wall_evidence": {
                        "source": "local-trace:codex_rollout_token_count:05418909e0e96dce"
                    },
                },
                "claude": "2026-09-16T13:18:09Z",
            }
        ),
        encoding="utf-8",
    )
    witness = read_wall_witness(path)
    assert witness["codex"] == {
        "observed_at": "2026-09-25T04:41:52Z",
        "outage_started_at": "2026-09-25T03:21:11Z",
        "cause": "quota_wall",
    }
    assert witness["claude"] == {"observed_at": "2026-09-16T13:18:09Z"}
    assert SECRET not in json.dumps(witness)
