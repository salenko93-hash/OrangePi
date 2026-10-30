"""Check the low-memory TV profile in a real browser; no hardware claims."""

import json
import shutil
from playwright.sync_api import sync_playwright
from browser_helpers import wait_for
from test_security import SecurityHTTPTests


def run():
    checks = []

    def passed(message):
        checks.append(message)
        print("PASS:", message, flush=True)

    SecurityHTTPTests.setUpClass()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=shutil.which("chromium")
                or shutil.which("chromium-browser"),
                headless=True,
            )
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(SecurityHTTPTests.base + "/?lite=1")
            wait_for(page, "document.documentElement.classList.contains('tv-lite')")
            wait_for(page, "typeof window.afterSchoolSlideshow === 'object'")
            self_check = page.evaluate("""() => ({
              hiddenBackdrop: getComputedStyle(document.querySelector('.slide-backdrop')).display,
              viewport: window.innerWidth,
              scroll: document.documentElement.scrollWidth,
            })""")
            assert self_check["hiddenBackdrop"] == "none", self_check
            assert self_check["scroll"] <= self_check["viewport"], self_check
            passed(
                "720p TV enables the lite profile without horizontal overflow or blurred media layers"
            )
            page.goto(SecurityHTTPTests.base + "/slideshow-preview?lite=1")
            wait_for(page, "document.documentElement.classList.contains('tv-lite')")
            assert page.locator("#previewFiles").count() == 1
            assert not errors, errors
            passed(
                "standalone holiday/weekend preview retains media controls under the lite profile"
            )
            page.goto(SecurityHTTPTests.base + "/")
            assert not page.evaluate(
                "document.documentElement.classList.contains('tv-lite')"
            )
            passed("regular remote browsers keep the standard TV profile")
            page.goto(SecurityHTTPTests.base + "/admin")
            page.fill("#adminKey", SecurityHTTPTests.config["admin_key"])
            page.click("#connect")
            wait_for(
                page, "document.getElementById('authState').textContent==='Підключено'"
            )
            with page.expect_response(
                lambda response: response.url.endswith("/api/admin/action")
            ) as response:
                page.click('[data-action="sync"]')
            assert response.value.json()["status"] == "local"
            wait_for(
                page,
                "document.getElementById('statusGrid').textContent.includes('ЛОКАЛЬНО')",
            )
            dashboard = page.evaluate("fetch('/api/ops/dashboard').then(r => r.json())")
            assert dashboard["state"]["sync"]["status"] == "local"
            assert not any(
                alert["code"] == "sync" for alert in dashboard["health_alerts"]
            )
            assert not errors, errors
            passed(
                "manual local-mode sync shows ЛОКАЛЬНО in admin and no false sync health alert in Operations Center"
            )
            browser.close()
    finally:
        SecurityHTTPTests.tearDownClass()
    print(json.dumps({"passed": checks}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()
