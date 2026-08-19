#!/bin/bash
#
apt-get update && apt-get upgrade -y
apt-get install tree jq docker.io docker-compose-y
usermod -aG docker $1
echo $1' ALL = NOPASSWD: /usr/bin/dockerd' | EDITOR='tee -a' visudo

code --install-extension ms-vscode-remote.remote-wsl

(type -p wget >/dev/null || (sudo apt update && sudo apt install wget -y)) \
	&& sudo mkdir -p -m 755 /etc/apt/keyrings \
	&& out=$(mktemp) && wget -nv -O$out https://cli.github.com/packages/githubcli-archive-keyring.gpg \
	&& cat $out | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
	&& sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
	&& sudo mkdir -p -m 755 /etc/apt/sources.list.d \
	&& echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
	&& sudo apt update \
	&& sudo apt install gh -y

cat << 'EOF' >> ~/.bashrc

ssh() {
    # Change background color to Dark Red (#400000)
    printf '\e]11;#400000\a'
    # Run the actual ssh command with all passed arguments
    command ssh "$@"
    # Reset background color back to default upon exit
    printf '\e]111\a'
}
EOF