"""Unit checks for the scanner's dormant detector and AST policy."""

from scripts.billing_surface_detector import (
    _marker_is_allowed_on,
    _node_findings_for_postimage,
    _text_classes,
)


def test_proxy_exemption_belongs_to_the_same_literal_bound_call() -> None:
    source = (
        'OpenAI(api_key=key, base_url="http://127.0.0.1:4000")\n'
        "OpenAI(api_key=key, base_url=host)\n"
        "OpenAI(api_key=key)\n"
        'OpenAI(api_key=key, base_url="https://api.openai.com")\n'
    )
    findings, allowed, parsed = _node_findings_for_postimage("app.py", source, {1, 2, 3, 4})
    assert parsed
    assert [(f.line, f.kind) for f in allowed] == [(1, "governed-proxy-route")]
    assert [(f.line, f.kind) for f in findings] == [
        (2, "api-key-route"),
        (3, "api-key-route"),
        (4, "api-key-route"),
    ]


def test_protective_strip_exempts_only_its_target() -> None:
    source = (
        "import os\n"
        'os.environ.pop("OLD_API_KEY", os.environ["OPENAI_API_KEY"])\n'
        'key = os.environ["OTHER_API_KEY"]\n'
    )
    findings, allowed, parsed = _node_findings_for_postimage("app.py", source, {2, 3})
    assert parsed
    assert [(f.line, f.kind) for f in allowed] == [(2, "protective-strip")]
    assert sorted((f.line, f.kind) for f in findings) == [
        (2, "credential-env-read"),
        (3, "credential-env-read"),
    ]


def test_multiline_node_covers_only_added_lines() -> None:
    source = "client = OpenAI(\n    api_key=key,\n    base_url=host,\n)\n"
    findings, _, parsed = _node_findings_for_postimage("tests/gen.py", source, {2})
    assert parsed
    assert [(f.kind, f.covers) for f in findings] == [("api-key-route", (2,))]


def test_marker_allowlist_requires_root_prefix_or_exact_file() -> None:
    assert _marker_is_allowed_on("tests/gen.py")
    assert _marker_is_allowed_on("scripts/check-billing-surface-diff.py")
    assert not _marker_is_allowed_on("pkg/tests/gen.py")
    assert not _marker_is_allowed_on("scripts/check-billing-surface-diff.py_helper.py")


def test_text_classes_cover_credential_host_and_payg_paths_without_ast() -> None:
    assert "credential-env-read" in _text_classes('value = os.environ["OPENAI_API_KEY"]')
    assert "api-key-route" in _text_classes("client = OpenAI(api_key=key)")
    assert "provider-api-endpoint" in _text_classes('url = "https://api.openai.com/v1"')
    assert "provider-api-endpoint" in _text_classes("client = OpenAI()")
    assert "capacity-pool-payg" in _text_classes('capacity_pool = "api_paid_spend"')


def test_unparseable_python_yields_no_structural_exemption_and_text_still_flags() -> None:
    source = 'OpenAI(api_key=os.environ["OPENAI_API_KEY"]\n'
    findings, allowed, parsed = _node_findings_for_postimage("app.py", source, {1})
    assert not parsed and not findings and not allowed
    assert "api-key-route" in _text_classes(source)
    assert "credential-env-read" in _text_classes(source)
