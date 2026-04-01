"""Verify DMN daemon no longer imports imagination modules."""

import ast


def test_dmn_main_does_not_import_imagination_loop():
    """DMN __main__.py must not import ImaginationLoop."""
    source = open("agents/dmn/__main__.py").read()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "imagination_loop" in node.module:
                raise AssertionError(
                    f"DMN still imports from {node.module} — extraction incomplete"
                )


def test_dmn_main_does_not_import_imagination_resolver():
    """DMN __main__.py must not import imagination_resolver."""
    source = open("agents/dmn/__main__.py").read()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "imagination_resolver" in node.module:
                raise AssertionError(
                    f"DMN still imports from {node.module} — extraction incomplete"
                )


def test_dmn_main_does_not_reference_tpn_active():
    """DMN must not read TPN active flag directly."""
    source = open("agents/dmn/__main__.py").read()
    assert "tpn_active" not in source.lower() or "# legacy" in source.lower(), (
        "DMN still references tpn_active — replace with perception signal observation"
    )
