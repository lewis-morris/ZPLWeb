import sys
import json
import datetime as dt
from threading import Thread
from functools import partial

from PySide6.QtCore import Qt, QSettings, QTimer, Signal, QObject
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QStyle,
    QTextEdit,
    QLabel,
    QDialog,
    QVBoxLayout,
    QLineEdit,
    QPushButton,
    QMessageBox,
    QSystemTrayIcon,
    QMenu,
)

import socketio

from ZPLWeb.utils import resource_path

# ──────────────────────────────────────────────────────────────────────────────
# Platform‑specific printer import
# ──────────────────────────────────────────────────────────────────────────────
if sys.platform.startswith("win"):
    import win32print
else:
    win32print = None  # noqa:  allow the file to import on non‑Windows hosts

# ──────────────────────────────────────────────────────────────────────────────
# Constants & defaults
# ──────────────────────────────────────────────────────────────────────────────
SERVER_URL = "http://192.168.0.7:5006"
DEFAULT_PRINTER = r"\\office-02\\ZPL500"
SETTINGS_SCOPE = ("ColemanAgent", "PrintAgent")

# Helper to load / save settings
S = QSettings(*SETTINGS_SCOPE)

# -----------------------------------------------------------------------------
# Printing util (thread‑safe)
# -----------------------------------------------------------------------------

def _print_zpl(printer_name: str, zpl_string: str, cb):
    """Run in background thread; calls back with (success, message)."""
    if not win32print:
        return cb(False, "win32print not available on this OS")

    try:
        handle = win32print.OpenPrinter(printer_name)
        job_id = win32print.StartDocPrinter(handle, 1, ("ZPL", None, "RAW"))
        win32print.StartPagePrinter(handle)
        win32print.WritePrinter(handle, zpl_string.encode("utf-8"))
        win32print.EndPagePrinter(handle)
        win32print.EndDocPrinter(handle)
        win32print.ClosePrinter(handle)
        cb(True, f"Printed via {printer_name}")
    except Exception as exc:  # pylint: disable=broad-except
        cb(False, f"Print error: {exc}")

