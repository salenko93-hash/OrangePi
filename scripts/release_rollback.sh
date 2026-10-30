#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/lyceumtv
exec python3 server/update_transaction.py --root /opt/lyceumtv --rollback
