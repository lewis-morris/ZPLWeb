import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

import ZPLWeb.main as main_module
from ZPLWeb.main import MainWindow, OptionsDialog
from ZPLWeb.main import TestPrintDialog as ZplTestPrintDialog


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class FakeSettings:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def value(self, key, default=""):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value


class FakeSocket:
    def __init__(self, *args, **kwargs):
        self.connected = False
        self.events = {}
        self.handlers = {}
        self.emitted = []
        self.connect_calls = []
        self.disconnect_calls = 0

    def event(self, func):
        self.events[func.__name__] = func
        return func

    def on(self, name):
        def decorate(func):
            self.handlers[name] = func
            return func

        return decorate

    def connect(self, server_url, transports, auth):
        self.connect_calls.append(
            {"server_url": server_url, "transports": transports, "auth": auth}
        )
        self.connected = True

    def emit(self, event, data):
        self.emitted.append((event, data))

    def disconnect(self):
        self.disconnect_calls += 1
        self.connected = False


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "user_data_dir", lambda *a, **k: tmp_path)
    settings = FakeSettings(
        {
            "api_key": "api-123",
            "printer_name": "Printer A",
            "server_url": "https://example.test",
        }
    )
    monkeypatch.setattr(main_module, "S", settings)
    monkeypatch.setattr(main_module.socketio, "Client", FakeSocket)
    win = MainWindow()
    yield win
    win.close()


def test_print_zpl_skips_physical_printing_when_no_windows_driver(monkeypatch):
    results = []
    monkeypatch.setattr(main_module, "win32print", None)

    main_module._print_zpl("Queue", "^XA^XZ", lambda ok, msg: results.append((ok, msg)))

    assert results == [(True, "Skipped printed via Queue")]


def test_print_zpl_uses_windows_raw_print_contract(monkeypatch):
    calls = []

    class FakeWin32Print:
        def OpenPrinter(self, printer_name):
            calls.append(("open", printer_name))
            return "handle"

        def StartDocPrinter(self, handle, level, doc_info):
            calls.append(("start_doc", handle, level, doc_info))

        def StartPagePrinter(self, handle):
            calls.append(("start_page", handle))

        def WritePrinter(self, handle, payload):
            calls.append(("write", handle, payload))

        def EndPagePrinter(self, handle):
            calls.append(("end_page", handle))

        def EndDocPrinter(self, handle):
            calls.append(("end_doc", handle))

        def ClosePrinter(self, handle):
            calls.append(("close", handle))

    results = []
    monkeypatch.setattr(main_module, "win32print", FakeWin32Print())

    main_module._print_zpl("Queue", "^XA^XZ", lambda ok, msg: results.append((ok, msg)))

    assert calls == [
        ("open", "Queue"),
        ("start_doc", "handle", 1, ("ZPL", None, "RAW")),
        ("start_page", "handle"),
        ("write", "handle", b"^XA^XZ"),
        ("end_page", "handle"),
        ("end_doc", "handle"),
        ("close", "handle"),
    ]
    assert results == [(True, "Printed via Queue")]


def test_print_zpl_reports_windows_print_failures(monkeypatch):
    class BrokenWin32Print:
        def OpenPrinter(self, printer_name):
            raise OSError("offline")

    results = []
    monkeypatch.setattr(main_module, "win32print", BrokenWin32Print())

    main_module._print_zpl("Queue", "^XA^XZ", lambda ok, msg: results.append((ok, msg)))

    assert results == [(False, "Print error: offline")]


def test_options_dialog_requires_api_key_and_printer(app, monkeypatch):
    settings = FakeSettings({"api_key": "", "printer_name": "", "server_url": "old"})
    monkeypatch.setattr(main_module, "S", settings)
    warning = MagicMock()
    monkeypatch.setattr(main_module.QMessageBox, "warning", warning)
    accepted = MagicMock()

    dlg = OptionsDialog()
    monkeypatch.setattr(dlg, "accept", accepted)
    dlg.api_edit.setText("")
    dlg.prn_edit.setText("Queue")
    dlg._save()

    warning.assert_called_once()
    accepted.assert_not_called()
    assert settings.values == {"api_key": "", "printer_name": "", "server_url": "old"}


