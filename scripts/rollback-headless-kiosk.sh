#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo "Run: sudo $0" >&2; exit 1; }
systemctl disable --now lyceumtv-watchdog.timer lyceumtv-kiosk.service
systemctl enable --now getty@tty1.service
systemctl set-default multi-user.target
echo "TV kiosk stopped. Text console and SSH are available; server and data are retained."
