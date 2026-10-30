from __future__ import annotations
import json, ast, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SERVER = ROOT / "server"
PUBLIC = ROOT / "public"
DATA = ROOT / "data"
TESTS = ROOT / "tests"


def fail(msg):
    print("FAIL:", msg)
    raise SystemExit(1)


def ok(msg):
    print("PASS:", msg)


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as e:
        fail(f"{path.relative_to(ROOT)}: {e}")


# Core runtime
required = [
    "server/app.py",
    "server/json_cache.py",
    "server/runtime_data.py",
    "server/update_transaction.py",
    "server/install_config.py",
    "launcher.py",
    "requirements.txt",
    "tools/build_demo.py",
    "server/version.py",
    "server/schedule_engine.py",
    "server/academic_cycle.py",
    "server/duty_rotation.py",
    "public/index.html",
    "public/js/app.js",
    "public/css/tv.css",
    "scripts/install.sh",
    "scripts/launch-kiosk.sh",
    "scripts/watchdog.sh",
    "scripts/kiosk_browser.py",
    "scripts/display_mode.py",
    "scripts/deployment_preflight.py",
    "scripts/tv-session.sh",
    "public/js/tv-profile.js",
    "INSTALL_TO_ORANGEPI.ps1",
]
missing = [x for x in required if not (ROOT / x).is_file()]
if missing:
    fail("missing: " + ", ".join(missing))

sys.path.insert(0, str(SERVER))
from version import VERSION
from package_validation import verify_manifest

if load(DATA / "config.example.json").get("version") != VERSION:
    fail("runtime/config version mismatch")
ok("runtime version " + VERSION)

# Schedule data: semantic source validation, no hard-coded workbook revision numbers.
names = (
    "schedule_numerator.json",
    "schedule_denominator.json",
    "shelter_numerator.json",
    "shelter_denominator.json",
)
expected_classes = ["10-А", "10-Б", "10-В", "10-Г", "11-А", "11-Б", "11-В", "11-Г"]
expected_days = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"]

for name in names:
    cur = load(DATA / "default" / name)
    source = cur.get("source")
    if not isinstance(source, str) or not source.lower().endswith(".xlsx"):
        fail(f"{name}: invalid source metadata: {source!r}")
    bells = cur.get("bellSchedule")
    if not isinstance(bells, list) or len(bells) != 8:
        fail(f"{name}: expected 8 bell periods in the initial schedule bundle")
    days = cur.get("days")
    if not isinstance(days, dict) or list(days.keys()) != expected_days:
        fail(f"{name}: unexpected day structure")
    for day in expected_days:
        if list(days[day].keys()) != expected_classes:
            fail(f"{name}: class order mismatch on {day}")
    ok(f"{name}: {source}")

# Manifest integrity
manifest = load(DATA / "default" / "content_manifest.json")
try:
    verify_manifest(manifest, DATA / "default")
except ValueError as exc:
    fail(str(exc))
ok("initial data manifest SHA-256")

# Offline demo is generated from the same canonical initial bundle.
for asset, variable, expected in (
    (
        "demo_data.js",
        "LYCEUM_DEMO_DATA",
        {name[:-5]: load(DATA / "default" / name) for name in names},
    ),
    (
        "demo_calendar.js",
        "LYCEUM_DEMO_CALENDAR",
        {
            key: load(DATA / "default" / "calendar.json").get(key, [])
            for key in ("ranges", "openEndedRanges", "daysOff")
        },
    ),
):
    source = (PUBLIC / "js" / asset).read_text(encoding="utf-8")
    try:
        generated = json.loads(
            source.split("window." + variable + "=", 1)[1].strip().rstrip(";")
        )
    except (ValueError, IndexError) as exc:
        fail(f"invalid generated demo data: {asset}: {exc}")
    if generated != expected:
        fail("offline demo out of date; run python tools/build_demo.py")
ok("offline demo matches initial data")


# Python syntax
for p in sorted(SERVER.glob("*.py")):
    ast.parse(p.read_text(encoding="utf-8-sig"), filename=str(p))
ok("server Python syntax")

# Run every shipped test; no references to missing legacy tests.
tests = sorted(TESTS.glob("test_*.py")) if TESTS.is_dir() else []
if not tests:
    fail("no tests/test_*.py shipped")
import unittest

suite = unittest.defaultTestLoader.discover(str(TESTS))
count = suite.countTestCases()
if not count:
    fail("zero test cases discovered")
result = unittest.TextTestRunner(verbosity=2).run(suite)
if not result.wasSuccessful():
    fail("unit tests failed")
ok(f"{count} test cases executed")

# Optional JavaScript syntax if Node is available.
import shutil

node = shutil.which("node")
if node:
    scripts = sorted(PUBLIC.rglob("*.js"))
    for script in scripts:
        result = subprocess.run(
            [node, "--check", str(script)], capture_output=True, text=True
        )
        if result.returncode:
            fail(str(script.relative_to(ROOT)) + ": " + result.stderr)
    ok(f"all {len(scripts)} JavaScript files")
    runtime = subprocess.run(
        [node, str(TESTS / "test_slideshow_runtime.js")], capture_output=True, text=True
    )
    print(runtime.stdout, end="")
    if runtime.returncode:
        fail("slideshow runtime regression tests failed: " + runtime.stderr)
    count = sum(line.startswith("PASS:") for line in runtime.stdout.splitlines())
    if not count:
        fail("zero JavaScript runtime checks")
    ok(f"{count} JavaScript runtime regression checks")
else:
    print("SKIP: Node unavailable; JavaScript syntax not verified")

# Slideshow runtime contract
front = (PUBLIC / "js/app.js").read_text(encoding="utf-8-sig")
smart = (SERVER / "smart_ops.py").read_text(encoding="utf-8-sig")
if "after_school" not in front.lower() or "after_school_slides" not in smart:
    fail("after-school slideshow contract missing")
ok("after-school slideshow runtime present")

# Installer sanity
installer = (ROOT / "INSTALL_TO_ORANGEPI.ps1").read_text(encoding="utf-8-sig")
installsh = (ROOT / "scripts/install.sh").read_text(encoding="utf-8-sig")
for token in ("server", "public", "data", "scripts"):
    if token not in installer:
        fail(f"installer missing {token}")
for token in ("lyceumtv.service", "lyceumtv-kiosk.service", "lyceumtv-watchdog.timer"):
    if token not in installsh:
        fail(f"install.sh missing {token}")
ok("Orange Pi PC deployment scripts")

# Slideshow UI policy.
tv_html = (PUBLIC / "index.html").read_text(encoding="utf-8-sig")
slide_js = (PUBLIC / "js/slideshow.js").read_text(encoding="utf-8-sig")
admin_html = (PUBLIC / "admin.html").read_text(encoding="utf-8-sig")
if 'id="slideshowTitle"' not in tv_html:
    fail("slideshow title element missing")
for forbidden in (
    "afterSchoolAnnouncement",
    "afterSchoolPhotoTitle",
    "afterSchoolPhotoCount",
):
    if forbidden in tv_html or forbidden in slide_js:
        fail(f"slideshow UI still exposes {forbidden}")
if 'name="slideshow_title"' not in admin_html:
    fail("admin slideshow_title setting missing")
ok("slideshow UI: title + photo/video media; no announcement, filename or counter")

print()
print("VERIFY SUCCESSFUL")
