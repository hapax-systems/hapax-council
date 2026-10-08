"""Unknown subscription shapes refuse; a billing label never qualifies executable code."""

import pytest

from shared.capability_envelope import EnvelopeDeclaration, EnvelopeRefusal, render

UNIT = {"memory_high": 64, "memory_max": 128, "memory_swap_max": 0, "runtime_max_sec": 30}


@pytest.mark.parametrize(
    "harness", ["claude", "codex", "agy", "grok", "kimi", "vibe", "opencode", "muse"]
)
@pytest.mark.parametrize(
    "argv",
    [
        ("harness", "--future-billing-switch"),
        ("harness", "--settings", '{"apiKeyHelper":"/unqualified"}'),
        ("/usr/bin/sh", "-c", "unqualified-client"),
        ("/usr/bin/true",),
        ("harness", "-p"),
    ],
)
@pytest.mark.parametrize("carrier", ["t1", "t2", "t3"])
def test_unqualified_subscription_shape_refuses_before_artifacts(tmp_path, harness, argv, carrier):
    decl = EnvelopeDeclaration(harness=harness, argv=argv, unit=UNIT)
    with pytest.raises(EnvelopeRefusal, match="billing.*qualification.*next action"):
        render(
            decl,
            run_root=tmp_path / "run",
            carrier=carrier,
            oci_uid=100000,
            oci_gid=100000,
            oci_launcher_uid=1000,
            oci_launcher_gid=1000,
        )
    assert not (tmp_path / "run").exists()
    assert decl.billing_surface == "subscription"


def test_explicit_api_shape_is_source_rendering_not_spend_admission(tmp_path):
    decl = EnvelopeDeclaration(
        harness="claude", argv=("/usr/bin/true",), unit=UNIT, billing_surface="api"
    )
    result = render(decl, run_root=tmp_path / "run")
    assert result.facts["billing_surface"] == "api"
