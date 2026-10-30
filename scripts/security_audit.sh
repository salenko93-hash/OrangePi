#!/usr/bin/env bash
# Read-only checks. Installed root-owned outside the application/OTA tree.
set -uo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin
if [[ $EUID -ne 0 ]]; then echo "Run: sudo /usr/local/sbin/lyceumtv-security-audit <Orange-Pi-IP>"; exit 1; fi
PI_IP=${1:?Orange-Pi-IPv4-address is required}
python3 - "$PI_IP" <<'PY' || exit 1
import ipaddress,sys
ipaddress.IPv4Address(sys.argv[1])
PY
failed=0
check() {
  if "$@"; then echo "PASS: $*"; else echo "FAIL: $*"; failed=$((failed+1)); fi
}
echo '=== Local listening ports ==='
ss -lntp
echo '=== Application must bind only to loopback ==='
addresses=$(ss -H -ltn '( sport = :8080 )' | awk '{print $4}')
if [[ -n "$addresses" ]] && printf '%s\n' "$addresses" | awk '!/^(127\.0\.0\.1|\[::1\]):8080$/ {bad=1} END {exit bad}'; then
  echo 'PASS: backend loopback binding'
else echo 'FAIL: backend missing or exposed beyond loopback'; failed=$((failed+1)); fi
echo '=== Privilege boundary ==='
check test "$(systemctl show lyceumtv.service -p User --value)" = lyceumtv
check test "$(systemctl show lyceumtv-kiosk.service -p User --value)" = lyceumtv-kiosk
check test "$(stat -c %U /usr/local/lib/lyceumtv/watchdog.sh)" = root
check test "$(stat -c %U /usr/local/lib/lyceumtv/launch-kiosk.sh)" = root
check test "$(stat -c %U /usr/local/lib/lyceumtv)" = root
for path in /usr/local/lib/lyceumtv /usr/local/lib/lyceumtv/watchdog.sh /usr/local/lib/lyceumtv/launch-kiosk.sh /usr/local/lib/lyceumtv/tv-session.sh /usr/local/lib/lyceumtv/kiosk_browser.py /usr/local/lib/lyceumtv/display_mode.py /usr/local/sbin/lyceumtv-security-audit /usr/local/sbin/lyceumtv-console /etc/lyceumtv; do
  if [[ ! -e "$path" ]]; then
    echo "FAIL: missing $path"; failed=$((failed+1))
  elif runuser -u lyceumtv -- test -w "$path"; then
    echo "FAIL: app can write $path"; failed=$((failed+1))
  else echo "PASS: app cannot write $path"; fi
done
check test "$(stat -c %a /opt/lyceumtv/data/config.json)" = 600
check test "$(stat -c %a /etc/lyceumtv/tls/server.key)" = 600
echo '=== Private role-key policy (values are never printed) ==='
check python3 -I - <<'PYKEYS'
import json,os,stat
fd=os.open('/opt/lyceumtv/data/config.json',os.O_RDONLY|os.O_NOFOLLOW)
with os.fdopen(fd) as file:
    assert stat.S_ISREG(os.fstat(file.fileno()).st_mode)
    config=json.loads(file.read(131073))
keys=[config.get(name) for name in ('admin_key','dispatcher_key','teacher_key')]
assert all(isinstance(key,str) and 24 <= len(key) <= 256 for key in keys), 'Rotate weak legacy keys in the admin panel'
assert len(set(keys))==3, 'Role keys must differ'
print('Role keys are distinct and meet the length policy')
PYKEYS
echo '=== HTTPS identity and health ==='
check openssl x509 -in /etc/lyceumtv/tls/server.crt -checkip "$PI_IP" -noout
check openssl x509 -in /etc/lyceumtv/tls/server.crt -checkend 2592000 -noout
check curl --fail --silent --show-error --max-time 8 --cacert /etc/lyceumtv/tls/ca.crt "https://$PI_IP/api/health"
echo
echo '=== Anonymous administrator access must be denied ==='
code=$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/api/admin/dashboard)
check test "$code" = 401
echo '=== Chromium debugging port must be closed ==='
if [[ -n "$(ss -H -ltn '( sport = :9222 )')" ]]; then
  echo 'FAIL: debug port 9222 is open'; failed=$((failed+1))
else echo 'PASS: no Chromium debug port'; fi
echo '=== Installed package versions ===' 
dpkg-query -W python3 python3-openpyxl python3-qrcode python3-gi gir1.2-webkit-6.0 cage pulseaudio nginx openssl openssh-server 2>/dev/null || true
echo '=== SSH effective policy (read only) ==='
sshd -T 2>/dev/null | awk '$1 ~ /^(permitrootlogin|passwordauthentication|pubkeyauthentication|maxauthtries|allowusers)$/ {print}'
echo '=== Service sandbox assessment ==='
systemd-analyze security lyceumtv.service --no-pager || true
echo '=== Firewall ==='
if command -v nft >/dev/null; then nft list ruleset; else echo 'nft is unavailable; inspect firewall/router separately'; fi
echo "Failed checks: $failed"
exit "$((failed > 0))"
