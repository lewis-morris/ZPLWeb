import os
import types
from importlib import reload

import ZPLWeb.utils as utils


def test_resource_path_frozen(tmp_path, monkeypatch):
    mod = reload(utils)
    monkeypatch.setattr(
        mod, "sys", types.SimpleNamespace(frozen=True, _MEIPASS=str(tmp_path))
    )
    assert mod.resource_path("foo") == os.path.join(str(tmp_path), "foo")


def test_resource_path_dev(monkeypatch):
    mod = reload(utils)
    monkeypatch.setattr(mod, "sys", types.SimpleNamespace(frozen=False))
    expected = os.path.join(os.path.abspath(os.path.dirname(mod.__file__)), "bar")
    assert mod.resource_path("bar") == expected
