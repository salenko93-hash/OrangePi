#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/lyceumtv
exec python3 server/backup_cli.py daily
