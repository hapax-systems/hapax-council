"""Unit checks for the scanner's dormant detector and AST policy."""

import ast
import time
from pathlib import Path

import pytest

from scripts.billing_surface_detector import (
    _host_of,
    _is_doc_path,
    _marker_is_allowed_on,
    _marker_outside_fixtures_finding,
    _node_credential_env_read,
    _node_findings_for_postimage,
    _pattern_only_classes,
    _strip_target_node,
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


def test_surfaces_on_unchanged_lines_yield_no_finding_and_no_exemption() -> None:
    source = (
        'key = os.environ["OPENAI_API_KEY"]\n'
        "client = OpenAI(api_key=key)\n"
        'proxied = OpenAI(api_key=key, base_url="http://localhost:4000")\n'
        'del os.environ["OLD_API_KEY"]\n'
        "ordinary = 1\n"
    )
    assert _node_findings_for_postimage("app.py", source, {5}) == ([], [], True)


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


def test_bearer_header_line_yields_api_key_route_finding_class() -> None:
    assert "api-key-route" in _text_classes('headers = {"Authorization": "Bearer token"}')


def test_javascript_process_env_read_yields_credential_finding_class() -> None:
    assert "credential-env-read" in _text_classes("const key = process.env.OPENAI_API_KEY;")


def test_provider_host_with_explicit_port_is_detected_without_prefix_false_positive() -> None:
    assert "provider-api-endpoint" in _pattern_only_classes('url = "https://api.openai.com:443/v1"')
    assert "provider-api-endpoint" in _text_classes('url = "https://api.openai.com:443/v1"')
    assert "provider-api-endpoint" not in _pattern_only_classes(
        'url = "https://api.openai.com.evil:443/v1"'
    )
    # A malformed port after the exact provider host remains suspicious.
    assert "provider-api-endpoint" in _pattern_only_classes(
        'url = "https://api.openai.com:443.evil/v1"'
    )


@pytest.mark.parametrize("scheme", ["http", "HTTPS"])
@pytest.mark.parametrize(
    "authority", ["API.OPENAI.COM", "api.openai.com.", "user:pass@api.openai.com:443"]
)
@pytest.mark.parametrize("suffix", ["/v1", "?model=gpt"])
def test_provider_url_normalization_matrix(scheme: str, authority: str, suffix: str) -> None:
    assert "provider-api-endpoint" in _pattern_only_classes(
        f'url = "{scheme}://{authority}{suffix}"'
    )


@pytest.mark.parametrize("url", ["https://api.openai.com.evil/v1", "https://not-api.openai.com/v1"])
def test_provider_url_normalization_rejects_similar_hosts(url: str) -> None:
    assert "provider-api-endpoint" not in _pattern_only_classes(f'url = "{url}"')


def test_scheme_relative_provider_url_is_detected() -> None:
    assert "provider-api-endpoint" in _pattern_only_classes('url = "//api.openai.com/v1"')


def test_provider_constructor_with_other_arguments_requires_same_call_proxy() -> None:
    source = (
        "OpenAI(timeout=30)\n"
        "Anthropic(max_retries=1)\n"
        "OpenAI(timeout=30, base_url=host)\n"
        'OpenAI(timeout=30, base_url="http://127.0.0.1:4000")\n'
        "OpenAI()\n"
    )
    findings, allowed, parsed = _node_findings_for_postimage("app.py", source, {1, 2, 3, 4, 5})
    assert parsed
    assert [(f.line, f.kind) for f in findings] == [
        (1, "provider-api-endpoint"),
        (2, "provider-api-endpoint"),
        (3, "provider-api-endpoint"),
        (5, "provider-api-endpoint"),
    ]
    assert [(f.line, f.kind) for f in allowed] == [(4, "governed-proxy-route")]
    assert "provider-api-endpoint" in _text_classes("OpenAI(timeout=30)")


@pytest.mark.parametrize(
    ("expression", "expected_finding"),
    [
        ("OpenAI()", True),
        ("OpenAI(timeout=30)", True),
        ("openai.OpenAI(max_retries=2)", True),
        ("Anthropic(**settings)", True),
        ("OpenAI(base_url=route)", True),
        ('OpenAI(base_url="http://localhost:443.evil")', True),
        ('OpenAI(timeout=30, base_url="http://localhost:4000")', False),
    ],
)
def test_constructor_argument_shape_matrix(expression: str, expected_finding: bool) -> None:
    findings, allowed, parsed = _node_findings_for_postimage("app.py", expression, {1})
    assert parsed
    assert bool(findings) is expected_finding
    assert bool(allowed) is not expected_finding


@pytest.mark.parametrize(
    "name", ["OPENAI_API_KEY", "openai_api_key", "ANTHROPIC_AUTH_TOKEN", "NEWPROVIDER_API_KEY"]
)
@pytest.mark.parametrize(
    "form",
    [
        'os.environ["{}"]',
        'os.getenv("{}")',
        "process.env.{}",
        'process.env["{}"]',
        "export {}=fixture",
    ],
)
def test_credential_name_form_matrix(name: str, form: str) -> None:
    assert "credential-env-read" in _text_classes(form.format(name))


@pytest.mark.parametrize(
    "line",
    [
        "Authorization: Bearer token",
        "Proxy-Authorization: Bearer token",
        'headers = {"authorization": "bearer token"}',
        'headers["AUTHORIZATION"] = f"BEARER {token}"',
    ],
)
def test_declared_bearer_header_forms(line: str) -> None:
    assert "api-key-route" in _text_classes(line)


def test_non_provider_call_still_reports_nested_credential_read() -> None:
    source = 'value = os.getenv("OPENAI_API_KEY")\n'
    findings, _, parsed = _node_findings_for_postimage("app.py", source, {1})
    assert parsed
    assert [(f.line, f.kind) for f in findings] == [(1, "credential-env-read")]


def test_unparseable_python_yields_no_structural_exemption_and_text_still_flags() -> None:
    source = 'OpenAI(api_key=os.environ["OPENAI_API_KEY"]\n'
    findings, allowed, parsed = _node_findings_for_postimage("app.py", source, {1})
    assert not parsed and not allowed
    assert [item.kind for item in findings] == ["unparseable-python"]
    assert "api-key-route" in _text_classes(source)
    assert "credential-env-read" in _text_classes(source)


def test_multiline_keyword_read_in_an_unparseable_file_is_a_blocking_finding() -> None:
    source = 'v = os.getenv(default=None,\n    key="OPENAI_API_KEY")\nbroken = (\n'
    findings, allowed, parsed = _node_findings_for_postimage("app.py", source, {1, 2, 3})
    assert not parsed and not allowed
    assert [(item.kind, item.covers) for item in findings] == [("unparseable-python", (1, 2, 3))]


def test_any_unparseable_python_postimage_fails_closed_at_the_syntax_error() -> None:
    source = "def ordinary():\n    return 1\n\ndef broken(:\n    pass\n"
    findings, allowed, parsed = _node_findings_for_postimage("app.py", source, {2})
    assert not parsed and not allowed
    assert [(item.kind, item.line, item.covers) for item in findings] == [
        ("unparseable-python", 4, (2,))
    ]
    assert "Next action" in findings[0].text


def test_parseable_python_without_a_surface_has_no_finding() -> None:
    source = "def ordinary(value):\n    return value + 1\n"
    assert _node_findings_for_postimage("app.py", source, {1, 2}) == ([], [], True)


def test_non_python_text_detection_is_unchanged_by_the_parse_rule() -> None:
    assert "provider-api-endpoint" in _text_classes("base_url: https://api.openai.com/v1")
    assert "credential-env-read" in _text_classes("export OPENAI_API_KEY=value")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://api.openai.com?next=@localhost", "api.openai.com"),
        ("https://api.openai.com/#@127.0.0.1", "api.openai.com"),
        ("https://user@localhost:4000/v1", "localhost"),
        ("https://api.openai.com/v1", "api.openai.com"),
        ("http://[::1]:4000/v1", "::1"),
        ("localhost:4000", "localhost"),
        ("http://[invalid", ""),
    ],
)
def test_host_parser_uses_authority_only_or_fails_closed(url: str, expected: str) -> None:
    assert _host_of(url) == expected


