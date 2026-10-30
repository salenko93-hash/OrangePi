#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/lyceumtv
if [[ $# -gt 0 ]]; then
  exec python3 server/backup_cli.py create --output "$1"
fi
exec python3 server/backup_cli.py create
