"""Tests for app setup: logging, the stall watchdog and never logging credentials."""

import logging
import time

from PySide6.QtCore import QTimer

from src.db.connection import DatabaseConnectionError
from src.qt import app as app_module
from src.qt.session import Session, SessionState


def test_log_file_is_under_config_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "get_config_directory", lambda: tmp_path)
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        path = app_module.configure_logging()
        logging.getLogger("bifrost.test").info("hello from the test")
        for handler in root.handlers:
            handler.flush()
        assert path == tmp_path / "logs" / "bifrost.log"
        assert "hello from the test" in path.read_text(encoding="utf-8")
    finally:
        for handler in list(root.handlers):
            if handler not in before:
                root.removeHandler(handler)
                handler.close()


def test_stall_watchdog_counts_blocked_ui(qtbot):
    watchdog = app_module.StallWatchdog()
    QTimer.singleShot(20, lambda: time.sleep(0.3))
    qtbot.waitUntil(lambda: watchdog.stalls >= 1, timeout=3000)


def test_dev_password_never_logged(qtbot, env, monkeypatch, caplog):
    secret = "Bf1!SuperSecretPassword123"
    monkeypatch.setenv("BIFROST_DEV_SQL_PASSWORD", secret)
    env.connect_error = DatabaseConnectionError("Authentication failed for bifrost_admin")
    caplog.set_level(logging.DEBUG)
    s = Session()
    s.start()
    qtbot.waitUntil(lambda: s.state is SessionState.FAILED, timeout=2000)
    assert secret not in caplog.text
    s.worker.shutdown(1000)
