import hashlib
import os
import sys
import time
from collections.abc import MutableMapping
from typing import TypeVar


def _make_fingerprint(invoice, pcs, zpl) -> str:
    h = hashlib.sha256()
    h.update((invoice or "").encode("utf-8"))
    h.update(str(pcs or "").encode("utf-8"))
    h.update((zpl or "").encode("utf-8"))
    return h.hexdigest()


K = TypeVar("K")


def expire_stale_jobs(
    store: MutableMapping[K, float], ttl: float, now: float | None = None
) -> None:
    """Remove entries older than ``ttl`` seconds from ``store``.

    Args:
        store: Mapping of identifiers to their insertion timestamps.
        ttl: Maximum age in seconds before an entry is discarded.
        now: Current timestamp. Defaults to :func:`time.time` when ``None``.

    """
    if now is None:
        now = time.time()
    for key, ts in list(store.items()):
        if now - ts > ttl:
            del store[key]


def resource_path(relative_path: str) -> str:
    """Return absolute path to a bundled resource.

    Args:
        relative_path: Path relative to the project root or frozen bundle.

    Returns:
        Absolute path to the resolved resource.
    """
    if getattr(sys, "frozen", False):
        # PyInstaller places extracted files in _MEIPASS
        base_path = getattr(sys, "_MEIPASS")
    else:
        # running in a normal Python environment
        base_path = os.path.abspath(os.path.dirname(__file__))

    return os.path.join(base_path, relative_path)
