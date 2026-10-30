#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $EUID -eq 0 ]]; then
  echo "Запускайте install.sh звичайним користувачем із sudo доступом."
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="$(id -un)"
GROUP_NAME="$(id -gn)"
INSTALL_DIR="/opt/lyceumtv"
APP_USER="lyceumtv"
KIOSK_USER="lyceumtv-kiosk"
KIOSK_WAS_ACTIVE="$(systemctl is-active lyceumtv-kiosk.service 2>/dev/null || true)"
PI_IP="${1:?Usage: ./scripts/install.sh <Orange-Pi-IPv4-address>}"
python3 -c 'import ipaddress,sys; ipaddress.IPv4Address(sys.argv[1])' "$PI_IP"

python3 "$ROOT/scripts/deployment_preflight.py"

echo "[1/8] Installing native Armbian packages..."
sudo apt-get update
packages=(
  python3 python3-openpyxl python3-qrcode python3-gi gir1.2-gtk-4.0 gir1.2-webkit-6.0
  rsync curl cage dbus-user-session fonts-dejavu-core fonts-noto-core
  fonts-noto-color-emoji nginx openssl libgl1-mesa-dri libegl-mesa0
  gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-libav
  pulseaudio pulseaudio-utils alsa-utils wlr-randr
)
# Resolve all dependencies before stopping a working installation. No Snap/PPA
# or cross-distribution repositories are added on 32-bit Ubuntu.
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${packages[@]}"
/usr/bin/python3 -I "$ROOT/scripts/kiosk_browser.py" --check

echo "[2/8] Preserving live settings..."
sudo mkdir -p "$INSTALL_DIR"
sudo python3 "$ROOT/server/install_config.py" --check "$INSTALL_DIR/data/config.json"
# Stop writers and the old privileged timer before code/ownership migration.
sudo systemctl stop lyceumtv-watchdog.timer lyceumtv-watchdog.service lyceumtv-backup.timer lyceumtv-mirror.timer lyceumtv.service 2>/dev/null || true
if ! id "$APP_USER" >/dev/null 2>&1; then
  sudo useradd --system --user-group --home-dir /var/lib/lyceumtv --create-home --shell /usr/sbin/nologin "$APP_USER"
fi
if ! id "$KIOSK_USER" >/dev/null 2>&1; then
  sudo useradd --user-group --home-dir /var/lib/lyceumtv-kiosk --create-home --shell /usr/sbin/nologin "$KIOSK_USER"
fi
KIOSK_UID="$(id -u "$KIOSK_USER")"
for account in "$APP_USER" "$KIOSK_USER"; do
  if [[ $(id -u "$account") -eq 0 ]] || id -nG "$account" | tr ' ' '\n' | grep -Eq '^(root|sudo|wheel|adm|docker|lxd|disk|shadow)$'; then
    echo "Refusing privileged service account: $account" >&2
    exit 1
  fi
  if [[ $(getent passwd "$account" | cut -d: -f7) != /usr/sbin/nologin ]]; then
    echo "Service account must have nologin shell: $account" >&2
    exit 1
  fi
done
sudo chmod 700 /var/lib/lyceumtv /var/lib/lyceumtv-kiosk
sudo python3 - "$INSTALL_DIR/data/ota_pending" <<'PYOTA'
import json, pathlib, sys, time
path=pathlib.Path(sys.argv[1])
if path.exists():
    try: value=json.loads(path.read_text())
    except ValueError: value=None
    if isinstance(value,dict) and value.get("schema")==1:
        raise SystemExit("Спочатку завершіть або відновіть поточне OTA-оновлення")
    path.rename(path.with_name("ota_pending.legacy-"+str(time.time_ns())))
PYOTA
TMP_CFG="$(mktemp -d)"
if [[ -f "$INSTALL_DIR/data/config.json" ]]; then
  sudo cp "$INSTALL_DIR/data/config.json" "$TMP_CFG/config.json"
