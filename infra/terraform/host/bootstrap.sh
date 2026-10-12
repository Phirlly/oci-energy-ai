#!/bin/bash
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
umask 077
trap 'touch /etc/oci-energy-ai/failed' ERR

timeout 900 dnf -y --setopt=timeout=30 --setopt=retries=2 install podman firewalld
if ! test -x /usr/bin/oci; then
  timeout 300 dnf -y --setopt=timeout=30 --setopt=retries=2 install oraclelinux-developer-release-el9
  timeout 600 dnf -y --setopt=timeout=30 --setopt=retries=2 install python39-oci-cli
fi
test -x /usr/bin/python3
test -x /usr/bin/oci
test -x /usr/bin/podman
test -f /sys/fs/cgroup/cgroup.controllers
/usr/bin/python3 -c 'import sys; assert sys.version_info >= (3, 9)'
/usr/bin/podman info --format '{{.Host.CgroupsVersion}}' | /usr/bin/grep -qx v2

install -d -m 0700 /var/lib/oci-energy-ai /run/oci-energy-ai
install -d -m 0700 -o 10001 -g 10001 /var/lib/oci-energy-ai/data
id ocarun >/dev/null
visudo -cf /etc/sudoers.d/oci-energy-ai
systemctl enable --now firewalld
firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.40.0.0/24" port port="8080" protocol="tcp" accept'
firewall-cmd --reload
systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/oci-energy-ai.service
systemctl enable oci-energy-ai.service
rm -f /etc/oci-energy-ai/failed
touch /etc/oci-energy-ai/ready
