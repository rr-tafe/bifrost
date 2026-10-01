"""
Connection settings dialog.

Fields: server, port, database, schema. Authentication is Windows only. Each
field shows its own error under it. Test connection runs in the background;
its result is shown only while the fields still match what was tested.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.models.config import Configuration
from src.qt.theme import tokens
from src.validation import validate_port, validate_schema_name

if TYPE_CHECKING:
    from src.qt.session import Session


def _same_connection(a: Configuration, b: Configuration) -> bool:
    return (a.server, a.port, a.database, a.schema) == (b.server, b.port, b.database, b.schema)


class SettingsDialog(QDialog):
    """Connection settings."""

    def __init__(
        self,
        session: Session,
        reason: str = "",
        parent: QWidget | None = None,
        last_test: tuple[Configuration, bool, str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.setWindowTitle("Connection settings")
        self.setMinimumWidth(520)
        self.last_test = last_test
        self._testing = False
        t = tokens()

        layout = QVBoxLayout(self)

        self.reason_label = QLabel(f"⚠ {reason}" if reason else "", self)
        self.reason_label.setWordWrap(True)
        self.reason_label.setStyleSheet(
            f"background: {t.staged_bg}; color: {t.staged}; padding: 8px; border-radius: 4px;"
        )
        self.reason_label.setVisible(bool(reason))
        self.reason_label.setAccessibleName(f"Warning: {reason}" if reason else "")
        layout.addWidget(self.reason_label)

        group = QGroupBox("Connection", self)
        form = QFormLayout(group)
        config = session.config or Configuration.default()
        self.server = self._field(config.server, "Server", "Hostname or IP, e.g. sql01.corp.local")
        self.port = self._field(str(config.port), "Port", "Usually 1433")
        self.database = self._field(config.database, "Database", "Database to manage")
        self.schema = self._field(config.schema, "Schema", "Where Bifrost keeps its audit log (usually dbo)")
        self.errors: dict[QLineEdit, QLabel] = {}
        for label, field in (
            ("&Server", self.server),
            ("&Port", self.port),
            ("&Database", self.database),
            ("S&chema", self.schema),
        ):
            column = QVBoxLayout()
            column.setSpacing(2)
            column.addWidget(field)
            error = QLabel("", group)
            error.setStyleSheet(f"color: {t.danger};")
            error.setWordWrap(True)
            error.hide()
            column.addWidget(error)
            self.errors[field] = error
            label_widget = QLabel(label, group)
            label_widget.setBuddy(field)
            form.addRow(label_widget, column)
            field.textChanged.connect(self._on_edited)
        layout.addWidget(group)

        auth = QGroupBox("Authentication", self)
        auth_layout = QVBoxLayout(auth)
        auth_layout.addWidget(QLabel("Windows Authentication (your current Windows sign-in)", auth))
        if os.environ.get("BIFROST_DEV_SQL_USER") and os.environ.get("BIFROST_DEV_SQL_PASSWORD"):
            dev_note = QLabel("Using the dev SQL login from the environment instead.", auth)
            dev_note.setStyleSheet(f"color: {t.muted};")
            auth_layout.addWidget(dev_note)
        layout.addWidget(auth)

        test_row = QHBoxLayout()
        self.test_status = QLabel("Not tested", self)
        self.test_status.setWordWrap(True)
        self.test_status.setAccessibleName("Connection test result")
        self.test_button = QPushButton("&Test connection", self)
        self.test_button.clicked.connect(self.test_connection)
        test_row.addWidget(self.test_status, 1)
        test_row.addWidget(self.test_button)
        layout.addLayout(test_row)

        self.save_error = QLabel("", self)
        self.save_error.setStyleSheet(f"color: {t.danger};")
        self.save_error.setWordWrap(True)
        self.save_error.hide()
        layout.addWidget(self.save_error)

        self.buttons = QDialogButtonBox(self)
        self.save_button = self.buttons.addButton("Save and connect", QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.save_button.setDefault(True)
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self._refresh_test_status()
        (self.server if not self.server.text() else self.database if not self.database.text() else self.save_button).setFocus()

    def _field(self, value: str, name: str, hint: str) -> QLineEdit:
        field = QLineEdit(value, self)
        field.setAccessibleName(name)
        field.setPlaceholderText(hint)
        field.setToolTip(hint)
        return field

    # --- Validation ------------------------------------------------------------------

    def validate(self) -> Configuration | None:
        """Show per-field errors. Returns the config if every field is valid."""
        t = tokens()
        problems: dict[QLineEdit, str] = {}
        if not self.server.text().strip():
            problems[self.server] = "Enter the server name or IP address."
        port_errors = validate_port(self.port.text().strip())
        if port_errors:
            problems[self.port] = port_errors[0]
        if not self.database.text().strip():
            problems[self.database] = "Enter the database name."
        schema_errors = validate_schema_name(self.schema.text().strip())
        if schema_errors:
            problems[self.schema] = schema_errors[0]

        for field, label in self.errors.items():
            message = problems.get(field, "")
            label.setText(message)
            label.setVisible(bool(message))
            field.setAccessibleDescription(message)
            field.setStyleSheet(f"border: 1px solid {t.danger};" if message else "")
        if problems:
            next(iter(problems)).setFocus()
            return None
        return Configuration(
            server=self.server.text().strip(),
            port=int(self.port.text().strip()),
            database=self.database.text().strip(),
            schema=self.schema.text().strip(),
            auth_type="windows",
        )

    def _current_config(self) -> Configuration | None:
        try:
            port = int(self.port.text().strip())
        except ValueError:
            return None
        return Configuration(
            server=self.server.text().strip(),
            port=port,
            database=self.database.text().strip(),
            schema=self.schema.text().strip(),
        )

    # --- Test connection --------------------------------------------------------------

    def test_connection(self) -> None:
        config = self.validate()
        if config is None:
            self._set_test_status("Fix the highlighted fields first", False)
            return
        self._testing = True
        self.test_button.setEnabled(False)
        self.test_button.setText("Testing…")
        self._set_test_status("Testing connection…", None)

        def done(success: bool, message: str) -> None:
            self._testing = False
            self.test_button.setEnabled(True)
            self.test_button.setText("&Test connection")
            self.last_test = (config, success, message)
            self._refresh_test_status()

        self.session.test_connection(config, done)

    def _on_edited(self) -> None:
        self.save_error.hide()
        if not self._testing:
            self._refresh_test_status()

    def _refresh_test_status(self) -> None:
        current = self._current_config()
        if self.last_test is not None and current is not None:
            tested, success, message = self.last_test
            if _same_connection(tested, current):
                self._set_test_status(message, success)
                return
        self._set_test_status("Not tested", None)

    def _set_test_status(self, message: str, success: bool | None) -> None:
        t = tokens()
        icon, colour = {True: ("✓", t.grant), False: ("✗", t.danger), None: ("○", t.muted)}[success]
        self.test_status.setText(f"{icon} {message}")
        self.test_status.setStyleSheet(f"color: {colour};")

    # --- Save ---------------------------------------------------------------------------

    def save(self) -> None:
        config = self.validate()
        if config is None:
            return
        error = self.session.save_settings(config)
        if error:
            self.save_error.setText(f"Couldn't save settings: {error}")
            self.save_error.show()
            return
        self.accept()
