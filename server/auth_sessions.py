"""Short-lived, revocable browser sessions. Raw role keys never enter cookies."""

from collections import OrderedDict
import hashlib
from http.cookies import SimpleCookie
import secrets
import threading
import time

COOKIE = "lyceumtv_session"
TTL = 2 * 60 * 60


class Sessions:
    def __init__(self):
        self.items = OrderedDict()
        self.lock = threading.Lock()

    @staticmethod
    def fingerprint(value):
        return hashlib.sha256(str(value).encode()).hexdigest()

    @staticmethod
    def token(cookie):
        try:
            parsed = SimpleCookie()
            parsed.load(cookie or "")
            return parsed[COOKIE].value if COOKIE in parsed else ""
        except Exception:
            return ""

    def create(self, role, config):
        token = secrets.token_urlsafe(32)
        with self.lock:
            now = time.monotonic()
            for old in list(self.items):
                if self.items[old][2] <= now:
                    del self.items[old]
            while len(self.items) >= 256:
                self.items.popitem(last=False)
            self.items[self.fingerprint(token)] = (
                role,
                self.fingerprint(config[role + "_key"]),
                now + TTL,
            )
        return token

    def resolve(self, cookie, config):
        token = self.token(cookie)
        if not token:
            return ""
        with self.lock:
            key = self.fingerprint(token)
            value = self.items.get(key)
            if not value:
                return ""
            role, fingerprint, until = value
            if until <= time.monotonic() or fingerprint != self.fingerprint(
                config.get(role + "_key", "")
            ):
                del self.items[key]
                return ""
            return role

    def revoke(self, cookie):
        with self.lock:
            self.items.pop(self.fingerprint(self.token(cookie)), None)


SESSIONS = Sessions()
