"""Tests for MainWindow: actions, enabled states, title, window state, commit and quit flows."""

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QDialog

from src.qt import main_window as mw
from src.qt.actions import ActionRegistry
from src.qt.dialogs import messages
from src.qt.main_window import MainWindow
from src.qt.session import Session, SessionState
from tests.unit.qt.conftest import stage


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


@pytest.fixture
def no_settings_dialog(monkeypatch):
    opened = []
    monkeypatch.setattr(mw.SettingsDialog, "exec", lambda self: opened.append(self.reason_label.text()) or 0)
    return opened


@pytest.fixture
def window(qtbot, session, settings, no_settings_dialog):
    w = MainWindow(session, settings)
    qtbot.addWidget(w)
    w._quitting = True  # let qtbot close it without prompts
    yield w


def test_no_duplicate_shortcuts_and_names(qtbot):
    from PySide6.QtWidgets import QWidget

    host = QWidget()
    qtbot.addWidget(host)
    registry = ActionRegistry(host)
    seen = {}
    for key, action in registry.actions.items():
        assert action.text() and action.toolTip(), key
        for shortcut in action.shortcuts():
            text = shortcut.toString()
            assert text not in seen, f"{text} used by {seen.get(text)} and {key}"
            seen[text] = key
    rows = registry.shortcut_rows()
    assert any(menu == "Edit" and command == "Undo" and keys != "—" for menu, command, keys in rows)
    assert "dev_stage_sample" not in registry.actions  # removed in step 3


def test_discard_has_no_menu_item_or_shortcut(qtbot):
    """Only the status bar Discard button can discard staged changes (user decision 2026-10-01)."""
    from PySide6.QtWidgets import QWidget

    host = QWidget()
    qtbot.addWidget(host)
    registry = ActionRegistry(host)
    assert "discard" not in registry.actions
    assert all("Discard" not in command for _menu, command, _keys in registry.shortcut_rows())


def test_escape_does_not_discard(qtbot):
    from PySide6.QtWidgets import QWidget

    host = QWidget()
    qtbot.addWidget(host)
    registry = ActionRegistry(host)
    assert all("Esc" not in s.toString() for a in registry.actions.values() for s in a.shortcuts())


def test_enabled_states_when_ready(window, session):
    r = window.registry
    assert r["refresh"].isEnabled()
    assert not r["commit"].isEnabled() and not window.status.discard_button.isEnabled() and not r["undo"].isEnabled()
    assert r["export_permissions"].isEnabled()
    assert r["jump"].isEnabled() and r["mode_object"].isEnabled()
    stage(session, 2)
    assert r["commit"].isEnabled() and window.status.discard_button.isEnabled() and r["undo"].isEnabled()
    assert window.status.commit_button.text() == "Commit 2"
    assert window.status.pending_pill.text() == "2 pending"
    assert window.isWindowModified()
    assert window.windowTitle() == "Bifrost — FinanceDW[*]"


def test_enabled_states_offline(window, session):
    stage(session, 1)
    session.disconnect()
    r = window.registry
    assert not r["refresh"].isEnabled() and not r["commit"].isEnabled()
    assert window.status.discard_button.isEnabled()  # can still throw changes away offline
    assert window.status.reconnect_button.isVisibleTo(window)
    assert window.status.connection_pill.kind == "offline"


def test_enabled_states_needs_settings(qtbot, env, settings, no_settings_dialog):
    env.config_error = "Configuration file not found"
    s = Session()
    w = MainWindow(s, settings)
    qtbot.addWidget(w)
    w._quitting = True
    s.start()
    qtbot.waitUntil(lambda: bool(no_settings_dialog), timeout=2000)
    assert no_settings_dialog[0].endswith("Configuration file not found")
    assert not w.registry["export_permissions"].isEnabled()
    assert not w.registry["refresh"].isEnabled()
    assert w.matrix_view.stack.currentWidget() is w.matrix_view.placeholder
    assert w.matrix_view.placeholder.stack.currentWidget() is w.matrix_view.placeholder.setup_page
    assert not w.registry["jump"].isEnabled()
    s.worker.shutdown(1000)


def test_window_state_round_trip(qtbot, session, settings, no_settings_dialog):
    first = MainWindow(session, settings)
    qtbot.addWidget(first)
    first._quitting = True
    first.resize(1111, 777)
    first.tabs.setCurrentIndex(mw.TAB_AUDIT)
    first.show()
    first.registry["toggle_pending"].setChecked(True)
    first.save_window_state()
    second = MainWindow(session, settings)
    qtbot.addWidget(second)
    second._quitting = True
    assert second.tabs.currentIndex() == mw.TAB_AUDIT
    assert not settings.value("window/geometry").isEmpty()  # size is clamped to the offscreen screen
    assert second.registry["toggle_pending"].isChecked() == second.tray.isVisibleTo(second)


def test_tray_toggle_syncs_with_action(qtbot, window):
    window.show()
    window.status.pending_pill.click()
    assert window.tray.isVisible()
    assert window.registry["toggle_pending"].isChecked()
    window.tray.close()
    assert not window.registry["toggle_pending"].isChecked()