@pytest.mark.parametrize(
    "line",
    [
        "SCAN_REVIEW_BASE=${SCAN_REVIEW_BASE:-https://api.openai.com}",
        "export SCAN_REVIEW_BASE=${SCAN_REVIEW_BASE:-https://api.anthropic.com}/v1",
        "provider: {base_url: https://api.openai.com}",
        "base_urls: [https://api.openai.com]",
    ],
)
def test_language_delimiters_after_a_provider_url_cannot_hide_it(line: str) -> None:
    assert "provider-api-endpoint" in _text_classes(line)


@pytest.mark.parametrize(
    "line",
    [
        'v = os.getenv(key="OPENAI_API_KEY")',
        'v = os.environ.get(key="OPENAI_API_KEY")',
        'os.environ.setdefault(key="OPENAI_API_KEY", default="x")',
    ],
)
def test_keyword_credential_reads_keep_their_classification(line: str) -> None:
    assert "credential-env-read" in _text_classes(line)
    findings, _allowed, parsed = _node_findings_for_postimage("app.py", f"{line}\n", {1})
    assert parsed
    assert "credential-env-read" in [item.kind for item in findings]


@pytest.mark.parametrize(
    "call",
    [
        'os.getenv(default=None, key="OPENAI_API_KEY")',
        "os.environ.get(default='', key='ANTHROPIC_API_KEY')",
        'os.environ.setdefault(default="x", key="OPENAI_API_KEY")',
        'os.getenv(default=str(), key="OPENAI_API_KEY")',
    ],
)
def test_reordered_keyword_reads_survive_the_unparseable_text_fallback(call: str) -> None:
    source = f"v = {call}\nbroken = (\n"
    findings, allowed, parsed = _node_findings_for_postimage("app.py", source, {1, 2})
    assert not parsed and not allowed
    assert [item.kind for item in findings] == ["unparseable-python"]
    assert "credential-env-read" in _text_classes(f"v = {call}")


