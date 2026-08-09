#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 || -z "${PYTHON_BIN:-}" ]]; then
  echo "usage: PYTHON_BIN=/absolute/python $0 SOURCE_REPO CURRENT_FIXTURES REPLAY_ROOT" >&2
  exit 2
fi

source_repo="$1"
current_fixtures="$2"
replay_root="$3"
lineage_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source_head="f4e97c367ec6467fc4ca516535ecc3be553cb46b"
package_patch="$lineage_dir/hapax-context-canon-package-preimage-20260711.patch"
support_patch="$lineage_dir/hapax-context-canon-frozen-fixture-support-preimage-20260711.patch"

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
git -C "$replay_root" apply --check "$package_patch"
git -C "$replay_root" apply "$package_patch"
git -C "$replay_root" apply --check "$support_patch"
git -C "$replay_root" apply "$support_patch"
mkdir "$replay_root/replayed-fixtures"

(
  cd "$replay_root"
  "$PYTHON_BIN" - <<'PY'
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

test_path = Path("tests/shared/test_session_context_canon.py")
spec = importlib.util.spec_from_file_location("frozen_fixture_producer", test_path)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

bundle = module.bundle.__wrapped__()
rich = module.rich_context.__wrapped__(bundle)
frame = rich["frame"]
projections = {
    "hapax": rich["hapax"],
    "operator": rich["operator"],
    "yard": rich["yard"],
}
compatibility = module.project_context_bundle_v1(
    frame,
    operator_private=rich["operator"],
    yard_context=rich["yard"],
    hapax_substrate=rich["hapax"],
)
output = Path("replayed-fixtures")
payloads = {
    "gate0-frame.json": module.canonical_json_bytes(frame) + b"\n",
    "gate0-projections.json": module.canonical_json_bytes(projections) + b"\n",
    "gate0-compatibility.json": module.canonical_json_bytes(compatibility) + b"\n",
}
for name, payload in payloads.items():
    (output / name).write_bytes(payload)

hashes = {
    name: {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    for name, payload in payloads.items()
}
hashes["semantic_ids"] = {
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
}
(output / "gate0-hashes.json").write_bytes(module.canonical_json_bytes(hashes) + b"\n")
PY
)

for name in \
  gate0-frame.json \
  gate0-projections.json \
  gate0-compatibility.json \
  gate0-hashes.json; do
  cmp "$replay_root/replayed-fixtures/$name" "$current_fixtures/$name"
done

echo "exact_match=true"
echo "replay_root=$replay_root"
echo "source_head=$(git -C "$replay_root" rev-parse HEAD)"
sha256sum "$package_patch" "$support_patch" "$replay_root"/replayed-fixtures/*
wc -c "$replay_root"/replayed-fixtures/*
"$PYTHON_BIN" -c 'import platform, sys; print(f"python={sys.version}"); print(f"platform={platform.platform()}")'
uv --version
