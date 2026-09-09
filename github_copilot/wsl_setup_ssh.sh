#!/usr/bin/env bash
set -euo pipefail

# Configuration Variables
REMOTE_USER=$1
REMOTE_HOST="10.1.0.6"
REMOTE_PASS=$2

KEY_PATH="$HOME/.ssh/id_ed25519"

# 1. Ensure sshpass is installed
# if ! command -v sshpass &> /dev/null; then
#   echo "Installing sshpass..."
#   sudo apt-get update -qq && sudo apt-get install -y sshpass
# fi

# 2. Generate SSH key pair if it doesn't already exist
if [ ! -f "$KEY_PATH" ]; then
  echo "Generating Ed25519 SSH keypair..."
  mkdir -p "$HOME/.ssh"
  chmod 700 "$HOME/.ssh"
  ssh-keygen -t ed25519 -C "ubuntu-auto-key" -f "$KEY_PATH" -N ""
else
  echo "SSH key already exists at $KEY_PATH, skipping creation."
fi

# 3. Copy the public key to the remote host using sshpass
echo "Copying SSH public key to ${REMOTE_USER}@${REMOTE_HOST}..."
sshpass -p "$REMOTE_PASS" ssh-copy-id \
  -i "${KEY_PATH}.pub" \
  -o StrictHostKeyChecking=accept-new \
  "${REMOTE_USER}@${REMOTE_HOST}"

echo "Key successfully installed! You can now connect using:"
echo "ssh ${REMOTE_USER}@${REMOTE_HOST}"

# Explicitly guarantee exit code 0 on success or skipped tasks
exit 0