fi
if [[ -f "$INSTALL_DIR/data/runtime.json" ]]; then
  sudo cp "$INSTALL_DIR/data/runtime.json" "$TMP_CFG/runtime.json"
fi
for f in control.json calendar_override.json bells_override.json screens.json; do
  if [[ -f "$INSTALL_DIR/data/$f" ]]; then
    sudo cp "$INSTALL_DIR/data/$f" "$TMP_CFG/$f"
  fi
done

echo "[3/8] Installing LyceumTV files..."
sudo rsync -a --delete \
  --exclude '.git' \
  --include 'data/' \
  --include 'data/default/***' \
  --include 'data/config.example.json' \
  --exclude 'data/***' \
  --exclude 'public/media/' \
  --exclude 'docs/' \
  --exclude 'tests/' \
  --exclude 'tools/' \
  --exclude 'cloud/' \
  "$ROOT/" "$INSTALL_DIR/"

if [[ -f "$TMP_CFG/config.json" ]]; then
  sudo cp "$TMP_CFG/config.json" "$INSTALL_DIR/data/config.json"
fi
if [[ -f "$TMP_CFG/runtime.json" ]]; then
  sudo cp "$TMP_CFG/runtime.json" "$INSTALL_DIR/data/runtime.json"
fi
for f in control.json calendar_override.json bells_override.json screens.json; do
  if [[ -f "$TMP_CFG/$f" ]]; then
    sudo cp "$TMP_CFG/$f" "$INSTALL_DIR/data/$f"
  fi
done


# Prepare application-owned storage before config and calendar migrations.
# Existing live files can belong to root or to the previous deployment user.
sudo chown -R "$USER_NAME:$GROUP_NAME" "$INSTALL_DIR"
sudo chmod -R u+rwX "$INSTALL_DIR/data"
if [[ -f "$INSTALL_DIR/data/config.json" ]]; then
  sudo chmod 600 "$INSTALL_DIR/data/config.json"
fi

python3 "$INSTALL_DIR/server/install_config.py" "$INSTALL_DIR/data/config.json" "$INSTALL_DIR/data/config.example.json" --public-ip "$PI_IP"

mkdir -p "$INSTALL_DIR/data/current" "$INSTALL_DIR/data/backups" "$INSTALL_DIR/data/logs"
python3 "$INSTALL_DIR/server/runtime_data.py" "$INSTALL_DIR"

# Migrate only the built-in academic calendar to the corrected
# learning-process structure. Custom/imported calendars and local overrides
# are preserved.
python3 - "$INSTALL_DIR/data/current/calendar.json" "$INSTALL_DIR/data/default/calendar.json" <<'PYCAL'
import json, os, shutil, sys
live, corrected = sys.argv[1], sys.argv[2]
should_replace = not os.path.exists(live)
if os.path.exists(live):
    try:
        with open(live, "r", encoding="utf-8") as f:
            obj = json.load(f)
        source = str(obj.get("source", ""))
        should_replace = (
            not source
            or "структура навчального року" in source
            or "нова структура навчального року з чергуванням" in source
        )
    except Exception:
        should_replace = True
if should_replace and os.path.exists(corrected):
    os.makedirs(os.path.dirname(live), exist_ok=True)
    shutil.copy2(corrected, live)
PYCAL
if [[ ! -f "$INSTALL_DIR/data/smart_ops.json" && -f "$INSTALL_DIR/data/default/smart_ops.json" ]]; then
  cp "$INSTALL_DIR/data/default/smart_ops.json" "$INSTALL_DIR/data/smart_ops.json"
fi
mkdir -p "$INSTALL_DIR/public/media"

# Preserve all four live schedules across updates.
# The initial install already populates missing schedules from data/default.
# Never replace teacher-edited live schedules in a maintenance release.

