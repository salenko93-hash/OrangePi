"""Security regressions; all HTTP and file mutations use disposable local copies."""

import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
from http.server import BaseHTTPRequestHandler
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from auth_sessions import Sessions, COOKIE
from http_security import BoundedHTTPServer, RateLimits
from install_config import migrate
from media_io import save_stream
from release_signature import signed_bytes, verify_manifest_signature


class SecurityUnitTests(unittest.TestCase):
    def test_release_builder_refuses_key_material(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "security_release_builder", ROOT / "tools/build_release.py"
        )
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "reports").mkdir()
            (root / "reports/accidental-private.key").write_text("dummy test marker")
            with self.assertRaises(ValueError):
                builder.release_files(root)

    def test_upgrade_rotates_known_defaults_once_and_preserves_custom_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            live = Path(directory) / "config.json"
            live.write_text(
                json.dumps(
                    {
                        "admin_key": "lyceumtv-admin",
                        "dispatcher_key": "custom-dispatch-key",
                        "teacher_key": "lyceumtv-teacher",
                        "host": "0.0.0.0",
                        "alerts_token": "preserve-token",
                    }
                )
            )
            first = migrate(live, ROOT / "data/config.example.json")
            self.assertGreaterEqual(len(first["admin_key"]), 32)
            self.assertGreaterEqual(len(first["teacher_key"]), 32)
            self.assertEqual(first["dispatcher_key"], "custom-dispatch-key")
            self.assertEqual(first["alerts_token"], "preserve-token")
            self.assertEqual(first["host"], "127.0.0.1")
            self.assertEqual(migrate(live, ROOT / "data/config.example.json"), first)
            if os.name == "posix":
                self.assertEqual(live.stat().st_mode & 0o777, 0o600)

    def test_sessions_expire_revoke_and_invalidate_on_key_rotation(self):
        sessions = Sessions()
        cfg = {"admin_key": "private-session-test-key"}
        token = sessions.create("admin", cfg)
        cookie = f"{COOKIE}={token}"
        self.assertNotIn(token, sessions.items)
        self.assertEqual(sessions.resolve(cookie, cfg), "admin")
        self.assertEqual(sessions.resolve(cookie, {"admin_key": "new-key"}), "")
        token = sessions.create("admin", cfg)
        cookie = f"{COOKIE}={token}"
        sessions.revoke(cookie)
        self.assertEqual(sessions.resolve(cookie, cfg), "")
        token = sessions.create("admin", cfg)
        with patch(
            "auth_sessions.time.monotonic", return_value=time.monotonic() + 7201
        ):
            self.assertEqual(sessions.resolve(f"{COOKIE}={token}", cfg), "")

    def test_media_signatures_quota_free_space_and_parallel_uploads(self):
        raw = b"\x00\x00\x00\x18ftypisom" + b"x" * 90
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                save_stream(directory, "fake.mp4", io.BytesIO(b"not a movie"), 11)
            with patch(
                "media_io.shutil.disk_usage",
                return_value=type("Disk", (), {"free": 0})(),
            ):
                with self.assertRaises(ValueError):
                    save_stream(directory, "clip.mp4", io.BytesIO(raw), len(raw))

            def upload(_):
                try:
                    save_stream(
                        directory,
                        "clip.mp4",
                        io.BytesIO(raw),
                        len(raw),
                        quota_bytes=len(raw) + 1,
                        reserve_bytes=0,
                    )
                    return True
                except ValueError:
                    return False

            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertEqual(sum(pool.map(upload, range(2))), 1)
            self.assertEqual(len(list(Path(directory).glob("*.mp4"))), 1)
            self.assertFalse(list(Path(directory).glob("*.part")))

    def test_rate_limit_is_bounded_and_recovers(self):
        limits = RateLimits()
        with patch("http_security.time.monotonic", return_value=100):
            self.assertTrue(limits.hit("client", 2, 10))
            self.assertTrue(limits.hit("client", 2, 10))
            self.assertFalse(limits.hit("client", 2, 10))
        with patch("http_security.time.monotonic", return_value=111):
            self.assertTrue(limits.hit("client", 2, 10))
        for n in range(2100):
            limits.hit(n, 1, 10)
        self.assertLessEqual(len(limits.items), 2048)

    def test_worker_limit_rejects_excess_and_releases_slots(self):
        release = threading.Event()
        entered = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                entered.set()
                release.wait(3)
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        server = BoundedHTTPServer(("127.0.0.1", 0), Handler, max_workers=1)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        first = socket.create_connection(server.server_address, timeout=3)
        first.sendall(b"GET / HTTP/1.0\r\n\r\n")
        try:
            self.assertTrue(entered.wait(2))
            with socket.create_connection(server.server_address, timeout=3) as second:
                second.sendall(b"GET / HTTP/1.0\r\n\r\n")
                self.assertIn(b"503", second.recv(1024))
            release.set()
            self.assertIn(b"200", first.recv(1024))
        finally:
            release.set()
            first.close()
            server.shutdown()
            server.server_close()
            worker.join(3)

    @unittest.skipUnless(shutil.which("openssl"), "requires OpenSSL Ed25519")
    def test_release_signature_rejects_tamper_unsigned_wrong_key(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            private, public = directory / "private.pem", directory / "public.pem"
            subprocess.run(
                ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private)],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "openssl",
                    "pkey",
                    "-in",
                    str(private),
                    "-pubout",
                    "-out",
                    str(public),
                ],
                check=True,
                capture_output=True,
            )
            manifest = {
                "version": "99.0.0",
                "package_url": "https://example.org/app.zip",
                "sha256": "a" * 64,
            }
            with self.assertRaises(ValueError):
                verify_manifest_signature(manifest, public, require_root=False)
            message, signature = directory / "message", directory / "signature"
            message.write_bytes(signed_bytes(manifest))
            subprocess.run(
                [
                    "openssl",
                    "pkeyutl",
                    "-sign",
                    "-inkey",
                    str(private),
                    "-rawin",
                    "-in",
                    str(message),
                    "-out",
                    str(signature),
                ],
                check=True,
                capture_output=True,
            )
            manifest["signature"] = base64.b64encode(signature.read_bytes()).decode()
            verify_manifest_signature(manifest, public, require_root=False)
            for field in ("version", "package_url", "sha256"):
                tampered = {**manifest, field: "changed"}
                with self.assertRaises(ValueError):
                    verify_manifest_signature(tampered, public, require_root=False)
            with self.assertRaises(ValueError):
                verify_manifest_signature(manifest, directory / "missing.pem")
            if hasattr(os, "getuid") and os.getuid() != 0:
                with self.assertRaises(ValueError):
                    verify_manifest_signature(manifest, public)


class SecurityHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="lyceum-security-http-")
        cls.app = Path(cls.tmp.name) / "app"
        shutil.copytree(
            ROOT,
            cls.app,
            ignore=shutil.ignore_patterns(
                ".git", "dist", "__pycache__", ".venv", ".ruff_cache"
            ),
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        cls.config = json.loads((cls.app / "data/config.example.json").read_text())
        cls.config.update(
            port=port,
            host="127.0.0.1",
            weather_enabled=False,
            manifest_url="",
            sheets_url="",
            alerts_token="",
            telegram_enabled=False,
            admin_key="test-admin-" + "a" * 32,
            dispatcher_key="test-dispatch-" + "b" * 32,
            teacher_key="test-teacher-" + "c" * 32,
        )
        (cls.app / "data/config.json").write_text(json.dumps(cls.config))
        cls.base = f"http://127.0.0.1:{port}"
        cls.port = port
        cls.log = (Path(cls.tmp.name) / "server.log").open("w")
        cls.server = subprocess.Popen(
            [sys.executable, "-B", "server/app.py"],
            cwd=cls.app,
            stdout=cls.log,
            stderr=cls.log,
        )
        for _ in range(100):
            try:
                with urlopen(cls.base + "/api/health", timeout=1):
                    return
            except OSError:
                time.sleep(0.1)
        cls.tearDownClass()
        raise RuntimeError("security test server failed to start")

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        try:
            cls.server.wait(5)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait()
        cls.log.close()
        cls.tmp.cleanup()

    def request(self, path, body=None, role=None, headers=None, raw=None):
        # Distinct simulated proxy clients keep brute-force tests independent.
        client = int(hashlib.sha256(self.id().encode()).hexdigest()[:4], 16)
        merged = {
            "Content-Type": "application/json",
            "X-Real-IP": f"198.18.{client // 256}.{client % 256}",
        }
        if role:
            merged["X-Admin-Key" if role == "admin" else "X-Role-Key"] = self.config[
                role + "_key"
            ]
        merged.update(headers or {})
        data = (
            raw
            if raw is not None
            else json.dumps(body).encode()
            if body is not None
            else None
        )
        try:
            response = urlopen(
                Request(self.base + path, data=data, headers=merged), timeout=6
            )
        except HTTPError as error:
            response = error
        with response:
            content = response.read()
            try:
                content = json.loads(content)
            except (ValueError, UnicodeError):
                pass
            return response.status, content, dict(response.headers)

    def test_roles_default_keys_and_public_secrets(self):
        for role in (None, "teacher", "dispatcher"):
            self.assertEqual(self.request("/api/admin/dashboard", role=role)[0], 401)
        self.assertEqual(
            self.request(
                "/api/admin/dashboard", headers={"X-Admin-Key": "lyceumtv-admin"}
            )[0],
            401,
        )
        self.assertEqual(self.request("/api/admin/dashboard", role="admin")[0], 200)
        state = self.request("/api/state")[1]
        for key in ("admin_key", "dispatcher_key", "teacher_key", "local_screen_token"):
            self.assertNotIn(key, state["config_public"])
            self.assertNotIn(self.config[key], json.dumps(state)) if self.config[
                key
            ] else None

    def test_session_cookie_csrf_logout_and_proxy_secure_flag(self):
        result = self.request(
            "/api/auth/login",
            {"key": self.config["admin_key"]},
            headers={"Origin": self.base},
        )
        self.assertEqual(result[0], 200)
        cookie = result[2]["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertNotIn(self.config["admin_key"], cookie)
        auth = {"Cookie": cookie.split(";")[0]}
        self.assertEqual(self.request("/api/admin/dashboard", headers=auth)[0], 200)
        self.assertEqual(
            self.request(
                "/api/admin/config",
                {"config": {"slideshow_title": "blocked"}},
                headers={**auth, "Origin": "https://evil.invalid"},
            )[0],
            403,
        )
        self.assertEqual(
            self.request(
                "/api/admin/config",
                {"config": {"slideshow_title": "blocked"}},
                headers=auth,
            )[0],
            403,
        )
        self.assertEqual(
            self.request("/api/auth/logout", {}, headers={**auth, "Origin": self.base})[
                0
            ],
            200,
        )
        self.assertEqual(self.request("/api/admin/dashboard", headers=auth)[0], 401)
        secure = self.request(
            "/api/auth/login",
            {"key": self.config["admin_key"]},
            headers={
                "Host": "192.168.0.18",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-For": "192.168.0.99",
                "Origin": "https://192.168.0.18",
            },
        )
        self.assertEqual(secure[0], 200)
        self.assertIn("; Secure", secure[2]["Set-Cookie"])
        self.assertEqual(
            self.request(
                "/api/auth/login",
                {"key": self.config["admin_key"]},
                headers={"Host": "192.168.0.18", "X-Forwarded-For": "192.168.0.99"},
            )[0],
            403,
        )

    def test_device_tokens_are_scoped_rotated_and_required(self):
        for path, body in [
            ("/api/screen/heartbeat", {"id": "untrusted"}),
            ("/api/screen/ack", {"id": "untrusted", "command_id": 1}),
        ]:
            self.assertEqual(self.request(path, body)[0], 401)
        paired = self.request(
            "/api/admin/screen", {"op": "pair", "id": "security-screen"}, role="admin"
        )[1]
        token = paired["token"]
        headers = {"X-Device-Token": token}
        self.assertEqual(
            self.request(
                "/api/screen/heartbeat", {"id": "security-screen"}, headers=headers
            )[0],
            200,
        )
        self.assertEqual(
            self.request(
                "/api/screen/heartbeat", {"id": "another-screen"}, headers=headers
            )[0],
            401,
        )
        self.request(
            "/api/admin/screen",
            {"op": "command", "id": "security-screen", "command": "reload"},
            role="admin",
        )
        pending = self.request(
            "/api/screen/heartbeat", {"id": "security-screen"}, headers=headers
        )[1]["screen"]
        ack = {"id": "security-screen", "command_id": pending["command_id"]}
        self.assertEqual(self.request("/api/screen/ack", ack)[0], 401)
        self.assertEqual(
            self.request(
                "/api/screen/heartbeat", {"id": "security-screen"}, headers=headers
            )[1]["screen"]["command"],
            "reload",
        )
        self.assertTrue(
            self.request("/api/screen/ack", ack, headers=headers)[1]["acknowledged"]
        )
        self.request(
            "/api/admin/screen", {"op": "pair", "id": "security-screen"}, role="admin"
        )
        self.assertEqual(
            self.request(
                "/api/screen/heartbeat", {"id": "security-screen"}, headers=headers
            )[0],
            401,
        )
        screens = self.request("/api/admin/dashboard", role="admin")[1]["screens"]
        self.assertFalse(any(x["id"] == "untrusted" for x in screens))
        self.assertNotIn("device_token_hash", json.dumps(screens))

    def test_local_kiosk_bootstrap_denies_proxy_and_rebinding(self):
        path = "/api/screen/local-token?id=main-hall"
        self.assertEqual(self.request(path)[0], 200)
        self.assertEqual(
            self.request(
                path,
                headers={
                    "X-Forwarded-For": "192.168.0.99",
                    "X-Forwarded-Proto": "https",
                },
            )[0],
            403,
        )
        self.assertEqual(self.request(path, headers={"Host": "evil.invalid"})[0], 403)
        self.assertEqual(
            self.request(path, headers={"Sec-Fetch-Site": "cross-site"})[0], 403
        )

    def test_xss_input_headers_and_fake_media_rejected(self):
        malicious = '<img src=x onerror="window.__xss=1">'
        body = {
            "kind": "audio",
            "item": {
                "name": "test",
                "time": "12:00",
                "url": "/media/test.wav",
                "days": [malicious],
            },
        }
        self.assertEqual(self.request("/api/ops/item", body, role="dispatcher")[0], 400)
        body["item"]["days"] = ["MONDAY"]
        self.assertEqual(self.request("/api/ops/item", body, role="dispatcher")[0], 200)
        self.assertEqual(
            self.request(
                "/api/ops/media/upload-file?name=fake.mp4",
                role="dispatcher",
                raw=b"not a video",
            )[0],
            400,
        )
        headers = self.request("/ops")[2]
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(self.request("/media/.locks/upload.lock")[0], 403)

    def test_dispatcher_cannot_poison_setting_types(self):
        for setting_patch in (
            {"music_volume_percent": []},
            {"music_enabled": "false"},
            {"music_volume_percent": float("nan")},
        ):
            status = self.request(
                "/api/ops/music/settings", {"config": setting_patch}, role="dispatcher"
            )[0]
            self.assertEqual(status, 400)
        self.assertEqual(self.request("/api/state")[0], 200)

    def test_incomplete_request_is_closed_by_timeout(self):
        with socket.create_connection(
            ("127.0.0.1", self.port), timeout=2
        ) as connection:
            connection.settimeout(11)
            connection.sendall(
                b"POST /api/screen/heartbeat HTTP/1.0\r\nHost: localhost\r\nContent-Length: 100\r\n\r\n{"
            )
            start = time.monotonic()
            response = connection.recv(4096)
            self.assertLess(time.monotonic() - start, 10)
            self.assertFalse(response.startswith(b"HTTP/1.0 200"))
        self.assertEqual(self.request("/api/health")[0], 200)

    def test_wrong_login_attempts_are_throttled(self):
        statuses = [
            self.request("/api/auth/login", {"key": "wrong"})[0] for _ in range(11)
        ]
        self.assertEqual(statuses[:10], [401] * 10)
        self.assertEqual(statuses[-1], 429)


if __name__ == "__main__":
    unittest.main()
