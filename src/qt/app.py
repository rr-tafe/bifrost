"""
Qt application entry point.

main() sets up logging and crash handling, creates the QApplication, shows the
main window, and starts the session once the window has painted.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
import traceback
from logging.handlers import RotatingFileHandler
from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, QElapsedTimer, QSettings, QTimer
from PySide6.QtWidgets import QApplication

from src.qt.gc_guard import UiThreadGarbageCollector
from src.services.config import get_config_directory

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger("bifrost")

STALL_CHECK_MS = 50
STALL_WARN_MS = 100
PROCESS_START = time.perf_counter()


def log_file_path() -> Path:
    """<config dir>/logs/bifrost.log"""
    return get_config_directory() / "logs" / "bifrost.log"


def configure_logging() -> Path:
    """Log to a rotating file (1 MB x 5) and to stderr when run from a terminal."""
    path = log_file_path()
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if os.environ.get("BIFROST_DEBUG") == "1" else logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(threadName)s] %(message)s")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as e:
        print(f"Bifrost: couldn't open log file {path}: {e}", file=sys.stderr)
    if sys.stderr is not None and sys.stderr.isatty():
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        root.addHandler(stream)
    return path


class StallWatchdog:
    """Logs a warning whenever the UI thread is blocked for more than STALL_WARN_MS."""

    def __init__(self) -> None:
        self.stalls = 0
        self._clock = QElapsedTimer()
        self._clock.start()
        self._timer = QTimer()
        self._timer.setInterval(STALL_CHECK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self) -> None:
        late = self._clock.restart() - STALL_CHECK_MS
        if late > STALL_WARN_MS:
            self.stalls += 1
            logger.warning("UI thread was blocked for about %d ms", late)


def install_crash_handlers(log_path: Path) -> None:
    """Log unexpected exceptions and show a dialog; the app keeps running."""

    def report(exc_type, exc, tb) -> None:
        details = "".join(traceback.format_exception(exc_type, exc, tb))
        logger.error("Unhandled exception\n%s", details)
        if QCoreApplication.instance() is None:
            return
        from src.qt.dialogs.messages import show_crash

        message = str(exc) or exc_type.__name__
        QTimer.singleShot(0, lambda: show_crash(QApplication.activeWindow(), message, details, str(log_path)))

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        report(args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = report
    threading.excepthook = thread_hook


def main(argv: list[str] | None = None) -> int:
    """Run the Qt app. Returns the process exit code."""
    log_path = configure_logging()
    install_crash_handlers(log_path)
    logger.info("Bifrost starting")

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("Bifrost")
    app.setOrganizationName("Bifrost")
    gc_guard = UiThreadGarbageCollector(app)  # never collect QObjects on worker threads

    from src.qt.main_window import MainWindow
    from src.qt.session import Session

    session = Session()
    window = MainWindow(session, QSettings(), str(log_path))
    window.apply_theme()
    window.show()
    logger.info("Window shown %.0f ms after start", (time.perf_counter() - PROCESS_START) * 1000)
    watchdog = StallWatchdog()
    QTimer.singleShot(0, session.start)

    code = app.exec()
    gc_guard.stop()
    logger.info("Bifrost exiting (UI stalls over %d ms: %d)", STALL_WARN_MS, watchdog.stalls)
    return code


if __name__ == "__main__":
    sys.exit(main())