def test_commit_preview_accept_commits(qtbot, window, session, env, monkeypatch):
    monkeypatch.setattr(mw.CommitPreviewDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    shown = []
    monkeypatch.setattr(mw.CommitSuccessDialog, "exec", lambda self: shown.append(1) or 0)
    stage(session, 5)
    with qtbot.waitSignal(session.commitFinished, timeout=3000):
        window.status.commit_button.click()
    assert len(env.conn.statements("GRANT")) == 5
    assert shown == [1]


def test_commit_preview_review_opens_tray(qtbot, window, session, env, monkeypatch):
    def review(self):
        self.review_requested = True
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(mw.CommitPreviewDialog, "exec", review)
    window.show()
    stage(session, 5)
    window.status.review_button.click()
    assert window.tray.isVisible()
    assert env.conn.statements("GRANT") == []


def test_partial_failure_discard_reverts_only_failed(qtbot, window, session, env, monkeypatch):
    stage(session, 3)
    first = session.matrix.prepare_commit().changes[0]
    target = f"GRANT {first.permission_type.value} ON [{first.schema_name}].[{first.object_name}]"
    env.conn.fail_on = lambda sql: sql.startswith(target)

    def choose_discard(self):
        self.choice = "discard_failed"
        return 1

    monkeypatch.setattr(mw.CommitPreviewDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(mw.PartialFailureDialog, "exec", choose_discard)
    with qtbot.waitSignal(session.commitFinished, timeout=3000):
        session.request_commit()
    assert session.staged_count == 0
    assert len(env.conn.statements("GRANT")) == 3  # 1 failed + 2 applied


def test_discard_confirmation(qtbot, window, session, monkeypatch):
    stage(session, 6)
    monkeypatch.setattr(messages, "confirm_discard", lambda parent, count: False)
    window.status.discard_button.click()
    assert session.staged_count == 6
    monkeypatch.setattr(messages, "confirm_discard", lambda parent, count: True)
    window.status.discard_button.click()
    assert session.staged_count == 0


class TestQuit:
    def make(self, qtbot, session, settings):
        w = MainWindow(session, settings)
        qtbot.addWidget(w)
        w.show()
        return w

    def test_cancel_keeps_window_open(self, qtbot, session, settings, no_settings_dialog, monkeypatch):
        w = self.make(qtbot, session, settings)
        stage(session, 2)
        monkeypatch.setattr(messages, "confirm_quit", lambda parent, count: "cancel")
        assert not w.close()
        assert w.isVisible()
        w._quitting = True

    def test_quit_without_committing_closes(self, qtbot, session, settings, no_settings_dialog, monkeypatch, env):
        w = self.make(qtbot, session, settings)
        stage(session, 2)
        monkeypatch.setattr(messages, "confirm_quit", lambda parent, count: "quit")
        assert w.close()
        assert env.tag_saves == 1
        assert env.conn.statements("GRANT") == []

    def test_commit_and_quit_closes_on_success(self, qtbot, session, settings, no_settings_dialog, monkeypatch, env):
        w = self.make(qtbot, session, settings)
        stage(session, 2)
        monkeypatch.setattr(messages, "confirm_quit", lambda parent, count: "commit")
        assert not w.close()  # waits for the commit
        qtbot.waitUntil(lambda: not w.isVisible(), timeout=3000)
        assert len(env.conn.statements("GRANT")) == 2

    def test_commit_and_quit_stays_open_on_failure(self, qtbot, session, settings, no_settings_dialog, monkeypatch, env):
        w = self.make(qtbot, session, settings)
        stage(session, 2)
        env.conn.fail_on = lambda sql: sql.strip().startswith("INSERT INTO")
        errors = []
        monkeypatch.setattr(messages, "confirm_quit", lambda parent, count: "commit")
        monkeypatch.setattr(messages, "show_error", lambda *args, **kwargs: errors.append(args[1]))
        w.close()
        qtbot.waitUntil(lambda: bool(errors), timeout=3000)
        assert w.isVisible()
        assert session.staged_count == 2
        w._quitting = True


def test_announce_does_not_crash(window):
    window.announce("3 changes staged")


def test_matrix_view_shows_split_view_when_loaded(window, session):
    assert window.matrix_view.stack.currentWidget() is window.matrix_view.content


def test_database_summary(window, session, monkeypatch):
    shown = []
    monkeypatch.setattr(messages, "show_info", lambda parent, title, text, details="": shown.append(text))
    stage(session, 2)
    window.registry["db_summary"].trigger()
    assert "Principals: 3" in shown[0]
    assert "Staged changes: 2" in shown[0]


def test_reveal_switches_to_matrix_tab(window, session):
    window.tabs.setCurrentIndex(mw.TAB_AUDIT)
    stage(session, 1)
    session.reveal(session.matrix.get_staged_changes()[0])
    assert window.tabs.currentIndex() == mw.TAB_MATRIX


def test_state_pill_text(window, session):
    assert window.status.connection_pill.text() == "● sql01/FinanceDW as CORP\\admin"
    assert session.state is SessionState.READY
