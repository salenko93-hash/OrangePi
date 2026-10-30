#!/usr/bin/env bash
# Installed root-owned outside the writable application tree. Never import app code.
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
STATE=/run/lyceumtv-watchdog
if /usr/bin/curl -fsS --max-time 4 http://127.0.0.1:8080/api/health >/dev/null; then
  rm -f "$STATE/ota-since"
else
  if [[ -f /opt/lyceumtv/data/ota_pending ]]; then
    now=$(date +%s)
    if [[ ! -f "$STATE/ota-since" ]]; then echo "$now" > "$STATE/ota-since"; fi
    since=$(cat "$STATE/ota-since")
    if (( now - since < 180 )); then exit 0; fi
  fi
  /usr/bin/logger -t lyceumtv-watchdog 'Health unavailable; restarting supervisor'
  /usr/bin/systemctl restart lyceumtv.service
  rm -f "$STATE/ota-since"
fi
if ! /usr/bin/systemctl is-active --quiet lyceumtv-kiosk.service; then
  /usr/bin/systemctl restart lyceumtv-kiosk.service
fi