def test_options_dialog_trims_and_persists_settings(app, monkeypatch):
    settings = FakeSettings()
    monkeypatch.setattr(main_module, "S", settings)
    accepted = MagicMock()

    dlg = OptionsDialog()
    monkeypatch.setattr(dlg, "accept", accepted)
    dlg.api_edit.setText("  key  ")
    dlg.prn_edit.setText("  Queue  ")
    dlg.server_edit.setText("  https://server.test  ")
    dlg._save()

    assert settings.values == {
        "api_key": "key",
        "printer_name": "Queue",
        "server_url": "https://server.test",
    }
    accepted.assert_called_once_with()


def test_test_print_dialog_warns_for_empty_zpl(app, monkeypatch):
    warning = MagicMock()
    monkeypatch.setattr(main_module.QMessageBox, "warning", warning)

    dlg = ZplTestPrintDialog(printer_name="Queue")
    dlg.text_edit.setPlainText("   ")
    dlg._do_print()

    warning.assert_called_once_with(dlg, "Test ZPL Print", "Please enter some ZPL.")


def test_request_missing_requires_connection_and_api_key(window, monkeypatch):
    logs = []
    window.log_sig.connect(logs.append)

    window.sio.connected = False
    window._request_missing()
    assert logs[-1] == "Not connected; will retry after reconnect."

    info = MagicMock()
    monkeypatch.setattr(main_module.QMessageBox, "information", info)
    window.sio.connected = True
    window.api_key = ""
    window._request_missing()
    info.assert_called_once_with(window, "Print Missing", "No API key configured.")


def test_request_missing_emits_api_key_and_recovers_emit_errors(window):
    logs = []
    window.log_sig.connect(logs.append)
    window.sio.connected = True
    window.api_key = "api-123"

    window._request_missing()
    assert window.sio.emitted[-1] == ("request_missing_prints", {"api_key": "api-123"})
    assert "Requesting outstanding labels" in logs[-1]

    def raise_emit(event, data):
        raise RuntimeError("network down")

    window.sio.emit = raise_emit
    window._request_missing()
    assert logs[-1] == "Request failed: network down"


def test_connect_socket_handles_missing_reentrant_disconnect_and_errors(window):
    statuses = []
    window.status_sig.connect(statuses.append)

    window.api_key = ""
    window._connect_socket()
    assert statuses[-1] == "Missing API key or URL"

    window.api_key = "api-123"
    window.server_url = "https://example.test"
    window._connecting = True
    window._connect_socket()
    assert window.sio.connect_calls == []

    window._connecting = False
    window.sio.connected = True
    window._connect_socket()
    assert window.sio.disconnect_calls == 1
    assert window.sio.connect_calls[-1] == {
        "server_url": "https://example.test",
        "transports": ["websocket", "polling"],
        "auth": {"api_key": "api-123"},
    }

    window._connecting = False
    window.sio.connect = MagicMock(side_effect=RuntimeError("refused"))
    window._connect_socket()
    assert statuses[-1] == "Disconnected"
    assert window._connecting is False


def test_registered_socket_handlers_drive_gui_and_print_callbacks(window, monkeypatch):
    logs = []
    started = []
    acked = []
    window.log_sig.connect(logs.append)
    window.ack_sig.connect(acked.append)
    monkeypatch.setattr(
        main_module,
        "Thread",
        lambda target, args, daemon: SimpleNamespace(
            start=lambda: started.append((target, args, daemon))
        ),
    )
    window._store_print(99, "INV-99", 1, "^XA^XZ")

    window.sio.events["connect"]()
    assert logs[-1] == "Connected"
    assert acked == [99]
    assert window._connecting is False

    window.sio.events["disconnect"]()
    assert logs[-1] == "Disconnected"
    assert window._reconnect_timer.isActive()

    window.sio.connected = False
    window.sio.events["connect_error"]("bad key")
    assert "Connect failed: bad key" in logs
    assert window.re_btn.isEnabled()

    window.sio.handlers["status"]({"msg": "ready"})
    assert logs[-1] == "Server status: ready"

    payload = {"job_id": 7, "invoice": "INV", "pcs": 1, "data": "^XA^XZ"}
    window.sio.handlers["print_label"](payload)
    assert started == [(window._handle_print_job, (payload,), True)]


