#!/usr/bin/env bash
# Dev-only Tauri/WebKit hapax-logos binary installer.
# Run from repo root: ./hapax-logos/scripts/install.sh
set -euo pipefail

if [[ "${HAPAX_ALLOW_TAURI_BINARY_INSTALL:-0}" != "1" ]]; then
    cat >&2 <<'MSG'
hapax-logos Tauri/WebKit is decommissioned as a production runtime.

This script no longer installs a systemd unit, starts the app, or enables it
on login. For explicit local inspection use:

  cd hapax-logos && ./scripts/dev.sh

Set HAPAX_ALLOW_TAURI_BINARY_INSTALL=1 only for a one-off local binary build.
MSG
    exit 2
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOGOS_DIR="$REPO_ROOT/hapax-logos"
INSTALL_BIN="$HOME/.local/bin/hapax-logos"

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

echo "==> Done. Installed binary only; no systemd unit was installed."
echo "    Production livestream surfaces are studio-compositor/OBS/V4L2 and logos-api."
