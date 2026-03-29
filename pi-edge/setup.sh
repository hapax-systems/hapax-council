#!/usr/bin/env bash
# setup.sh — Provision a Pi for IR edge inference
# Usage: ssh hapax@hapax-piN 'bash -s' < setup.sh ROLE
# where ROLE is one of: desk, room, overhead
set -euo pipefail

ROLE="${1:?Usage: setup.sh <desk|room|overhead>}"
EDGE_DIR="$HOME/hapax-edge"

echo "=== Hapax IR Edge Setup (role=$ROLE) ==="

# System packages
sudo apt update
sudo apt install -y python3-picamera2 python3-libcamera python3-venv

# Create venv with system site packages (for libcamera/picamera2)
mkdir -p "$EDGE_DIR"
python3 -m venv --system-site-packages "$EDGE_DIR/.venv"

# Install Python deps
"$EDGE_DIR/.venv/bin/pip" install --upgrade pip
"$EDGE_DIR/.venv/bin/pip" install \
    tflite-runtime \
    face-detection-tflite \
    httpx \
    numpy \
    opencv-python-headless \
    pydantic

# Ensure video group membership
sudo usermod -aG video hapax

# Install systemd service
SERVICE_FILE="/etc/systemd/system/hapax-ir-edge.service"
sudo cp "$EDGE_DIR/hapax-ir-edge.service" "$SERVICE_FILE"
sudo sed -i "s/ROLE_PLACEHOLDER/$ROLE/" "$SERVICE_FILE"
sudo systemctl daemon-reload
sudo systemctl enable hapax-ir-edge

echo "=== Setup complete. Deploy files to $EDGE_DIR then: sudo systemctl start hapax-ir-edge ==="
