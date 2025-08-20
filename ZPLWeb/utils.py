import atexit
import hashlib
import os
import sys
import tempfile
from pathlib import Path


def _make_fingerprint(invoice, pcs, zpl) -> str:
    h = hashlib.sha256()
    h.update((invoice or "").encode("utf-8"))
    h.update(str(pcs or "").encode("utf-8"))
    h.update((zpl or "").encode("utf-8"))
    return h.hexdigest()


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


_LOCK_FILE = Path(tempfile.gettempdir()) / "ZPLWeb.lock"


def _pid_alive(pid: int) -> bool:
    """Return ``True`` if ``pid`` is currently running."""

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def ensure_single_instance(window_title: str) -> bool:
    """Ensure only one copy of the application runs.

    Attempts to use a Windows named mutex to prevent multiple instances. If
    the ``pywin32`` modules are unavailable or the platform is not Windows, a
    cross‑platform file lock in the temporary directory is used instead.

    Args:
        window_title: Title of the main window used for lookup when an
            existing instance should be focused.

    Returns:
        ``True`` if this is the first running instance. ``False`` if another
        instance already holds the lock.
    """

    if sys.platform.startswith("win"):
        try:
            import win32api
            import win32con
            import win32event
            import win32gui
            import winerror

            win32event.CreateMutex(None, False, "ZPLWebSingleton")
            if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
                hwnd = win32gui.FindWindow(None, window_title)
                if hwnd:
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                    win32gui.SetForegroundWindow(hwnd)
                return False
            return True
        except Exception:  # pragma: no cover - pywin32 absent or failing
            pass

    pid = os.getpid()
    while True:
        try:
            fd = os.open(_LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(pid).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                existing_pid = int(_LOCK_FILE.read_text())
            except Exception:
                existing_pid = None
            if existing_pid and _pid_alive(existing_pid):
                return False
            try:
                _LOCK_FILE.unlink()
            except FileNotFoundError:  # race: file removed after exist check
                continue

    def _cleanup() -> None:
        try:
            if _LOCK_FILE.exists() and _LOCK_FILE.read_text() == str(pid):
                _LOCK_FILE.unlink()
        except Exception:
            pass

    atexit.register(_cleanup)
    return True
