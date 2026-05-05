#!/usr/bin/env python3
"""Prepare and optionally execute Stripe Tax + Payment Link bootstrap.

The runner handles the automation Stripe exposes through the merchant REST API:
product creation, price creation, Payment Link creation with automatic tax, and
webhook endpoint registration for the existing receive-only rail. Direct
merchant signup, EIN/KYC, payout bank verification, pass-store writes, and live
charges remain explicit operator gates.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

STRIPE_API_BASE = "https://api.stripe.com/v1"
DEFAULT_PRODUCTS_CONFIG = Path(
    os.environ.get(
        "HAPAX_STRIPE_PRODUCTS_CONFIG",
        str(Path.home() / ".config/hapax/stripe-products.toml"),
    )
)
DEFAULT_OUTPUT_DIR = Path.home() / ".local/state/hapax/stripe-bootstrap-runner"
DEFAULT_VAULT_NOTE = Path.home() / "Documents/Personal/30-areas/hapax/stripe-bootstrap-record.md"
DEFAULT_API_KEY_ENV = "STRIPE_SECRET_KEY"
LIVE_CONFIRM_ENV = "HAPAX_STRIPE_BOOTSTRAP_LIVE"
WEBHOOK_URL_ENV = "HAPAX_STRIPE_WEBHOOK_URL"
PAYMENT_RAIL_ROUTE = "/api/stripe-webhook"
CANONICAL_PAYMENT_RAIL_ROUTE = "/api/payment-rails/stripe-payment-link"
API_KEY_PASS_ENTRY = "api/stripe-secret"
WEBHOOK_SECRET_PASS_ENTRY = "api/stripe-webhook-secret"

WEBHOOK_EVENTS: tuple[str, ...] = (
    "payment_intent.succeeded",
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.deleted",
)

DEFERRED_WEBHOOK_EVENTS: dict[str, str] = {
    "charge.refunded": (
        "refund review is intentionally operator-mediated at v1; do not point "
        "this event at the Payment Link fulfillment receiver"
    ),
    "customer.tax_id.updated": (
        "tax-id updates can contain taxpayer data; wire only after a dedicated "
        "non-PII tax handler exists"
    ),
}

OPERATOR_GATES: tuple[str, ...] = (
    "create or verify the direct Stripe merchant account in the Stripe portal",
    "enter LLC EIN, DBA, beneficial-owner identity, and payout bank details",
    "complete Stripe identity/KYC review and any manual risk review",
    "confirm tax registrations with the relevant authority before creating "
    "Stripe tax.registration objects",
    "set the Stripe head-office address before creating tax registrations",
    f"store live credentials in pass entries {API_KEY_PASS_ENTRY!r} and "
    f"{WEBHOOK_SECRET_PASS_ENTRY!r}",
    "run the first live $1 charge and confirm RevenueMetricsDashboard ingestion",
)

EXAMPLE_CONFIG = """# No secrets, EINs, tax IDs, bank details, or API keys belong in this file.
[defaults]
currency = "usd"
tax_behavior = "exclusive"
metadata = { mode_ceiling = "monetized", surface = "stripe-payment-link" }

[[products]]
slug = "article50-cert-starter"
name = "Hapax - Claude Code - Oudepode - Article 50 Compliance Cert (Starter)"
description = "One Article 50 provenance certificate issuance."
unit_amount_cents = 100
tax_code = "txcd_10000000"
success_url = "https://example.invalid/hapax/stripe/success?product=article50-cert-starter"

[[products]]
slug = "supporter-monthly"
name = "Hapax - Claude Code - Oudepode - Supporter Monthly"
description = "Recurring supporter payment link."
unit_amount_cents = 500
recurring_interval = "month"
tax_code = "txcd_10000000"

