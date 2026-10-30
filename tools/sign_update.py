"""Sign a release manifest OFF the Pi; never put the private key in a release."""

import argparse
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from release_signature import signed_bytes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--key", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as directory:
        message = Path(directory) / "message"
        signature = Path(directory) / "signature"
        message.write_bytes(signed_bytes(manifest))
        subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-sign",
                "-inkey",
                str(args.key),
                "-rawin",
                "-in",
                str(message),
                "-out",
                str(signature),
            ],
            check=True,
        )
        manifest["signature"] = base64.b64encode(signature.read_bytes()).decode()
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