rm -rf "$TMP_CFG"
# The network service has no SSH identity or sudo rights.
sudo chown -R "$APP_USER:$APP_USER" "$INSTALL_DIR"
sudo chmod 700 "$INSTALL_DIR/data"
sudo chmod 755 "$INSTALL_DIR" "$INSTALL_DIR/scripts"
sudo install -d -o root -g root -m 755 /usr/local/lib/lyceumtv
sudo install -o root -g root -m 755 "$ROOT/scripts/watchdog.sh" /usr/local/lib/lyceumtv/watchdog.sh
sudo install -o root -g root -m 755 "$ROOT/scripts/launch-kiosk.sh" /usr/local/lib/lyceumtv/launch-kiosk.sh
sudo install -o root -g root -m 755 "$ROOT/scripts/tv-session.sh" /usr/local/lib/lyceumtv/tv-session.sh
sudo install -o root -g root -m 644 "$ROOT/scripts/kiosk_browser.py" /usr/local/lib/lyceumtv/kiosk_browser.py
sudo install -o root -g root -m 644 "$ROOT/scripts/display_mode.py" /usr/local/lib/lyceumtv/display_mode.py
sudo /usr/bin/python3 -I "$ROOT/scripts/hide_cursor.py"
sudo install -o root -g root -m 755 "$ROOT/scripts/rollback-headless-kiosk.sh" /usr/local/sbin/lyceumtv-console
sudo install -o root -g root -m 755 "$ROOT/scripts/security_audit.sh" /usr/local/sbin/lyceumtv-security-audit
sudo install -o root -g root -m 755 "$ROOT/scripts/show_keys.py" /usr/local/sbin/lyceumtv-show-keys
sudo "$ROOT/scripts/configure_https.sh" "$PI_IP"
sudo install -o "$USER_NAME" -g "$GROUP_NAME" -m 644 /etc/lyceumtv/tls/ca.crt "$HOME/lyceumtv-ca.crt"
sudo chmod 600 "$INSTALL_DIR/data/config.json"
sudo chmod +x "$INSTALL_DIR/scripts/"*.sh

echo "[4/8] Preparing kiosk user..."
for grp in video render input audio; do
  if getent group "$grp" >/dev/null 2>&1; then
    sudo usermod -aG "$grp" "$KIOSK_USER"
  fi
done
sudo "$ROOT/scripts/prepare-kiosk.sh" "$KIOSK_USER"

echo "[5/8] Installing systemd services..."
sudo tee /etc/systemd/system/lyceumtv.service >/dev/null <<EOF
[Unit]
Description=LyceumTV 3.7.3
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
NoNewPrivileges=true
UMask=0077
TasksMax=128
MemoryHigh=128M
MemoryMax=256M
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=$INSTALL_DIR
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 $INSTALL_DIR/launcher.py
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/lyceumtv-kiosk.service >/dev/null <<EOF
[Unit]
Description=LyceumTV Adaptive TV Kiosk
After=network-online.target systemd-user-sessions.service lyceumtv.service
Wants=network-online.target lyceumtv.service
Requires=user-runtime-dir@$KIOSK_UID.service
After=user-runtime-dir@$KIOSK_UID.service
Conflicts=getty@tty1.service
StartLimitIntervalSec=0

[Service]
Type=simple
User=$KIOSK_USER
Group=$KIOSK_USER
NoNewPrivileges=true
AmbientCapabilities=
UMask=0077
ProtectHome=tmpfs
BindPaths=/run/user/$KIOSK_UID
MemoryHigh=384M
MemoryMax=576M
TasksMax=256
PAMName=lyceumtv-kiosk
TTYPath=/dev/tty1
StandardInput=tty-force
StandardOutput=journal
StandardError=journal
TTYReset=yes
TTYVHangup=yes
TTYVTDisallocate=yes
UtmpIdentifier=tty1
UtmpMode=user
Environment=XDG_RUNTIME_DIR=/run/user/$KIOSK_UID
ExecStart=/usr/local/lib/lyceumtv/launch-kiosk.sh
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/lyceumtv-watchdog.service >/dev/null <<EOF
[Unit]
Description=LyceumTV watchdog