def test_store_load_reprint_and_flush_pending_acks(window, monkeypatch):
    emitted_acks = []
    window.ack_sig.connect(emitted_acks.append)
    threads = []
    monkeypatch.setattr(
        main_module,
        "Thread",
        lambda target, args, daemon: SimpleNamespace(
            start=lambda: threads.append((target, args, daemon))
        ),
    )

    window._store_print(10, "INV-10", 2, "^XA^XZ")
    window._store_print(11, "INV-11", 0, "^XA^XZ")
    window._load_history()
    assert [window.list.item(i).text() for i in range(window.list.count())] == [
        "INV-10  x2",
        "INV-11  x1",
    ]

    window._flush_pending_acks()
    assert emitted_acks == [10, 11]

    window.list.setCurrentRow(0)
    window._reprint_selected()
    assert threads[-1][1][:2] == ("Printer A", "^XA^XZ")

    window.list.addItem("MISSING  x1")
    window.list.setCurrentRow(window.list.count() - 1)
    warning = MagicMock()
    monkeypatch.setattr(main_module.QMessageBox, "warning", warning)
    window._reprint_selected()
    warning.assert_called_once_with(
        window, "Re-print", "ZPL not found for that invoice"
    )


def test_print_history_sql_queries_keep_latest_row_semantics(window, monkeypatch):
    emitted_acks = []
    threads = []
    window.ack_sig.connect(emitted_acks.append)
    monkeypatch.setattr(
        main_module,
        "Thread",
        lambda target, args, daemon: SimpleNamespace(
            start=lambda: threads.append((target, args, daemon))
        ),
    )

    window._store_print(40, "DUP", 1, "older-zpl")
    window._store_print(41, "OTHER", 2, "other-zpl")
    window._store_print(40, "DUP", 3, "newer-zpl")

    window.sio.connected = True
    window._emit_ack(40)

    assert window._is_job_acked(40) is True
    assert window._is_job_acked(41) is False

    window._load_history()
    assert [window.list.item(i).text() for i in range(window.list.count())] == [
        "DUP  x1",
        "OTHER  x2",
        "DUP  x3",
    ]

    window.list.setCurrentRow(0)
    window._reprint_selected()
    assert threads[-1][1][:2] == ("Printer A", "newer-zpl")

    window._flush_pending_acks()
    assert emitted_acks == [41]


