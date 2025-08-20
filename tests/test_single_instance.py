"""Tests for single-instance behavior."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import ZPLWeb.utils as utils


def test_existing_instance_brought_to_front(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    fake_modules = {
        "win32event": SimpleNamespace(CreateMutex=MagicMock()),
        "win32api": SimpleNamespace(GetLastError=MagicMock(return_value=1)),
        "win32con": SimpleNamespace(SW_RESTORE=9),
        "win32gui": SimpleNamespace(
            FindWindow=MagicMock(return_value=42),
            ShowWindow=MagicMock(),
            SetForegroundWindow=MagicMock(),
        ),
        "winerror": SimpleNamespace(ERROR_ALREADY_EXISTS=1),
    }
    monkeypatch.setitem(sys.modules, "win32event", fake_modules["win32event"])
    monkeypatch.setitem(sys.modules, "win32api", fake_modules["win32api"])
    monkeypatch.setitem(sys.modules, "win32con", fake_modules["win32con"])
    monkeypatch.setitem(sys.modules, "win32gui", fake_modules["win32gui"])
    monkeypatch.setitem(sys.modules, "winerror", fake_modules["winerror"])

    assert utils.ensure_single_instance("T") is False
    fake_modules["win32gui"].FindWindow.assert_called_with(None, "T")
    fake_modules["win32gui"].ShowWindow.assert_called_with(42, 9)
    fake_modules["win32gui"].SetForegroundWindow.assert_called_with(42)


def test_primary_instance(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    fake_modules = {
        "win32event": SimpleNamespace(CreateMutex=MagicMock()),
        "win32api": SimpleNamespace(GetLastError=MagicMock(return_value=0)),
        "win32con": SimpleNamespace(SW_RESTORE=9),
        "win32gui": SimpleNamespace(
            FindWindow=MagicMock(return_value=42),
            ShowWindow=MagicMock(),
            SetForegroundWindow=MagicMock(),
        ),
        "winerror": SimpleNamespace(ERROR_ALREADY_EXISTS=1),
    }
    monkeypatch.setitem(sys.modules, "win32event", fake_modules["win32event"])
    monkeypatch.setitem(sys.modules, "win32api", fake_modules["win32api"])
    monkeypatch.setitem(sys.modules, "win32con", fake_modules["win32con"])
    monkeypatch.setitem(sys.modules, "win32gui", fake_modules["win32gui"])
    monkeypatch.setitem(sys.modules, "winerror", fake_modules["winerror"])

    assert utils.ensure_single_instance("T") is True
    fake_modules["win32gui"].FindWindow.assert_not_called()


def test_file_lock_fallback(monkeypatch, tmp_path):
    """Fallback to a file lock when pywin32 is unavailable."""

    monkeypatch.setattr(sys, "platform", "linux")
    lock_file = tmp_path / "lock"
    monkeypatch.setattr(utils, "_LOCK_FILE", lock_file)

    assert utils.ensure_single_instance("T") is True
    assert utils.ensure_single_instance("T") is False
    lock_file.unlink(missing_ok=True)
