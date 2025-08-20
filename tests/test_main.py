"""Tests for the application entry point."""

import sys
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6.QtWidgets")
import ZPLWeb.main as main_module


def test_second_instance_warns_and_exits(monkeypatch):
    """A warning is shown and the process exits when already running."""
    monkeypatch.setattr(main_module, "ensure_single_instance", lambda *_: False)
    monkeypatch.setattr(main_module, "QApplication", MagicMock())
    warn_mock = MagicMock()
    monkeypatch.setattr(main_module.QMessageBox, "warning", warn_mock)
    exit_mock = MagicMock()
    monkeypatch.setattr(sys, "exit", exit_mock)

    main_module.main()

    warn_mock.assert_called_once()
    exit_mock.assert_called_once_with(0)
