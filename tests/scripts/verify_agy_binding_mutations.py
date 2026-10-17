"""Reproduce binding red/restore/green in a temporary tree, with fake native transport.

Run: uv run --no-sync python tests/scripts/verify_agy_binding_mutations.py --out /tmp/new-evidence
No production files, credentials, provider calls or installed receipts are used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEST = "tests/scripts/test_agy_model_binding.py"
LEDGER = "shared/quota_spend_ledger.py"
REVIEWER = "scripts/hapax-agy-reviewer"
PRODUCER = "scripts/hapax-agy-quota-admission"
WRITER = "scripts/hapax-quota-telemetry-writer"
PATHS = [LEDGER, REVIEWER, PRODUCER, WRITER]
EFFECT = "changed_binding_crosses_process"
LAZY = "consumers_import_without_binding"
MUTATIONS = [
    (
        "ledger-resolves-at-import",
        LEDGER,
        "AGY_ADMISSION_RECEIPT_LABEL_RE = re.compile(",
        "agy_review_model_binding()\nAGY_ADMISSION_RECEIPT_LABEL_RE = re.compile(",
        LAZY,
    ),
    (
        "reviewer-resolves-at-import",
        REVIEWER,
        'DEFAULT_PRINT_TIMEOUT = "20m0s"',
        'agy_review_model_binding()\nDEFAULT_PRINT_TIMEOUT = "20m0s"',
        LAZY,
    ),
    (
        "producer-resolves-at-import",
        PRODUCER,
        'ADMISSION_SCHEMA = "hapax.agy_quota_admission.v1"',
        'agy_review_model_binding()\nADMISSION_SCHEMA = "hapax.agy_quota_admission.v1"',
        LAZY,
    ),
    (
        "writer-resolves-at-import",
        WRITER,
        'AGY_ADMISSION_SCHEMA = "hapax.agy_quota_admission.v1"',
        'agy_review_model_binding()\nAGY_ADMISSION_SCHEMA = "hapax.agy_quota_admission.v1"',
        LAZY,
    ),
    (
        "malformed-blocking-metadata-admitted",
        LEDGER,
        '            or not isinstance(variants[0]["blocked_reasons"], list)\n',
        "",
        "malformed_blocked_reasons",
    ),
    (
        "valid-empty-blocking-metadata-rejected",
        LEDGER,
        '            or variants[0]["blocked_reasons"]\n',
        '            or not variants[0]["blocked_reasons"]\n',
        "empty_blocked_reasons_allows_binding",
    ),
    (
        "invalid-binding-default",
        LEDGER,
        '    path = REPO_ROOT / "config" / "platform-capability-registry.json"',
        '    return "gemini-3.1-pro-high", "gemini-3.1-pro-preview"',
        "invalid_registry or " + LAZY,
    ),
    (
        "native-model-hardcode",
        REVIEWER,
        "cli_model = pinned_model",
        'cli_model = "gemini-3.1-pro-high"',
        EFFECT,
    ),
    (
        "producer-receipt-hardcode",
        PRODUCER,
        "model, _ = agy_review_model_binding()",
        'model = "gemini-3.1-pro-high"',
        EFFECT,
    ),
    (
        "writer-model-hardcode",
        WRITER,
        "admission_models = agy_review_model_binding()",
        'admission_models = ("gemini-3.1-pro-high", "gemini-3.1-pro-preview")',
        EFFECT,
    ),
    (
        "ledger-model-hardcode",
        LEDGER,
        "for model in agy_review_model_binding())",
        'for model in ("gemini-3.1-pro-high", "gemini-3.1-pro-preview"))',
        EFFECT,
    ),
    (
        "alias-not-canonicalized",
        REVIEWER,
        "cli_model = pinned_model",
        "cli_model = args.model",
        EFFECT,
    ),
    (
        "writer-admits-superseded",
        WRITER,
        'if not failed and fields.get("model", "") not in admission_models:',
        "if False:",
        EFFECT,
    ),
    (
        "ledger-admits-superseded",
        LEDGER,
        'and any(f":model:{model}:" in ref for model in agy_review_model_binding())',
        "and True",
        EFFECT,
    ),
    (
        "reviewer-admits-superseded",
        REVIEWER,
        "if args.model not in {pinned_model, legacy_model}:",
        "if False:",
        EFFECT,
    ),
    ("reviewer-swallows-rejection", REVIEWER, "return result.returncode", "return 0", EFFECT),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    source = {name: (ROOT / name).read_bytes() for name in [*PATHS, TEST]}
    records = []
    with tempfile.TemporaryDirectory(prefix="agy-binding-verification-") as temp:
        tree = Path(temp)
        for folder in ["shared", "config"]:
            shutil.copytree(
                ROOT / folder, tree / folder, ignore=shutil.ignore_patterns("__pycache__")
            )
        for name in [*PATHS[1:], TEST]:
            (tree / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, tree / name)
        baseline = {name: ((tree / name).read_bytes(), (tree / name).stat()) for name in PATHS}
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(tree / "empty-home"),
            "PYTHONPATH": str(tree),
            "PYTHONDONTWRITEBYTECODE": "1",
            "OTEL_SDK_DISABLED": "true",
            "LANG": "C.UTF-8",
        }

        def run(label: str, selector: str = "") -> int:
            command = [sys.executable, "-B", "-m", "pytest", TEST, "-q", "--tb=short"]
            if selector:
                command += ["-k", selector]
            result = subprocess.run(
                command, cwd=tree, env=env, capture_output=True, text=True, timeout=120
            )
            (args.out / f"{label}.txt").write_text(result.stdout + result.stderr)
            print(f"{label}: exit={result.returncode}", flush=True)
            return result.returncode

        def restore() -> None:
            for name, (data, before) in baseline.items():
                path = tree / name
                path.write_bytes(data)
                os.chmod(path, before.st_mode)
                os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
                assert path.read_bytes() == data
                after = path.stat()
                assert (after.st_ino, after.st_mode, after.st_mtime_ns) == (
                    before.st_ino,
                    before.st_mode,
                    before.st_mtime_ns,
                )

        assert run("baseline-green") == 0
        try:
            for name in PATHS:
                old = subprocess.check_output(["git", "show", "ab0c262a^:" + name], cwd=ROOT)
                (tree / name).write_bytes(old)
            assert run("pre-refactor-red") == 1
        finally:
            restore()
        assert run("pre-refactor-restored-green") == 0
        records.append({"mutation": "pre-refactor-all-four", "red": True, "restored_green": True})
        for name, path, old, new, selector in MUTATIONS:
            try:
                content = (tree / path).read_text()
                assert content.count(old) == 1, name
                (tree / path).write_text(content.replace(old, new, 1))
                assert run(name + "-red", selector) == 1, name
            finally:
                restore()
            assert run(name + "-restored-green", selector) == 0, name
            records.append(
                {
                    "mutation": name,
                    "selector": selector,
                    "red": True,
                    "exact_restore": True,
                    "restored_green": True,
                }
            )
        assert run("final-green") == 0
    assert all((ROOT / name).read_bytes() == data for name, data in source.items())
    (args.out / "results.json").write_text(
        json.dumps(
            {
                "source_sha256": {
                    name: hashlib.sha256(data).hexdigest() for name, data in source.items()
                },
                "mutations": records,
                "production_sources_unchanged": True,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
