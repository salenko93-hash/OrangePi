"""Browser security and real nginx/TLS integration, on disposable loopback servers.

python tests/browser_security.py [--nginx /path/to/nginx]
Without nginx, browser tests still run against the local development HTTP server.
"""

import argparse
import json
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen
from playwright.sync_api import sync_playwright
from browser_helpers import wait_for
from test_security import ROOT, SecurityHTTPTests


def run(nginx=None):
    checks = []

    def passed(message):
        checks.append(message)
        print("PASS:", message, flush=True)

    SecurityHTTPTests.setUpClass()
    fixture = SecurityHTTPTests
    process = None
    nginx_log = None
    try:
        app = fixture.app
        legacy = (
            '<img src="/missing-security-probe" onerror="window.__securityXss=true">'
        )
        ops = json.loads((app / "data/default/smart_ops.json").read_text())
        ops["audio_events"] = [
            {
                "id": "legacy-xss",
                "name": "Legacy test",
                "time": "12:00",
                "url": "/media/test.wav",
                "days": [legacy],
                "active": True,
            }
        ]
        (app / "data/smart_ops.json").write_text(json.dumps(ops))
        base = fixture.base
        with tempfile.TemporaryDirectory(prefix="lyceum-tls-") as directory:
            directory = Path(directory)
            if nginx:
                # Exercise the real install helper in an unprivileged sandbox.
                tls = directory / "etc/lyceumtv/tls"
                confdir = directory / "etc/nginx/conf.d"
                confdir.mkdir(parents=True)
                script = (ROOT / "scripts/configure_https.sh").read_text()
                script = script.replace("[[ $EUID -eq 0 ]]", "true")
                script = script.replace("-o root -g root", "")
                script = script.replace(
                    "/etc/lyceumtv", str(directory / "etc/lyceumtv")
                )
                script = script.replace("/etc/nginx/conf.d", str(confdir))
                script = script.replace(
                    "nginx -t",
                    "true # nginx validated with actual isolated config below",
                )
                script = script.replace("systemctl enable nginx", "true").replace(
                    "systemctl reload-or-restart nginx", "true"
                )
                subprocess.run(
                    ["bash", "-c", script, "tls-test", "127.0.0.1"],
                    check=True,
                    capture_output=True,
                )
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = sock.getsockname()[1]
                config = (confdir / "lyceumtv.conf").read_text()
                config = config.replace(
                    "listen 443 ssl;", f"listen 127.0.0.1:{port} ssl;"
                )
                config = config.replace("http://127.0.0.1:8080", fixture.base)
                config = "fastcgi_temp_path PLACEHOLDER;\n" + config
                config = config.replace(
                    "fastcgi_temp_path PLACEHOLDER;",
                    "fastcgi_temp_path "
                    + str(directory / "fastcgi")
                    + ";\nuwsgi_temp_path "
                    + str(directory / "uwsgi")
                    + ";\nscgi_temp_path "
                    + str(directory / "scgi")
                    + ";",
                )
                config = (
                    'worker_processes 1;\npid "'
                    + str(directory / "nginx.pid")
                    + '";\nerror_log stderr warn;\nevents {worker_connections 128;}\nhttp {\naccess_log off;\nclient_body_temp_path "'
                    + str(directory / "body")
                    + '";\nproxy_temp_path "'
                    + str(directory / "proxy")
                    + '";\n'
                    + config
                    + "\n}\n"
                )
                path = directory / "nginx.conf"
                path.write_text(config)
                validation = subprocess.run(
                    [nginx, "-p", str(directory), "-c", str(path), "-t"],
                    capture_output=True,
                )
                assert validation.returncode == 0, validation.stderr.decode()
                nginx_log = (directory / "nginx.log").open("w")
                process = subprocess.Popen(
                    [nginx, "-p", str(directory), "-c", str(path), "-g", "daemon off;"],
                    stdout=nginx_log,
                    stderr=nginx_log,
                )
                base = f"https://127.0.0.1:{port}"
                context = ssl.create_default_context(cafile=str(tls / "ca.crt"))
                for _ in range(60):
                    try:
                        with urlopen(
                            base + "/api/health", context=context, timeout=2
                        ) as response:
                            assert json.load(response)["version"] == "3.7.2"
                            break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise AssertionError((directory / "nginx.log").read_text())
                try:
                    urlopen(base + "/api/health", timeout=3)
                except URLError:
                    pass
                else:
                    raise AssertionError(
                        "untrusted CA must not pass system certificate validation"
                    )
                try:
                    urlopen(
                        base + "/api/screen/local-token?id=main-hall",
                        context=context,
                        timeout=3,
                    )
                except URLError as error:
                    assert getattr(error, "code", None) == 403
                else:
                    raise AssertionError("nginx must block local bootstrap")
                passed(
                    "real nginx config, trusted TLS chain/IP verification and remote bootstrap denial"
                )
            else:
                print(
                    "SKIP: nginx/TLS integration; provide --nginx to include it",
                    flush=True,
                )
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    executable_path=shutil.which("chromium")
                    or shutil.which("chromium-browser"),
                    args=["--no-sandbox"],
                )
                # TLS identity is verified above with the generated CA. Browser
                # trust bypass is confined to this disposable test context.
                context = browser.new_context(ignore_https_errors=bool(nginx))
                errors = []
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(base + "/admin")
                page.fill("#adminKey", fixture.config["admin_key"])
                page.click("#connect")
                wait_for(
                    page,
                    "document.getElementById('authState').textContent==='Підключено'",
                )
                assert page.input_value("#adminKey") == ""
                assert page.evaluate(
                    "['adminKey','opsKey','teacherKey'].every(k=>!localStorage.getItem('lyceumtv.'+k))"
                )
                assert "lyceumtv_session" not in page.evaluate("document.cookie")
                cookie = next(
                    x for x in context.cookies() if x["name"] == "lyceumtv_session"
                )
                assert cookie["httpOnly"] and cookie["sameSite"] == "Strict"
                assert cookie["secure"] == bool(nginx)
                passed(
                    "admin login uses HttpOnly/SameSite session; Secure over TLS; no stored role keys"
                )
                opspage = context.new_page()
                opspage.on("pageerror", lambda error: errors.append(str(error)))
                opspage.goto(base + "/ops")
                opspage.wait_for_selector("#app:not(.hidden)")
                assert opspage.locator("#audioList img").count() == 0
                assert legacy in opspage.locator("#audioList").text_content()
                assert not opspage.evaluate("!!window.__securityXss")
                passed("persisted legacy XSS renders as text; no handler executes")
                result = opspage.evaluate("""async () => {
                  const r=await fetch('/api/ops/item',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'audio',item:{name:'probe',time:'12:00',url:'/media/probe.wav',days:['<img src=x onerror=alert(1)>']}})});
                  return r.status;
                }""")
                assert result == 400
                passed(
                    "malicious new audio days rejected by the server through browser session"
                )
                awaitable = opspage.evaluate("""async () => {
                  const r=await fetch('/api/ops/media/upload-file?name=probe.png',{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aRZkAAAAASUVORK5CYII='),c=>c.charCodeAt(0))});
                  return {status:r.status,...await r.json()};
                }""")
                assert awaitable["status"] == 200
                passed(
                    "authenticated upload works with session cookie and content signature"
                )
                page.get_by_role("button", name="ВИЙТИ", exact=True).click()
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(300)
                assert (
                    page.evaluate("fetch('/api/admin/dashboard').then(r=>r.status)")
                    == 401
                )
                passed("logout revokes the server session")
                for role, path, allowed in (
                    ("dispatcher", "/ops", "/api/ops/dashboard"),
                    ("teacher", "/teacher", "/api/teacher/directory"),
                ):
                    role_context = browser.new_context(ignore_https_errors=bool(nginx))
                    role_page = role_context.new_page()
                    role_page.on("pageerror", lambda error: errors.append(str(error)))
                    role_page.goto(base + path)
                    role_page.fill("#roleKey", fixture.config[role + "_key"])
                    role_page.click("#connect")
                    role_page.wait_for_selector("#app:not(.hidden)")
                    assert role_page.input_value("#roleKey") == ""
                    assert (
                        role_page.evaluate(
                            "path => fetch(path).then(r => r.status)", allowed
                        )
                        == 200
                    )
                    assert (
                        role_page.evaluate(
                            "fetch('/api/admin/dashboard').then(r=>r.status)"
                        )
                        == 401
                    )
                    role_context.close()
                passed(
                    "Dispatcher and Teacher browser sessions work and cannot access admin API"
                )
                probe = SecurityHTTPTests(
                    methodName="test_device_tokens_are_scoped_rotated_and_required"
                )
                pairing = probe.request(
                    "/api/admin/screen",
                    {"op": "pair", "id": "remote-lobby"},
                    role="admin",
                )[1]
                remote = context.new_page()
                remote.goto(base + "/?screen=remote-lobby#device=" + pairing["token"])
                wait_for(
                    remote, "!!localStorage.getItem('lyceumtv.device.remote-lobby')"
                )
                assert "#" not in remote.url
                result = remote.evaluate("""async () => {
                  const r = await fetch('/api/screen/heartbeat', {method:'POST',headers:{'Content-Type':'application/json','X-Device-Token':localStorage.getItem('lyceumtv.device.remote-lobby')},body:JSON.stringify({id:'remote-lobby'})});
                  return r.status;
                }""")
                assert result == 200
                passed(
                    "paired remote TV stores only its device token and removes it from the address bar"
                )
                # The main kiosk still enrolls itself over its loopback origin.
                kiosk = browser.new_page()
                kiosk.goto(fixture.base)
                wait_for(kiosk, "!!localStorage.getItem('lyceumtv.device.main-hall')")
                kiosk.wait_for_timeout(200)
                response = kiosk.evaluate(
                    """async () => {const r=await fetch('/api/screen/heartbeat',{method:'POST',headers:{'Content-Type':'application/json','X-Device-Token':localStorage.getItem('lyceumtv.device.main-hall')},body:JSON.stringify({id:'main-hall'})});return r.status;}"""
                )
                assert response == 200
                passed(
                    "main kiosk enrolls automatically and sends authenticated heartbeats"
                )
                assert not errors, errors
                browser.close()
    finally:
        if process:
            process.terminate()
            try:
                process.wait(5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if nginx_log:
            nginx_log.close()
        fixture.tearDownClass()
    return checks


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nginx", default=shutil.which("nginx"))
    print(
        json.dumps(
            {"passed": run(parser.parse_args().nginx)}, ensure_ascii=False, indent=2
        )
    )
