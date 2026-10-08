"""Narrow source mutation witness for the unit/channel/OCI renderer.

Run in an exclusively claimed checkout, passing a new evidence directory. Every
mutation gets its own red log and JUnit report, exact-byte restoration, then green.
The existing runtime C10 mutation programme is separate and is not invoked here.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "shared/capability_envelope"


def mutations():
    yield (
        "environment-clear",
        "carriers.py",
        "if not cleared:",
        "if False:",
        "readback_requires_environment_clear",
    )
    yield (
        "generated-config",
        "carriers.py",
        "if config != expected_config:",
        "if False:",
        "generated_config and settings",
    )
    yield (
        "binding-no-fallback",
        "../coord_dispatch.py",
        "envelope = request.validated_envelope()",
        "envelope = None",
        "declared_launch_cannot_fall_back",
    )
    yield (
        "binding-propagation",
        "../capability_adapter_protocol.py",
        "rendered_envelope=rendered_envelope,",
        "rendered_envelope=None,",
        "bound_t2_reaches",
    )
    yield (
        "binding-snapshot",
        "../coord_dispatch.py",
        "if self.envelope.model_dump_json() != self._envelope_json:",
        "if False:",
        "mutated_declaration",
    )
    yield (
        "binding-source-hash",
        "../coord_dispatch.py",
        'if rendered_envelope.facts.get("declaration_sha256") != request.envelope_sha256:',
        "if False:",
        "rendered_identity_must_match",
    )
    yield (
        "binding-replay",
        "../coord_dispatch.py",
        'if event.payload.get("envelope_sha256") != request.envelope_sha256:',
        "if False:",
        "replay_cannot_accept",
    )
    yield (
        "binding-executor",
        "../coord_dispatch.py",
        "execute(rendered_envelope, timeout=envelope.unit.runtime_max_sec).returncode",
        "launch()",
        "bound_t2_reaches",
    )
    yield (
        "binding-runner",
        "../coord_dispatch.py",
        'if rendered_envelope.carrier != "t2":',
        "if False:",
        "unimplemented_unit_oci",
    )
    yield (
        "binding-event",
        "../coord_dispatch.py",
        '"envelope_sha256": request.envelope_sha256,',
        '"envelope_sha256": None,',
        "bound_t2_reaches",
    )
    yield (
        "binding-command-env",
        "carriers.py",
        'raise EnvelopeRefusal(\n                "conformance: command/environment differs; next action: re-render"\n            )',
        "pass",
        "forged_renderer_metadata",
    )
    yield (
        "unit-default",
        "declaration.py",
        "unit: UnitSection | None = None",
        "unit: UnitSection | None = UnitSection(memory_high=64, memory_max=128, memory_swap_max=0, runtime_max_sec=30)",
        "missing_unit",
    )
    for field, value in (("memory_max", 134217728), ("runtime_max_sec", 30)):
        yield (
            f"default-{field}",
            "declaration.py",
            f"{field}: int = Field(gt=0)",
            f"{field}: int = Field(default={value}, gt=0)",
            f"missing_hard_bound and {field}",
        )
    yield (
        "strict-limits",
        "declaration.py",
        'extra="forbid", strict=True',
        'extra="forbid", strict=False',
        "limits_are_positive",
    )
    for prop, field in (
        ("MemoryHigh", "memory_high"),
        ("MemoryMax", "memory_max"),
        ("MemorySwapMax", "memory_swap_max"),
        ("RuntimeMaxSec", "runtime_max_sec"),
        ("OOMPolicy", "oom_policy"),
        ("Restart", "restart"),
    ):
        yield (
            f"unit-{prop}",
            "carriers.py",
            f'f"{prop}={{unit.{field}}}"',
            f'"{prop}=WRONG"',
            "t1_has_exact_unit",
        )
    yield (
        "billing",
        "render.py",
        'and decl.billing_surface != "api"',
        "and False",
        "billing_flags",
    )
    yield (
        "import-masks",
        "render.py",
        "return list(dict.fromkeys(masked))",
        "return []",
        "t3_is_rootless",
    )
    yield (
        "channel-comparison",
        "carriers.py",
        "if _bytes(actual) != _bytes(expected):",
        "if False:",
        "conformance_reads_actual_carrier_not_facts and mount",
    )
    yield (
        "check-at-render",
        "render.py",
        "channel_bytes = check_conformance(decl, rendered)",
        'channel_bytes = b"{}"',
        "render_invokes_conformance or actual_rendered_mount_mismatch",
    )
    yield (
        "bwrap-network",
        "carriers.py",
        'if not parts["network"]:',
        "if False:",
        "conformance_reads_actual_carrier_not_facts and network and not t3",
    )
    yield (
        "oci-network",
        "carriers.py",
        'if {"type": "network"} not in namespaces or any(n.get("path") for n in namespaces):',
        "if False:",
        "conformance_reads_actual_carrier_not_facts and network and t3",
    )
    yield (
        "oci-id-range",
        "render.py",
        "0 < value < 2**32 - 1",
        "0 < value < 2**64",
        "explicit_valid_subordinate_id",
    )
    for name, message, selector in (
        ("oci-root", "OCI root or imports changed", "oci_cannot_add_imports and (root or hook)"),
        ("oci-user", "OCI privilege differs", "oci_cannot_add_imports and user"),
        ("oci-mapping", "OCI identity binding differs", "oci_cannot_add_imports and mapping"),
        ("oci-files", "undeclared OCI rootfs import", "oci_cannot_add_imports and file"),
        ("oci-mount-fields", "extra mount bindings", "mount_cannot_smuggle"),
    ):
        # Match the statement after formatting without depending on line wrapping.
        source = (SOURCE / "carriers.py").read_text()
        import re

        pattern = (
            r'raise EnvelopeRefusal\(\s*"conformance: '
            + re.escape(message)
            + r'; next action: re-render"\s*\)'
        )
        match = re.search(pattern, source)
        if match is None:
            raise RuntimeError(f"mutation not found: {name}")
        yield (name, "carriers.py", match.group(), "pass", selector)
    yield (
        "oci-recursive-ro",
        "carriers.py",
        '(["rro"] if kind == "bind" and mount["access"] == "ro" else [])',
        "[]",
        "read_only_binds_cover_submounts",
    )


def run(evidence: Path, label: str, selector: str) -> dict:
    command = [
        sys.executable,
        str(ROOT / "tests/capability_envelope/run_source_checks.py"),
        "tests/capability_envelope/test_launch_binding.py"
        if label.startswith("binding-")
        else "tests/capability_envelope/test_carriers.py",
        "-q",
        "--tb=short",
        "-k",
        selector,
        f"--junitxml={evidence / (label + '.xml')}",
    ]
    with tempfile.TemporaryDirectory() as cache:
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPYCACHEPREFIX": cache}
        result = subprocess.run(
            command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60
        )
    (evidence / (label + ".txt")).write_text(result.stdout + result.stderr)
    report = ET.parse(evidence / (label + ".xml")).getroot()
    suites = list(report.iter("testsuite"))
    return {
        "returncode": result.returncode,
        **{
            key: sum(int(s.attrib.get(key, 0)) for s in suites)
            for key in ("tests", "errors", "failures", "skipped")
        },
        "failed_cases": [
            c.attrib["name"] for c in report.iter("testcase") if c.find("failure") is not None
        ],
    }


def main() -> int:
    evidence = Path(sys.argv[1]).resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    results = []
    for name, filename, before, after, selector in mutations():
        path = (SOURCE / filename).resolve()
        original = path.read_bytes()
        mode = path.stat().st_mode
        if original.count(before.encode()) != 1:
            raise RuntimeError(f"mutation preimage not unique: {name}")
        modified = original.replace(before.encode(), after.encode(), 1)
        try:
            path.write_bytes(modified)
            red = run(evidence, name + "-red", selector)
        finally:
            if path.read_bytes() != modified:
                raise RuntimeError(f"concurrent source change: {path}; restore refused")
            path.write_bytes(original)
        if path.read_bytes() != original or path.stat().st_mode != mode:
            raise RuntimeError(f"restoration mismatch: {path}")
        green = run(evidence, name + "-green", selector)
        passed = (
            red["returncode"] == 1
            and red["errors"] == 0
            and red["failures"] > 0
            and green["returncode"] == 0
            and green["tests"] > 0
            and green["skipped"] == 0
        )
        results.append(
            {
                "name": name,
                "path": str(path.relative_to(ROOT)),
                "selector": selector,
                "original_sha256": hashlib.sha256(original).hexdigest(),
                "mutated_sha256": hashlib.sha256(modified).hexdigest(),
                "restored_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "red": red,
                "green": green,
                "passed": passed,
            }
        )
        (evidence / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        print(
            f"{name}: {'PASS' if passed else 'FAIL'}; red={red['failures']} green={green['tests']}",
            flush=True,
        )
        if not passed:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