@pytest.mark.parametrize(
    "content",
    [
        'v = os.getenv(default=None,\n    key="OPENAI_API_KEY")',
        'v = os.environ.get(\n    default="",\n    key="ANTHROPIC_API_KEY",\n)',
        'v = os.getenv(\n    "OPENAI_API_KEY")',
    ],
)
def test_text_classes_keeps_a_multiline_read_given_the_full_text(content: str) -> None:
    assert "credential-env-read" in _text_classes(content)


def test_keyword_scan_across_lines_is_capped() -> None:
    content = "v = os.getenv(default=None,\n" + "#\n" * 1_500 + '    key="OPENAI_API_KEY")'
    assert "credential-env-read" not in _text_classes(content)


def test_reordered_keyword_read_of_a_non_credential_is_not_a_finding() -> None:
    assert "credential-env-read" not in _text_classes('os.getenv(default=None, key="PATH")')


def test_nested_read_before_a_keyword_still_finds_the_outer_key() -> None:
    line = 'v = os.getenv(default=os.getenv("HOME"), key="OPENAI_API_KEY")'
    assert "credential-env-read" in _text_classes(line)
    assert "credential-env-read" in _text_classes(
        'os.getenv(default=os.environ, key="OPENAI_API_KEY")'
    )


def test_keyword_scan_stays_linear_on_repeated_call_openings() -> None:
    # Quadratic scanning takes about 10 s here; a linear scan takes milliseconds.
    started = time.perf_counter()
    assert _text_classes("os.getenv(" * 20_000) == ()
    assert time.perf_counter() - started < 2.0


def test_a_delimited_proxy_host_receives_no_exemption() -> None:
    source = 'OpenAI(api_key=key, base_url="https://localhost}.evil.example/v1")\n'
    findings, allowed, parsed = _node_findings_for_postimage("app.py", source, {1})
    assert parsed
    assert [(item.kind, item.line) for item in findings] == [("api-key-route", 1)]
    assert allowed == []


