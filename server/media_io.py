"""Bounded uploads and byte-range media responses without loading videos into RAM."""

from pathlib import Path
import mimetypes
import os
import re
import uuid
import shutil
from storage_lock import storage_lock

QUOTA_BYTES = 2 * 1024**3
RESERVE_BYTES = 256 * 1024**2


def validate_signature(name, prefix):
    ext = Path(name).suffix.lower()
    valid = {
        ".jpg": prefix.startswith(b"\xff\xd8\xff"),
        ".jpeg": prefix.startswith(b"\xff\xd8\xff"),
        ".png": prefix.startswith(b"\x89PNG\r\n\x1a\n"),
        ".webp": prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP",
        ".wav": prefix.startswith(b"RIFF") and prefix[8:12] == b"WAVE",
        ".ogg": prefix.startswith(b"OggS"),
        ".webm": prefix.startswith(b"\x1aE\xdf\xa3"),
        ".mp4": prefix[4:8] == b"ftyp",
        ".m4a": prefix[4:8] == b"ftyp",
        ".mp3": prefix.startswith(b"ID3")
        or (len(prefix) >= 2 and prefix[0] == 255 and prefix[1] & 224 == 224),
    }.get(ext, False)
    if not valid:
        raise ValueError("Вміст файлу не відповідає його формату")


def media_type(name):
    ext = Path(name).suffix.lower()
    if ext in {".jpg", ".jpeg", ".png", ".webp"}:
        return "image", 15 * 1024 * 1024
    if ext in {".mp4", ".webm"}:
        return "video", 200 * 1024 * 1024
    if ext in {".mp3", ".wav", ".ogg", ".m4a"}:
        return "audio", 35 * 1024 * 1024
    raise ValueError("Потрібні JPG/PNG/WEBP, MP4/WEBM або MP3/WAV/OGG/M4A")


def save_stream(
    directory,
    file_name,
    stream,
    length,
    *,
    quota_bytes=QUOTA_BYTES,
    reserve_bytes=RESERVE_BYTES,
):
    name = Path(str(file_name)).name
    kind, limit = media_type(name)
    if length <= 0 or length > limit:
        raise ValueError(f"Файл порожній або перевищує {limit // (1024 * 1024)} МБ")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(name).stem)[:50].strip("-") or "media"
    stored = uuid.uuid4().hex + "-" + stem + Path(name).suffix.lower()
    target = directory / stored
    partial = directory / (stored + ".part")
    # Hold the cross-process lock for reservation + stream + commit. A second
    # uploader cannot pass a quota check using the same unreserved free space.
    with storage_lock(directory, "upload"):
        used = sum(
            p.stat().st_size
            for p in directory.rglob("*")
            if p.is_file() and not p.is_symlink()
        )
        if used + length > quota_bytes:
            raise ValueError(
                "Медіатека досягла загального ліміту 2 ГіБ. Видаліть непотрібні файли"
            )
        if shutil.disk_usage(directory).free < length + reserve_bytes:
            raise ValueError(
                "Недостатньо місця: потрібно залишити 256 МіБ для роботи системи"
            )
        try:
            with partial.open("xb") as output:
                remaining = length
                prefix = b""
                while remaining:
                    chunk = stream.read(min(64 * 1024, remaining))
                    if not chunk:
                        raise ValueError("Завантаження перервано; повторіть спробу")
                    prefix = (prefix + chunk)[:512]
                    output.write(chunk)
                    remaining -= len(chunk)
                validate_signature(name, prefix)
            os.replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)
    return {
        "ok": True,
        "url": "/media/" + stored,
        "file": stored,
        "bytes": length,
        "media_kind": kind,
        "content_type": mimetypes.guess_type(stored)[0] or "application/octet-stream",
    }


def byte_range(value, size):
    """Return inclusive range; reject malformed/multiple/unsatisfiable ranges."""
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value)
    if not match or size <= 0:
        raise ValueError("Invalid range")
    start, end = match.groups()
    if not start:
        if not end or int(end) <= 0:
            raise ValueError("Invalid suffix")
        return max(0, size - int(end)), size - 1
    start = int(start)
    end = min(int(end), size - 1) if end else size - 1
    if start >= size or end < start:
        raise ValueError("Unsatisfiable range")
    return start, end


def send_media(handler, target):
    with target.open("rb") as source:
        size = os.fstat(source.fileno()).st_size
        start, end = 0, size - 1
        request_range = handler.headers.get("Range")
        if request_range:
            try:
                start, end = byte_range(request_range, size)
            except ValueError:
                handler.send_response(416)
                handler.send_header("Content-Range", f"bytes */{size}")
                handler.send_header("Content-Length", "0")
                handler.end_headers()
                return
        handler.send_response(206 if request_range else 200)
        handler.send_header(
            "Content-Type",
            mimetypes.guess_type(target.name)[0] or "application/octet-stream",
        )
        handler.send_header("Content-Length", str(max(0, end - start + 1)))
        handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("Cache-Control", "public, max-age=86400")
        if request_range:
            handler.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        handler.end_headers()
        source.seek(start)
        remaining = end - start + 1
        try:
            while remaining > 0:
                chunk = source.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                handler.wfile.write(chunk)
                remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass  # A media element may cancel buffering on each transition.
