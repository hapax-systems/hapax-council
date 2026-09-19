# Producer declaration identity fixture

Generated from the Personal vault repository at commit
`f8f19c0656b7917025c5ee65775481bcb9203e97`. The producer files were clean. <!-- pragma: allowlist secret -->
`frame/procedure/builtin.py::fs_glob` (reader version 1.0.1) read a small
synthetic tree; `frame/procedure/declaration.py::load_declaration` produced the
member declaration identity. No consumer code participates in generation.

`mass.json` holds the exact UTF-8 declaration input bytes. The generator captures
`json.dumps`'s return value from the producer's member identity code path;
`declaration.canonical.json` stores those exact UTF-8 hash-input bytes with **no
trailing newline**. `declaration.digest.txt` contains the producer's literal
SHA-256 hex digest followed by `  # pragma: allowlist secret` and a newline.
The test strips the first `#` and everything after it, trims whitespace, checks
for exactly 64 lowercase hex characters, and restores the `declaration:` prefix.
A text sidecar keeps the literal producer evidence together and independently
inspectable, rather than embedding it in the consumer test module.

`read-result.jsonc` records the producer's observations as hex bytes and its
exclusion residue; timestamps are deliberately omitted. It is JSON-with-comments
only because the push-time secret scanner requires a same-line pragma on hex
digests. Each digest-bearing line has ` // pragma: allowlist secret` appended.
The test removes line comments and their preceding horizontal whitespace outside
JSON strings, preserving escaped quotes, backslashes, UTF-8 bytes and newlines.
The comment-stripped canonical form is the original round-six `read-result.json`
byte sequence: two-space indentation, original key order, LF line endings and
one final LF, without JSON reserialization. `read-result.sha256.txt` pins its
literal SHA-256; the test verifies it before `json.loads`:

`37441bfc9b4cd59917b8f7e45a3c3f48a774c41905c552a47936dd636d287c72`. <!-- pragma: allowlist secret -->

The tree has two included Markdown files, one declared exclusion, one file
skipped by path part, and one non-matching text file. Non-ASCII text, nested
mappings, ordered lists, booleans and null exercise serialization compatibility.
Tests load the literal fixture without the vault or producer, and never compute
the expected identity with the consumer function.

Run from the council checkout to reproduce (requires the producer checkout at
the commit above; this command overwrites only this fixture's generated files):

```sh
env PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/store-fast/tmp/uv-cache-verify uv run python - <<'PY'
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

producer = Path.home() / 'Documents/Personal/30-areas/hapax'
fixture = Path('tests/shared/fixtures/frame-producer-identity').resolve()
fixture.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(producer))
from frame.procedure import declaration as producer_declaration
from frame.procedure.builtin import fs_glob
from frame.procedure.params import ParameterProfile

commit = subprocess.check_output(['git', '-C', str(producer), 'rev-parse', 'HEAD'], text=True).strip()
raw = {
    'declaration_version': 'fixture-1',
    'projection': 'frame-reduction',
    'members': [{
        'id': 'fixture-notes',
        'declared': '2026-09-05',
        'axes': {'phase': 'fixture', 'host': 'local', 'capability': 'notes',
                 'status': 'active', 'cwd': 'tree', 'time': 'persistent'},
        'enumerability': 'BOUNDED',
        'boundary': 'Synthetic café notes, excluding generated residue',
        'location': {'path': 'tree', 'patterns': ['*.md', 'nested/*.md', 'excluded/*.md', 'cache/*.md'],
                     'skip_dirs': ['cache']},
        'reader': {'id': 'fs.glob', 'version': '1.0.1'},
        'extractors': [], 'rules': [],
        'bounds': {'max_units': 16, 'max_bytes': 4096, 'max_seconds': None},
        'acceptance_required': False,
        'note': 'UTF-8: café / λ',
    }],
    'exclusions': [{
        'id': 'fixture-generated', 'declared': '2026-09-05',
        'receipt': 'fixture:generated-residue', 'reason': 'Synthetic generated output',
        'paths': ['tree/excluded'],
    }],
}
encoded = (json.dumps(raw, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
canonical = []
dumps = json.dumps

def capture(value, *args, **kwargs):
    result = dumps(value, *args, **kwargs)
    if isinstance(value, dict) and set(value) == {'member', 'exclusions'}:
        canonical.append(result.encode('utf-8'))
    return result

with tempfile.TemporaryDirectory(prefix='frame-producer-fixture-') as scratch:
    os.chdir(scratch)
    Path('mass.json').write_bytes(encoded)
    for name, content in {'one.md': 'café\n', 'nested/two.md': 'λ\n',
                          'excluded/generated.md': 'generated\n', 'cache/skipped.md': 'skip\n',
                          'ignored.txt': 'outside\n'}.items():
        path = Path('tree') / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode('utf-8'))
    with patch.object(producer_declaration.json, 'dumps', capture):
        declaration = producer_declaration.load_declaration(Path('mass.json'))
    result = fs_glob(
        declaration.member('fixture-notes'),
        ParameterProfile('fixture', {'max_unit_bytes': 4096, 'encoding_error_policy': 'strict'}, 'fixture'),
        declaration,
    )
    assert result.complete and not result.failure
    assert len(canonical) == 1
    identity = declaration.member_declaration_identity('fixture-notes')
    observed = {
        'producer_commit': commit,
        'enumerated_units': result.enumerated_units,
        'excluded_units': result.excluded_units,
        'bytes_read': result.bytes_read,
        'observations': [{'unit_id': row.unit_id, 'content_hex': row.content.hex()}
                         for row in result.observations],
        'residue': result.residue,
    }
    (fixture / 'mass.json').write_bytes(encoded)
    (fixture / 'declaration.canonical.json').write_bytes(canonical[0])
    digest = identity.removeprefix('declaration:')
    assert re.fullmatch(r'[0-9a-f]{64}', digest)
    (fixture / 'declaration.digest.txt').write_text(digest + '  # pragma: allowlist secret\n', encoding='utf-8')
    observed_json = dumps(observed, ensure_ascii=False, indent=2) + '\n'
    annotated = '\n'.join(
        line + ' // pragma: allowlist secret' if re.search(r'"[0-9a-f]{40,64}"', line) else line
        for line in observed_json.split('\n')
    )
    (fixture / 'read-result.jsonc').write_bytes(annotated.encode('utf-8'))
    result_digest = hashlib.sha256(observed_json.encode('utf-8')).hexdigest()
    (fixture / 'read-result.sha256.txt').write_text(result_digest + '  # pragma: allowlist secret\n', encoding='utf-8')
    print('producer_commit=' + commit)
    print(identity)
    print(dumps(observed, ensure_ascii=False, sort_keys=True))
PY
```

