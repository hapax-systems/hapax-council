#!/usr/bin/env bash
# Install obsidian-headless for automated vault publishing

set -euo pipefail

# Ensure we have Node.js available. The system uses nvm typically, or system node.
# obsidian-headless requires Node.js 22+.
echo "Checking for npm..."
if ! command -v npm >/dev/null 2>&1; then
    echo "Error: npm is required but not found in PATH." >&2
    exit 1
fi

echo "Installing obsidian-headless globally..."
# We install globally so the systemd service can find the `ob` command easily
# without needing complex path resolution.
npm install -g obsidian-headless

echo "Installation complete."
echo "You can verify the installation by running: ob --help"
