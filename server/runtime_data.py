"""Create working data on first start; leave all existing deployments intact."""

from pathlib import Path
import shutil


def initialize_runtime_data(root):
    root = Path(root)
    defaults = root / "data/default"
    current = root / "data/current"
    current.mkdir(parents=True, exist_ok=True)
    if any(current.iterdir()):
        return False
    for source in defaults.glob("*.json"):
        if source.name != "smart_ops.json":
            shutil.copy2(source, current / source.name)
    return True


if __name__ == "__main__":
    import sys

    initialize_runtime_data(sys.argv[1])
