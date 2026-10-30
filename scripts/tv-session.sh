#!/usr/bin/env bash
# Runs inside Cage as lyceumtv-kiosk, with its own session bus.
set -Eeuo pipefail

# Only change a connected output when its EDID explicitly advertises 720p.
# Do not alter Armbian boot files or force an unsupported HDMI mode.
/usr/bin/python3 -I /usr/local/lib/lyceumtv/display_mode.py || true

# A per-user PulseAudio instance supplies HDMI/analogue audio to GStreamer.
# The enclosing systemd cgroup terminates it when the kiosk stops.
if ! /usr/bin/pactl info >/dev/null 2>&1; then
  /usr/bin/pulseaudio --start --exit-idle-time=-1 --log-target=stderr || \
    echo "Audio service could not start; inspect the kiosk journal." >&2
fi
exec /usr/bin/python3 -I /usr/local/lib/lyceumtv/kiosk_browser.py