# Uncomment only after the operator has the legal tax registration and Stripe
# head-office address in place. Stripe uses IE OSS for EU union one-stop-shop
# registration; do not create this as a legal substitute for authority filing.
# [[tax_registrations]]
# slug = "ie-oss-union"
# country = "IE"
# active_from = "now"
# country_options = { ie = { type = "oss_union" } }
"""

SENSITIVE_CONFIG_KEY_RE = re.compile(
    r"(?:^|_)(?:ein|ssn|itin|dob|taxpayer|beneficial_owner|routing|"
    r"account_number|bank_account|secret|api_key|password|token|private_key)(?:_|$)",
    re.IGNORECASE,
)
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,80}$")
CURRENCY_RE = re.compile(r"^[a-z]{3}$")
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
TAX_BEHAVIORS = frozenset({"exclusive", "inclusive", "unspecified"})
RECURRING_INTERVALS = frozenset({"day", "week", "month", "year"})


class ConfigError(ValueError):
    """Invalid Stripe products config."""


class HttpPoster(Protocol):
    def post(
        self,
        url: str,
        *,
        data: Sequence[tuple[str, str]],
        headers: Mapping[str, str],
        timeout: float,
    ) -> Any:
        """Post form-encoded data and return a response-like object."""


@dataclass(frozen=True)
class ProductSpec:
    slug: str
    name: str
    unit_amount_cents: int
    currency: str = "usd"
    tax_behavior: str = "exclusive"
    tax_code: str | None = None
    description: str | None = None
    recurring_interval: str | None = None
    success_url: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, entry: Mapping[str, Any]) -> ProductSpec:
        metadata = entry.get("metadata", {})
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, Mapping):
            raise ConfigError("product metadata must be a TOML table")

        spec = cls(
            slug=_required_str(entry, "slug"),
            name=_required_str(entry, "name"),
            unit_amount_cents=_required_int(entry, "unit_amount_cents"),
            currency=_optional_str(entry, "currency", default="usd").lower(),
            tax_behavior=_optional_str(entry, "tax_behavior", default="exclusive").lower(),
            tax_code=_optional_str(entry, "tax_code"),
            description=_optional_str(entry, "description"),
            recurring_interval=_optional_str(entry, "recurring_interval"),
            success_url=_optional_str(entry, "success_url"),
            metadata={str(k): str(v) for k, v in metadata.items()},
        )
        spec.validate()
        return spec

    def validate(self) -> None:
        if not SLUG_RE.fullmatch(self.slug):
            raise ConfigError(f"invalid product slug: {self.slug!r}")
        if not self.name.strip():
            raise ConfigError(f"{self.slug}: product name must be non-empty")
        if self.unit_amount_cents <= 0:
            raise ConfigError(f"{self.slug}: unit_amount_cents must be positive")
        if not CURRENCY_RE.fullmatch(self.currency):
            raise ConfigError(f"{self.slug}: currency must be a lowercase ISO-4217 code")
        if self.tax_behavior not in TAX_BEHAVIORS:
            raise ConfigError(f"{self.slug}: invalid tax_behavior {self.tax_behavior!r}")
        if self.recurring_interval is not None:
            if self.recurring_interval not in RECURRING_INTERVALS:
                raise ConfigError(
                    f"{self.slug}: invalid recurring_interval {self.recurring_interval!r}"
                )


@dataclass(frozen=True)
class TaxRegistrationSpec:
    slug: str
    country: str
    country_options: dict[str, Any]
    active_from: str = "now"

    @classmethod
    def from_mapping(cls, entry: Mapping[str, Any]) -> TaxRegistrationSpec:
        country_options = entry.get("country_options")
        if not isinstance(country_options, Mapping) or not country_options:
            raise ConfigError("tax registration country_options must be a non-empty table")
        spec = cls(
            slug=_required_str(entry, "slug"),
            country=_required_str(entry, "country").upper(),
            active_from=_optional_str(entry, "active_from", default="now") or "now",
            country_options=_jsonish_dict(country_options, path="country_options"),
        )
        spec.validate()
        return spec

    def validate(self) -> None:
        if not SLUG_RE.fullmatch(self.slug):
            raise ConfigError(f"invalid tax registration slug: {self.slug!r}")
        if not COUNTRY_RE.fullmatch(self.country):
            raise ConfigError(f"{self.slug}: country must be an ISO-3166 alpha-2 code")


@dataclass(frozen=True)
class BootstrapSecrets:
    webhook_secret: str | None = None


class StripeRestClient:
    """Small REST client for Stripe form-encoded API calls."""

    def __init__(
        self,
        api_key: str,
        *,
        http: HttpPoster | None = None,
        api_base: str = STRIPE_API_BASE,
    ) -> None:
        self._api_key = api_key
        self._http = http if http is not None else httpx.Client()
        self._api_base = api_base.rstrip("/")

    def post(self, resource: str, params: Mapping[str, Any]) -> dict[str, Any]:
        url = f"{self._api_base}/{resource.lstrip('/')}"
        response = self._http.post(
            url,
            data=stripe_form_pairs(params),
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=30.0,
        )
        status_code = int(getattr(response, "status_code", 0))
        if status_code >= 400:
            body = getattr(response, "text", "")
            raise RuntimeError(f"Stripe API POST {resource} failed: {status_code} {body}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Stripe API POST {resource} returned non-object JSON")
        return payload


def _required_str(entry: Mapping[str, Any], key: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"missing required string field {key!r}")
    return value.strip()


def _optional_str(entry: Mapping[str, Any], key: str, *, default: str | None = None) -> str | None:
    value = entry.get(key, default)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"optional field {key!r} must be a non-empty string when present")
    return value.strip()


def _required_int(entry: Mapping[str, Any], key: str) -> int:
    value = entry.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"missing required integer field {key!r}")
    return value


def _reject_sensitive_keys(value: Any, *, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_str = str(key)
            if SENSITIVE_CONFIG_KEY_RE.search(key_str):
                raise ConfigError(f"sensitive key {path}.{key_str} is not allowed in config")
            _reject_sensitive_keys(nested, path=f"{path}.{key_str}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_sensitive_keys(nested, path=f"{path}[{index}]")


def load_products_config(path: Path) -> list[ProductSpec]:
    raw = _load_config(path)
    products = raw.get("products")
    if not isinstance(products, list) or not products:
        raise ConfigError("products config must contain at least one [[products]] table")

    defaults_raw = raw.get("defaults", {})
    if defaults_raw is None:
        defaults_raw = {}
    if not isinstance(defaults_raw, Mapping):
        raise ConfigError("[defaults] must be a TOML table when present")

    defaults = dict(defaults_raw)
    default_metadata = defaults.pop("metadata", {})
    if default_metadata is None:
        default_metadata = {}
    if not isinstance(default_metadata, Mapping):
        raise ConfigError("[defaults].metadata must be a TOML table when present")

    specs: list[ProductSpec] = []
    for entry in products:
        if not isinstance(entry, Mapping):
            raise ConfigError("each [[products]] entry must be a TOML table")
        merged = {**defaults, **entry}
        entry_metadata = entry.get("metadata", {}) or {}
        if not isinstance(entry_metadata, Mapping):
            raise ConfigError("[[products]].metadata must be a TOML table when present")
        metadata = {**dict(default_metadata), **dict(entry_metadata)}
        merged["metadata"] = metadata
        specs.append(ProductSpec.from_mapping(merged))
    return specs


def load_tax_registration_config(path: Path) -> list[TaxRegistrationSpec]:
    raw = _load_config(path)
    registrations = raw.get("tax_registrations", [])
    if registrations is None:
        registrations = []
    if not isinstance(registrations, list):
        raise ConfigError("[[tax_registrations]] must be TOML tables")
    specs: list[TaxRegistrationSpec] = []
    for entry in registrations:
        if not isinstance(entry, Mapping):
            raise ConfigError("each [[tax_registrations]] entry must be a TOML table")
        specs.append(TaxRegistrationSpec.from_mapping(entry))
    return specs


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"products config not found: {path}")
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    _reject_sensitive_keys(raw)
    return raw


def _jsonish_dict(value: Mapping[str, Any], *, path: str) -> dict[str, Any]:
    converted: dict[str, Any] = {}
    for key, nested in value.items():
        key_str = str(key)
        nested_path = f"{path}.{key_str}"
        if isinstance(nested, Mapping):
            converted[key_str] = _jsonish_dict(nested, path=nested_path)
        elif isinstance(nested, list):
            converted[key_str] = [
                _jsonish_dict(item, path=f"{nested_path}[]") if isinstance(item, Mapping) else item
                for item in nested
            ]
        elif isinstance(nested, str | int | bool):
            converted[key_str] = nested
        else:
            raise ConfigError(f"{nested_path} contains unsupported TOML value")
    return converted


def _base_metadata(spec: ProductSpec) -> dict[str, str]:
    return {
        "hapax_slug": spec.slug,
        "mode_ceiling": "monetized",
        "rail": "stripe-payment-link",
        **spec.metadata,
    }


def product_params(spec: ProductSpec) -> dict[str, Any]:
    params: dict[str, Any] = {"name": spec.name, "metadata": _base_metadata(spec)}
    if spec.description:
        params["description"] = spec.description
    if spec.tax_code:
        params["tax_code"] = spec.tax_code
    return params


def price_params(spec: ProductSpec, *, product_id: str) -> dict[str, Any]:
    params: dict[str, Any] = {
        "product": product_id,
        "unit_amount": spec.unit_amount_cents,
        "currency": spec.currency,
        "tax_behavior": spec.tax_behavior,
        "metadata": _base_metadata(spec),
    }
    if spec.recurring_interval:
        params["recurring"] = {"interval": spec.recurring_interval}
    return params


def payment_link_params(spec: ProductSpec, *, price_id: str) -> dict[str, Any]:
    params: dict[str, Any] = {
        "line_items": [{"price": price_id, "quantity": 1}],
        "automatic_tax": {"enabled": True},
        "metadata": _base_metadata(spec),
    }
    if spec.success_url:
        params["after_completion"] = {
            "type": "redirect",
            "redirect": {"url": spec.success_url},
        }
    return params


def webhook_endpoint_params(webhook_url: str) -> dict[str, Any]:
    return {
        "url": webhook_url,
        "enabled_events": list(WEBHOOK_EVENTS),
        "metadata": {
            "hapax_route": PAYMENT_RAIL_ROUTE,
            "hapax_delegate_route": CANONICAL_PAYMENT_RAIL_ROUTE,
            "mode_ceiling": "monetized",
            "rail": "stripe-payment-link",
        },
    }


def tax_registration_params(spec: TaxRegistrationSpec) -> dict[str, Any]:
    return {
        "country": spec.country,
        "country_options": spec.country_options,
        "active_from": spec.active_from,
    }


def stripe_form_pairs(params: Mapping[str, Any]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for key, value in params.items():
        _append_form_pairs(pairs, str(key), value)
    return pairs


def _append_form_pairs(pairs: list[tuple[str, str]], key: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, Mapping):
        for nested_key, nested_value in value.items():
            _append_form_pairs(pairs, f"{key}[{nested_key}]", nested_value)
        return
    if isinstance(value, list | tuple):
        for index, nested_value in enumerate(value):
            _append_form_pairs(pairs, f"{key}[{index}]", nested_value)
        return
    if isinstance(value, bool):
        pairs.append((key, "true" if value else "false"))
        return
    pairs.append((key, str(value)))


def build_plan(
    specs: Sequence[ProductSpec],
    *,
    webhook_url: str | None,
    tax_registrations: Sequence[TaxRegistrationSpec] = (),
    now: datetime | None = None,
) -> dict[str, Any]:
    created_at = (now or datetime.now(UTC)).isoformat().replace("+00:00", "Z")
    products = [
        {
            "slug": spec.slug,
            "product_create": product_params(spec),
            "price_create": price_params(spec, product_id=f"{{product:{spec.slug}}}"),
            "payment_link_create": payment_link_params(spec, price_id=f"{{price:{spec.slug}}}"),
        }
        for spec in specs
    ]
    webhook = None
    if webhook_url:
        webhook = {
            "webhook_endpoint_create": webhook_endpoint_params(webhook_url),
            "secret_pass_entry": WEBHOOK_SECRET_PASS_ENTRY,
        }
    tax_plans = [
        {"slug": spec.slug, "tax_registration_create": tax_registration_params(spec)}
        for spec in tax_registrations
    ]
    return {
        "schema": 1,
        "created_at": created_at,
        "mode": "dry_run_plan",
        "stripe_api_base": STRIPE_API_BASE,
        "payment_rail_route": PAYMENT_RAIL_ROUTE,
        "canonical_payment_rail_route": CANONICAL_PAYMENT_RAIL_ROUTE,
        "tax_registrations": tax_plans,
        "products": products,
        "webhook_endpoint": webhook,
        "accepted_webhook_events": list(WEBHOOK_EVENTS),
        "deferred_webhook_events": DEFERRED_WEBHOOK_EVENTS,
        "operator_gates": list(OPERATOR_GATES),
        "pass_store_entries": [API_KEY_PASS_ENTRY, WEBHOOK_SECRET_PASS_ENTRY],
        "connect_boundary": (
            "Stripe /v1/accounts creates connected accounts for Connect platforms. "
            "This runner intentionally does not create a direct merchant account."
        ),
    }


def execute_bootstrap(
    specs: Sequence[ProductSpec],
    *,
    webhook_url: str | None,
    tax_registrations: Sequence[TaxRegistrationSpec] = (),
    client: StripeRestClient,
    now: datetime | None = None,
) -> tuple[dict[str, Any], BootstrapSecrets]:
    created_at = (now or datetime.now(UTC)).isoformat().replace("+00:00", "Z")
    tax_registration_records: list[dict[str, str]] = []
    for spec in tax_registrations:
        registration = client.post("tax/registrations", tax_registration_params(spec))
        tax_registration_records.append(
            {
                "slug": spec.slug,
                "tax_registration_id": _require_stripe_id(
                    registration,
                    resource="tax_registration",
                ),
                "country": spec.country,
            }
        )

    products: list[dict[str, Any]] = []
    for spec in specs:
        product = client.post("products", product_params(spec))
        product_id = _require_stripe_id(product, resource="product")
        price = client.post("prices", price_params(spec, product_id=product_id))
        price_id = _require_stripe_id(price, resource="price")
        link = client.post("payment_links", payment_link_params(spec, price_id=price_id))
        products.append(
            {
                "slug": spec.slug,
                "product_id": product_id,
                "price_id": price_id,
                "payment_link_id": _require_stripe_id(link, resource="payment_link"),
                "payment_link_url": str(link.get("url", "")),
                "automatic_tax_enabled": True,
            }
        )

    webhook_record = None
    webhook_secret = None
    if webhook_url:
        webhook = client.post("webhook_endpoints", webhook_endpoint_params(webhook_url))
        webhook_secret = _optional_response_secret(webhook)
        webhook_record = {
            "webhook_endpoint_id": _require_stripe_id(webhook, resource="webhook_endpoint"),
            "enabled_events": list(WEBHOOK_EVENTS),
            "secret_received": webhook_secret is not None,
            "secret_pass_entry": WEBHOOK_SECRET_PASS_ENTRY,
        }

    return (
        {
            "schema": 1,
            "created_at": created_at,
            "mode": "executed",
            "tax_registrations": tax_registration_records,
            "products": products,
            "webhook_endpoint": webhook_record,
            "deferred_webhook_events": DEFERRED_WEBHOOK_EVENTS,
            "operator_gates": list(OPERATOR_GATES),
        },
        BootstrapSecrets(webhook_secret=webhook_secret),
    )


def _require_stripe_id(payload: Mapping[str, Any], *, resource: str) -> str:
    value = payload.get("id")
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"Stripe {resource} response did not include an id")
    return value


def _optional_response_secret(payload: Mapping[str, Any]) -> str | None:
    value = payload.get("secret")
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise RuntimeError("Stripe webhook endpoint secret was present but malformed")
    return value


def _resolve_api_key(
    env: Mapping[str, str],
    *,
    api_key_env: str,
    live: bool,
) -> str:
    api_key = env.get(api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(f"missing Stripe API key in ${api_key_env}")
    if live:
        if env.get(LIVE_CONFIRM_ENV) != "1":
            raise RuntimeError(f"refusing live Stripe calls: set {LIVE_CONFIRM_ENV}=1")
        if not api_key.startswith(("sk_live_", "rk_live_")):
            raise RuntimeError("live execution requires a live Stripe secret or restricted key")
    elif not api_key.startswith(("sk_test_", "rk_test_")):
        raise RuntimeError("test-mode execution requires a test Stripe secret or restricted key")
    return api_key


def write_pass_entries(
    *,
    api_key: str,
    webhook_secret: str | None,
    pass_runner: Any = subprocess.run,
) -> list[str]:
    written = [_pass_insert(API_KEY_PASS_ENTRY, api_key, pass_runner=pass_runner)]
    if webhook_secret:
        written.append(
            _pass_insert(WEBHOOK_SECRET_PASS_ENTRY, webhook_secret, pass_runner=pass_runner)
        )
    return written


def _pass_insert(key: str, value: str, *, pass_runner: Any) -> str:
    pass_runner(
        ["pass", "insert", "-m", key],
        input=value + "\n",
        text=True,
        check=True,
    )
    return key


def render_operator_note(
    *,
    plan: Mapping[str, Any],
    execution: Mapping[str, Any] | None = None,
) -> str:
    lines = [
        "# Stripe Bootstrap Record",
        "",
        "## Boundary",
        "",
        "- Direct Stripe merchant signup, EIN entry, KYC, payout bank verification, "
        "and live charges are operator actions.",
        "- This runner does not call Stripe Connect account creation; /v1/accounts is "
        "for connected accounts on registered platforms.",
        "- No secrets are written into this note.",
        "",
        "## Payment Link Rail",
        "",
        f"- Receiver route: `{PAYMENT_RAIL_ROUTE}`",
        "- Webhook events: " + ", ".join(f"`{event}`" for event in WEBHOOK_EVENTS),
        "",
        "## Deferred Events",
        "",
    ]
    for event, reason in DEFERRED_WEBHOOK_EVENTS.items():
        lines.append(f"- `{event}`: {reason}")
    lines.extend(["", "## Products", ""])
    for product in plan.get("products", []):
        if isinstance(product, Mapping):
            lines.append(f"- `{product.get('slug', 'unknown')}`")
    tax_registrations = plan.get("tax_registrations", [])
    if tax_registrations:
        lines.extend(["", "## Tax Registrations", ""])
        for registration in tax_registrations:
            if isinstance(registration, Mapping):
                lines.append(f"- `{registration.get('slug', 'unknown')}`")
    if execution is not None:
        lines.extend(["", "## Execution IDs", ""])
        for product in execution.get("products", []):
            if not isinstance(product, Mapping):
                continue
            lines.append(
                "- "
                f"`{product.get('slug', 'unknown')}` "
                f"product=`{product.get('product_id', '')}` "
                f"price=`{product.get('price_id', '')}` "
                f"link=`{product.get('payment_link_id', '')}`"
            )
        webhook = execution.get("webhook_endpoint")
        if isinstance(webhook, Mapping):
            lines.append(f"- webhook_endpoint=`{webhook.get('webhook_endpoint_id', '')}`")
    lines.extend(["", "## Operator Gates", ""])
    for gate in OPERATOR_GATES:
        lines.append(f"- {gate}")
    return "\n".join(lines).rstrip() + "\n"


def write_example_config(path: Path, *, force: bool) -> None:
    if path.exists() and not force:
        raise ConfigError(f"refusing to overwrite existing config: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(EXAMPLE_CONFIG, encoding="utf-8")


def write_records(
    *,
    output_dir: Path,
    plan: Mapping[str, Any],
    execution: Mapping[str, Any] | None,
    write_vault_note: bool,
    vault_note: Path,
) -> dict[str, str]:
    run_dir = output_dir / datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    run_dir.mkdir(parents=True, exist_ok=True)
    plan_path = run_dir / "stripe-bootstrap-plan.json"
    note_path = run_dir / "operator-checklist.md"
    plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    note = render_operator_note(plan=plan, execution=execution)
    note_path.write_text(note, encoding="utf-8")
    paths = {"output_dir": str(run_dir), "plan_path": str(plan_path), "note_path": str(note_path)}
    if execution is not None:
        execution_path = run_dir / "stripe-bootstrap-execution.json"
        execution_path.write_text(
            json.dumps(execution, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        paths["execution_path"] = str(execution_path)
    if write_vault_note:
        vault_note.parent.mkdir(parents=True, exist_ok=True)
        vault_note.write_text(note, encoding="utf-8")
        paths["vault_note_path"] = str(vault_note)
    return paths


def _args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--products-config", type=Path, default=DEFAULT_PRODUCTS_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--webhook-url", default=os.environ.get(WEBHOOK_URL_ENV, ""))
    parser.add_argument("--api-key-env", default=DEFAULT_API_KEY_ENV)
    parser.add_argument(
        "--execute", action="store_true", help="call Stripe in test mode by default"
    )
    parser.add_argument("--live", action="store_true", help="allow live Stripe calls with env gate")
    parser.add_argument("--write-pass-store", action="store_true")
    parser.add_argument("--write-vault-note", action="store_true")
    parser.add_argument("--vault-note", type=Path, default=DEFAULT_VAULT_NOTE)
    parser.add_argument("--write-example-config", type=Path)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    *,
    env: Mapping[str, str] = os.environ,
    http: HttpPoster | None = None,
    pass_runner: Any = subprocess.run,
) -> int:
    args = _args(argv)
    try:
        if args.write_example_config:
            write_example_config(args.write_example_config.expanduser(), force=args.force)
            print(json.dumps({"example_config": str(args.write_example_config.expanduser())}))
            return 0

        specs = load_products_config(args.products_config.expanduser())
        tax_registrations = load_tax_registration_config(args.products_config.expanduser())
        webhook_url = args.webhook_url.strip() or None
        plan = build_plan(specs, tax_registrations=tax_registrations, webhook_url=webhook_url)
        execution = None
        if args.execute:
            api_key = _resolve_api_key(env, api_key_env=args.api_key_env, live=args.live)
            client = StripeRestClient(api_key, http=http)
            execution, secrets = execute_bootstrap(
                specs,
                tax_registrations=tax_registrations,
                webhook_url=webhook_url,
                client=client,
            )
            if args.write_pass_store:
                written = write_pass_entries(
                    api_key=api_key,
                    webhook_secret=secrets.webhook_secret,
                    pass_runner=pass_runner,
                )
                execution = {**execution, "pass_store_entries_written": written}
        paths = write_records(
            output_dir=args.output_dir.expanduser(),
            plan=plan,
            execution=execution,
            write_vault_note=args.write_vault_note,
            vault_note=args.vault_note.expanduser(),
        )
    except (ConfigError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"stripe-bootstrap-runner: {exc}", file=sys.stderr)
        return 2

    summary = {
        **paths,
        "mode": "executed" if execution is not None else "dry_run",
        "products": len(specs),
        "tax_registrations": len(tax_registrations),
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
