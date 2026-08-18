#!/bin/bash
#
useradd $1 --create-home --shell /usr/bin/bash --user-group --groups adm,dialout,cdrom,floppy,sudo,audio,dip,video,plugdev,netdev
echo $1:$2 | chpasswd

tee -a /etc/wsl.conf << EOF
[user]
default=$1
EOF