#!/usr/bin/env bash
# Root-owned entry point; WebKit and Cage run as the dedicated kiosk user.
set -Eeuo pipefail

# BEGIN LyceumTV cursor environment
export XCURSOR_THEME=lyceumtv-invisible
export XCURSOR_PATH=/usr/local/share/lyceumtv-cursors
export WLR_NO_HARDWARE_CURSORS=1
echo "TV cursor: theme=$XCURSOR_THEME path=$XCURSOR_PATH software=$WLR_NO_HARDWARE_CURSORS"
# END LyceumTV cursor environment

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if [[ ! -d "$XDG_RUNTIME_DIR" || ! -w "$XDG_RUNTIME_DIR" || ! -x "$XDG_RUNTIME_DIR" ]]; then
  echo "Kiosk cannot write XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR. Check ProtectHome=tmpfs and BindPaths in lyceumtv-kiosk.service." >&2
  exit 1
fi
if [[ $(stat -c %u -- "$XDG_RUNTIME_DIR") != "$(id -u)" || $(stat -c %a -- "$XDG_RUNTIME_DIR") != 700 ]]; then
  echo "Kiosk runtime directory must belong to the kiosk user and have mode 0700: $XDG_RUNTIME_DIR" >&2
  exit 1
fi
runtime_probe=$(mktemp "$XDG_RUNTIME_DIR/.lyceumtv-runtime-XXXXXX")
rm -f -- "$runtime_probe"

ready=false
for _ in $(seq 1 90); do
  if curl -fsS --max-time 1 http://127.0.0.1:8080/api/health >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 1
done
if [[ "$ready" != true ]]; then
  echo "LyceumTV health check failed; retrying through systemd." >&2
  exit 1
fi

export LIBSEAT_BACKEND=logind
export GDK_BACKEND=wayland
# Mali-400/Lima provides GLES2; modern GTK4 GL renderers require newer GL.
# Cairo/SHM avoid newer GL requirements; the WebKit sandbox remains enabled.
export GSK_RENDERER=cairo
export WEBKIT_DISABLE_DMABUF_RENDERER=1
# Separate homes, private runtime and the default WebKit sandbox remain enabled.
# Armbian exposes a firmware Unknown-1 output alongside physical HDMI. Extend
# would span the TV window over both; the last detected HDMI owns the kiosk.
exec /usr/bin/dbus-run-session -- /usr/bin/cage -m last -- /usr/local/lib/lyceumtv/tv-session.sh
