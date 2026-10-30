#!/usr/bin/env bash
set -Eeuo pipefail
INSTALL_DIR="/opt/lyceumtv"
CFG="$INSTALL_DIR/data/config.json"
MARKER="$INSTALL_DIR/data/mirror_last_run"

readarray -t VALUES < <(python3 - "$CFG" <<'PY'
import json, sys
try: cfg=json.load(open(sys.argv[1],encoding="utf-8"))
except Exception: cfg={}
print("1" if cfg.get("cloud_mirror_enabled") else "0")
print(str(cfg.get("cloud_mirror_url") or ""))
print(str(cfg.get("cloud_mirror_token") or ""))
print(max(1,int(cfg.get("cloud_mirror_interval_minutes",5) or 5)))
PY
)
ENABLED="${VALUES[0]:-0}"; URL="${VALUES[1]:-}"; TOKEN="${VALUES[2]:-}"; INTERVAL="${VALUES[3]:-5}"
[[ "$ENABLED" == "1" && -n "$URL" ]] || exit 0
NOW="$(date +%s)"; LAST="$(cat "$MARKER" 2>/dev/null || echo 0)"
(( NOW - LAST >= INTERVAL * 60 )) || exit 0

TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
curl -fsS --max-time 15 http://127.0.0.1:8080/api/public/export -o "$TMP"
ARGS=(-fsS --max-time 20 -X POST -H 'Content-Type: application/json' --data-binary "@$TMP")
[[ -n "$TOKEN" ]] && ARGS+=(-H "Authorization: Bearer $TOKEN")
curl "${ARGS[@]}" "$URL" >/dev/null
echo "$NOW" >"$MARKER"
