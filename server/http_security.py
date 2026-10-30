"""Bounded HTTP workers, deadlines, same-origin writes and security headers."""

from collections import OrderedDict, deque
from http.server import ThreadingHTTPServer
import ipaddress
import socket
import threading
import time
from urllib.parse import urlsplit


class RateLimits:
    def __init__(self):
        self.lock = threading.Lock()
        self.items = OrderedDict()

    def hit(self, key, limit, seconds):
        with self.lock:
            now = time.monotonic()
            values = self.items.pop(key, deque())
            while values and values[0] <= now - seconds:
                values.popleft()
            permitted = len(values) < limit
            if permitted:
                values.append(now)
            self.items[key] = values
            while len(self.items) > 2048:
                self.items.popitem(last=False)
            return permitted

    def blocked(self, key, limit, seconds):
        with self.lock:
            values = self.items.get(key, ())
            return sum(t > time.monotonic() - seconds for t in values) >= limit


LIMITS = RateLimits()


class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32

    def __init__(self, *args, max_workers=24, **kwargs):
        self.slots = threading.BoundedSemaphore(max_workers)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            try:
                request.settimeout(0.2)
                request.sendall(
                    b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                )
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class SecureHTTPMixin:
    def setup(self):
        super().setup()
        self.connection.settimeout(8)
        self._deadline = None
        self._set_deadline(10)

    def _set_deadline(self, seconds):
        if self._deadline:
            self._deadline.cancel()

        def expire():
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        self._deadline = threading.Timer(seconds, expire)
        self._deadline.daemon = True
        self._deadline.start()

    def finish(self):
        try:
            super().finish()
        finally:
            self._deadline.cancel()

    def direct_loopback(self):
        host = urlsplit("http://" + self.headers.get("Host", "")).hostname
        return (
            self.client_address[0] in {"127.0.0.1", "::1"}
            and host in {"127.0.0.1", "localhost", "::1"}
            and not self.headers.get("X-Forwarded-For")
            and not self.headers.get("X-Forwarded-Proto")
        )

    def peer_ip(self):
        peer = self.client_address[0]
        if peer in {"127.0.0.1", "::1"} and self.headers.get("X-Real-IP"):
            try:
                return str(ipaddress.ip_address(self.headers["X-Real-IP"]))
            except ValueError:
                pass
        return peer

    def is_secure(self):
        return (
            self.client_address[0] in {"127.0.0.1", "::1"}
            and self.headers.get("X-Forwarded-Proto") == "https"
        )

    def parse_request(self):
        if not super().parse_request():
            return False
        path = urlsplit(self.path).path
        upload = path == "/api/ops/media/upload-file"
        self._set_deadline(300 if upload or path.startswith("/media/") else 25)
        if self.command == "POST":
            if (
                self.headers.get("Transfer-Encoding")
                or len(self.headers.get_all("Content-Length", [])) > 1
            ):
                self._send_json(
                    400, {"ok": False, "error": "Некоректне обрамлення запиту"}
                )
                return False
            origin = self.headers.get("Origin", "")
            expected = (
                ("https" if self.is_secure() else "http")
                + "://"
                + self.headers.get("Host", "")
            )
            if (origin and origin != expected) or (
                self.headers.get("Cookie")
                and not origin
                and not self.headers.get("X-Device-Token")
            ):
                self._send_json(
                    403, {"ok": False, "error": "Потрібен запит з цього самого сайту"}
                )
                return False
        if path.startswith("/api/"):
            peer = self.peer_ip()
            if not LIMITS.hit(("requests", peer), 120, 10):
                self._send_json(
                    429, {"ok": False, "error": "Забагато запитів. Спробуйте пізніше"}
                )
                return False
            if path not in {"/api/health", "/api/state"} and LIMITS.blocked(
                ("auth", peer), 10, 60
            ):
                self._send_json(
                    429,
                    {
                        "ok": False,
                        "error": "Забагато невдалих спроб входу. Зачекайте хвилину",
                    },
                )
                return False
        return True

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; media-src 'self' blob: https:; connect-src 'self' https:; font-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        )
        if getattr(self, "response_cookie", None):
            self.send_header("Set-Cookie", self.response_cookie)
        super().end_headers()
