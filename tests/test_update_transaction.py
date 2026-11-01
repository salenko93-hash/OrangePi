from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.request
import update_transaction as update

ROOT = Path(__file__).resolve().parents[1]
APP = """import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from version import VERSION
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  raw=json.dumps({'ok':True,'service':'LyceumTV','version':VERSION}).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
 def log_message(self,*args):pass
if __name__=='__main__':
 root=Path(__file__).resolve().parents[1];cfg=json.loads((root/'data/config.json').read_text());HTTPServer(('127.0.0.1',cfg['port']),Handler).serve_forever()
"""


def fixture(root, version):
    files = {
        "server/app.py": APP,
        "server/version.py": f'VERSION = "{version}"\n',
        "server/update_transaction.py": (
            ROOT / "server/update_transaction.py"
        ).read_text(),
        "launcher.py": (ROOT / "launcher.py").read_text(),
        "public/index.html": "<html></html>",
        "public/js/app.js": "void 0;",
        "data/config.example.json": json.dumps({"version": version}),
    }
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    (root / "PACKAGE_SHA256.json").write_text(
        json.dumps(
            {
                name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                for name in files
            }
        )
    )


@contextmanager
def supervisor(root, log):
    args = [sys.executable, "-B", str(ROOT / "launcher.py"), "--root", str(root)]
    options = {}
    job = None
    process = None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.TerminateJobObject.restype = wintypes.BOOL
        kernel.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        kernel.QueryInformationJobObject.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL

        class Accounting(ctypes.Structure):
            _fields_ = [
                ("times", ctypes.c_longlong * 4),
                ("faults", wintypes.DWORD),
                ("total", wintypes.DWORD),
                ("active", wintypes.DWORD),
                ("terminated", wintypes.DWORD),
            ]

        job = kernel.CreateJobObjectW(None, None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())

    try:
        if job is not None:
            os.set_handle_inheritable(job, True)
            startup = subprocess.STARTUPINFO()
            startup.lpAttributeList = {"handle_list": [job]}
            options["startupinfo"] = startup
            # Keep worker console signals away from the test runner.
            options["creationflags"] = subprocess.CREATE_NO_WINDOW
            # Join before executing launcher, so even its first child belongs to
            # this test's job. Descendants cannot escape if launcher exits early.
            probe = """import ctypes, runpy, sys
from ctypes import wintypes
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
kernel.AssignProcessToJobObject.restype = wintypes.BOOL
kernel.GetCurrentProcess.restype = wintypes.HANDLE
kernel.CloseHandle.argtypes = [wintypes.HANDLE]
handle = int(sys.argv[1])
if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
    raise ctypes.WinError(ctypes.get_last_error())
kernel.CloseHandle(handle)
sys.argv = sys.argv[2:]
runpy.run_path(sys.argv[0], run_name='__main__')
"""
            args = [sys.executable, "-B", "-c", probe, str(job)] + args[2:]
        process = subprocess.Popen(args, stdout=log, stderr=log, **options)
        yield process
    finally:
        try:
            if job is not None:
                if not kernel.TerminateJobObject(job, 1):
                    raise ctypes.WinError(ctypes.get_last_error())
                # Termination is asynchronous; wait before removing the fixture.
                deadline = time.monotonic() + 10
                while True:
                    accounting = Accounting()
                    if not kernel.QueryInformationJobObject(
                        job,
                        1,
                        ctypes.byref(accounting),
                        ctypes.sizeof(accounting),
                        None,
                    ):
                        raise ctypes.WinError(ctypes.get_last_error())
                    if not accounting.active:
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError("supervisor process tree did not stop")
                    time.sleep(0.01)
            elif process is not None:
                process.terminate()
            if process is not None:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        finally:
            if job is not None:
                kernel.CloseHandle(job)


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "installed"
        self.source = Path(self.tmp.name) / "source"
        fixture(self.root, "3.5.0")
        fixture(self.source, "3.5.1")
        (self.root / "data/config.json").write_text(
            '{"alerts_token":"keep-token","port":8080}'
        )
        (self.root / "public/media").mkdir()
        (self.root / "public/media/keep.mp4").write_bytes(b"keep-video")

    def prepare(self):
        result = update.prepare(self.root, self.source)
        state = update.read_state(self.root)
        state["not_before"] = 0
        update.atomic_json(self.root / "data/ota_pending", state)
        return result

    @unittest.skipUnless(os.name == "nt", "Windows process-tree cleanup")
    def test_supervisor_tree_cleanup_on_exit_error_and_timeout(self):
        for outcome in ("success", "error", "timeout", "launcher_exit"):
            with self.subTest(outcome=outcome):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    fixture(root, "3.5.0")
                    with socket.socket() as sock:
                        sock.bind(("127.0.0.1", 0))
                        port = sock.getsockname()[1]
                    (root / "data/config.json").write_text(json.dumps({"port": port}))
                    with tempfile.TemporaryFile() as log:
                        try:
                            with supervisor(root, log) as process:
                                deadline = time.monotonic() + 10
                                while not (root / "data/app.pid").exists():
                                    if process.poll() is not None:
                                        self.fail(
                                            "supervisor exited before spawning app"
                                        )
                                    if time.monotonic() >= deadline:
                                        self.fail("supervisor did not spawn app")
                                    time.sleep(0.01)
                                if outcome == "error":
                                    raise RuntimeError("test failure")
                                if outcome == "timeout":
                                    raise subprocess.TimeoutExpired("test", 0)
                                if outcome == "launcher_exit":
                                    process.terminate()
                                    process.wait(timeout=10)
                        except (RuntimeError, subprocess.TimeoutExpired):
                            if outcome not in {"error", "timeout"}:
                                raise
                # The log and fixture must be removable after every exit path.
                self.assertFalse(root.exists())

    def test_manual_snapshot_and_queued_rollback_use_same_worker(self):
        original = (self.root / "server/version.py").read_bytes()
        update.snapshot(self.root)
        (self.root / "server/version.py").write_text('VERSION="changed"')
        update.queue_rollback(self.root)
        update.execute(self.root)
        self.assertEqual((self.root / "server/version.py").read_bytes(), original)
        self.assertIsNone(update.read_state(self.root))

    def test_preparation_does_not_modify_live_code(self):
        self.prepare()
        self.assertEqual(update.version_at(self.root), "3.5.0")
        self.assertTrue((self.root / "data/ota_pending").exists())
        with self.assertRaises(ValueError):
            self.prepare()

    def test_partial_copy_failure_rolls_back_entire_code(self):
        self.prepare()
        original = update.copy_file
        calls = 0

        def fail_once(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("disk failure")
            return original(source, destination)

        with patch.object(update, "copy_file", side_effect=fail_once):
            update.execute(self.root, check=lambda _: True, poll=0)
        self.assertEqual(update.version_at(self.root), "3.5.0")
        self.assertIsNone(update.read_state(self.root))
        self.assertEqual(
            json.loads((self.root / "data/last_update.json").read_text())["phase"],
            "rolled_back",
        )
        self.assertEqual(
            (self.root / "public/media/keep.mp4").read_bytes(), b"keep-video"
        )
        self.assertEqual(
            json.loads((self.root / "data/config.json").read_text())["alerts_token"],
            "keep-token",
        )

    def test_three_correct_health_results_are_required(self):
        self.prepare()
        checks = []
        update.execute(
            self.root, check=lambda expected: checks.append(expected) or True, poll=0
        )
        self.assertEqual(checks, ["3.5.1"] * 3)
        self.assertEqual(update.version_at(self.root), "3.5.1")
        self.assertIsNone(update.read_state(self.root))

    def test_watchdog_never_accepts_a_pending_update_by_http_alone(self):
        import shlex

        bash = shutil.which("bash")
        if os.name == "nt":
            # System32/bash.exe uses the default WSL distro, which may be
            # docker-desktop. Git Bash operates directly on Windows fixtures.
            git = shutil.which("git")
            candidate = Path(git).parents[1] / "bin/bash.exe" if git else None
            self.assertTrue(candidate and candidate.is_file(), "Git Bash is required")
            bash = str(candidate)
        self.assertIsNotNone(bash, "Bash is required for the watchdog test")
        marker = self.root / "data/ota_pending"
        marker.write_text('{"target":"3.5.1"}')
        state = self.root / "watchdog-state"
        state.mkdir()
        calls = self.root / "privileged-calls"
        for healthy in (True, False):
            source = (ROOT / "scripts/watchdog.sh").read_text()
            source = source.replace(
                "/run/lyceumtv-watchdog", shlex.quote(state.as_posix())
            )
            source = source.replace("/opt/lyceumtv", shlex.quote(self.root.as_posix()))
            # Replace fixed binaries only in this temporary test copy.
            source = (
                source.replace("/usr/bin/curl", "test_curl")
                .replace("/usr/bin/systemctl", "test_systemctl")
                .replace("/usr/bin/logger", "test_logger")
            )
            prelude = (
                "test_curl(){ return " + ("0" if healthy else "1") + "; }; "
                "test_systemctl(){ if [[ $1 == is-active ]]; then return 0; fi; echo called >> "
                + shlex.quote(calls.as_posix())
                + "; }; "
                "test_logger(){ :; };\n"
            )
            result = subprocess.run(
                [bash, "-c", prelude + source],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(marker.exists())
            self.assertFalse(calls.exists())
        # After a bounded grace period an interrupted update is recovered by
        # restarting the unprivileged supervisor, never by running app Python as root.
        (state / "ota-since").write_text(str(int(time.time()) - 181))
        result = subprocess.run(
            [bash, "-c", prelude + source], capture_output=True, text=True, timeout=10
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(calls.exists())
        self.assertTrue(marker.exists())

    def test_old_health_version_is_rejected(self):
        class Response(io.BytesIO):
            status = 200

        response = Response(b'{"ok":true,"service":"LyceumTV","version":"3.5.0"}')
        with patch.object(update.urllib.request, "urlopen", return_value=response):
            self.assertFalse(update.health_ok(self.root, "3.5.1"))

    def test_health_failure_rolls_back(self):
        self.prepare()
        update.execute(self.root, check=lambda _: False, timeout=0.01, poll=0.001)
        self.assertEqual(update.version_at(self.root), "3.5.0")
        self.assertIsNone(update.read_state(self.root))

    def test_failed_rollback_can_retry_without_changing_local_data(self):
        self.prepare()
        config = (self.root / "data/config.json").read_bytes()
        media = (self.root / "public/media/keep.mp4").read_bytes()
        with patch.object(
            update, "restore_files", side_effect=OSError("restore failed")
        ):
            with self.assertRaisesRegex(OSError, "restore failed"):
                update.execute(self.root, check=lambda _: False, timeout=0, poll=0)
        state = update.read_state(self.root)
        self.assertEqual(state["phase"], "recovery_required")
        self.assertEqual(state["error"], "restore failed")
        self.assertFalse((self.root / "data/last_update.json").exists())
        self.assertTrue(
            (update.job_path(self.root, state["job"]) / "old-files.json").is_file()
        )
        with self.assertRaises(ValueError):
            update.prepare(self.root, self.source)
        update.execute(self.root, recover=True)
        self.assertIsNone(update.read_state(self.root))
        self.assertEqual(update.version_at(self.root), "3.5.0")
        result = json.loads((self.root / "data/last_update.json").read_text())
        self.assertEqual(result["phase"], "rolled_back")
        self.assertEqual(result["job"], state["job"])
        self.assertEqual((self.root / "data/config.json").read_bytes(), config)
        self.assertEqual((self.root / "public/media/keep.mp4").read_bytes(), media)
        self.assertEqual(list(self.root.rglob("*.update-tmp")), [])

    def test_windows_stop_waits_for_supervisor_without_signalling_app(self):
        marker = self.root / "data/app.pid"
        marker.write_text("12345")
        with (
            patch.object(update, "os") as windows_os,
            patch.object(update.time, "sleep", side_effect=lambda _: marker.unlink()),
        ):
            windows_os.name = "nt"
            update.wait_app_stopped(self.root)
        windows_os.kill.assert_not_called()

    def test_interrupted_job_recovers_from_snapshot(self):
        self.prepare()
        state = update.read_state(self.root)
        job = update.job_path(self.root, state["job"])
        update.copy_file(job / "new/server/version.py", self.root / "server/version.py")
        update.set_phase(self.root, state, "applying")
        update.execute(self.root, recover=True)
        self.assertEqual(update.version_at(self.root), "3.5.0")

    def test_tampered_release_is_rejected_before_live_changes(self):
        (self.source / "server/app.py").write_text("bad")
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(update.version_at(self.root), "3.5.0")
        self.assertIsNone(update.read_state(self.root))

    def test_supervisor_rolls_back_when_new_process_reports_wrong_version(self):
        app = self.source / "server/app.py"
        app.write_text(
            app.read_text().replace("'version':VERSION", "'version':'0.0.0'")
        )
        manifest = json.loads((self.source / "PACKAGE_SHA256.json").read_text())
        manifest["server/app.py"] = hashlib.sha256(app.read_bytes()).hexdigest()
        (self.source / "PACKAGE_SHA256.json").write_text(json.dumps(manifest))
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        (self.root / "data/config.json").write_text(
            json.dumps({"port": port, "alerts_token": "keep"})
        )
        self.prepare()
        state = update.read_state(self.root)
        state["health_timeout_seconds"] = 3
        update.atomic_json(self.root / "data/ota_pending", state)
        with tempfile.TemporaryFile() as log:
            with supervisor(self.root, log):
                deadline = time.monotonic() + 15
                result = self.root / "data/last_update.json"
                while time.monotonic() < deadline:
                    if (
                        result.exists()
                        and json.loads(result.read_text())["phase"] == "rolled_back"
                    ):
                        break
                    time.sleep(0.1)
                log.seek(0)
                self.assertTrue(
                    result.exists(),
                    (update.read_state(self.root), log.read().decode(errors="replace")),
                )
                self.assertEqual(json.loads(result.read_text())["phase"], "rolled_back")
                self.assertEqual(update.version_at(self.root), "3.5.0")
                self.assertEqual(
                    json.loads((self.root / "data/config.json").read_text())[
                        "alerts_token"
                    ],
                    "keep",
                )

    def test_supervisor_completes_real_process_update(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        (self.root / "data/config.json").write_text(
            json.dumps({"port": port, "alerts_token": "keep"})
        )
        self.prepare()
        with tempfile.TemporaryFile() as log:
            with supervisor(self.root, log) as process:
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    path = self.root / "data/last_update.json"
                    if (
                        path.exists()
                        and json.loads(path.read_text())["phase"] == "healthy"
                    ):
                        break
                    if process.poll() is not None:
                        break
                    time.sleep(0.1)
                else:
                    self.fail("supervisor update timed out")
                self.assertTrue((self.root / "data/last_update.json").exists())
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/health"
                ) as response:
                    self.assertEqual(json.load(response)["version"], "3.5.1")
