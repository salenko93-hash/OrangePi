"""Verify Ed25519 releases against an operator-installed, root-owned trust key."""

import base64
import json
from pathlib import Path
import stat
import subprocess
import tempfile

TRUSTED_KEY = Path("/etc/lyceumtv/release-public.pem")


def signed_bytes(manifest):
    payload = {k: v for k, v in manifest.items() if k != "signature"}
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def verify_manifest_signature(manifest, key_path=TRUSTED_KEY, *, require_root=True):
    key_path = Path(key_path)
    if not key_path.is_file():
        raise ValueError(
            "OTA вимкнено: адміністратор Pi має встановити довірений release-public.pem. Використайте повний інсталятор"
        )
    if require_root:
        for path in (key_path, *key_path.parents):
            info = path.lstat()
            if info.st_uid != 0 or info.st_mode & 0o022 or stat.S_ISLNK(info.st_mode):
                raise ValueError(
                    "Довірений ключ OTA та його каталоги мають належати root і бути недоступними програмі для запису"
                )
    try:
        signature = base64.b64decode(manifest.get("signature", ""), validate=True)
    except (TypeError, ValueError) as error:
        raise ValueError("Некоректний підпис OTA") from error
    if len(signature) != 64:
        raise ValueError("Потрібен цифровий підпис Ed25519")
    with tempfile.TemporaryDirectory(prefix="lyceum-signature-") as directory:
        message = Path(directory) / "message"
        sig = Path(directory) / "signature"
        message.write_bytes(signed_bytes(manifest))
        sig.write_bytes(signature)
        try:
            result = subprocess.run(
                [
                    "openssl",
                    "pkeyutl",
                    "-verify",
                    "-pubin",
                    "-inkey",
                    str(key_path),
                    "-rawin",
                    "-in",
                    str(message),
                    "-sigfile",
                    str(sig),
                ],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ValueError("Не вдалося перевірити підпис OTA") from error
        if result.returncode:
            raise ValueError("Підпис OTA недійсний: пакет не прийнято")
