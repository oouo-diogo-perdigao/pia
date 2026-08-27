"""Wakeword package exports and convenience helpers.

Avoid importing submodules with runtime side-effects at package import time.
Use :func:`main` to run the server from outside.
"""

from importlib import import_module
from typing import Callable


def main() -> None:
    """Run the wakeword server main function (lazy import).

    This avoids importing submodules during package import which can cause
    warnings when run with runpy or -m.
    """
    mod = import_module(".server", package=__name__)
    # mypy-friendly: call attribute
    getattr(mod, "main")()


__all__ = ["main"]
