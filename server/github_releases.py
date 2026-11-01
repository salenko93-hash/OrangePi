"""Read and verify releases from the sole official Orange Pi repository."""

import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import ssl
import stat
import urllib.error
import urllib.parse
import urllib.request
import zipfile

REPOSITORY = "salenko93-hash/OrangePi"
API = "https://api.github.com/repos/" + REPOSITORY + "/releases"
BASE = "https://github.com/" + REPOSITORY + "/releases/download/"
TAG = re.compile(r"v?(\d+\.\d+\.\d+)(?:-rc\.[1-9]\d*)?")
HEX = re.compile(r"[0-9a-f]{64}")
MAX_PACKAGE = 128 * 1024 * 1024


def official_asset(url):
    value = urllib.parse.urlsplit(str(url))
    if (
        value.scheme != "https"
        or value.netloc != "github.com"
        or value.query
        or value.fragment
        or not str(url).startswith(BASE)
    ):
        raise ValueError("Only official OrangePi GitHub release assets are accepted")
    parts = value.path[len("/" + REPOSITORY + "/releases/download/") :].split("/")
    if (
        len(parts) != 2
        or not TAG.fullmatch(parts[0])
        or not re.fullmatch(r"[A-Za-z0-9._-]+", parts[1])
    ):
        raise ValueError("Invalid official release asset URL")
    return str(url)


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        if (
            target.scheme != "https"
            or target.hostname
            not in {
                "github.com",
                "api.github.com",
                "release-assets.githubusercontent.com",
                "objects.githubusercontent.com",
            }
            or target.port not in (None, 443)
            or target.username
            or target.password
        ):
            raise ValueError("Untrusted release redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url, *, limit=MAX_PACKAGE, timeout=90):
    if url != API and not url.startswith(API + "/") and not url.startswith(API + "?"):
        official_asset(url)
    else:
        parsed = urllib.parse.urlsplit(url)
        if parsed.netloc != "api.github.com" or parsed.fragment:
            raise ValueError("Untrusted GitHub API URL")
    opener = urllib.request.build_opener(
        HTTPSRedirect(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "LyceumTV-OrangePi",
            "Accept": "application/vnd.github+json"
            if url.startswith(API)
            else "application/octet-stream",
        },
    )
    with opener.open(request, timeout=timeout) as response:
        raw = response.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("Release download exceeds size limit")
        return raw


def version_tuple(version):
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(version)):
        raise ValueError("Invalid runtime version")
    return tuple(int(part) for part in version.split("."))


def release(tag=None, *, allow_prerelease=False):
    if tag is not None and not TAG.fullmatch(tag):
        raise ValueError("Invalid release tag")
    endpoint = API + (
        "/tags/" + tag if tag else ("?per_page=100" if allow_prerelease else "/latest")
    )
    payload = json.loads(download(endpoint, limit=1024 * 1024))
    if isinstance(payload, list):
        payload = next((item for item in payload if not item.get("draft")), None)
    if not isinstance(payload, dict) or payload.get("draft"):
        raise ValueError("No published official release")
    selected = payload.get("tag_name", "")
    match = TAG.fullmatch(selected)
    if not match or (tag and tag != selected):
        raise ValueError("Release tag does not match request")
    prerelease = bool(payload.get("prerelease")) or "-" in selected
    if prerelease and not allow_prerelease:
        raise ValueError("Prerelease requires explicit administrator opt-in")
    version = match.group(1)
    name = f"LyceumTV-{version}-ORANGEPI-PC.zip"
    assets = payload.get("assets", [])

    def asset(filename):
        matches = [item for item in assets if item.get("name") == filename]
        if len(matches) != 1:
            raise ValueError("Missing or duplicate release asset: " + filename)
        item = matches[0]
        url = official_asset(item.get("browser_download_url", ""))
        if url != BASE + selected + "/" + filename:
            raise ValueError("Asset belongs to a different release")
        return item, url

    package, url = asset(name)
    _, checksum_url = asset(name + ".sha256")
    digest = str(package.get("digest", ""))
    if not digest.startswith("sha256:") or not HEX.fullmatch(digest[7:]):
        raise ValueError("GitHub asset SHA-256 digest is required")
    checksum = download(checksum_url, limit=4096).decode("ascii").strip().split()
    if len(checksum) != 2 or checksum[0] != digest[7:] or checksum[1] != name:
        raise ValueError("GitHub digest and checksum sidecar disagree")
    return {
        "version": version,
        "tag": selected,
        "prerelease": prerelease,
        "package_url": url,
        "sha256": digest[7:],
        "name": name,
        "source": "https://github.com/" + REPOSITORY,
    }


def unpack(raw, directory, version):
    """Validate the entire archive before creating any extracted files."""
    from update_transaction import validate_release

    prefix = f"LyceumTV-{version}-ORANGEPI-PC/"
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        if len(infos) > 4096 or sum(i.file_size for i in infos) > 256 * 1024 * 1024:
            raise ValueError("Release ZIP exceeds extraction limits")
        names = set()
        folded = set()
        target = Path(directory) / prefix.rstrip("/")
        if target.exists() or target.is_symlink():
            raise ValueError("Extraction target must be new")
        for item in infos:
            name = item.filename
            path = PurePosixPath(name)
            mode = item.external_attr >> 16
            if (
                not name.startswith(prefix)
                or name == prefix
                or "\\" in name
                or ":" in name
                or path.is_absolute()
                or ".." in path.parts
                or str(path) != name
                or name.casefold() in folded
                or item.is_dir()
                or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
            ):
                raise ValueError("Unsafe or duplicate ZIP member")
            relative = name[len(prefix) :]
            if (
                relative.startswith(("public/media/", ".git/"))
                or (
                    relative.startswith("data/")
                    and not relative.startswith("data/default/")
                    and relative != "data/config.example.json"
                )
                or Path(relative).suffix.lower() in {".key", ".pem", ".p12", ".pfx"}
            ):
                raise ValueError("Private or live files in release ZIP")
            names.add(name)
            folded.add(name.casefold())
        manifest = json.loads(archive.read(prefix + "PACKAGE_SHA256.json"))
        if not isinstance(manifest, dict) or names != {prefix + n for n in manifest} | {
            prefix + "PACKAGE_SHA256.json"
        }:
            raise ValueError("ZIP files and manifest differ")
        for name, wanted in manifest.items():
            if (
                not isinstance(wanted, str)
                or not HEX.fullmatch(wanted)
                or hashlib.sha256(archive.read(prefix + name)).hexdigest() != wanted
            ):
                raise ValueError("Release file SHA-256 mismatch")
        target = Path(directory) / prefix.rstrip("/")
        for item in infos:
            destination = Path(directory) / item.filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(item))
            destination.chmod(0o755 if destination.suffix == ".sh" else 0o644)
    if validate_release(target) != version:
        raise ValueError("Runtime version differs from release tag")
    return target


def package(info):
    raw = download(official_asset(info["package_url"]))
    if hashlib.sha256(raw).hexdigest() != info["sha256"]:
        raise ValueError("Release ZIP SHA-256 mismatch")
    return raw
