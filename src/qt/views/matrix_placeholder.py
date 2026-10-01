"""
Matrix tab content until the split view arrives in step 3.

Shows what the session is doing: needs settings, connecting, loading (with each
stage and a Cancel button), failed (with Retry), or a summary of what was loaded.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.qt.session import SessionState

if TYPE_CHECKING:
    from src.qt.session import LoadSummary, Session
    from src.services.loader import LoadProgress

STAGES = (
    ("principals", "Principals"),
    ("objects", "Objects"),
    ("permissions", "Permissions"),
    ("privileges", "Your privileges"),
)
PRINCIPAL_TYPES = {"U": "Windows users", "G": "Windows groups", "S": "SQL users"}
OBJECT_TYPES = {"TABLE": "tables", "VIEW": "views", "PROCEDURE": "procedures", "FUNCTION": "functions"}
SUMMARY_ROWS = (
    "Principals",
    "Objects",
    "Explicit permissions",
    "Staged changes",
    "Signed in as",
    "Load time",
    "Loaded at",
)


def _heading(text: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    font = label.font()
    font.setPointSizeF(font.pointSizeF() * 1.35)
    font.setBold(True)
    label.setFont(font)
    label.setWordWrap(True)
    label.setAccessibleName(text)
    return label


def _body(text: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class _Page(QWidget):
    """Centred column with a heading, text and buttons."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.column = QVBoxLayout()
        self.column.setSpacing(10)
        holder = QWidget(self)
        holder.setLayout(self.column)
        holder.setMaximumWidth(620)
        row.addWidget(holder, 4)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)

    def add_buttons(self, *buttons: QPushButton) -> None:
        row = QHBoxLayout()
        for button in buttons:
            row.addWidget(button)
        row.addStretch(1)
        self.column.addLayout(row)


