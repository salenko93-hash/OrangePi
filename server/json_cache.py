"""Small process-local JSON cache; disk changes invalidate on the next read."""

from collections import OrderedDict
from copy import deepcopy
import json
from pathlib import Path
from threading import RLock

_LOCK = RLock()
_CACHE = OrderedDict()
_LIMIT = 64


def load_json(path, *, copy=True):
    """Return an independent value, or a read-only snapshot for internal readers.

    copy=False avoids copying entire schedules when a caller only reads them.
    Those callers must construct their own output objects rather than mutate input.
    """
    path = Path(path)
    with _LOCK:
        stat = path.stat()
        signature = (
            stat.st_dev,
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_ctime_ns,
        )
        entry = _CACHE.get(path)
        if entry is None or entry[0] != signature:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
            _CACHE[path] = (signature, value)
            if len(_CACHE) > _LIMIT:
                _CACHE.popitem(last=False)
        else:
            value = entry[1]
        _CACHE.move_to_end(path)
        return deepcopy(value) if copy else value


def clear_json_cache():
    with _LOCK:
        _CACHE.clear()
