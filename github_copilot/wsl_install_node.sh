#!/usr/bin/env bash
set -e

# Install NVM for the active user
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.7/install.sh | bash

# Load NVM for the current session
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

# Install Node.js
nvm install 24.13.0

# Explicitly guarantee exit code 0 on success or skipped tasks
exit 0