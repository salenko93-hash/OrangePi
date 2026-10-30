#!/usr/bin/env bash
# Runs inside Cage as lyceumtv-kiosk, with its own session bus.
set -Eeuo pipefail

# Keep Cage's EDID-preferred mode. An unsolicited 720p change can make the
# Sharp TV drop/reconnect HDMI; the low-memory web profile stays enabled.
/usr/bin/python3 -I /usr/local/lib/lyceumtv/display_mode.py || true

# A per-user PulseAudio instance supplies HDMI/analogue audio to GStreamer.
# The enclosing systemd cgroup terminates it when the kiosk stops.
if ! /usr/bin/pactl info >/dev/null 2>&1; then
  /usr/bin/pulseaudio --start --exit-idle-time=-1 --log-target=stderr || \
    echo "Audio service could not start; inspect the kiosk journal." >&2
fi
exec /usr/bin/python3 -I /usr/local/lib/lyceumtv/kiosk_browser.py
