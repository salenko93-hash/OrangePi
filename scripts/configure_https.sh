#!/usr/bin/env bash
# Privileged install helper; never invoked by the running application.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo "Run through the installer with sudo" >&2; exit 1; }
PI_IP=${1:?Orange-Pi-IPv4-address is required}
python3 - "$PI_IP" <<'PY'
import ipaddress,sys
ipaddress.IPv4Address(sys.argv[1])
PY
TLS=/etc/lyceumtv/tls
install -d -o root -g root -m 755 /etc/lyceumtv
install -d -o root -g root -m 700 "$TLS"
umask 077
if [[ ! -f "$TLS/ca.key" || ! -f "$TLS/ca.crt" ]]; then
  openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 3650 \
    -keyout "$TLS/ca.key" -out "$TLS/ca.crt" \
    -subj '/CN=LyceumTV Local CA' \
    -addext 'basicConstraints=critical,CA:TRUE,pathlen:0' \
    -addext 'keyUsage=critical,keyCertSign,cRLSign'
fi
if [[ ! -f "$TLS/server.crt" ]] || ! openssl x509 -in "$TLS/server.crt" -checkend 2592000 -noout || \
   ! openssl x509 -in "$TLS/server.crt" -checkip "$PI_IP" -noout; then
  openssl req -new -newkey rsa:3072 -nodes -keyout "$TLS/server.key" \
    -out "$TLS/server.csr" -subj '/CN=lyceumtv.local'
  cat > "$TLS/server.ext" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=IP:$PI_IP,DNS:lyceumtv.local
EOF
  openssl x509 -req -in "$TLS/server.csr" -CA "$TLS/ca.crt" -CAkey "$TLS/ca.key" \
    -CAcreateserial -out "$TLS/server.crt" -days 825 -sha256 -extfile "$TLS/server.ext"
fi
chmod 600 "$TLS/ca.key" "$TLS/server.key"
chmod 644 "$TLS/ca.crt" "$TLS/server.crt"
cat > /etc/nginx/conf.d/lyceumtv.conf <<'NGINX'
limit_req_zone $binary_remote_addr zone=lyceumtv_rate:10m rate=15r/s;
limit_conn_zone $binary_remote_addr zone=lyceumtv_connections:10m;
server {
    listen 443 ssl;
    server_name _;
    ssl_certificate /etc/lyceumtv/tls/server.crt;
    ssl_certificate_key /etc/lyceumtv/tls/server.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    server_tokens off;
    client_max_body_size 200m;
    client_header_timeout 10s;
    client_body_timeout 20s;
    send_timeout 30s;
    limit_conn lyceumtv_connections 30;
    location = /api/screen/local-token { return 403; }
    location / {
        limit_req zone=lyceumtv_rate burst=100 nodelay;
        limit_req_status 429;
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
        proxy_request_buffering off;
        proxy_read_timeout 310s;
    }
}
NGINX
nginx -t
systemctl enable nginx
systemctl reload-or-restart nginx
