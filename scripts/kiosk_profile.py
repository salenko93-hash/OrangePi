"""Prepare each private kiosk directory, including parents, without following links."""

import os
from pathlib import Path
import sys


def prepare_profile(home, uid, gid):
    home = Path(home)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptors = {"": os.open(home, flags)}
    try:
        for relative in (
            "",
            ".cache",
            ".cache/lyceumtv-webkit",
            ".local",
            ".local/share",
            ".local/share/lyceumtv-webkit",
        ):
            if relative:
                parent, _, name = relative.rpartition("/")
                parent_fd = descriptors[parent]
                try:
                    os.mkdir(name, mode=0o700, dir_fd=parent_fd)
                except FileExistsError:
                    pass
                descriptors[relative] = os.open(name, flags, dir_fd=parent_fd)
            descriptor = descriptors[relative]
            os.fchown(descriptor, uid, gid)
            os.fchmod(descriptor, 0o700)
    finally:
        for descriptor in reversed(list(descriptors.values())):
            os.close(descriptor)


def main():
    import pwd

    if len(sys.argv) != 2:
        raise SystemExit("Usage: kiosk_profile.py <kiosk-user>")
    account = pwd.getpwnam(sys.argv[1])
    if account.pw_uid == 0 or account.pw_dir != "/var/lib/lyceumtv-kiosk":
        raise SystemExit("Refusing an unexpected kiosk account/home directory")
    prepare_profile(account.pw_dir, account.pw_uid, account.pw_gid)


if __name__ == "__main__":
    main()
