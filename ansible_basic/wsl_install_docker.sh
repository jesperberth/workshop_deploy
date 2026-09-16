#!/bin/bash
set -euo pipefail

# Check for required input argument
if [ -z "${1:-}" ]; then
  echo "Usage: $0 <username>"
  exit 1
fi

USERNAME="$1"

# 1. System Update & Package Installation
apt-get update && apt-get upgrade -y
apt-get install sshpass tree jq docker.io docker-compose -y

# 2. Add user to docker group if not already a member
if id -nG "$USERNAME" | grep -qw "docker"; then
  echo "User '$USERNAME' is already in the docker group."
else
  usermod -aG docker "$USERNAME"
  echo "Added '$USERNAME' to docker group."
fi

# 3. Check if the user already has the dockerd NOPASSWD rule in sudoers
SUDO_RULE="$USERNAME ALL = NOPASSWD: /usr/bin/dockerd"

if grep -qs "^$USERNAME.*NOPASSWD:.*dockerd" /etc/sudoers /etc/sudoers.d/*; then
  echo "Sudoers entry for '$USERNAME' already exists. Skipping."
else
  echo "Adding '$USERNAME' NOPASSWD entry for dockerd to sudoers..."
  echo "$SUDO_RULE" | EDITOR='tee -a' visudo
fi

# 4. Install VS Code Extension safely
if su - "$USERNAME" -c "command -v code" &>/dev/null; then
  su - "$USERNAME" -c "code --install-extension ms-vscode-remote.remote-wsl" || true
else
  echo "VS Code CLI ('code') not found in user environment. Skipping extension install."
fi

# Explicitly guarantee exit code 0 on success or skipped tasks
exit 0