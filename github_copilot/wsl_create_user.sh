#!/bin/bash
set -euo pipefail

# Ensure arguments are provided
if [ -z "${1:-}" ] || [ -z "${2:-}" ]; then
  echo "Usage: $0 <username> <password>"
  exit 1
fi

USERNAME="$1"
PASSWORD="$2"

# Check if the user already exists
if id "$USERNAME" &>/dev/null; then
  echo "User '$USERNAME' already exists. Exiting without making changes."
  exit 0
fi

# Create user with primary group and supplementary groups
useradd "$USERNAME" \
  --create-home \
  --shell /usr/bin/bash \
  --user-group \
  --groups adm,dialout,cdrom,floppy,sudo,audio,dip,video,plugdev,netdev

# Set user password
echo "$USERNAME:$PASSWORD" | chpasswd

# Set as default user in WSL configuration
tee -a /etc/wsl.conf << EOF
[user]
default=$USERNAME
EOF

echo "User '$USERNAME' successfully created and set as default WSL user."