"""Poll through DevTools without requiring unsafe-eval in the page CSP."""

import time


def wait_for(page, expression, *, timeout=30000):
    deadline = time.monotonic() + timeout / 1000
    while time.monotonic() < deadline:
        if page.evaluate(expression):
            return
        page.wait_for_timeout(50)
    raise AssertionError("Browser condition timed out: " + expression)
