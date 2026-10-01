"""
Bifrost main window.

Menus and toolbar (from the action registry), tabs (Matrix, Audit log), the
pending changes tray and the status bar. The window reacts to Session signals
and opens dialogs; Session does the actual work.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyodbc
from PySide6.QtCore import QByteArray, QSettings, Qt, QTimer
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent, QCloseEvent, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QRadioButton,
    QSizePolicy,
    QStackedWidget,
    QTabBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from src.models.config import Configuration
from src.qt.actions import ActionRegistry
from src.qt.dialogs import messages
from src.qt.dialogs.commit_preview import CommitPreviewDialog
from src.qt.dialogs.commit_result import CommitSuccessDialog, PartialFailureDialog
from src.qt.dialogs.connection_lost import ConnectionLostDialog
from src.qt.dialogs.settings_dialog import SettingsDialog
from src.qt.dialogs.tag_manager import TagManagerDialog
from src.qt.session import Session, SessionState, describe_change
from src.qt.theme import tokens
from src.qt.views.audit_view import AuditView
from src.qt.views.matrix_placeholder import MatrixPlaceholder
from src.qt.widgets.pending_tray import PendingTray
from src.qt.widgets.status_bar import BifrostStatusBar
from src.services.export import get_suggested_filename

if TYPE_CHECKING:
    from src.models.permission import StagedChange
    from src.qt.session import CommitReport
    from src.services.matrix import CommitPlan, RestageReport

TAB_MATRIX = 0
TAB_AUDIT = 1
FULL_EXPORT_WARN_ROWS = 5_000_000
MIN_SIZE = (1024, 680)
DEFAULT_SIZE = (1280, 860)


class ExportOptionsDialog(QDialog):
    """Choose between explicit permissions only and every cell."""

    def __init__(self, explicit_rows: int, all_rows: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export permissions")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("What should the CSV include?", self))
        self.explicit = QRadioButton(f"Only explicit GRANT and DENY permissions ({explicit_rows:,} rows)", self)
        self.everything = QRadioButton(
            f"Every principal, object and permission, including none ({all_rows:,} rows)", self
        )
        self.explicit.setChecked(True)
        layout.addWidget(self.explicit)
        layout.addWidget(self.everything)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self)
        choose = buttons.addButton("Choose file…", QDialogButtonBox.ButtonRole.AcceptRole)
        choose.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def include_none(self) -> bool:
        return self.everything.isChecked()


class MainWindow(QMainWindow):
    """Bifrost main window."""

    def __init__(
        self,
        session: Session,
        settings: QSettings | None = None,
        log_path: str = "",
        include_dev: bool | None = None,
    ) -> None:
        super().__init__()
        self.session = session
        self.settings = settings or QSettings()
        self.log_path = log_path
        self.registry = ActionRegistry(self, include_dev=include_dev)
        self._quitting = False
        self._quit_after_commit = False
        self._connection_dialog_open = False
        self._settings_dialog_open = False
        self._last_test: tuple[Configuration, bool, str] | None = None
        self.tag_manager: TagManagerDialog | None = None

        self.setWindowTitle("Bifrost")
        self.setMinimumSize(*MIN_SIZE)
        self.resize(*DEFAULT_SIZE)

        self._build_menus()
        self._build_toolbar()
        self.matrix_view = MatrixPlaceholder(session, self)
        self.audit_view = AuditView(session, self)
        self.stack = QStackedWidget(self)
        self.stack.addWidget(self.matrix_view)
        self.stack.addWidget(self.audit_view)
        self.setCentralWidget(self.stack)

        self.tray = PendingTray(session, self)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.tray)
        self.tray.hide()
        self.tray.visibilityChanged.connect(self._sync_tray_action)

        self.status = BifrostStatusBar(self)
        self.setStatusBar(self.status)

        self._wire_actions()
        self._wire_status_bar()
        self._wire_session()
        self.matrix_view.openSettings.connect(lambda: self.open_settings())

        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda _scheme: self.apply_theme())
        self._restore_window_state()
        self.update_state()

    # --- Building --------------------------------------------------------------------

    def _build_menus(self) -> None:
        bar = self.menuBar()
        for menu_name in self.registry.menus:
            menu = bar.addMenu(f"&{menu_name}")
            for action in self.registry.menu_entries(menu_name):
                if action is None:
                    menu.addSeparator()
                else:
                    menu.addAction(action)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main", self)
        toolbar.setObjectName("main_toolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.tabs = QTabBar(toolbar)
        self.tabs.addTab("Matrix")
        self.tabs.addTab("Audit log")
        self.tabs.setDrawBase(False)
        self.tabs.setAccessibleName("Views")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        toolbar.addWidget(self.tabs)
        spacer = QWidget(toolbar)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        for key in ("jump", "refresh", "tags", "settings"):
            toolbar.addAction(self.registry[key])
        self.registry["settings"].setIconText("Settings")
        self.registry["jump"].setIconText("Jump to…  Ctrl+K")
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

    def _wire_actions(self) -> None:
        r = self.registry
        s = self.session
        r["settings"].triggered.connect(lambda: self.open_settings())
        r["disconnect"].triggered.connect(s.disconnect)
        r["export_permissions"].triggered.connect(self.export_permissions)
        r["export_audit"].triggered.connect(self.export_audit)
        r["exit"].triggered.connect(self.close)
        r["undo"].triggered.connect(s.undo)
        r["redo"].triggered.connect(s.redo)
        r["commit"].triggered.connect(lambda: s.request_commit())
        r["toggle_pending"].setCheckable(True)
        r["toggle_pending"].toggled.connect(self._set_tray_visible)
        r["view_matrix"].triggered.connect(lambda: self.tabs.setCurrentIndex(TAB_MATRIX))
        r["view_audit"].triggered.connect(lambda: self.tabs.setCurrentIndex(TAB_AUDIT))
        r["refresh"].triggered.connect(s.refresh)
        r["jump"].setEnabled(False)
        r["tags"].triggered.connect(self.open_tags)
        r["shortcuts"].triggered.connect(lambda: messages.ShortcutsDialog(self.registry, self).exec())
        r["about"].triggered.connect(self.show_about)
        if "dev_stage_sample" in r.actions:
            r["dev_stage_sample"].triggered.connect(self.dev_stage_sample)

    def _wire_status_bar(self) -> None:
        st = self.status
        st.connection_pill.clicked.connect(lambda: self.open_settings())
        st.reconnect_button.clicked.connect(self.session.reconnect)
        st.pending_pill.clicked.connect(lambda: self.registry["toggle_pending"].toggle())
        st.undo_button.clicked.connect(self.session.undo)
        st.discard_button.clicked.connect(lambda: self.session.discard_all())
        st.review_button.clicked.connect(lambda: self.session.request_commit(always_preview=True))
        st.commit_button.clicked.connect(lambda: self.session.request_commit())
        st.cancelRequested.connect(self._cancel_running)

    def _wire_session(self) -> None:
        s = self.session
        s.stateChanged.connect(lambda _state: self.update_state())
        s.stagedCountChanged.connect(lambda _count: self.update_state())
        s.undoStateChanged.connect(lambda *_: self.update_state())
        s.dataLoaded.connect(lambda _summary: self.update_state())
        s.statusMessage.connect(self.status.show_status)
        s.busyMessage.connect(self._on_busy)
        s.announce.connect(self.announce)
        s.settingsRequested.connect(lambda reason: QTimer.singleShot(0, lambda: self.open_settings(reason)))
        s.connectionLost.connect(self._on_connection_lost)
        s.commitPreviewRequested.connect(self._on_commit_preview)
        s.commitFinished.connect(self._on_commit_finished)
        s.privilegeDenied.connect(self._on_privilege_denied)
        s.discardConfirmationRequested.connect(self._on_discard_confirmation)
        s.restageReport.connect(self._on_restage_report)
        s.revealRequested.connect(self._on_reveal)

    # --- State -------------------------------------------------------------------------

    def update_state(self) -> None:
        """Refresh enabled states, title and status bar from the session (spec section 8.2)."""
        s = self.session
        r = self.registry
        state = s.state
        staged = s.staged_count
        committing = state is SessionState.COMMITTING

        r["refresh"].setEnabled(s.connected and not s.busy)
        r["commit"].setEnabled(s.can_commit)
        r["undo"].setEnabled(s.can_undo)
        r["redo"].setEnabled(s.can_redo)
        r["export_permissions"].setEnabled(s.matrix is not None)
        r["export_audit"].setEnabled(s.connected)
        r["disconnect"].setEnabled(s.connected)
        if "dev_stage_sample" in r.actions:
            r["dev_stage_sample"].setEnabled(s.can_edit)

        st = self.status
        st.set_staged_count(staged)
        st.commit_button.setEnabled(s.can_commit)
        st.review_button.setEnabled(s.can_commit)
        st.discard_button.setEnabled(staged > 0 and not committing)
        st.undo_button.setEnabled(s.can_undo)

        config = s.config
        target = f"{config.server}/{config.database}" if config else ""
        if state is SessionState.CONNECTING:
            st.connection_pill.set_state("busy", f"Connecting to {target}…")
        elif state in (SessionState.LOADING, SessionState.READY, SessionState.COMMITTING):
            user = f" as {s.current_user}" if s.current_user else ""
            st.connection_pill.set_state("connected", f"{target}{user}")
        elif state is SessionState.OFFLINE:
            st.connection_pill.set_state("offline", f"Offline · {target}")
        elif state is SessionState.FAILED:
            st.connection_pill.set_state("failed", "Not connected")
        else:
            st.connection_pill.set_state("none", "Not connected")
        st.reconnect_button.setVisible(state in (SessionState.OFFLINE, SessionState.FAILED) and config is not None)

        self.setWindowTitle(f"Bifrost — {config.database}[*]" if config and config.database else "Bifrost[*]")
        self.setWindowModified(staged > 0)

    def apply_theme(self) -> None:
        self.status.apply_theme(tokens())

    def announce(self, text: str) -> None:
        """Send text to screen readers (live region equivalent)."""
        QAccessible.updateAccessibility(QAccessibleAnnouncementEvent(self, text))

    def _on_busy(self, text: str, progress) -> None:
        cancellable = self.session.state is SessionState.LOADING or text.startswith("Exporting")
        self.status.show_busy(text, progress, cancellable)

    def _cancel_running(self) -> None:
        if self.session.state is SessionState.LOADING:
            self.session.cancel_load()
        else:
            self.session.cancel_export()

    # --- Tabs and tray -----------------------------------------------------------------

    def _on_tab_changed(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        if index == TAB_AUDIT:
            self.audit_view.ensure_loaded()

    def _set_tray_visible(self, visible: bool) -> None:
        self.tray.setVisible(visible)

    def _sync_tray_action(self, visible: bool) -> None:
        action = self.registry["toggle_pending"]
        if action.isChecked() != visible:
            action.blockSignals(True)
            action.setChecked(visible)
            action.blockSignals(False)

    def _on_reveal(self, _cell) -> None:
        self.tabs.setCurrentIndex(TAB_MATRIX)
        self.status.show_status("Jumping to a cell arrives with the new matrix view.", 5000)

    # --- Dialogs -----------------------------------------------------------------------

    def open_settings(self, reason: str = "") -> None:
        if self._settings_dialog_open:
            return
        self._settings_dialog_open = True
        try:
            dialog = SettingsDialog(self.session, reason, self, self._last_test)
            dialog.exec()
            self._last_test = dialog.last_test
        finally:
            self._settings_dialog_open = False

    def open_tags(self) -> None:
        if self.tag_manager is None:
            self.tag_manager = TagManagerDialog(self.session, self)
        self.tag_manager.show()
        self.tag_manager.raise_()
        self.tag_manager.activateWindow()

    def show_about(self) -> None:
        drivers = ", ".join(d for d in pyodbc.drivers() if "SQL Server" in d) or "none found"
        text = messages.about_text(str(Configuration.get_config_path()), self.log_path or "—", drivers)
        messages.show_about(self, text)

    def _on_connection_lost(self, error: str, staged: int) -> None:
        if self._connection_dialog_open or self._quitting:
            return
        self._connection_dialog_open = True
        try:
            config = self.session.config
            target = f"{config.server}/{config.database}" if config else "the database"
            dialog = ConnectionLostDialog(target, error, staged, self)
            dialog.exec()
        finally:
            self._connection_dialog_open = False
        if dialog.choice == "reconnect":
            self.session.reconnect()
        elif dialog.choice == "settings":
            self.open_settings()

    def _on_discard_confirmation(self, count: int) -> None:
        if messages.confirm_discard(self, count):
            self.session.discard_all(confirmed=True)

    def _on_restage_report(self, report: RestageReport) -> None:
        parts = []
        if report.dropped_missing:
            parts.append(
                f"{len(report.dropped_missing):,} staged changes were removed because the principal "
                "or object no longer exists."
            )
        if report.already_applied:
            parts.append(f"{len(report.already_applied):,} changes were already made by someone else.")
        details = "\n".join(
            [f"Removed: {describe_change(c)}" for c in report.dropped_missing]
            + [f"Already made: {describe_change(c)}" for c in report.already_applied]
        )
        box = QMessageBox(QMessageBox.Icon.Information, "Staged changes updated", " ".join(parts), parent=self)
        box.setDetailedText(details)
        box.setModal(False)
        box.show()

    def _on_privilege_denied(self, changes: list[StagedChange]) -> None:
        shown = changes[:10]
        lines = [
            f"You cannot grant {c.permission_type.value} on {c.schema_name}.{c.object_name} "
            "because you do not have this permission yourself."
            for c in shown
        ]
        if len(changes) > len(shown):
            lines.append(f"…and {len(changes) - len(shown):,} more.")
        messages.show_error(
            self,
            "Grants removed",
            f"{len(changes):,} grants were removed from your staged changes and nothing was committed. "
            "Contact a database owner or sysadmin for these permissions, then commit the rest.",
            "\n".join(lines),
        )
        self._quit_after_commit = False

    # --- Commit ------------------------------------------------------------------------

    def _on_commit_preview(self, plan: CommitPlan) -> None:
        database = self.session.config.database if self.session.config else "the database"
        dialog = CommitPreviewDialog(plan, database, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.session.confirm_commit(plan)
            return
        self._quit_after_commit = False
        if dialog.review_requested:
            self.tabs.setCurrentIndex(TAB_MATRIX)
            self.registry["toggle_pending"].setChecked(True)
            self.tray.table.setFocus()

    def _on_commit_finished(self, report: CommitReport) -> None:
        if self._quit_after_commit:
            self._quit_after_commit = False
            if report.all_succeeded:
                QTimer.singleShot(0, self.close)
                return
        if report.connection_lost:
            return  # the connection-lost dialog explains it
        if report.rolled_back:
            messages.show_error(
                self,
                "Nothing was committed",
                f"{report.error or 'The commit failed.'}\n\nYour staged changes are still here.",
            )
        elif report.failed:
            dialog = PartialFailureDialog(report, self)
            dialog.exec()
            if dialog.choice == "discard_failed":
                self.session.revert_changes([c for c, _ in report.failed], "Discard failed changes")
            elif dialog.choice == "view_audit":
                self.show_audit_since(report)
        elif len(report.succeeded) >= 5 and CommitSuccessDialog(report, self).exec() == QDialog.DialogCode.Accepted:
            self.show_audit_since(report)

    def show_audit_since(self, report: CommitReport) -> None:
        self.tabs.setCurrentIndex(TAB_AUDIT)
        self.audit_view.set_from_datetime(report.started_at)

    # --- Export -------------------------------------------------------------------------

    def export_permissions(self) -> None:
        s = self.session
        if s.matrix is None:
            return
        options = ExportOptionsDialog(s.estimate_export_rows(False), s.estimate_export_rows(True), self)
        if options.exec() != QDialog.DialogCode.Accepted:
            return
        include_none = options.include_none
        rows = s.estimate_export_rows(include_none)
        if include_none and rows > FULL_EXPORT_WARN_ROWS and not messages.confirm_full_export(self, rows):
            return
        database = s.config.database if s.config else "database"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export permissions", get_suggested_filename("permissions", database), "CSV files (*.csv)"
        )
        if not path:
            return

        def done(error: str | None) -> None:
            if error:
                self.status.show_status(f"Export failed: {error}", 0)
            else:
                self.status.show_status(f"Exported {rows:,} rows to {path}", 10_000)
                self.announce("Export finished")

        s.export_permissions(path, include_none, done)

    def export_audit(self) -> None:
        self.tabs.setCurrentIndex(TAB_AUDIT)
        if self.audit_view.model.entries:
            self.audit_view.export()
        else:
            self.status.show_status("Search the audit log first, then export what it shows.", 8000)

    # --- Dev ------------------------------------------------------------------------------

    def dev_stage_sample(self) -> None:
        count, ok = QInputDialog.getInt(self, "Dev: stage sample changes", "How many changes?", 12, 1, 20_000)
        if ok:
            changed = self.session.dev_stage_sample(count)
            self.status.show_status(f"Dev: staged {changed:,} sample changes", 5000)

    # --- Window state and quit -------------------------------------------------------------

    def _restore_window_state(self) -> None:
        geometry = self.settings.value("window/geometry")
        if isinstance(geometry, QByteArray) and not geometry.isEmpty():
            self.restoreGeometry(geometry)
        else:
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                frame = self.frameGeometry()
                frame.moveCenter(screen.availableGeometry().center())
                self.move(frame.topLeft())
        state = self.settings.value("window/state")
        if isinstance(state, QByteArray) and not state.isEmpty():
            self.restoreState(state)
        tab = self.settings.value("window/tab", TAB_MATRIX)
        try:
            self.tabs.setCurrentIndex(int(tab))
        except (TypeError, ValueError):
            self.tabs.setCurrentIndex(TAB_MATRIX)
        self._sync_tray_action(not self.tray.isHidden())  # the window isn't shown yet

    def save_window_state(self) -> None:
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/state", self.saveState())
        self.settings.setValue("window/tab", self.tabs.currentIndex())
        self.settings.sync()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        if self._quitting:
            event.accept()
            return
        s = self.session
        if s.commit_running:
            event.ignore()
            if messages.confirm_wait_for_commit(self):
                self._quit_after_commit = True
            return
        if s.staged_count > 0:
            choice = messages.confirm_quit(self, s.staged_count)
            if choice == "cancel":
                event.ignore()
                return
            if choice == "commit":
                event.ignore()
                if not s.can_commit:
                    messages.show_error(
                        self, "Can't commit now", "Bifrost isn't connected. Reconnect first, or quit without committing."
                    )
                    return
                self._quit_after_commit = True
                s.request_commit()
                return
        self._finish_quit()
        event.accept()

    def _finish_quit(self) -> None:
        self._quitting = True
        self.save_window_state()
        if self.tag_manager is not None:
            self.tag_manager.close()
        error = self.session.close()
        if error:
            messages.show_error(self, "Couldn't save tags", error)