def test_init_db_migrates_legacy_prints_table_and_preloads_job_ids(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(main_module, "user_data_dir", lambda *a, **k: tmp_path)
    db_path = tmp_path / "prints.sqlite"
    with sqlite3.connect(db_path) as con:
        con.execute("""CREATE TABLE prints (
                   id       INTEGER PRIMARY KEY AUTOINCREMENT,
                   job_id   INTEGER,
                   invoice  TEXT,
                   pcs      INTEGER,
                   zpl      TEXT,
                   tstamp   TEXT
               )""")
        con.execute(
            (
                "INSERT INTO prints (job_id, invoice, pcs, zpl, tstamp) "
                "VALUES (?,?,?,?,?)"
            ),
            (55, "LEGACY", 1, "^XA", "2026-01-01T00:00:00"),
        )

    win = MainWindow.__new__(MainWindow)
    win._seen_jobs = set()

    MainWindow._init_db(win)

    assert win._db_path == db_path
    assert win._seen_jobs == {55}
    with sqlite3.connect(db_path) as con:
        columns = {row[1] for row in con.execute("PRAGMA table_info(prints)")}
        assert "acked" in columns
        assert (
            con.execute("SELECT acked FROM prints WHERE job_id=55").fetchone()[0] == 0
        )


def test_flush_pending_acks_streams_only_unacked_jobs_in_db_order(window):
    emitted_acks = []
    window.ack_sig.connect(emitted_acks.append)

    window._store_print(60, "ACKED", 1, "^XA")
    window._store_print(61, "PENDING-1", 1, "^XA")
    window._store_print(62, "PENDING-2", 1, "^XA")
    window.sio.connected = True
    window._emit_ack(60)

    window._flush_pending_acks()

    assert emitted_acks == [61, 62]


def test_handle_print_job_success_failure_and_duplicate_contracts(window, monkeypatch):
    printed = []
    acked = []
    logs = []
    window.ack_sig.connect(acked.append)
    window.log_sig.connect(logs.append)

    def print_success(printer, zpl, cb):
        printed.append((printer, zpl))
        cb(True, "printed")

    monkeypatch.setattr(main_module, "_print_zpl", print_success)

    window._handle_print_job(
        {"job_id": 20, "invoice": "INV-20", "pcs": 3, "data": "^XA"}
    )
    assert printed == [("Printer A", "^XA")]
    assert 20 in window._seen_jobs
    assert 20 not in window._inflight
    assert acked == [20]
    assert window._is_job_acked(20) is False

    window._handle_print_job(
        {"job_id": 20, "invoice": "INV-20", "pcs": 3, "data": "^XA"}
    )
    assert logs[-1] == "Job 20 ignored (already printed, ack pending)"
    assert acked == [20, 20]

    window.sio.connected = True
    window._emit_ack(20)
    window._handle_print_job(
        {"job_id": 20, "invoice": "INV-20", "pcs": 3, "data": "^XA"}
    )
    assert logs[-1] == "Job 20 ignored (already printed)"

    window._inflight.add(21)
    window._handle_print_job(
        {"job_id": 21, "invoice": "INV-21", "pcs": 1, "data": "^XA"}
    )
    assert logs[-1] == "Job 21 ignored (already in-flight)"

    def print_failure(printer, zpl, cb):
        cb(False, "offline")

    monkeypatch.setattr(main_module, "_print_zpl", print_failure)
    window._handle_print_job(
        {"job_id": 22, "invoice": "INV-22", "pcs": 1, "data": "^XA"}
    )
    assert 22 not in window._inflight
    assert 22 not in window._seen_jobs
    with sqlite3.connect(window._db_path) as con:
        assert (
            con.execute("SELECT COUNT(*) FROM prints WHERE job_id=22").fetchone()[0]
            == 0
        )


def test_handle_print_job_suppresses_recent_unlabeled_duplicates(window, monkeypatch):
    printed = []

    def print_success(printer, zpl, cb):
        printed.append((printer, zpl))
        cb(True, "printed")

    monkeypatch.setattr(main_module, "_print_zpl", print_success)
    payload = {"invoice": "INV-X", "pcs": 1, "data": "^XA"}

    window._handle_print_job(payload)
    window._handle_print_job(payload)

    assert printed == [("Printer A", "^XA")]
    with sqlite3.connect(window._db_path) as con:
        assert (
            con.execute("SELECT COUNT(*) FROM prints WHERE invoice='INV-X'").fetchone()[
                0
            ]
            == 1
        )


def test_ack_pending_and_emit_failure_do_not_mark_job_acked(window):
    logs = []
    window.log_sig.connect(logs.append)
    window._store_print(30, "INV-30", 1, "^XA")

    window.sio.connected = False
    window._emit_ack(30)
    assert logs[-1] == "Ack pending for job 30"
    assert window._is_job_acked(30) is False

    window.sio.connected = True
    window.sio.emit = MagicMock(side_effect=RuntimeError("server down"))
    window._emit_ack(30)
    assert logs[-1] == "Ack error for job 30: server down"
    assert window._is_job_acked(30) is False


def test_open_options_reloads_preferences_after_accept(window, monkeypatch):
    class AcceptedOptions:
        def __init__(self, parent):
            self.parent = parent

        def exec(self):
            return True

    reconnected = []
    window._reconnect.connect(lambda: reconnected.append("reconnect"))
    window.api_key = "old"
    window.server_url = "old"
    window.printer_name = "old"
    main_module.S.values.update(
        {
            "api_key": "new",
            "server_url": "https://new.test",
            "printer_name": "New Printer",
        }
    )
    monkeypatch.setattr(main_module, "OptionsDialog", AcceptedOptions)

    window._open_options()

    assert (window.api_key, window.server_url, window.printer_name) == (
        "new",
        "https://new.test",
        "New Printer",
    )
    assert reconnected == ["reconnect"]
