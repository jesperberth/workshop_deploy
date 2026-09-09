#!/bin/bash
set -euo pipefail
# Install GitHub CLI an Copilot on WSL

(type -p wget >/dev/null || (sudo apt update && sudo apt install wget -y)) \
	&& sudo mkdir -p -m 755 /etc/apt/keyrings \
	&& out=$(mktemp) && wget -nv -O$out https://cli.github.com/packages/githubcli-archive-keyring.gpg \
	&& cat $out | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
	&& sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
	&& sudo mkdir -p -m 755 /etc/apt/sources.list.d \
	&& echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
	&& sudo apt update \
	&& sudo apt install gh -y

curl -fsSL https://gh.io/copilot-install | bash

# Check for required username argument
if [ -z "${1:-}" ]; then
  echo "Usage: $0 <username>"
  exit 1
fi

USERNAME="$1"
BASHRC="/home/$USERNAME/.bashrc"

# Ensure the .bashrc file exists before checking or writing
if [ ! -f "$BASHRC" ]; then
  echo "Error: $BASHRC does not exist."
  exit 1
fi

# 1. Check and add the SSH color-wrapper function
if grep -q "ssh()" "$BASHRC"; then
  echo "SSH function already present in $BASHRC. Skipping."
else
  echo "Adding SSH color-wrapper to $BASHRC..."
  cat >> "$BASHRC" << 'EOF'

# SSH background color switch
ssh() {
    # Change background color to Dark Red (#9e3737)
    printf '\e]11;#9e3737\a'
    # Run the actual ssh command with all passed arguments
    command ssh "$@"
    # Reset background color back to default upon exit
    printf '\e]111\a'
}
EOF
fi

# 2. Check and add the COPILOT environment variables
if grep -q "COPILOT_PROVIDER_TYPE" "$BASHRC"; then
  echo "Copilot environment variables already present in $BASHRC. Skipping."
else
  echo "Adding Copilot configuration to $BASHRC..."
  cat >> "$BASHRC" << 'EOF'

# Copilot configuration
export COPILOT_PROVIDER_TYPE="openai"
export COPILOT_PROVIDER_BASE_URL="http://10.1.0.6:8000/v1"
export COPILOT_PROVIDER_API_KEY="my-super-secret-key-1234"
export COPILOT_MODEL="Qwen/Qwen3.8-27B-FP8"
EOF
fi

# Ensure correct file ownership if script is run as root/sudo
chown "$USERNAME:$USERNAME" "$BASHRC"

# Explicitly guarantee exit code 0 on success or skipped tasks
exit 0