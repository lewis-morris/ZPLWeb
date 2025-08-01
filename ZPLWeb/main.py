"""GUI application for printing ZPL labels received via socket.io."""
import sqlite3
import sys
import datetime as dt
from pathlib import Path
from threading import Thread

from PySide6.QtCore import QEventLoop, QSettings, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QListWidget,
    QMainWindow,
    QSizePolicy,
    QSplitter,
    QStyle,
    QTextEdit,
    QLabel,
    QDialog,
    QToolButton,
    QVBoxLayout,
    QLineEdit,
    QPushButton,
    QMessageBox,
    QSystemTrayIcon,
    QMenu,
    QWidget,
)

import socketio
from appdirs import user_data_dir

from ZPLWeb.utils import resource_path
from typing import Callable, Any

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
SERVER_URL = "https://colemanbros.co.uk"
DEFAULT_PRINTER = r"\\office-02\\ZPL500"
SETTINGS_SCOPE = ("ColemanAgent", "PrintAgent")

# Helper to load / save settings
S = QSettings(*SETTINGS_SCOPE)

# -----------------------------------------------------------------------------
# Printing util (thread‑safe)
# -----------------------------------------------------------------------------

import logging, queue

def wait_ms(ms: int):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()    # blocks here, but UI remains responsive



def _print_zpl(
    printer_name: str, zpl_string: str, cb: Callable[[bool, str], Any]
) -> None:
    """Send ZPL to the given printer.

    The function executes in a background thread and notifies the caller
    through ``cb`` when finished.

    Args:
        printer_name: Target printer queue name.
        zpl_string: Raw ZPL command string.
        cb: Callback receiving ``(success, message)``.
    """
    if not win32print:
        return cb(True, f"Skipped printed via {printer_name}")

    try:
        handle = win32print.OpenPrinter(printer_name)
        win32print.StartDocPrinter(handle, 1, ("ZPL", None, "RAW"))
        win32print.StartPagePrinter(handle)
        win32print.WritePrinter(handle, zpl_string.encode("utf-8"))
        win32print.EndPagePrinter(handle)
        win32print.EndDocPrinter(handle)
        win32print.ClosePrinter(handle)
        cb(True, f"Printed via {printer_name}")
    except Exception as exc:  # pylint: disable=broad-except

        return cb(False, f"Print error: {exc}")





# -----------------------------------------------------------------------------
# Options dialog
# -----------------------------------------------------------------------------
class OptionsDialog(QDialog):
    """Dialog for editing API key, printer and server settings."""

    def __init__(self, parent: QDialog | None = None) -> None:
        """Set up the dialog widgets with existing preferences."""
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
        self.setFixedWidth(500)
    # ------------------------------------------------------------------
    def _save(self) -> None:
        """Persist the entered values back to :class:`QSettings`."""

        api_key = self.api_edit.text().strip()
        prn = self.prn_edit.text().strip()
        svr = self.server_edit.text().strip()

        if not api_key or not prn:
            QMessageBox.warning(self, "Options", "Both fields are required")
            return

        S.setValue("api_key", api_key)
        S.setValue("printer_name", prn)
        S.setValue("server_url", svr)  # <── consistent key
        self.accept()

