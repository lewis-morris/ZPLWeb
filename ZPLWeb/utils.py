import hashlib
import os
import sys


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


def ensure_single_instance(window_title: str) -> bool:
    """Prevent multiple Windows instances and focus existing window.

    On Windows, a named mutex guards against launching more than one
    instance of the application. If a prior instance is detected, its
    window is restored and focused.

    Args:
        window_title: Title of the main window used for lookup.

    Returns:
        ``True`` if this is the primary instance and startup should
        continue. ``False`` if another instance is activated instead.
    """
    if not sys.platform.startswith("win"):
        return True
    try:
        import win32api
        import win32con
        import win32event
        import win32gui
    except Exception:  # pragma: no cover - pywin32 absent on non-Windows
        return True

    win32event.CreateMutex(None, False, "ZPLWebSingleton")
    if win32api.GetLastError() == win32con.ERROR_ALREADY_EXISTS:
        hwnd = win32gui.FindWindow(None, window_title)
        if hwnd:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
        return False
    return True
