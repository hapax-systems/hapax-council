#!/usr/bin/env python
"""Local audit of council's license-policy alignment.

Per cc-task ``repo-pres-license-policy``: validates that this repo's
declared license metadata matches the canonical
``docs/repo-pres/repo-registry.yaml`` matrix.

The full cross-repo gate lives in ``hapax-constitution``'s
``hapax_sdlc render --check`` (renderer extension still pending). This
script is the council-local pre-cursor — runs in isolation, no
hapax-sdlc dependency, exits non-zero on divergence.

Checks (council-only):
1. ``CITATION.cff`` ``license:`` matches the registry's
   ``hapax-council`` entry.
2. ``codemeta.json`` ``license`` URL matches the registry's
   ``license_url``.
3. ``LICENSE`` file's first non-blank line names the same SPDX
   identifier OR the canonical license title (Apache 2.0 vs PolyForm
   Strict 1.0.0 are distinguishable by header text).

Exits 0 on alignment, 1 on divergence. Output is human-readable —
intended for both CI and operator-readable runs.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY = REPO_ROOT / "docs" / "repo-pres" / "repo-registry.yaml"
CITATION_CFF = REPO_ROOT / "CITATION.cff"
CODEMETA_JSON = REPO_ROOT / "codemeta.json"
LICENSE_FILE = REPO_ROOT / "LICENSE"

# License-text fingerprints — first-line header substrings. Add
# entries when new license classes appear in the registry.
_LICENSE_FINGERPRINTS = {
    "PolyForm-Strict-1.0.0": "PolyForm Strict License",
    "MIT": "MIT License",
    "CC-BY-NC-ND-4.0": "Creative Commons Attribution-NonCommercial-NoDerivatives",
    "Apache-2.0": "Apache License",
}


def _load_registry_council_entry() -> dict:
    """Hand-parse the YAML for the hapax-council block.

    PyYAML is not in the council's runtime deps; this is a regex-based
    parse that handles the registry's known shape (``- name:`` entry
    with following ``license:`` + ``license_url:`` keys).
    """
    text = REGISTRY.read_text(encoding="utf-8")
    block_re = re.compile(
        r"^\s*-\s*name:\s*hapax-council\b.*?(?=^\s*-\s*name:|^\w|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = block_re.search(text)
    if not m:
        raise SystemExit(f"FAIL: no hapax-council entry in {REGISTRY}")
    block = m.group(0)
    return {
        "license": _value_for_key(block, "license"),
        "license_url": _value_for_key(block, "license_url"),
    }


def _value_for_key(block: str, key: str) -> str:
    m = re.search(rf"^\s*{re.escape(key)}:\s*(\S+)\s*$", block, re.MULTILINE)
    if not m:
        raise SystemExit(f"FAIL: registry block missing '{key}:' line")
    return m.group(1).strip()


def _check_citation_cff(expected: str) -> str | None:
    text = CITATION_CFF.read_text(encoding="utf-8")
    m = re.search(r"^license:\s*(\S+)\s*$", text, re.MULTILINE)
    if not m:
        return "CITATION.cff: missing 'license:' line"
    actual = m.group(1).strip().strip('"').strip("'")
    if actual != expected:
        return f"CITATION.cff: license={actual!r} (expected {expected!r})"
    return None


def _check_codemeta(expected_url: str) -> str | None:
    data = json.loads(CODEMETA_JSON.read_text(encoding="utf-8"))
    actual = data.get("license", "")
    if actual != expected_url:
        return f"codemeta.json: license={actual!r} (expected {expected_url!r})"
    return None


def _check_license_file(expected_spdx: str) -> str | None:
    fingerprint = _LICENSE_FINGERPRINTS.get(expected_spdx)
    if fingerprint is None:
        return (
            f"LICENSE check: no fingerprint registered for {expected_spdx!r}; "
            "extend _LICENSE_FINGERPRINTS in this script"
        )
    text = LICENSE_FILE.read_text(encoding="utf-8")
    if fingerprint not in text:
        # Surface the fingerprint that IS present, if recognisable, so
        # the operator sees the exact divergence.
        present = next(
            (spdx for spdx, fp in _LICENSE_FINGERPRINTS.items() if fp in text),
            None,
        )
        if present:
            return f"LICENSE: file declares {present!r}, registry expects {expected_spdx!r}"
        return f"LICENSE: file does not match {expected_spdx!r} fingerprint"
    return None


def main() -> int:
    entry = _load_registry_council_entry()
    expected_spdx = entry["license"]
    expected_url = entry["license_url"]

    failures = list(
        filter(
            None,
            (
                _check_citation_cff(expected_spdx),
                _check_codemeta(expected_url),
                _check_license_file(expected_spdx),
            ),
        )
    )
    if failures:
        print("LICENSE-POLICY DIVERGENCE for hapax-council:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        print("", file=sys.stderr)
        print(
            f"Registry expects: {expected_spdx} ({expected_url})",
            file=sys.stderr,
        )
        return 1

    print(f"license-policy OK for hapax-council ({expected_spdx})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
