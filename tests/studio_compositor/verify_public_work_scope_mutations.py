"""Offline mutation replay under an authorized source claim; restores exact bytes.

From the repo root: uv run --no-sync python
tests/studio_compositor/verify_public_work_scope_mutations.py /tmp/fresh-evidence-dir
The output directory must not exist. No service, live input or provider is used.
Optional trailing mutation names select individual legs; omit them to replay all.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

TICKER = Path("agents/studio_compositor/chronicle_ticker.py")
PROJECTION = Path("agents/studio_compositor/public_work_projection.py")
ATLAS = Path("scripts/quake-live-ward-atlas-source.py")
TEST = "tests/studio_compositor/test_public_work_projection.py"


def main() -> None:
    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=False)
    mutations = [
        (
            "controls",
            TICKER,
            "style.text.isprintable() and ",
            "",
            "control_character or nul_scope_pair",
        ),
        (
            "measurement-order",
            TICKER,
            " if text_supported else []",
            "",
            "unsupported_scope_never_reaches",
        ),
        (
            "text-cap",
            TICKER,
            "len(style.text) <= MAX_PANGO_TEXT_CHARS",
            "True",
            "renderer_text_cap",
        ),
        (
            "height",
            TICKER,
            "sum(h + 4 for _, h in sizes) > height - 16",
            "False",
            "oversize_qualified_content",
        ),
        (
            "claim-scope",
            TICKER,
            "            (f\"Scope: {claim['scope_limit']}\", content),\n",
            "",
            "material_scope_changes",
        ),
        (
            "permitted-scope",
            TICKER,
            '            lines.append((f"Permitted scope: {permitted_scope}", content))',
            "            pass",
            "material_scope_changes",
        ),
    ]
    for field, expression in (
        ("ts", "event.ts != event.transaction_time"),
        ("valid_time", "event.valid_time != projected.valid_time"),
        ("evidence_refs", "event.evidence_refs != projected.evidence_refs"),
        ("payload", "event.payload != projected.payload"),
    ):
        mutations.append(
            (
                f"envelope-{field}",
                PROJECTION,
                f"            or {expression}\n",
                "",
                f"fresh_envelope_integrity and {field}",
            )
        )
    mutations.append(
        (
            "query-exception",
            TICKER,
            'log.debug("public work projection unavailable", exc_info=True)\n        return []',
            'log.debug("public work projection unavailable", exc_info=True)\n        raise',
            "raising_query",
        )
    )
    mutations.extend(
        [
            (
                "observation-clock",
                PROJECTION,
                "if isinstance(observed_at, bool) or not math.isfinite(observed_at):",
                "if False:",
                "invalid_observation_clock",
            ),
            (
                "aperture-kind",
                PROJECTION,
                "if aperture_registry().require(APERTURE).kind.value != SURFACE:",
                "if False:",
                "aperture_kind_mismatch",
            ),
            (
                "finite-ttl",
                PROJECTION,
                "            or not math.isfinite(ttl)\n",
                "",
                "unbound_or_held_grounding",
            ),
        ]
    )
    for field in (
        "unavailable_reasons",
        "must_emit_refusal_artifact",
        "must_emit_correction_artifact",
    ):
        mutations.append(
            (
                field,
                PROJECTION,
                f'            or result["{field}"]\n',
                "",
                f"unbound_or_held_grounding and {field}",
            )
        )
    mutations.extend(
        [
            (
                "timezone-repair",
                PROJECTION,
                "; append Z or an explicit UTC offset",
                "",
                "timestamp_error",
            ),
            (
                "selection-repair",
                ATLAS,
                "f\"select only from: {', '.join(sorted(SOFTWARE_SOURCE_CLASSES))}\"",
                '""',
                "rejects_unpermitted_source",
            ),
            (
                "backend-repair",
                ATLAS,
                'f"in {layout_path}; configure backend=cairo "',
                'f"in {layout_path}; "',
                "different_backend",
            ),
            (
                "missing-source-repair",
                ATLAS,
                'f"missing layout source {ward_id!r} in {layout_path}; {repair}"',
                '"missing layout source"',
                "missing_selected_layout",
            ),
        ]
    )
    if len(sys.argv) > 2:
        requested = set(sys.argv[2:])
        unknown = requested - {entry[0] for entry in mutations}
        if unknown:
            raise ValueError(f"unknown mutations {sorted(unknown)}; select names from this helper")
        mutations = [entry for entry in mutations if entry[0] in requested]

    for name, source, old, new, selection in mutations:
        original, metadata = source.read_bytes(), source.stat()
        before = hashlib.sha256(original).hexdigest()
        if original.count(old.encode()) != 1:
            raise RuntimeError(f"{name}: mutation target is not unique")
        test_file = (
            "tests/scripts/test_quake_live_ward_atlas_source.py" if source == ATLAS else TEST
        )
        command = [sys.executable, "-m", "pytest", test_file, "-q", "-k", selection]
        try:
            source.write_bytes(original.replace(old.encode(), new.encode(), 1))
            red = subprocess.run(command, capture_output=True, check=False)
            red_output = red.stdout + red.stderr
            (output / f"{name}.red.txt").write_bytes(red_output)
        finally:
            source.write_bytes(original)
            os.utime(source, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
        if source.read_bytes() != original or source.stat().st_mtime_ns != metadata.st_mtime_ns:
            raise RuntimeError(f"{name}: exact restoration failed")
        green = subprocess.run(command, capture_output=True, check=False)
        (output / f"{name}.green.txt").write_bytes(green.stdout + green.stderr)
        record = {
            "mutation": name,
            "source": str(source),
            "old": old,
            "new": new,
            "command": command,
            "red_exit": red.returncode,
            "green_exit": green.returncode,
            "assertion_red": b"AssertionError" in red_output,
            "original_sha256": before,
            "restored_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "mtime_restored": source.stat().st_mtime_ns == metadata.st_mtime_ns,
        }
        (output / f"{name}.json").write_text(json.dumps(record, indent=2) + "\n")
        print(json.dumps(record), flush=True)
        expected_error = (
            b"OSError: synthetic query failure" if name == "query-exception" else b"AssertionError"
        )
        if red.returncode != 1 or expected_error not in red_output or green.returncode != 0:
            raise RuntimeError(f"{name}: expected assertion-red / restored-green; inspect logs")


if __name__ == "__main__":
    main()