class MatrixPlaceholder(QWidget):
    """
    Matrix tab placeholder.

    Signals:
        openSettings: user asked for connection settings
    """

    openSettings = Signal()

    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self.stack = QStackedWidget(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)

        # Needs settings
        self.setup_page = _Page(self)
        self.setup_page.column.addWidget(_heading("Set up a connection to get started", self.setup_page))
        self.setup_page.column.addWidget(
            _body("Bifrost needs the SQL Server and database to manage permissions for.", self.setup_page)
        )
        settings_button = QPushButton("Open connection settings", self.setup_page)
        settings_button.clicked.connect(self.openSettings)
        self.setup_page.add_buttons(settings_button)

        # Connecting / loading
        self.loading_page = _Page(self)
        self.loading_heading = _heading("Connecting…", self.loading_page)
        self.loading_page.column.addWidget(self.loading_heading)
        self.stage_labels: dict[str, QLabel] = {}
        for key, title in STAGES:
            label = _body(f"○  {title}", self.loading_page)
            self.stage_labels[key] = label
            self.loading_page.column.addWidget(label)
        self.loading_bar = QProgressBar(self.loading_page)
        self.loading_bar.setAccessibleName("Loading progress")
        self.loading_page.column.addWidget(self.loading_bar)
        self.cancel_button = QPushButton("Cancel", self.loading_page)
        self.cancel_button.setAccessibleName("Cancel loading")
        self.cancel_button.clicked.connect(session.cancel_load)
        self.loading_page.add_buttons(self.cancel_button)

        # Failed
        self.failed_page = _Page(self)
        self.failed_page.column.addWidget(_heading("Couldn't load permissions", self.failed_page))
        self.error_label = _body("", self.failed_page)
        self.failed_page.column.addWidget(self.error_label)
        retry_button = QPushButton("Retry", self.failed_page)
        retry_button.clicked.connect(session.reconnect)
        failed_settings = QPushButton("Open connection settings", self.failed_page)
        failed_settings.clicked.connect(self.openSettings)
        self.failed_page.add_buttons(retry_button, failed_settings)

        # Summary
        self.summary_page = _Page(self)
        self.summary_heading = _heading("", self.summary_page)
        self.summary_page.column.addWidget(self.summary_heading)
        self.summary_grid = QGridLayout()
        self.summary_grid.setHorizontalSpacing(24)
        self.summary_grid.setVerticalSpacing(4)
        self.summary_values: dict[str, QLabel] = {}
        for row, name in enumerate(SUMMARY_ROWS):
            name_label = QLabel(name, self.summary_page)
            name_label.setStyleSheet("font-weight: 600;")
            value_label = _body("", self.summary_page)
            name_label.setBuddy(value_label)
            self.summary_grid.addWidget(name_label, row, 0, Qt.AlignmentFlag.AlignTop)
            self.summary_grid.addWidget(value_label, row, 1)
            self.summary_values[name] = value_label
        self.summary_grid.setColumnStretch(1, 1)
        self.summary_page.column.addLayout(self.summary_grid)
        line = QFrame(self.summary_page)
        line.setFrameShape(QFrame.Shape.HLine)
        self.summary_page.column.addWidget(line)
        self.summary_page.column.addWidget(
            _body(
                "The new matrix view arrives in the next update. Until then, edit permissions in the "
                "previous version with: python main.py --legacy-tk",
                self.summary_page,
            )
        )

        for page in (self.setup_page, self.loading_page, self.failed_page, self.summary_page):
            self.stack.addWidget(page)

        session.stateChanged.connect(lambda _state: self.update_view())
        session.loadProgress.connect(self._on_progress)
        session.dataLoaded.connect(lambda _summary: self.update_view())
        session.stagedCountChanged.connect(lambda _count: self.update_view())
        self.update_view()

    def update_view(self) -> None:
        """Show the page for the session's current state."""
        state = self.session.state
        if state is SessionState.NEEDS_SETTINGS:
            self.stack.setCurrentWidget(self.setup_page)
        elif state in (SessionState.CONNECTING, SessionState.LOADING) and self.session.last_load is None:
            self._show_loading(state)
        elif state is SessionState.FAILED and self.session.last_load is None:
            self.error_label.setText(self.session.last_error or "Something went wrong.")
            self.stack.setCurrentWidget(self.failed_page)
        elif self.session.last_load is not None:
            self._show_summary(self.session.last_load)
        else:
            self._show_loading(state)

    def _show_loading(self, state: SessionState) -> None:
        config = self.session.config
        target = f"{config.server}/{config.database}" if config else "the database"
        if state is SessionState.CONNECTING:
            self.loading_heading.setText(f"Connecting to {target}…")
            for key, title in STAGES:
                self.stage_labels[key].setText(f"○  {title}")
            self.loading_bar.setRange(0, 0)
            self.cancel_button.hide()
        else:
            self.loading_heading.setText(f"Loading permissions from {target}…")
            self.cancel_button.show()
        self.stack.setCurrentWidget(self.loading_page)

    def _on_progress(self, progress: LoadProgress) -> None:
        if self.stack.currentWidget() is not self.loading_page:
            return
        for number, (key, title) in enumerate(STAGES, start=1):
            label = self.stage_labels[key]
            if number < progress.stage_number:
                label.setText(f"✓  {title}")
            elif number == progress.stage_number:
                extra = f" — {progress.rows:,} rows" if progress.rows else ""
                label.setText(f"◌  {title}{extra}")
            else:
                label.setText(f"○  {title}")
        self.loading_bar.setRange(0, progress.stage_count)
        self.loading_bar.setValue(progress.stage_number - 1)

    def _show_summary(self, summary: LoadSummary) -> None:
        config = self.session.config
        target = f"{config.server}/{config.database}" if config else ""
        self.summary_heading.setText(f"{target} is loaded")
        principals = ", ".join(
            f"{summary.principals_by_type[k]:,} {PRINCIPAL_TYPES.get(k, k)}" for k in sorted(summary.principals_by_type)
        )
        objects = ", ".join(f"{n:,} {OBJECT_TYPES.get(t, t)}" for t, n in sorted(summary.objects_by_type.items()))
        timings = ", ".join(f"{name} {seconds * 1000:,.0f} ms" for name, seconds in summary.timings.items())
        values = {
            "Principals": f"{summary.principals:,}  ({principals})",
            "Objects": f"{summary.objects:,}  ({objects})",
            "Explicit permissions": f"{summary.grants:,} grants, {summary.denies:,} denies",
            "Staged changes": f"{self.session.staged_count:,}",
            "Signed in as": self.session.current_user or "—",
            "Load time": timings or "—",
            "Loaded at": summary.loaded_at.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        }
        for name, value in values.items():
            self.summary_values[name].setText(value)
        self.stack.setCurrentWidget(self.summary_page)
