param(
    [string]$BoardHost = "192.168.0.160",
    [string]$BoardUser = "admin"
)
$ErrorActionPreference = "Stop"
$parsedIP = $null
if (-not [System.Net.IPAddress]::TryParse($BoardHost, [ref]$parsedIP) -or $parsedIP.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) { throw "BoardHost must be an IPv4 address." }
if ($BoardUser -notmatch '^[a-z_][a-z0-9_-]{0,31}$') { throw "Invalid Linux username." }
foreach ($cmd in @("ssh", "scp")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "Windows OpenSSH Client is required." }
}
Write-Host "Collecting first-boot display diagnostics; leave the TV unchanged."
$remoteCode = @'
set -eu
trap 'rm -f -- "$0"' EXIT
sudo /usr/bin/python3 -I - <<'PYDIAG'
"""Read boot/display state without changing outputs, services or configuration."""

import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
from urllib.request import urlopen

ENV_KEYS = (
    "XCURSOR_THEME",
    "XCURSOR_PATH",
    "WLR_NO_HARDWARE_CURSORS",
    "XDG_RUNTIME_DIR",
    "WAYLAND_DISPLAY",
    "GDK_BACKEND",
    "GSK_RENDERER",
    "WEBKIT_DISABLE_DMABUF_RENDERER",
    "LIBSEAT_BACKEND",
)


def read(path):
    try:
        return Path(path).read_text(errors="replace").strip()
    except OSError as error:
        return "unavailable: " + str(error)


def filtered_environment(raw):
    entries = (item.partition(b"=") for item in raw.split(b"\0"))
    return {
        key.decode(): value.decode(errors="replace")
        for key, separator, value in entries
        if separator and key.decode(errors="replace") in ENV_KEYS
    }


def processes(uid, proc=Path("/proc")):
    records = []
    for directory in sorted(proc.iterdir()):
        if not directory.name.isdigit():
            continue
        try:
            status = (directory / "status").read_text()
            identity = re.search(r"^Uid:\s+(\d+)\s+(\d+)", status, re.M)
            # /proc inode ownership can become root after privilege changes;
            # use the process's effective UID rather than the directory owner.
            if not identity or int(identity.group(2)) != uid:
                continue
            comm = (directory / "comm").read_text().strip()
            # Inspect argv only to identify our host, never include argv in output.
            is_host = b"kiosk_browser.py" in (directory / "cmdline").read_bytes()
            if (
                comm not in ("cage", "Xwayland", "WebKitWebProces", "WebKitWebProcess")
                and not is_host
            ):
                continue
            record = {"pid": int(directory.name), "comm": comm}
            record["environment"] = filtered_environment(
                (directory / "environ").read_bytes()
            )
            record["status"] = [
                line
                for line in status.splitlines()
                if re.match(
                    r"^(PPid|Uid|CapInh|CapPrm|CapEff|CapAmb|NoNewPrivs):", line
                )
            ]
            record["cgroup"] = read(directory / "cgroup")
            records.append(record)
        except OSError:
            continue  # Process may exit during a snapshot.
    return records


