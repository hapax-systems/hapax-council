#!/usr/bin/env bash
# setup-hapax-assets-repo.sh — one-time bootstrap for the ryanklee/hapax-assets
# external repo that serves as the aesthetic-library CDN.
#
# Operator action — run once to:
#   1. Create the public GitHub repo `ryanklee/hapax-assets`
#   2. Initialize it with README + .github/workflows/publish.yml (from
#      config/hapax-assets/ in this repo)
#   3. Seed it with the current aesthetic-library tree
#   4. Enable GitHub Pages (Source: "GitHub Actions")
#   5. Clone it into ~/.cache/hapax/hapax-assets-checkout/ so the publisher
#      daemon can push on subsequent changes
#
# After running, enable the systemd user unit:
#   systemctl --user enable --now hapax-assets-publisher.service
#
# Idempotent: re-running on an existing repo is safe (it skips creation and
# only re-syncs local config files).

set -euo pipefail

REPO="ryanklee/hapax-assets"
CHECKOUT_DIR="${HAPAX_ASSETS_CHECKOUT_DIR:-$HOME/.cache/hapax/hapax-assets-checkout}"
COUNCIL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DIR="$COUNCIL_ROOT/config/hapax-assets"
SOURCE_DIR="$COUNCIL_ROOT/assets/aesthetic-library"

# Require gh + git + rsync
for bin in gh git rsync; do
  command -v "$bin" >/dev/null || {
    echo "error: $bin required" >&2
    exit 1
  }
done

# Step 1: create the repo if missing.
if gh repo view "$REPO" &>/dev/null; then
  echo "✓ $REPO already exists"
else
  echo "→ creating $REPO (public) ..."
  gh repo create "$REPO" \
    --public \
    --description "Asset CDN for hapax-council (auto-mirrored from assets/aesthetic-library/)" \
    --disable-issues \
    --disable-wiki
fi

# Step 2: clone into checkout dir.
mkdir -p "$(dirname "$CHECKOUT_DIR")"
if [ -d "$CHECKOUT_DIR/.git" ]; then
  echo "✓ checkout exists at $CHECKOUT_DIR"
  git -C "$CHECKOUT_DIR" fetch origin --quiet || true
else
  echo "→ cloning $REPO → $CHECKOUT_DIR"
  gh repo clone "$REPO" "$CHECKOUT_DIR"
fi

cd "$CHECKOUT_DIR"

# Step 3: ensure we're on main (create if brand-new).
if git rev-parse --verify --quiet HEAD >/dev/null; then
  git checkout main 2>/dev/null || git checkout -b main
else
  # Brand-new empty repo — commit a README so main exists.
  git checkout -b main
  cp "$CONFIG_DIR/README.md" README.md
  git add README.md
  git commit -m "init: README"
fi

# Step 4: install the publish workflow + README (idempotent).
mkdir -p .github/workflows
cp "$CONFIG_DIR/publish.yml" .github/workflows/publish.yml
cp "$CONFIG_DIR/README.md" README.md

# Step 5: seed aesthetic-library tree.
rsync -a --delete-after \
  --exclude='.git' --exclude='.github' --exclude='README.md' \
  "$SOURCE_DIR/" "$CHECKOUT_DIR/"

# Step 6: commit + push if dirty.
if ! git diff --quiet HEAD -- || [ -n "$(git status --porcelain)" ]; then
  git add -A
  git commit -m "bootstrap: initial asset library seed + publish workflow"
  git push -u origin main
  echo "✓ pushed initial state to $REPO:main"
else
  echo "✓ $REPO:main already up-to-date"
fi

# Step 7: enable GitHub Pages with Actions source (idempotent).
echo "→ enabling GitHub Pages (Actions source)"
gh api -X POST "repos/$REPO/pages" \
  --field build_type=workflow \
  --field source[branch]=main 2>&1 | head -5 || true

# Already enabled? Try to update.
gh api -X PUT "repos/$REPO/pages" \
  --field build_type=workflow 2>&1 | head -5 || true

echo ""
echo "Done. Next:"
echo "  1. Wait ~1–2 minutes for the first Pages deploy to finish"
echo "  2. Visit https://ryanklee.github.io/hapax-assets/ to verify"
echo "  3. Enable the publisher daemon:"
echo "       systemctl --user enable --now hapax-assets-publisher.service"
