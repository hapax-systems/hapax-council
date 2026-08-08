#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 || -z "${PYTHON_BIN:-}" ]]; then
  echo "usage: PYTHON_BIN=/absolute/python $0 SOURCE_REPO REPLAY_ROOT" >&2
  exit 2
fi

source_repo="$1"
replay_root="$2"
lineage_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
checkpoint_dir="$(cd "$lineage_dir/.." && pwd)"
source_head="f4e97c367ec6467fc4ca516535ecc3be553cb46b"
source_patch="$lineage_dir/pre-observability-source.patch.gz"

if [[ "$replay_root" != /* ]]; then
  echo "replay root must be an absolute disk-backed path: $replay_root" >&2
  exit 2
fi
probe="$(dirname "$replay_root")"
while [[ ! -e "$probe" && "$probe" != / ]]; do
  probe="$(dirname "$probe")"
done
filesystem_type="$(findmnt -n -o FSTYPE --target "$probe")"
if [[ "$filesystem_type" == "tmpfs" || "$filesystem_type" == "ramfs" ]]; then
  echo "replay root must be disk-backed, observed $filesystem_type at $probe" >&2
  exit 2
fi
if [[ -e "$replay_root/.git" || -n "$(find "$replay_root" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
  echo "replay root must be absent or empty: $replay_root" >&2
  exit 2
fi

git clone --quiet --no-checkout "$source_repo" "$replay_root"
git -C "$replay_root" checkout --quiet --detach "$source_head"
gzip -dc "$source_patch" | git -C "$replay_root" apply --check -
gzip -dc "$source_patch" | git -C "$replay_root" apply -
mkdir "$replay_root/replayed-fixtures"

REPLAY_ROOT="$replay_root" \
PYTHONPATH="$replay_root/packages/hapax-context-canon/src:$replay_root" \
PYTHONDONTWRITEBYTECODE=1 \
PYTHONSAFEPATH=1 \
  "$PYTHON_BIN" - <<'PY'
from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import sys

root = Path(os.environ["REPLAY_ROOT"])
test_path = root / "tests/shared/test_session_context_canon.py"
spec = importlib.util.spec_from_file_location("pre_observability_fixture_producer", test_path)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

bundle = module.bundle.__wrapped__()
rich = module.rich_context.__wrapped__(bundle)
frame = rich["frame"]
projections = {name: rich[name] for name in ("operator", "yard", "hapax")}
compatibility = module.project_context_bundle_v1(
    frame,
    operator_private=rich["operator"],
    yard_context=rich["yard"],
    hapax_substrate=rich["hapax"],
)
purpose_projections = {
    "lifecycle_possibility": module.project_context_frame(
        frame,
        audience="operator_private",
        purpose="lifecycle_possibility",
        depth="inspectable",
        device_class="accessible_linear",
        register="plain",
        decoder_ref="decoder:context-v1",
        focus_ref="fact:capability-gap",
        producer_ref="producer:deterministic-projector",
        generated_at="2026-07-10T16:06:00Z",
        lifecycle_possibility_ref=rich["lifecycle_possibility"].facet_ref,
    ),
    "operation": module.project_context_frame(
        frame,
        audience="operator_private",
        purpose="operation",
        depth="inspectable",
        device_class="monitor",
        register="formal",
        decoder_ref="decoder:context-v1",
        focus_ref="fact:capability-gap",
        producer_ref="producer:deterministic-projector",
        generated_at="2026-07-10T16:06:00Z",
    ),
}
payloads = {
    "gate0-frame.json": module.canonical_json_bytes(frame) + b"\n",
    "gate0-projections.json": module.canonical_json_bytes(projections) + b"\n",
    "gate0-compatibility.json": module.canonical_json_bytes(compatibility) + b"\n",
    "gate0-purpose-projections.json": (
        module.canonical_json_bytes(purpose_projections) + b"\n"
    ),
}
output = root / "replayed-fixtures"
for name, payload in payloads.items():
    (output / name).write_bytes(payload)

hashes = {
    name: {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    for name, payload in payloads.items()
}
hashes["semantic_ids"] = {
    "bundle_hash": bundle.bundle_hash,
    "bundle_ref": bundle.bundle_ref,
    "compatibility_hash": compatibility.compatibility_hash,
    "compatibility_ref": compatibility.compatibility_ref,
    "frame_hash": frame.frame_hash,
    "frame_ref": frame.frame_ref,
    "projection_hashes": {
        name: projection.projection_hash for name, projection in projections.items()
    },
    "projection_refs": {
        name: projection.projection_ref for name, projection in projections.items()
    },
    "purpose_projection_hashes": {
        name: projection.projection_hash for name, projection in purpose_projections.items()
    },
    "purpose_projection_refs": {
        name: projection.projection_ref for name, projection in purpose_projections.items()
    },
}
(output / "gate0-hashes.json").write_bytes(module.canonical_json_bytes(hashes) + b"\n")
(output / "coordination-canon.schema.json").write_bytes(module.bundle_json_schema_bytes())
(output / "context-canon-carrier.schema.json").write_bytes(
    module.context_canon_package.carrier_json_schema_bytes()
)
PY

for name in \
  context-canon-carrier.schema.json \
  coordination-canon.schema.json \
  gate0-frame.json \
  gate0-projections.json \
  gate0-compatibility.json \
  gate0-purpose-projections.json \
  gate0-hashes.json; do
  cmp "$replay_root/replayed-fixtures/$name" "$checkpoint_dir/$name"
done

echo "exact_match=true"
echo "replay_root=$replay_root"
echo "source_head=$(git -C "$replay_root" rev-parse HEAD)"
sha256sum "$source_patch" "$replay_root"/replayed-fixtures/*
wc -c "$replay_root"/replayed-fixtures/*
"$PYTHON_BIN" -c 'import platform, sys; print(f"python={sys.version}"); print(f"platform={platform.platform()}")'
uv --version
