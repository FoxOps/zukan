import os
from importlib.metadata import PackageNotFoundError, version


def _version() -> str:
    # Docker images carry the release version (dev-<branch> for dev builds).
    if env := os.environ.get("FUDABAKO_VERSION"):
        return env
    try:
        return version("fudabako")
    except PackageNotFoundError:
        return "0.0.0"


__version__ = _version()