# -----------------------------------------------------------------------------
# Options dialog
# -----------------------------------------------------------------------------
class OptionsDialog(QDialog):
    """Simple dialog to edit API key & printer name."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Options")

        self.api_edit = QLineEdit(self)
        self.api_edit.setPlaceholderText("API key")
        self.api_edit.setText(S.value("api_key", ""))

        self.prn_edit = QLineEdit(self)
        self.prn_edit.setPlaceholderText("Printer name, e.g. \\host\\queue")
        self.prn_edit.setText(S.value("printer_name", DEFAULT_PRINTER))

        self.server_edit = QLineEdit(self)
        self.server_edit.setPlaceholderText("Server URL")
        self.server_edit.setText(S.value("server_url", SERVER_URL))

        save_btn = QPushButton("Save", self)
        save_btn.clicked.connect(self._save)

        lay = QVBoxLayout(self)
        lay.addWidget(self.api_edit)
        lay.addWidget(self.prn_edit)
        lay.addWidget(self.server_edit)
        lay.addWidget(save_btn)

    # ------------------------------------------------------------------
    def _save(self):
        api_key = self.api_edit.text().strip()
        prn     = self.prn_edit.text().strip()
        svr = self.server_edit.text().strip()

        if not api_key or not prn:
            QMessageBox.warning(self, "Options", "Both fields are required")
            return

        S.setValue("api_key", api_key)
        S.setValue("printer_name", prn)
        S.setValue("server_url", svr)          # <── consistent key
        self.accept()

# -----------------------------------------------------------------------------
# Main Qt window
# -----------------------------------------------------------------------------
class MainWindow(QMainWindow):
    log_sig     = Signal(str)
    status_sig  = Signal(str)
    ack_sig     = Signal(int)            # job_id to ack
    _reconnect  = Signal()

    # .........................................................................
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Coleman Print Agent")
        self.resize(650, 450)

        # -- widgets -----------------------------------------------------------
        self.out = QTextEdit(self, readOnly=True)
        self.setCentralWidget(self.out)

        self.stat = QLabel("Disconnected")
        self.stat.setStyleSheet("font-weight:bold; margin:5px;")
        self.statusBar().addPermanentWidget(self.stat)

        self._build_menu()
        self._build_tray()

        # -- data --------------------------------------------------------------
        self._load_prefs()

        # -- timers ------------------------------------------------------------
        self.retry_timer = QTimer(self, interval=10_000, timeout=self._connect_socket)

        # -- socket ------------------------------------------------------------
        self.sio = socketio.Client(  # auto reconnect off (we handle it)
            reconnection=False,
            logger=False,
            engineio_logger=False,
        )
        self._register_handlers()
        self._connect_socket()


        # -- signals connect ---------------------------------------------------
        self.log_sig.connect(self._log)
        self.status_sig.connect(self.stat.setText)
        self.ack_sig.connect(self._emit_ack)
        self._reconnect.connect(self._connect_socket)

    # ===================================================================== MENU
    def _build_menu(self):
        mb = self.menuBar()
        file_m = mb.addMenu("File")
        file_m.addAction("Exit", self.close)
        edit_m = mb.addMenu("Edit")
        edit_m.addAction("Options", self._open_options)

    # ==================================================================== TRAY
    def _build_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray = QSystemTrayIcon(self)
        tray.setIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))
        menu = QMenu()
        menu.addAction("Show", self.showNormal)
        menu.addAction("Exit", self.close)
        tray.setContextMenu(menu)
        tray.activated.connect(lambda *_: self.showNormal())
        tray.show()
        self.tray = tray

    # ================================================================== PREFS
    def _load_prefs(self):
        self.api_key      = S.value("api_key", "")
        self.printer_name = S.value("printer_name", DEFAULT_PRINTER)
        self.server_url   = S.value("server_url", SERVER_URL)   # <── new

        if not self.api_key:
            self.status_sig.emit("No API key")

    # ============================================================ SOCKET HANDL.
    def _register_handlers(self):
        @self.sio.event
        def connect():
            self.log_sig.emit("Connected")
            self.status_sig.emit("Connected")
            self.retry_timer.stop()

        @self.sio.event
        def disconnect():
            self.log_sig.emit("Disconnected")
            self.status_sig.emit("Disconnected")
            self.retry_timer.start()

        @self.sio.event
        def connect_error(err):  # noqa: N802
            self.log_sig.emit(f"Connect failed: {err}")
            self.status_sig.emit("Disconnected")
            self.retry_timer.start()

        @self.sio.on("print_label")
        def on_print_label(data):
            Thread(target=self._handle_print_job, args=(data,), daemon=True).start()

    # .........................................................................
    def _connect_socket(self):
        # nothing to do?
        if not self.api_key or not self.server_url:
            return

        # Already connected to the right place
        if self.sio.connected and self.current_url == self.server_url:
            return

        # If connected to a *different* URL, drop first
        if self.sio.connected:
            self.sio.disconnect()

        try:
            self.current_url = self.server_url         # remember where we dial
            self.sio.connect(self.server_url, auth={"api_key": self.api_key})
        except Exception as exc:  # pylint: disable=broad-except
            self.log_sig.emit(f"Connection error: {exc}")
            self.status_sig.emit("Disconnected")
            self.retry_timer.start()
    # .........................................................................
    def _handle_print_job(self, data: dict):
        job_id = data.get("job_id")
        inv    = data.get("invoice")
        pcs    = data.get("pcs")
        zpl    = data.get("data")

        self.log_sig.emit(f"Printing {inv} x {pcs or '?'} pcs…")

        cb = lambda ok, msg: self.log_sig.emit(msg) or (self.ack_sig.emit(job_id) if ok and job_id else None)
        _print_zpl(self.printer_name, zpl, cb)

    # .........................................................................
    def _emit_ack(self, job_id: int):
        if self.sio.connected and job_id:
            self.sio.emit("print_label_ack", {"job_id": job_id, "status": "printed"})

    # ================================================================ GUI UTILS
    def _open_options(self):
        dlg = OptionsDialog(self)
        if dlg.exec():
            self._load_prefs()
            self._reconnect.emit()

    def _log(self, text):
        ts = dt.datetime.now().strftime("%H:%M:%S")
        self.out.append(f"[{ts}] {text}")

# -----------------------------------------------------------------------------
# main
# -----------------------------------------------------------------------------

def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    icon_file = resource_path("assets/icon.ico")
    icon = QIcon(icon_file)

    app.setWindowIcon(icon)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
