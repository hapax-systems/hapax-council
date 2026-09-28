"""Observe green/red/exact-restore-green calls in a disposable CI checkout.

This supplies evidence, never the independent judgment that a mutation represents a claim.
The admission consumer downloads the artifact from Actions rather than trusting a local copy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_CALLS: list[dict[str, str]] = []


def pytest_runtest_logreport(report):
    if report.when == "call":
        _CALLS.append({"nodeid": report.nodeid, "outcome": report.outcome})


def pytest_sessionfinish(session, exitstatus):
    destination = os.environ.get("HAPAX_REFUTATION_CALLS")
    if destination:
        Path(destination).write_text(json.dumps(_CALLS))


def calls_match(calls, tests, outcome):
    return (
        isinstance(calls, list)
        and len(calls) == len(tests)
        and all(isinstance(c, dict) and c.get("outcome") == outcome for c in calls)
        and sorted(c.get("nodeid", "") for c in calls) == sorted(tests)
    )


def valid_tests(tests):
    return (
        isinstance(tests, list)
        and bool(tests)
        and len(tests) == len(set(tests))
        and all(
            isinstance(t, str)
            and re.fullmatch(r"tests/[\w./-]+\.py::[^\s]+", t)
            and ".." not in t.split("::")[0].split("/")
            for t in tests
        )
    )


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run_tests(root, tests):
    with tempfile.TemporaryDirectory(prefix="refutation-test-") as scratch:
        scratch = Path(scratch)
        env = dict(os.environ)
        env.update(
            HOME=str(scratch / "home"),
            HAPAX_REFUTATION_CALLS=str(scratch / "calls.json"),
            PYTHONDONTWRITEBYTECODE="1",
            PYTHONPYCACHEPREFIX=str(scratch / "pycache"),
            PYTHONPATH=os.pathsep.join([str(root), str(Path(__file__).resolve().parent)]),
            OTEL_SDK_DISABLED="true",
        )
        for key in ("LITELLM_BASE_URL", "QDRANT_URL", "OLLAMA_HOST", "LANGFUSE_HOST"):
            env[key] = "http://0.0.0.0:1"  # pragma: allowlist secret — inert CI endpoint
        (scratch / "home").mkdir()
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "review_refutation_proof",
            "-p",
            "no:cacheprovider",
            *tests,
            "-q",
            "--tb=short",
        ]
        p = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=600)
        path = scratch / "calls.json"
        return {
            "returncode": p.returncode,
            "calls": json.loads(path.read_text()) if path.exists() else [],
            "stdout": p.stdout,
            "stderr": p.stderr,
        }


def produce_proof(root: Path, head: str, mutation: str, tests: list[str]) -> dict:
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root)

    if not valid_tests(tests) or not all(
        re.fullmatch(r"[0-9a-f]{40}", x) for x in (head, mutation)
    ):
        raise ValueError("exact commits and unique pytest node IDs required")
    if git("rev-parse", "HEAD").decode().strip() != head or git("status", "--porcelain").strip():
        raise ValueError("proof requires a clean exact-head checkout")
    paths = git("diff", "--name-only", head, mutation).decode().splitlines()
    if not paths:
        raise ValueError("mutation must change source")
    original = {}
    mutated = {}
    for path in paths:
        if (
            Path(path).parts[0] not in {"agents", "shared", "scripts"}
            or path == "scripts/review_refutation_proof.py"
            or not path.endswith(".py")
            or ".." in Path(path).parts
        ):
            raise ValueError(
                "mutation may only change existing Python source, never tests or harness"
            )
        for commit in (head, mutation):
            if git("ls-tree", commit, "--", path).split(b" ", 1)[0] not in {b"100644", b"100755"}:
                raise ValueError("source must be a regular tracked file")
        original[path] = git("show", f"{head}:{path}")
        mutated[path] = git("show", f"{mutation}:{path}")
        if (root / path).is_symlink() or (root / path).read_bytes() != original[path]:
            raise ValueError("source bytes differ from the reviewed head")
    legs = [run_tests(root, tests)]
    if legs[0]["returncode"] != 0 or not calls_match(legs[0]["calls"], tests, "passed"):
        raise ValueError("named tests did not pass before mutation")
    try:
        for path, data in mutated.items():
            (root / path).write_bytes(data)
        legs.append(run_tests(root, tests))
    finally:
        for path, data in original.items():
            (root / path).write_bytes(data)
    restored = {p: (root / p).read_bytes() for p in original}
    if restored != original or git("diff", "HEAD", "--").strip():
        raise ValueError("exact-byte restoration failed or tests changed other tracked files")
    legs.append(run_tests(root, tests))
    if (
        legs[1]["returncode"] != 1
        or not calls_match(legs[1]["calls"], tests, "failed")
        or legs[2]["returncode"] != 0
        or not calls_match(legs[2]["calls"], tests, "passed")
        or git("diff", "HEAD", "--").strip()
    ):
        raise ValueError(
            "named tests must fail in their call phase and pass after exact restoration"
        )
    return {
        "schema": 1,
        "head_sha": head,
        "mutation_sha": mutation,
        "tests": tests,
        "legs": legs,
        "producer_sha256": digest(Path(__file__).read_bytes()),
        "files": [
            {
                "path": p,
                "before": digest(original[p]),
                "mutated": digest(mutated[p]),
                "restored": digest(restored[p]),
            }
            for p in original
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--head", required=True)
    parser.add_argument("--mutation", required=True)
    parser.add_argument("--tests-json", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or root != Path(os.environ.get("GITHUB_WORKSPACE", "/")).resolve()
    ):
        parser.error("run only in a disposable Actions checkout")
    result = produce_proof(root, args.head, args.mutation, json.loads(args.tests_json))
    args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
