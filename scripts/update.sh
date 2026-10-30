#!/usr/bin/env bash
set -euo pipefail
echo "LyceumTV 3.5.1 uses SHA-256 checked OTA packages from Control Center."
echo "Open: http://$(hostname -I | awk '{print $1}'):8080/admin"
echo "System -> OTA update"