class TestPrintDialog(QDialog):
    """Light-weight dialog to paste ZPL and send a one-off test print."""

    def __init__(self, parent: QDialog | None = None, printer_name: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Test ZPL Print")
        self.printer_name = printer_name

        self.text_edit = QTextEdit(self)
        self.text_edit.setAcceptRichText(False)
        self.text_edit.setPlaceholderText("Paste or type raw ZPL here…")

        self.status_lbl = QLabel(self)

        send_btn = QPushButton("Print", self)
        send_btn.clicked.connect(self._do_print)

        lay = QVBoxLayout(self)
        lay.addWidget(self.text_edit)
        lay.addWidget(send_btn)
        lay.addWidget(self.status_lbl)
        self.setFixedWidth(500)

    # ------------------------------------------------------------------
    def _do_print(self) -> None:
        zpl = self.text_edit.toPlainText().strip()
        if not zpl:
            QMessageBox.warning(self, "Test ZPL Print", "Please enter some ZPL.")
            return

        def cb(ok: bool, msg: str) -> None:
            def show_result() -> None:             # runs later in GUI thread
                self.status_lbl.setText(msg)
                parent = self if ok else self.parent()
                QMessageBox.information(parent, "Test ZPL Print", msg)

            QTimer.singleShot(0, show_result)      # hop to GUI thread

        # run the actual I/O in a worker thread
        Thread(target=_print_zpl, args=(self.printer_name, zpl, cb), daemon=True).start()

# -----------------------------------------------------------------------------
# Main Qt window
# -----------------------------------------------------------------------------
class MainWindow(QMainWindow):
    log_sig = Signal(str)
    status_sig = Signal(str)
    ack_sig = Signal(int)  # job_id to ack
    _reconnect = Signal()
    gui_connected   = Signal()
    gui_disconnected = Signal()
    add_print_sig = Signal(str, int, str)  # invoice, copies, timestamp

    # .........................................................................
    def __init__(self) -> None:
        """Initialize the main window and connect to the socket server."""
        super().__init__()
        self.setWindowTitle("Coleman Print Agent")
        self.resize(650, 450)

        self.splitter = QSplitter(Qt.Horizontal, self)
        self.list = QListWidget()
        self.out = QTextEdit(readOnly=True)

        self.splitter.addWidget(self.list)
        self.splitter.addWidget(self.out)

        # 25% / 75% resize ratio
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 3)

        self.setCentralWidget(self.splitter)

        # initial sizes once layout is settled
        QTimer.singleShot(0, lambda: self.splitter.setSizes([
            int(self.splitter.width() * 0.25),
            int(self.splitter.width() * 0.75),
        ]))

        self.reprint_btn = QToolButton(self)
        self.reprint_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.reprint_btn.setToolTip("Re-print selected invoice")
        self.reprint_btn.clicked.connect(self._reprint_selected)

        self.reprint_label = QLabel("")
        self.reprint_label.setStyleSheet("font-weight:bold; margin:5px;")


        self.stat = QLabel("Disconnected")
        self.stat.setStyleSheet("font-weight:bold; margin:5px;")

        # manual reconnect button
        self.re_btn = QToolButton(self)
        self.re_btn.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self.re_btn.setToolTip("Reconnect to server now")
        self.re_btn.clicked.connect(self._manual_reconnect)
        self.re_btn.setEnabled(True)        # enabled while we are disconnected

        # left-aligned: reprint button
        self.statusBar().addWidget(self.reprint_btn)
        self.statusBar().addWidget(self.reprint_label)

        # spacer to push the rest to the right
        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.statusBar().addWidget(spacer)

        # right-aligned: status label and reconnect
        self.statusBar().addPermanentWidget(self.stat)
        self.statusBar().addPermanentWidget(self.re_btn)


        self._seen_jobs: set[int] = set()   # de-dupe tracker
        self._init_db()                     # create DB + load history

        self._load_history()     # ← add this line

        self._build_menu()
        self._build_tray()

        # -- data --------------------------------------------------------------
        self._load_prefs()

        # -- socket ------------------------------------------------------------
        self.sio = socketio.Client(  # auto reconnect off (we handle it)
            reconnection=False,
            logger=True,            # <── add
            engineio_logger=True,   # <── add
        )
        self._register_handlers()
        QTimer.singleShot(0, self._connect_socket)

        # -- signals connect ---------------------------------------------------
        self.log_sig.connect(self._log, Qt.QueuedConnection)
        self.status_sig.connect(self.stat.setText, Qt.QueuedConnection)
        self.gui_connected.connect(self._on_gui_connected, Qt.QueuedConnection)
        self.gui_disconnected.connect(self._on_gui_disconnected, Qt.QueuedConnection)
        self.ack_sig.connect(self._emit_ack, Qt.QueuedConnection)
        self.add_print_sig.connect(self._add_print_to_list, Qt.QueuedConnection)

        # label de dupe
        from threading import Lock

        self._job_lock = Lock()
        self._inflight: set[int] = set()  # jobs currently being printed
        self._recent_fingerprints: dict[str, float] = {}  # fingerprint -> last seen timestamp (for job_id-less jobs)
        self._fingerprint_ttl = 60  # seconds window to suppress duplicates for unlabeled jobs

    def _load_history(self) -> None:
        """Populate the left-hand list from the existing DB rows."""
        self.list.clear()                         # start with a clean slate
        with sqlite3.connect(self._db_path) as con:
            for invoice, pcs, ts in con.execute(
                "SELECT invoice, pcs, tstamp FROM prints ORDER BY id DESC"
            ):
                self._add_print_to_list(invoice, pcs, ts)

    def _add_print_to_list(self, invoice: str, pcs: int, ts: str) -> None:
        self.list.insertItem(0, f"{invoice}  x{pcs or 1}")

    def _reprint_selected(self) -> None:
        row = self.list.currentRow()
        if row < 0:
            return
        invoice_line = self.list.item(row).text()
        invoice = invoice_line.split("  x")[0].strip()

        with sqlite3.connect(self._db_path) as con:
            row = con.execute("SELECT zpl, copies FROM prints WHERE invoice=? ORDER BY id DESC LIMIT 1", (invoice,)).fetchone()

        if not row:
            QMessageBox.warning(self, "Re-print", "ZPL not found for that invoice")
            return

        zpl, copies = row
        self.log_sig.emit(f"Re-printing {invoice} x{copies or 1}…")
        Thread(target=_print_zpl, args=(self.printer_name, zpl, lambda *_: None), daemon=True).start()

    def _init_db(self) -> None:
        """Create the SQLite DB (if missing) and load printed job-ids."""
        data_dir = Path(user_data_dir("ColemanAgent", "Coleman"))
        data_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = data_dir / "prints.sqlite"

        with sqlite3.connect(self._db_path) as con:
            con.execute(
                """CREATE TABLE IF NOT EXISTS prints (
                       id       INTEGER PRIMARY KEY AUTOINCREMENT,
                       job_id   INTEGER,
                       invoice  TEXT,
                       pcs   INTEGER,
                       zpl      TEXT,
                       tstamp   TEXT
                   )"""
            )
            # pre-load IDs so we don’t re-print across restarts
            self._seen_jobs.update(
                row[0] for row in con.execute("SELECT DISTINCT job_id FROM prints WHERE job_id IS NOT NULL")
            )

    # ------------------------------------------------------------------
    def _open_test_print(self) -> None:
        """Menu handler: open the raw-ZPL test-print dialog."""
        TestPrintDialog(self, self.printer_name).exec()

    @Slot()
    def _on_gui_connected(self):
        self.re_btn.setEnabled(False)
        self.status_sig.emit("Connected")

    @Slot()
    def _on_gui_disconnected(self):
        self.re_btn.setEnabled(True)
        self.status_sig.emit("Disconnected")

    # ─── still inside MainWindow class (anywhere convenient) ─────────────────────
    def _manual_reconnect(self) -> None:
        """User‑initiated reconnect via the reload button."""
        self._connect_socket()

    # ===================================================================== MENU
    def _build_menu(self) -> None:
        mb = self.menuBar()

        file_m = mb.addMenu("File")
        file_m.addAction("Exit", self.close)

        edit_m = mb.addMenu("Edit")
        edit_m.addAction("Options", self._open_options)

        # NEW —–––––––––––––––––––––––––––––––––––––
        tools_m = mb.addMenu("Tools")
        tools_m.addAction("Test ZPL Print", self._open_test_print)

    # ==================================================================== TRAY
    def _build_tray(self) -> None:
        """Create a system tray icon if supported."""
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
    def _load_prefs(self) -> None:
        """Load persisted preferences."""
        self.api_key      = S.value("api_key", "").strip()
        self.printer_name = S.value("printer_name", DEFAULT_PRINTER)
        self.server_url   = S.value("server_url", SERVER_URL).strip()

        if not self.api_key:
            self.status_sig.emit("No API key")

    # ============================================================ SOCKET HANDL.
    def _register_handlers(self) -> None:
        """Register socket.io event handlers."""

        @self.sio.event
        def connect():
            print("SocketIO: connected, emitting api_key explicitly")
            self.sio.emit('auth', {'api_key': self.api_key})  # ensure your server expects this event
            self.log_sig.emit("Connected")
            self.gui_connected.emit()

        @self.sio.event
        def disconnect():
            print("SocketIO: disconnect event fired")
            self.log_sig.emit("Disconnected")
            self.gui_disconnected.emit()

        @self.sio.event
        def connect_error(err):
            print(f"SocketIO: connect_error fired: {err}")
            self.log_sig.emit(f"Connect failed: {err}")
            if not self.sio.connected:
                self.status_sig.emit("Disconnected")
                self.re_btn.setEnabled(True)

        @self.sio.on("status")
        def on_status(data):
            print(f"SocketIO: status event fired with data: {data}")
            self.log_sig.emit(f"Server status: {data.get('msg')}")

        @self.sio.on("print_label")
        def on_print_label(data):
            print(f"SocketIO: print_label event fired with data: {data}")
            Thread(target=self._handle_print_job, args=(data,), daemon=True).start()

    # .........................................................................
    def _connect_socket(self) -> None:
        """Connect/reconnect to socket.io with logging."""
        if not self.api_key or not self.server_url:
            self.status_sig.emit("Missing API key or URL")
            return

        if self.sio.connected:
            self.sio.disconnect()

        try:
            self.sio.connect(
                self.server_url,
                transports=["websocket"],
                auth={"api_key": self.api_key},
            )
            print("Attempting socket.io connection...")
        except Exception as exc:
            self.log_sig.emit(f"Connection error: {exc}")
            self.status_sig.emit("Disconnected")

    # .........................................................................
    def _handle_print_job(self, data: dict) -> None:
        job_id = data.get("job_id")
        inv = data.get("invoice")
        pcs = data.get("pcs")
        zpl = data.get("data")

        # Dedupe / reserve before doing any work
        with self._job_lock:
            if job_id:
                if job_id in self._seen_jobs or job_id in self._inflight:
                    self.log_sig.emit(f"Job {job_id} ignored (already printed or in-flight)")
                    return
                self._inflight.add(job_id)
            else:
                # fingerprint-based suppression for jobs without ID
                fp = self._make_fingerprint(inv, pcs, zpl)
                now = dt.datetime.now().timestamp()
                # cleanup stale fingerprints
                for key, ts in list(self._recent_fingerprints.items()):
                    if now - ts > self._fingerprint_ttl:
                        del self._recent_fingerprints[key]
                last = self._recent_fingerprints.get(fp)
                if last and now - last < self._fingerprint_ttl:
                    self.log_sig.emit(f"Ignoring duplicate unlabeled job for invoice {inv}")
                    return
                self._recent_fingerprints[fp] = now

        def cb(ok: bool, msg: str) -> None:
            self.log_sig.emit(msg)
            if ok:
                with self._job_lock:
                    if job_id:
                        self._inflight.discard(job_id)
                        self._seen_jobs.add(job_id)
                # persist to DB + update GUI list
                self._store_print(job_id, inv, pcs, zpl)
                if job_id:
                    self.ack_sig.emit(job_id)
            else:
                # on failure, release reservation so it can be retried
                with self._job_lock:
                    if job_id:
                        self._inflight.discard(job_id)

        _print_zpl(self.printer_name, zpl, cb)

    # .........................................................................
    def _emit_ack(self, job_id: int) -> None:
        """Acknowledge a completed print job back to the server."""
        if self.sio.connected and job_id:
            self.sio.emit("print_label_ack", {"job_id": job_id, "status": "printed"})

    def _store_print(self, job_id, invoice, pcs, zpl) -> None:
        tstamp = dt.datetime.now().isoformat(timespec="seconds")
        with sqlite3.connect(self._db_path) as con:
            con.execute(
                "INSERT INTO prints (job_id, invoice, pcs, zpl, tstamp) VALUES (?,?,?,?,?)",
                (job_id, invoice, pcs, zpl, tstamp),
            )
        # safely update GUI from any thread:
        self.add_print_sig.emit(invoice, pcs or 1, tstamp)

    # ================================================================ GUI UTILS
    def _open_options(self) -> None:
        """Open the options dialog and reload preferences on accept."""
        dlg = OptionsDialog(self)
        if dlg.exec():
            self._load_prefs()
            self._reconnect.emit()

    def _log(self, text: str) -> None:
        """Append a timestamped line to the output widget."""
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
