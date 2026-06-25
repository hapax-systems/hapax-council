# Aesthetic library — redistributable-asset URL primitive

Canonical reference for the SHA-pinned-URL primitive
`shared.aesthetic_library.web_export.build_web_url` and its
ergonomic surface `library().web_url(asset)`.

## Why a primitive

The aesthetic library at `assets/aesthetic-library/` is mirrored to a
public CDN at `https://hapax-systems.github.io/hapax-assets/` (governance
+ standup details in `agents/hapax_assets_publisher/`). Any surface
that wants to embed a stable reference to a redistributable asset
(font, palette excerpt, image, splash text) needs:

  * **A URL that resolves to the byte-identical asset on the CDN**
  * **An invalidation handle that flips when the asset changes**

Hardcoding the CDN base URL inline in templates / HTML / markdown /
content publishers couples every consumer to the bucket layout AND
loses the SHA invalidation handle. The primitive solves both: every
URL is constructed from `(library_root, asset_path, sha256)` so the
URL is bit-stable for a fixture asset across runs **and** changes
when the underlying bytes change.

## API

```python
from shared.aesthetic_library import library

asset = library().assets["fonts/Px437_IBM_VGA_8x16.woff2"]
url = library().web_url(asset)
# → 'https://hapax-systems.github.io/hapax-assets/fonts/Px437_IBM_VGA_8x16.woff2?sha=abc12345'
```

The implementation is a 3-line function in
`shared/aesthetic_library/web_export.py`:

```python
def build_web_url(library_root: Path, asset_path: Path, sha256: str) -> str:
    rel = asset_path.relative_to(library_root)
    return f"{CDN_BASE_URL}/{rel.as_posix()}?sha={sha256[:8]}"
```

The `?sha=…` query string is the cache-busting / invalidation handle.
GitHub Pages serves the asset whether the query is present or not;
consumers gain HTTP-level invalidation when a manifest update
changes the SHA-256.

## Bit-stability invariant

For a fixture asset that hasn't changed (SHA-256 unchanged), the URL
is byte-identical across runs, processes, hosts, and Python versions.
This is regression-pinned in
`tests/shared/test_aesthetic_library_web_export.py::TestUrlStability`.

The invariant matters because consumers persist these URLs (omg.lol
posts, livestream description footers, generated HTML / markdown).
URL drift would invalidate cached references everywhere.

## Consumers

Production consumers as of 2026-04-25:

  * **`agents/omg_credits_publisher/data.py`** — credits CDN URLs in the
    rendered credits HTML
  * **`scripts/generate-aesthetic-library-cdn-index.py`** — generates
    a markdown index of every redistributable asset's SHA-pinned URL
    (used to populate `docs/aesthetic-library/cdn-index.md`)

When adding a new consumer, prefer `library().web_url(asset)` over
hardcoded `https://hapax-systems.github.io/hapax-assets/...` URLs.
Hardcoded URLs:

  * skip the SHA invalidation handle, so cached references go stale
    silently
  * couple to the CDN bucket layout, so a future hosting flip
    (different repo, custom domain, alternate provider) requires
    grepping every consumer
  * bypass the integrity gate — a hardcoded URL whose path doesn't
    match a manifest entry will 404 on consumer request, but no
    earlier verification fires

## Governance

The CDN itself is governed by:

  * `assets/aesthetic-library/_manifest.yaml` — SHA-256 per asset
  * `assets/aesthetic-library/<group>/provenance.yaml` — license +
    attribution per source group (CODEOWNERS-protected)
  * `scripts/verify-aesthetic-library.py` — CI integrity gate
  * `hooks/scripts/asset-provenance-gate.sh` — local commit-time
    integrity gate

The `web_url` primitive does not duplicate any of those gates; it
just produces the URL string. Consumers that want the CI-gated
bytes can call `asset.bytes()`; consumers that want the public URL
call `library().web_url(asset)`.

## Spec history

  * Original primitive shipped as part of ytb-AUTH-HOSTING (#1287)
  * AUDIT-21 (v4 workstream realignment §3.4.2) documented the
    primitive canonically + added the second consumer
    (`scripts/generate-aesthetic-library-cdn-index.py`) outside the
    OMG cascade + pinned the bit-stability invariant
