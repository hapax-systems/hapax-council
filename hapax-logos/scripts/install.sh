#!/usr/bin/env bash
# Build and install hapax-logos binary + systemd service.
# Run from repo root: ./hapax-logos/scripts/install.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOGOS_DIR="$REPO_ROOT/hapax-logos"
INSTALL_BIN="$HOME/.local/bin/hapax-logos"
SERVICE_SRC="$REPO_ROOT/systemd/units/hapax-logos.service"
SERVICE_DST="$HOME/.config/systemd/user/hapax-logos.service"

echo "==> Building frontend..."
cd "$LOGOS_DIR"
pnpm install --frozen-lockfile
pnpm build

echo "==> Building Rust release binary..."
cd "$LOGOS_DIR/src-tauri"
cargo build --release

echo "==> Installing binary to $INSTALL_BIN"
mkdir -p "$(dirname "$INSTALL_BIN")"
cp -f "$LOGOS_DIR/src-tauri/target/release/hapax-logos" "$INSTALL_BIN"
chmod +x "$INSTALL_BIN"

echo "==> Installing systemd service"
mkdir -p "$(dirname "$SERVICE_DST")"
cp -f "$SERVICE_SRC" "$SERVICE_DST"
systemctl --user daemon-reload

echo "==> Done. To start:"
echo "    systemctl --user start hapax-logos"
echo "    systemctl --user enable hapax-logos  # start on login"
echo ""
echo "    To stop the old visual service (replaced by Logos):"
echo "    systemctl --user disable --now hapax-visual"