[Service]
Type=oneshot
User=root
RuntimeDirectory=lyceumtv-watchdog
RuntimeDirectoryMode=0700
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ExecStart=/usr/local/lib/lyceumtv/watchdog.sh
EOF

sudo tee /etc/systemd/system/lyceumtv-watchdog.timer >/dev/null <<'EOF'
[Unit]
Description=Run LyceumTV watchdog every 20 seconds

[Timer]
OnBootSec=45
OnUnitActiveSec=20
AccuracySec=3
Unit=lyceumtv-watchdog.service

[Install]
WantedBy=timers.target
EOF

sudo tee /etc/systemd/system/lyceumtv-backup.service >/dev/null <<EOF
[Unit]
Description=LyceumTV daily Smart Campus backup
After=lyceumtv.service

[Service]
Type=oneshot
User=$APP_USER
Group=$APP_USER
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ExecStart=$INSTALL_DIR/scripts/daily_backup.sh
EOF

sudo tee /etc/systemd/system/lyceumtv-backup.timer >/dev/null <<'EOF'
[Unit]
Description=LyceumTV daily backup timer

[Timer]
OnCalendar=hourly
Persistent=true
RandomizedDelaySec=300
Unit=lyceumtv-backup.service

[Install]
WantedBy=timers.target
EOF

sudo tee /etc/systemd/system/lyceumtv-mirror.service >/dev/null <<EOF
[Unit]
Description=LyceumTV Cloud Mirror sync
After=network-online.target lyceumtv.service
Wants=network-online.target

[Service]
Type=oneshot
User=$APP_USER
Group=$APP_USER
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ExecStart=$INSTALL_DIR/scripts/cloud_mirror.sh
EOF

sudo tee /etc/systemd/system/lyceumtv-mirror.timer >/dev/null <<'EOF'
[Unit]
Description=LyceumTV Cloud Mirror timer

[Timer]
OnBootSec=120
OnUnitActiveSec=60
Persistent=true
Unit=lyceumtv-mirror.service

[Install]
WantedBy=timers.target
EOF

echo "[6/8] Preparing Armbian kiosk boot..."
# Armbian owns its boot configuration and zram settings. Keep them intact.
# The logind/Cage session controls blanking and the cursor after reboot.

echo "[7/8] Enabling services..."
sudo systemctl daemon-reload
sudo systemctl enable lyceumtv.service
sudo systemctl restart lyceumtv.service
sudo systemctl enable lyceumtv-kiosk.service
if [[ "$KIOSK_WAS_ACTIVE" == active ]]; then sudo systemctl restart lyceumtv-kiosk.service; fi
sudo systemctl enable --now lyceumtv-watchdog.timer
sudo systemctl enable --now lyceumtv-backup.timer
sudo systemctl enable --now lyceumtv-mirror.timer

echo "[8/8] Health check..."
sleep 2
healthy=false
for _ in $(seq 1 30); do
  if curl -fsS --max-time 3 http://127.0.0.1:8080/api/health; then healthy=true; break; fi
  sleep 1
done
[[ "$healthy" == true ]] || { echo "Server health check failed. Inspect: sudo journalctl -u lyceumtv -n 60" >&2; exit 1; }

echo
echo "LyceumTV 3.7.3 installed."
echo "TV:      https://$PI_IP/"
echo "Admin:   https://$PI_IP/admin"
echo "Ops:     https://$PI_IP/ops"
echo "Teacher: https://$PI_IP/teacher"
echo "Campus:  https://$PI_IP/campus/"
echo "Trust certificate: /etc/lyceumtv/tls/ca.crt (copy using SSH)"
echo "Role keys are private in /opt/lyceumtv/data/config.json; retrieve using sudo via SSH."
echo "The next reboot starts directly into Cage + WebKitGTK, without a desktop session."
echo
echo "Reboot:"
echo "  sudo reboot"
echo
echo "Status after reboot:"
echo "  systemctl status lyceumtv --no-pager"
echo "  systemctl status lyceumtv-kiosk --no-pager"
echo "  systemctl status lyceumtv-watchdog.timer --no-pager"
