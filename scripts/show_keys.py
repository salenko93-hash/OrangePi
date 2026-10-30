#!/usr/bin/python3 -I
"""Installed root-owned outside the application tree; show only the role keys."""

import json
import os
import pwd
import stat

if os.geteuid() != 0:
    raise SystemExit("Run: sudo /usr/local/sbin/lyceumtv-show-keys")
flags = os.O_RDONLY | os.O_NOFOLLOW
fd = os.open("/opt/lyceumtv/data/config.json", flags)
with os.fdopen(fd, encoding="utf-8") as handle:
    info = os.fstat(handle.fileno())
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != pwd.getpwnam("lyceumtv").pw_uid
        or info.st_size > 131072
    ):
        raise SystemExit(
            "Unexpected configuration owner/type/size; inspect installation"
        )
    config = json.load(handle)
print(
    json.dumps(
        {name: config[name] for name in ("admin_key", "dispatcher_key", "teacher_key")},
        ensure_ascii=True,
        indent=2,
    )
)
