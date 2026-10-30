"""Thread/process locks for operations that also run from systemd timers."""

from contextlib import contextmanager
from pathlib import Path
from threading import RLock

try:
    import fcntl
except ImportError:  # Local Windows development; Pi uses flock.
    fcntl = None

_REGISTRY = {}
_REGISTRY_LOCK = RLock()


@contextmanager
def storage_lock(directory, name, *, blocking=True):
    key = (str(Path(directory).resolve()), name)
    with _REGISTRY_LOCK:
        thread_lock = _REGISTRY.setdefault(key, RLock())
    with thread_lock:
        path = Path(directory) / ".locks"
        path.mkdir(parents=True, exist_ok=True)
        with (path / (name + ".lock")).open("a+b") as handle:
            if fcntl:
                flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
                fcntl.flock(handle, flags)
            try:
                yield
            finally:
                if fcntl:
                    fcntl.flock(handle, fcntl.LOCK_UN)