def command(argv, **kwargs):
    print("COMMAND:", " ".join(argv), flush=True)
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=10, **kwargs
        )
        print(result.stdout[-40000:])
        if result.stderr:
            print(result.stderr[-4000:])
        print("exit:", result.returncode, flush=True)
    except (OSError, subprocess.SubprocessError) as error:
        print("unavailable:", error, flush=True)


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run this diagnostic using sudo.")
    print("LyceumTV read-only display diagnostic v1", flush=True)
    command(["date", "--iso-8601=seconds"])
    command(["uptime"])
    command(["uname", "-a"])
    try:
        with urlopen("http://127.0.0.1:8080/api/health", timeout=3) as response:
            health = json.load(response)
        print(
            "API:",
            json.dumps({key: health.get(key) for key in ("ok", "version", "service")}),
        )
    except (OSError, ValueError) as error:
        print("API unavailable:", error)
    command(
        [
            "systemctl",
            "show",
            "--no-pager",
            "lyceumtv-kiosk.service",
            "-p",
            "ActiveState",
            "-p",
            "SubState",
            "-p",
            "MainPID",
            "-p",
            "NRestarts",
            "-p",
            "ExecMainStatus",
            "-p",
            "FragmentPath",
            "-p",
            "DropInPaths",
        ]
    )
    launcher = Path("/usr/local/lib/lyceumtv/launch-kiosk.sh")
    try:
        source = launcher.read_bytes()
        print("launcher SHA256:", hashlib.sha256(source).hexdigest())
        print("launcher cursor block:", b"BEGIN LyceumTV cursor environment" in source)
        print("launcher single output:", b"/usr/bin/cage -m last --" in source)
    except OSError as error:
        print("launcher unavailable:", error)

    print("=== DRM CONNECTORS ===")
    for connector in sorted(Path("/sys/class/drm").glob("card*-*")):
        if not (connector / "status").exists():
            continue
        print(connector.name)
        for name in ("status", "enabled", "dpms", "modes"):
            print(name + ":", read(connector / name))
        try:
            edid = (connector / "edid").read_bytes()
            print("EDID bytes:", len(edid), "SHA256:", hashlib.sha256(edid).hexdigest())
        except OSError as error:
            print("EDID unavailable:", error)
    print("=== DRM PLANE / CRTC STATE ===")
    states = list(Path("/sys/kernel/debug/dri").glob("*/state"))
    if not states:
        print("DRM debug state unavailable; debugfs will not be mounted by this check.")
    for path in states:
        print(str(path), read(path)[:20000])

    account = pwd.getpwnam("lyceumtv-kiosk")
    if account.pw_uid == 0:
        raise SystemExit("Refusing unexpected kiosk UID 0")
    snapshot = processes(account.pw_uid)
    print("=== ACTUAL CAGE / BROWSER PROCESSES (selected fields only) ===")
    print(json.dumps(snapshot, ensure_ascii=False, indent=2), flush=True)
    display = next(
        (
            item["environment"]
            for item in snapshot
            if item["environment"].get("WAYLAND_DISPLAY")
        ),
        None,
    )
    if display:
        env = {
            "PATH": "/usr/bin:/bin",
            "XDG_RUNTIME_DIR": display.get(
                "XDG_RUNTIME_DIR", f"/run/user/{account.pw_uid}"
            ),
            "WAYLAND_DISPLAY": display["WAYLAND_DISPLAY"],
        }
        command(
            ["/usr/bin/wlr-randr", "--json"],
            user=account.pw_uid,
            group=account.pw_gid,
            extra_groups=os.getgrouplist(account.pw_name, account.pw_gid),
            env=env,
            cwd="/",
        )
    else:
        print("No running browser Wayland environment found; output query skipped.")
    print("=== CURSOR THEME FILES ===")
    for name in ("default", "left_ptr", "lyceumtv-invisible"):
        path = Path("/usr/local/share/lyceumtv-cursors") / name / "cursors/left_ptr"
        try:
            raw = path.read_bytes()
            print(
                name,
                "bytes:",
                len(raw),
                "mode:",
                stat.S_IMODE(path.stat().st_mode),
                "SHA256:",
                hashlib.sha256(raw).hexdigest(),
            )
        except OSError as error:
            print(name, "unavailable:", error)
    print("=== FIRST BOOT KIOSK LOG ===", flush=True)
    command(
        ["journalctl", "-b", "-u", "lyceumtv-kiosk.service", "--no-pager", "-n", "100"]
    )
    command(["journalctl", "-b", f"_UID={account.pw_uid}", "--no-pager", "-n", "100"])
    command(
        [
            "journalctl",
            "-b",
            "-k",
            "--no-pager",
            "--grep=drm|hdmi|sun4i|sun8i|lima",
            "-n",
            "80",
        ]
    )
    print(
        "DIAGNOSTIC COMPLETE. No services, display modes or settings were changed.",
        flush=True,
    )


if __name__ == "__main__":
    main()
PYDIAG
'@
$temporaryPath = Join-Path $env:TEMP ("lyceumtv-diagnostic-" + [guid]::NewGuid().ToString("N") + ".sh")
$remotePath = "/home/$BoardUser/lyceumtv-diagnostic-$([guid]::NewGuid().ToString('N')).sh"
$target = "${BoardUser}@${BoardHost}"
$logPath = Join-Path $PSScriptRoot ("LyceumTV-HDMI-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".txt")
try {
    [System.IO.File]::WriteAllText($temporaryPath, $remoteCode.Replace("`r", "") + "`n", [System.Text.UTF8Encoding]::new($false))
    & scp -o ConnectTimeout=10 $temporaryPath "${target}:$remotePath"
    if ($LASTEXITCODE -ne 0) { throw "Cannot upload diagnostic." }
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & ssh -o ConnectTimeout=10 -o LogLevel=ERROR -t $target "bash '$remotePath'" 2>&1 | Tee-Object -FilePath $logPath
        $diagnosticExit = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previousPreference }
    if ($diagnosticExit -ne 0) { throw "Diagnostic did not finish. Send the saved log: $logPath" }
}
finally { Remove-Item $temporaryPath -ErrorAction SilentlyContinue }
Write-Host "Send this file: $logPath"
