from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts/stripe-bootstrap-runner.py"
SPEC = importlib.util.spec_from_file_location("stripe_bootstrap_runner", MODULE_PATH)
assert SPEC is not None
stripe_bootstrap_runner = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = stripe_bootstrap_runner
SPEC.loader.exec_module(stripe_bootstrap_runner)


CONFIG = """
[defaults]
currency = "usd"
tax_behavior = "exclusive"
metadata = { surface = "article50-cert" }

[[products]]
slug = "article50-cert-starter"
name = "Hapax - Article 50 Compliance Cert"
description = "One certificate issuance."
unit_amount_cents = 100
tax_code = "txcd_10000000"
success_url = "https://example.invalid/success"
"""

CONFIG_WITH_TAX = (
    CONFIG
    + """

[[tax_registrations]]
slug = "ie-oss-union"
country = "IE"
active_from = "now"
country_options = { ie = { type = "oss_union" } }
"""
)


class FakeResponse:
    def __init__(self, payload: dict[str, Any], *, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeHttp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[tuple[str, str]], dict[str, str]]] = []

    def post(
        self,
        url: str,
        *,
        data: list[tuple[str, str]],
        headers: dict[str, str],
        timeout: float,
    ) -> FakeResponse:
        del timeout
        self.calls.append((url, data, headers))
        if url.endswith("/products"):
            return FakeResponse({"id": "prod_article50"})
        if url.endswith("/prices"):
            return FakeResponse({"id": "price_article50"})
        if url.endswith("/payment_links"):
            return FakeResponse(
                {"id": "plink_article50", "url": "https://buy.stripe.com/test_article50"}
            )
        if url.endswith("/webhook_endpoints"):
            return FakeResponse({"id": "we_article50", "secret": "whsec_test"})
        if url.endswith("/tax/registrations"):
            return FakeResponse({"id": "taxreg_ie_oss"})
        raise AssertionError(f"unexpected Stripe endpoint: {url}")


def _write_config(tmp_path: Path, text: str = CONFIG) -> Path:
    path = tmp_path / "stripe-products.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_products_config_rejects_sensitive_fields(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path,
        CONFIG
        + """
ein = "12-3456789"
""",
    )

    try:
        stripe_bootstrap_runner.load_products_config(path)
    except stripe_bootstrap_runner.ConfigError as exc:
        assert "sensitive key" in str(exc)
    else:
        raise AssertionError("expected sensitive key rejection")


def test_build_plan_enables_payment_link_automatic_tax(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, CONFIG_WITH_TAX)
    specs = stripe_bootstrap_runner.load_products_config(config_path)
    tax_registrations = stripe_bootstrap_runner.load_tax_registration_config(config_path)

    plan = stripe_bootstrap_runner.build_plan(
        specs,
        webhook_url="https://hapax.example/api/payment-rails/stripe-payment-link",
        tax_registrations=tax_registrations,
    )

    product = plan["products"][0]
    tax_registration = plan["tax_registrations"][0]["tax_registration_create"]
    assert tax_registration["country"] == "IE"
    assert tax_registration["country_options"] == {"ie": {"type": "oss_union"}}
    assert product["price_create"]["tax_behavior"] == "exclusive"
    assert product["payment_link_create"]["automatic_tax"] == {"enabled": True}
    assert plan["webhook_endpoint"]["webhook_endpoint_create"]["enabled_events"] == list(
        stripe_bootstrap_runner.WEBHOOK_EVENTS
    )
    assert "customer.tax_id.updated" in plan["deferred_webhook_events"]
    assert "Connect" in plan["connect_boundary"]


def test_execute_bootstrap_uses_stripe_form_payloads(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, CONFIG_WITH_TAX)
    specs = stripe_bootstrap_runner.load_products_config(config_path)
    tax_registrations = stripe_bootstrap_runner.load_tax_registration_config(config_path)
    http = FakeHttp()
    client = stripe_bootstrap_runner.StripeRestClient("sk_test_123", http=http)

    execution, secrets = stripe_bootstrap_runner.execute_bootstrap(
        specs,
        webhook_url="https://hapax.example/api/payment-rails/stripe-payment-link",
        tax_registrations=tax_registrations,
        client=client,
    )

    assert secrets.webhook_secret == "whsec_test"
    assert execution["tax_registrations"][0]["tax_registration_id"] == "taxreg_ie_oss"
    assert execution["products"][0]["product_id"] == "prod_article50"
    assert execution["products"][0]["payment_link_url"] == "https://buy.stripe.com/test_article50"
    tax_registration_call = next(
        call for call in http.calls if call[0].endswith("/tax/registrations")
    )
    payment_link_call = next(call for call in http.calls if call[0].endswith("/payment_links"))
    webhook_call = next(call for call in http.calls if call[0].endswith("/webhook_endpoints"))
    assert ("country_options[ie][type]", "oss_union") in tax_registration_call[1]
    assert ("automatic_tax[enabled]", "true") in payment_link_call[1]
    assert ("line_items[0][price]", "price_article50") in payment_link_call[1]
    assert ("enabled_events[0]", "payment_intent.succeeded") in webhook_call[1]
    assert ("metadata[hapax_route]", stripe_bootstrap_runner.PAYMENT_RAIL_ROUTE) in webhook_call[1]


def test_main_dry_run_writes_plan_without_secret(tmp_path: Path, capsys: Any) -> None:
    config_path = _write_config(tmp_path)
    output_dir = tmp_path / "out"

    code = stripe_bootstrap_runner.main(
        [
            "--products-config",
            str(config_path),
            "--output-dir",
            str(output_dir),
            "--webhook-url",
            "https://hapax.example/api/payment-rails/stripe-payment-link",
        ],
        env={},
    )

    assert code == 0
    summary = json.loads(capsys.readouterr().out)
    plan_text = Path(summary["plan_path"]).read_text(encoding="utf-8")
    assert "automatic_tax" in plan_text
    assert "sk_test" not in plan_text
    assert "whsec" not in plan_text


def test_execute_requires_test_key_or_live_gate(tmp_path: Path, capsys: Any) -> None:
    config_path = _write_config(tmp_path)

    code = stripe_bootstrap_runner.main(
        [
            "--products-config",
            str(config_path),
            "--output-dir",
            str(tmp_path / "out"),
            "--execute",
        ],
        env={"STRIPE_SECRET_KEY": "sk_live_without_gate"},
        http=FakeHttp(),
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "test-mode execution requires" in err


def test_write_pass_store_keeps_secrets_out_of_execution_record(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    calls: list[tuple[list[str], str]] = []

    def pass_runner(cmd: list[str], *, input: str, text: bool, check: bool) -> None:
        assert text is True
        assert check is True
        calls.append((cmd, input))

    code = stripe_bootstrap_runner.main(
        [
            "--products-config",
            str(config_path),
            "--output-dir",
            str(tmp_path / "out"),
            "--webhook-url",
            "https://hapax.example/api/payment-rails/stripe-payment-link",
            "--execute",
            "--write-pass-store",
        ],
        env={"STRIPE_SECRET_KEY": "sk_test_123"},
        http=FakeHttp(),
        pass_runner=pass_runner,
    )

    assert code == 0
    assert [call[0][-1] for call in calls] == ["api/stripe-secret", "api/stripe-webhook-secret"]
    execution_path = next((tmp_path / "out").glob("*/stripe-bootstrap-execution.json"))
    execution_text = execution_path.read_text(encoding="utf-8")
    assert "sk_test_123" not in execution_text
    assert "whsec_test" not in execution_text
