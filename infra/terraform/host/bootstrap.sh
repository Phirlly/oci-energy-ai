#!/bin/bash
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
umask 077
trap 'touch /etc/oci-energy-ai/failed' ERR

printf '%s' packages > /etc/oci-energy-ai/bootstrap-stage
timeout 900 dnf -y --setopt=timeout=30 --setopt=retries=2 install podman firewalld
if ! test -x /usr/bin/oci; then
  printf '%s' cli-repository > /etc/oci-energy-ai/bootstrap-stage
  timeout 300 dnf -y --setopt=timeout=30 --setopt=retries=2 install oraclelinux-developer-release-el9
  printf '%s' cli-install > /etc/oci-energy-ai/bootstrap-stage
  timeout 600 dnf -y --setopt=timeout=30 --setopt=retries=2 install python39-oci-cli
fi
printf '%s' runtime > /etc/oci-energy-ai/bootstrap-stage
test -x /usr/bin/python3
test -x /usr/bin/oci
test -x /usr/bin/podman
test -f /sys/fs/cgroup/cgroup.controllers
/usr/bin/python3 -c 'import sys; assert sys.version_info >= (3, 9)'
/usr/bin/podman info --format '{{.Host.CgroupsVersion}}' | /usr/bin/grep -qx v2

printf '%s' permissions > /etc/oci-energy-ai/bootstrap-stage
install -d -m 0700 /var/lib/oci-energy-ai /run/oci-energy-ai
install -d -m 0700 -o 10001 -g 10001 /var/lib/oci-energy-ai/data
id ocarun >/dev/null
visudo -cf /etc/sudoers.d/oci-energy-ai
printf '%s' firewall > /etc/oci-energy-ai/bootstrap-stage
systemctl enable --now firewalld
firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.40.0.0/24" port port="8080" protocol="tcp" accept'
firewall-cmd --reload
printf '%s' service > /etc/oci-energy-ai/bootstrap-stage
systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/oci-energy-ai.service
systemctl enable oci-energy-ai.service
rm -f /etc/oci-energy-ai/failed
touch /etc/oci-energy-ai/ready
printf '%s' complete > /etc/oci-energy-ai/bootstrap-stage
