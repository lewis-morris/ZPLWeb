import sys
import os


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
