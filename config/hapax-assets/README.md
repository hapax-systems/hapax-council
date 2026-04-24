# hapax-assets

Public asset CDN for [hapax-council](https://github.com/ryanklee/hapax-council).

Contents are mirrored from `assets/aesthetic-library/` in the council repo by the
[`hapax-assets-publisher` daemon](https://github.com/ryanklee/hapax-council/tree/main/agents/hapax_assets_publisher);
edits should land in the source repo, not here. This repo's `main` branch is
the canonical surface; the `Publish to GitHub Pages` workflow deploys `main`
→ `gh-pages` on every push.

## Attribution

Every asset is third-party content redistributed under its declared license.
The canonical attribution surface is `_NOTICES.md`. Licenses covered include
BSD-3-Clause (BitchX) and CC-BY-SA-4.0 (Px437 IBM VGA 8×16 font).

## Consumers

Omg.lol surfaces (hapax.omg.lol, /now, /credits, /statuses, /weblog) embed
these assets via SHA-pinned URLs synthesized by
`shared.aesthetic_library.web_export.build_web_url`. Example:

```css
@font-face {
  font-family: "Px437 IBM VGA 8x16";
  src: url("https://ryanklee.github.io/hapax-assets/fonts/Px437_IBM_VGA_8x16.woff2?sha=0cc1138b") format("woff2");
}
```

## CORS

GitHub Pages serves with `Access-Control-Allow-Origin: *` by default —
suitable for cross-origin embedding.
