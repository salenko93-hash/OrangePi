#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo "Run through install.sh with sudo" >&2; exit 1; }
KIOSK_USER="${1:?Kiosk username is required}"
KIOSK_HOME="$(getent passwd "$KIOSK_USER" | cut -d: -f6)"
[[ -n "$KIOSK_HOME" && -d "$KIOSK_HOME" ]] || exit 1
/usr/bin/python3 -I "$(dirname "$0")/kiosk_profile.py" "$KIOSK_USER"

# Real logind seat, without a desktop keyring or an interactive login.
cat >/etc/pam.d/lyceumtv-kiosk <<'PAM'
#%PAM-1.0
auth       required   pam_permit.so
account    required   pam_permit.so
session    required   pam_env.so
session    required   pam_limits.so
session    optional   pam_systemd.so
PAM
chmod 644 /etc/pam.d/lyceumtv-kiosk

for svc in display-manager.service lightdm.service gdm3.service sddm.service; do
  systemctl disable "$svc" >/dev/null 2>&1 || true
  systemctl mask "$svc" >/dev/null 2>&1 || true
done
systemctl disable getty@tty1.service >/dev/null 2>&1 || true
systemctl set-default multi-user.target
echo "Cage + WebKitGTK will own HDMI/tty1 after reboot. SSH remains available."
