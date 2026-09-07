#!/bin/bash
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

cat >> /home/$1/.bashrc << 'EOF'

ssh() {
    # Change background color to Dark Red (#9e3737)
    printf '\e]11;#9e3737\a'
    # Run the actual ssh command with all passed arguments
    command ssh "$@"
    # Reset background color back to default upon exit
    printf '\e]111\a'
}

export COPILOT_PROVIDER_TYPE="openai"
export COPILOT_PROVIDER_BASE_URL="http://10.1.0.6:8000/v1"
export COPILOT_PROVIDER_API_KEY="my-super-secret-key-1234"
export COPILOT_MODEL="Qwen/Qwen3.8-27B-FP8"
EOF