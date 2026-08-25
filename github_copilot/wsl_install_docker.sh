#!/bin/bash
#
apt-get update && apt-get upgrade -y
apt-get install tree jq docker.io docker-compose -y
usermod -aG docker $1
echo $1' ALL = NOPASSWD: /usr/bin/dockerd' | EDITOR='tee -a' visudo

code --install-extension ms-vscode-remote.remote-wsl