@pytest.mark.parametrize(
    "url",
    ["https://api.openai.com?next=@localhost", "https://api.openai.com/#@127.0.0.1"],
)
def test_provider_url_with_proxy_name_outside_authority_is_not_exempt(url: str) -> None:
    source = f'OpenAI(api_key=key, base_url="{url}")\n'
    findings, allowed, parsed = _node_findings_for_postimage("app.py", source, {1})
    assert parsed
    assert [(item.kind, item.line) for item in findings] == [("api-key-route", 1)]
    assert allowed == []


@pytest.mark.parametrize(
    ("path", "expected"),
    [("docs/spec.py", True), ("notes.md", True), ("src/app.py", False)],
)
def test_doc_path_boundary(path: str, expected: bool) -> None:
    assert _is_doc_path(path) is expected


def test_marker_outside_fixture_is_a_finding_with_next_action() -> None:
    finding = _marker_outside_fixtures_finding(
        "src/app.py", 7, "client = OpenAI(api_key=key)  # billing-scan:allow"
    )
    assert (finding.path, finding.line, finding.kind) == (
        "src/app.py",
        7,
        "billing-scan-allow-outside-fixtures",
    )
    assert "Next action" in finding.text


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ('os.environ["OPENAI_API_KEY"]', True),
        ('os.environ.get("OPENAI_API_KEY")', True),
        ('os.environ.setdefault("OPENAI_API_KEY", value)', True),
        ('os.getenv("OPENAI_API_KEY")', True),
        ('os.getenv(key="OPENAI_API_KEY")', True),
        ('os.environ.get(key="OPENAI_API_KEY")', True),
        ('os.environ.setdefault(key="OPENAI_API_KEY", default=value)', True),
        ('os.getenv(key="PATH")', False),
        ('environ["OPENAI_API_KEY"]', True),
        ("os.getenv(name)", False),
        ('os.getenv("PATH")', False),
    ],
)
def test_credential_env_read_requires_a_literal_credential_name(
    expression: str, expected: bool
) -> None:
    node = ast.parse(expression).body[0]
    assert isinstance(node, ast.Expr)
    assert _node_credential_env_read(node.value) is expected


def test_strip_target_is_only_the_literal_removed_by_a_governed_strip() -> None:
    deletion = ast.parse('del os.environ["OLD_API_KEY"]').body[0]
    assert isinstance(_strip_target_node(deletion), ast.Subscript)
    pop = ast.parse('os.environ.pop("OLD_API_KEY", os.environ["OPENAI_API_KEY"])').body[0]
    assert isinstance(pop, ast.Expr)
    target = _strip_target_node(pop.value)
    assert isinstance(target, ast.Constant) and target.value == "OLD_API_KEY"
    arbitrary = ast.parse('env.pop("OLD_API_KEY")').body[0]
    assert isinstance(arbitrary, ast.Expr)
    assert _strip_target_node(arbitrary.value) is None


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ('url = "https://api.openai.com/v1"', ("provider-api-endpoint",)),
        ("client = OpenAI()", ()),
        ('capacity_pool = "api_paid_spend"', ("capacity-pool-payg",)),
        ("plan_type = 'api'", ("capacity-pool-payg",)),
        ("ordinary = 1", ()),
    ],
)
def test_pattern_only_classes_have_no_structural_exemption(
    line: str, expected: tuple[str, ...]
) -> None:
    assert _pattern_only_classes(line) == expected


def test_exemption_functions_take_ast_nodes_without_line_text() -> None:
    source = Path(__file__).resolve().parents[2] / "scripts" / "billing_surface_detector.py"
    tree = ast.parse(source.read_text())
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    for name in ("_call_is_proxy_bound", "_strip_target_node"):
        arguments = [arg.arg for arg in functions[name].args.args]
        assert arguments in (["call"], ["node"])
        assert not {"content", "line", "raw", "text", "source"}.intersection(arguments)
