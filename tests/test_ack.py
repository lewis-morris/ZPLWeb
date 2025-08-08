import pytest
from PySide6.QtWidgets import QApplication

from ZPLWeb.main import MainWindow


@pytest.fixture(scope="module")
def app():
    """Provide a QApplication instance for widget tests."""
    return QApplication.instance() or QApplication([])


def test_emit_ack_updates_db(app, tmp_path, monkeypatch):
    """_emit_ack should mark jobs as acknowledged in the database."""
    monkeypatch.setattr("ZPLWeb.main.user_data_dir", lambda *a, **k: tmp_path)
    win = MainWindow()
    job_id = 123
    win._store_print(job_id, "INV", 1, "^XA^XZ")
    assert not win._is_job_acked(job_id)

    class DummySio:
        connected = True

        def emit(self, event, data):
            self.last = (event, data)

    win.sio = DummySio()
    win._emit_ack(job_id)
    assert win._is_job_acked(job_id)
    assert win.sio.last == ("print_label_ack", {"job_id": job_id, "status": "printed"})
    win.close()
