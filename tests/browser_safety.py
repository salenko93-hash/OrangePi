"""Optional browser regressions: python tests/browser_safety.py (Playwright).

All data, generated PNG/WAV and the server live in a disposable temporary copy.
No physical Pi or production server is contacted.
"""

import binascii
import json
import math
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import wave
import zlib
from playwright.sync_api import sync_playwright
from browser_helpers import wait_for

ROOT = Path(__file__).resolve().parents[1]


def fixtures(directory):
    def chunk(name, data):
        return (
            struct.pack("!I", len(data))
            + name
            + data
            + struct.pack("!I", binascii.crc32(name + data) & 0xFFFFFFFF)
        )

    png = directory / "frame.png"
    png.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!2I5B", 32, 32, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + b"\x20\x60\xa0" * 32) * 32))
        + chunk(b"IEND", b"")
    )
    audio = directory / "track.wav"
    with wave.open(str(audio), "wb") as output:
        output.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
        output.writeframes(
            b"".join(
                struct.pack("<h", int(1000 * math.sin(n * 2 * math.pi * 220 / 22050)))
                for n in range(6600)
            )
        )
    return png, audio


def run():
    checks = []

    def passed(message):
        checks.append(message)
        print("PASS:", message, flush=True)

    with tempfile.TemporaryDirectory(prefix="lyceum-browser-") as tmp:
        directory = Path(tmp)
        app = directory / "app"
        shutil.copytree(
            ROOT,
            app,
            ignore=shutil.ignore_patterns(
                ".venv", "dist", "__pycache__", ".git", ".ruff_cache"
            ),
        )
        png, audio = fixtures(directory)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        cfg = json.loads((app / "data/config.example.json").read_text())
        cfg.update(
            port=port,
            weather_enabled=False,
            manifest_url="",
            alerts_token="",
            telegram_enabled=False,
            admin_key="browser-admin-test-" + "a" * 24,
            dispatcher_key="browser-dispatch-test-" + "b" * 24,
            teacher_key="browser-teacher-test-" + "c" * 24,
        )
        (app / "data/config.json").write_text(json.dumps(cfg))
        python = sys.executable
        subprocess.run(
            [
                python,
                "-B",
                "-c",
                "import sys;sys.path.insert(0,'server');from config_store import ConfigStore;ConfigStore().save({'host':'127.0.0.1','port':int(sys.argv[1]),'weather_enabled':False,'manifest_url':'','alerts_token':'','telegram_enabled':False})",
                str(port),
            ],
            cwd=app,
            check=True,
        )
        with (directory / "server.log").open("w") as log:
            server = subprocess.Popen(
                [python, "-B", "server/app.py"], cwd=app, stdout=log, stderr=log
            )
            base = f"http://127.0.0.1:{port}"

            def request(path, body=None, key=cfg["dispatcher_key"], expected=200):
                headers = {"X-Role-Key": key}
                if body is not None:
                    headers["Content-Type"] = "application/json"
                req = urllib.request.Request(
                    base + path,
                    data=json.dumps(body).encode() if body is not None else None,
                    headers=headers,
                )
                try:
                    response = urllib.request.urlopen(req, timeout=5)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    raw = response.read()
                    assert response.status == expected, (path, response.status, raw)
                    return json.loads(raw)

            try:
                for _ in range(60):
                    try:
                        state = request("/api/state")
                        break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("server did not start")
                payload = {
                    "items": [{"url": "/media/frame.png", "kind": "image"}],
                    "music": {
                        "url": "/media/retry.wav",
                        "volume": 0.2,
                        "screen_id": "main-hall",
                    },
                }
                with sync_playwright() as p:
                    executable = shutil.which("chromium") or shutil.which(
                        "chromium-browser"
                    )
                    browser = p.chromium.launch(
                        executable_path=executable,
                        headless=True,
                        args=["--autoplay-policy=no-user-gesture-required"],
                    )
                    context = browser.new_context(timezone_id="Europe/Kyiv")
                    context.add_init_script(
                        "window.__audio=[];const Native=Audio;window.Audio=function(...args){const audio=new Native(...args);window.__audio.push(audio);return audio}"
                    )
                    errors = []
                    context.on(
                        "page",
                        lambda page: page.on(
                            "pageerror", lambda error: errors.append(str(error))
                        ),
                    )
                    preview = context.new_page()
                    attempts = []
                    preview.route(
                        "**/api/slideshow", lambda route: route.fulfill(json=payload)
                    )
                    preview.route(
                        "**/media/frame.png", lambda route: route.fulfill(path=str(png))
                    )

                    def music(route):
                        attempts.append(True)
                        if len(attempts) == 1:
                            route.abort()
                        else:
                            route.fulfill(path=str(audio))

                    preview.route("**/media/retry.wav", music)
                    preview.goto(
                        base + "/slideshow-preview", wait_until="domcontentloaded"
                    )
                    preview.locator("#previewSound").click()
                    wait_for(
                        preview,
                        "window.__audio.some(a=>a.loop&&!a.paused&&a.currentTime>0)",
                        timeout=10000,
                    )
                    assert len(attempts) >= 2
                    preview.close()
                    passed(
                        "music recovers after the first real media request fails, without changing URL"
                    )
                    page = context.new_page()
                    offline = [False]
                    page.clock.install()
                    page.clock.set_system_time("2026-10-19T13:59:55Z")
                    state.update(
                        mode="NORMAL",
                        after_school_info=True,
                        now="2026-10-19T16:59:55+03:00",
                        after_school_until="2026-10-19T17:00:00+03:00",
                    )
                    state["schedule"]["phase"] = "AFTER_SCHOOL"
                    stalled = []
                    page.route(
                        "**/api/state",
                        lambda route: stalled.append(route)
                        if offline[0]
                        else route.fulfill(json=state),
                    )
                    page.route(
                        "**/api/slideshow", lambda route: route.fulfill(json=payload)
                    )
                    page.route(
                        "**/media/frame.png", lambda route: route.fulfill(path=str(png))
                    )
                    page.route(
                        "**/media/retry.wav",
                        lambda route: route.fulfill(path=str(audio)),
                    )
                    page.route(
                        "**/api/music/state",
                        lambda route: route.fulfill(json={"allowed": False}),
                    )
                    page.route(
                        "**/api/audio/current",
                        lambda route: route.fulfill(json={"event": None}),
                    )
                    page.goto(base, wait_until="domcontentloaded")
                    wait_for(page, "window.afterSchoolSlideshow.getStatus().active")
                    offline[0] = True
                    page.clock.fast_forward(5100)
                    wait_for(page, "!window.afterSchoolSlideshow.getStatus().active")
                    page.clock.fast_forward(3000)
                    wait_for(
                        page,
                        "!document.getElementById('offlineBadge').classList.contains('hidden')",
                    )
                    assert page.evaluate(
                        "!window.afterSchoolSlideshow.getStatus().active&&window.__audio.every(a=>a.paused)"
                    )
                    assert page.locator("#timerValue").inner_text() == "--:--"
                    page.clock.fast_forward(120000)
                    offline[0] = False
                    page.clock.fast_forward(6500)
                    wait_for(
                        page,
                        "document.getElementById('offlineBadge').classList.contains('hidden')",
                    )
                    assert page.evaluate(
                        "new Date().getHours()>=17&&!window.afterSchoolSlideshow.getStatus().active"
                    )
                    passed(
                        "stalled API times out; independent 17:00 deadline stops media before the response returns"
                    )
                    for route in stalled:
                        try:
                            route.abort()
                        except Exception:
                            pass
                    page.close()
                    reload_page = context.new_page()
                    navigations = []
                    reload_page.on(
                        "framenavigated",
                        lambda frame: navigations.append(frame.url)
                        if frame == reload_page.main_frame
                        else None,
                    )
                    version_state = json.loads(json.dumps(state))
                    version_state["after_school_info"] = False
                    reload_page.route(
                        "**/api/state", lambda route: route.fulfill(json=version_state)
                    )
                    reload_page.goto(base, wait_until="domcontentloaded")
                    reload_page.wait_for_timeout(1200)
                    version_state["app"]["version"] = "3.5.2"
                    for _ in range(40):
                        reload_page.wait_for_timeout(100)
                        if len(navigations) >= 2:
                            break
                    assert len(navigations) >= 2, (
                        "TV must reload after server version changes"
                    )
                    count = len(navigations)
                    reload_page.wait_for_timeout(1400)
                    assert len(navigations) == count
                    reload_page.close()
                    passed("TV reloads once after an update changes the server version")
                    # Exercise reference-aware deletion and the real cleanup UI.
                    media = app / "public/media"
                    media.mkdir(exist_ok=True)
                    file = media / "keep.wav"
                    shutil.copy2(audio, file)
                    request(
                        "/api/ops/item",
                        {
                            "kind": "media",
                            "item": {
                                "id": "keep",
                                "title": "Keep",
                                "url": "/media/keep.wav",
                                "media_kind": "video",
                            },
                        },
                    )
                    request(
                        "/api/ops/slideshow/settings",
                        {"slideshow_music_url": "/media/keep.wav"},
                    )
                    request(
                        "/api/ops/item", {"kind": "media", "op": "delete", "id": "keep"}
                    )
                    assert file.exists(), "a soundtrack reference must protect the file"
                    request("/api/ops/slideshow/settings", {"slideshow_music_url": ""})
                    os.utime(file, (time.time() - 7200,) * 2)
                    assert (
                        request("/api/ops/media/cleanup", {"dry_run": True})["files"]
                        == 1
                    )
                    assert file.exists()
                    request(
                        "/api/ops/media/cleanup",
                        {"dry_run": False},
                        key=cfg["teacher_key"],
                        expected=401,
                    )
                    ops = context.new_page()
                    ops.on("dialog", lambda dialog: dialog.accept())
                    ops.goto(base + "/ops")
                    ops.locator("#roleKey").fill(cfg["dispatcher_key"])
                    ops.locator("#connect").click()
                    ops.locator('[data-tab="media"]').click()
                    ops.locator("#cleanupMedia").click()
                    wait_for(
                        ops,
                        "document.getElementById('slideshowUploadStatus').textContent.includes('Видалено 1 файлів')",
                    )
                    assert not file.exists()
                    passed(
                        "shared media survive deletion; cleanup preview/UI removes only unused old files; Teacher is denied"
                    )
                    assert not errors, errors
                    browser.close()
            finally:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()
    return checks


if __name__ == "__main__":
    print(json.dumps({"passed": run()}, ensure_ascii=False, indent=2))
