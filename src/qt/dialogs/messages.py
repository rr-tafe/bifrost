"""
Standard message boxes with consistent wording and button roles.

Each confirm_* function returns which button was chosen. Defaults are always the
safe choice (keep editing, cancel).
"""

from __future__ import annotations

import platform
from importlib import metadata
from typing import TYPE_CHECKING

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import Qt, qVersion
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from src.qt.actions import ActionRegistry


def confirm_discard(parent: QWidget, count: int) -> bool:
    """Ask before discarding count staged changes. Returns True to discard."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Discard changes")
    box.setText(f"Discard {count:,} staged changes?")
    box.setInformativeText("This can't be undone.")
    discard = box.addButton(f"Discard {count:,} changes", QMessageBox.ButtonRole.DestructiveRole)
    keep = box.addButton("Keep editing", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(keep)
    box.setEscapeButton(keep)
    box.exec()
    return box.clickedButton() is discard


def confirm_quit(parent: QWidget, count: int) -> str:
    """
    Ask what to do with staged changes when quitting.

    Returns:
        str: "commit", "quit" or "cancel"
    """
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Quit Bifrost")
    box.setText(f"You have {count:,} staged changes that haven't been committed.")
    box.setInformativeText("Commit them before quitting?")
    commit = box.addButton("Commit and quit", QMessageBox.ButtonRole.AcceptRole)
    quit_button = box.addButton("Quit without committing", QMessageBox.ButtonRole.DestructiveRole)
    cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel)
    box.setEscapeButton(cancel)
    box.exec()
    clicked = box.clickedButton()
    if clicked is commit:
        return "commit"
    if clicked is quit_button:
        return "quit"
    return "cancel"


def confirm_wait_for_commit(parent: QWidget) -> bool:
    """Ask to wait for a running commit before quitting. Returns True to wait and quit after."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle("Commit in progress")
    box.setText("A commit is in progress.")
    box.setInformativeText("Bifrost will close when it finishes.")
    wait = box.addButton("Wait, then quit", QMessageBox.ButtonRole.AcceptRole)
    cancel = box.addButton("Keep Bifrost open", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(wait)
    box.setEscapeButton(cancel)
    box.exec()
    return box.clickedButton() is wait


def confirm_full_export(parent: QWidget, rows: int) -> bool:
    """Warn before exporting every cell including those with no permission."""
    estimated_mb = rows * 60 / 1_000_000  # ~60 bytes per row
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Large export")
    box.setText(f"This export will write about {rows:,} rows (about {estimated_mb:,.0f} MB).")
    box.setInformativeText(
        "Including cells with no permission makes the file very large. Export only explicit "
        "permissions instead?"
    )
    export_all = box.addButton("Export everything", QMessageBox.ButtonRole.AcceptRole)
    cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel)
    box.setEscapeButton(cancel)
    box.exec()
    return box.clickedButton() is export_all


def show_error(parent: QWidget, title: str, text: str, details: str = "") -> None:
    """Show an error with optional details."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle(title)
    box.setText(text)
    if details:
        box.setDetailedText(details)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()


def show_info(parent: QWidget, title: str, text: str, details: str = "") -> None:
    """Show information with optional details."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle(title)
    box.setText(text)
    if details:
        box.setDetailedText(details)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()


def show_crash(parent: QWidget | None, message: str, details: str, log_path: str) -> None:
    """Show an unexpected error with Copy details. The app keeps running."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle("Something went wrong")
    box.setText(f"Something went wrong: {message}")
    box.setInformativeText(f"Your staged changes are untouched. Details are in the log:\n{log_path}")
    box.setDetailedText(details)
    copy = box.addButton("Copy details", QMessageBox.ButtonRole.ActionRole)
    copy.clicked.disconnect()
    copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(details))
    box.addButton(QMessageBox.StandardButton.Ok)
    box.exec()


class ShortcutsDialog(QDialog):
    """Lists every command and its shortcut, generated from the action registry."""

    def __init__(self, registry: ActionRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keyboard shortcuts")
        self.resize(560, 520)
        layout = QVBoxLayout(self)
        rows = registry.shortcut_rows()
        table = QTableWidget(len(rows), 3, self)
        table.setHorizontalHeaderLabels(["Menu", "Command", "Shortcut"])
        table.verticalHeader().hide()
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAccessibleName("Keyboard shortcuts")
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.resizeColumnsToContents()
        layout.addWidget(table)
        note = QLabel("Escape closes dialogs and popups. It doesn't discard staged changes.", self)
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def _version(package: str) -> str:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return "dev"


def about_text(config_path: str, log_path: str, driver: str) -> str:
    """Diagnostics shown in the About dialog."""
    return (
        f"Bifrost {_version('bifrost')}\n"
        "SQL Server permissions manager\n\n"
        f"Python {platform.python_version()}\n"
        f"Qt {qVersion()} (PySide6 {pyside_version})\n"
        f"pyodbc {_version('pyodbc')}\n"
        f"ODBC driver: {driver}\n\n"
        f"Config: {config_path}\n"
        f"Log: {log_path}"
    )


def show_about(parent: QWidget, text: str) -> None:
    """About dialog with selectable diagnostics."""
    dialog = QDialog(parent)
    dialog.setWindowTitle("About Bifrost")
    layout = QVBoxLayout(dialog)
    label = QLabel(text, dialog)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(label)
    copy = QPushButton("Copy", dialog)
    copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(text))
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
    buttons.addButton(copy, QDialogButtonBox.ButtonRole.ActionRole)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.exec()
