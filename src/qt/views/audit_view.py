"""
Audit log tab.

Filters (principal, object, action, dates) run as a database query when the
user presses Search or Enter. Up to 5,000 newest rows are shown; the total is
shown when there are more.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QAbstractTableModel,
    QDate,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
)
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from src.qt.widgets.tables import compact_rows
from src.services.export import get_suggested_filename

if TYPE_CHECKING:
    from src.models.audit_entry import AuditEntry
    from src.qt.session import AuditResult, Session

DEFAULT_DAYS = 30


def _local(dt: datetime) -> datetime:
    """Audit timestamps are stored as UTC (naive from the driver); convert to local time."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone()


class AuditLogModel(QAbstractTableModel):
    """Table model over audit entries."""

    HEADERS = ("Time", "Administrator", "Principal", "Object", "Permission", "Action", "Explanation")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.entries: list[AuditEntry] = []

    def set_entries(self, entries: list[AuditEntry]) -> None:
        self.beginResetModel()
        self.entries = list(entries)
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008, N802 - Qt API
        return 0 if parent.isValid() else len(self.entries)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008, N802 - Qt API
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        entry = self.entries[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return _local(entry.changed_at).strftime("%Y-%m-%d %H:%M:%S")
            return (
                entry.administrator,
                entry.affected_user,
                f"{entry.schema_name}.{entry.object_name}",
                entry.permission_type,
                entry.action,
                entry.explanation,
            )[column - 1]
        if role == Qt.ItemDataRole.ToolTipRole:
            if column == 0:
                return f"{entry.changed_at:%Y-%m-%d %H:%M:%S} UTC"
            if column == 6:
                return entry.explanation
        if role == Qt.ItemDataRole.UserRole:  # sort key
            if column == 0:
                return entry.changed_at.isoformat()
            return self.data(index, Qt.ItemDataRole.DisplayRole)
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None


class _DateFilter(QWidget):
    """Date picker with a "no limit" checkbox."""

    def __init__(self, label: str, parent: QWidget) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.enabled = QCheckBox(label, self)
        self.date = QDateEdit(self)
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("yyyy-MM-dd")
        self.date.setDate(QDate.currentDate())
        self.date.setAccessibleName(f"{label} date")
        self.enabled.toggled.connect(self.date.setEnabled)
        self.enabled.setChecked(False)
        self.date.setEnabled(False)
        layout.addWidget(self.enabled)
        layout.addWidget(self.date)

    def set_value(self, value: QDate | None) -> None:
        self.enabled.setChecked(value is not None)
        if value is not None:
            self.date.setDate(value)

    def value(self) -> QDate | None:
        return self.date.date() if self.enabled.isChecked() else None


class AuditView(QWidget):
    """Audit log tab."""

    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self._loaded_once = False
        self._from_exact: datetime | None = None  # exact start time after a commit

        layout = QVBoxLayout(self)

        filters = QHBoxLayout()
        self.principal_field = QLineEdit(self)
        self.principal_field.setPlaceholderText("Principal contains…")
        self.principal_field.setAccessibleName("Filter by principal")
        self.object_field = QLineEdit(self)
        self.object_field.setPlaceholderText("Object contains… (schema.name)")
        self.object_field.setAccessibleName("Filter by object")
        self.action_combo = QComboBox(self)
        self.action_combo.addItems(["All actions", "GRANT", "DENY", "REVOKE"])
        self.action_combo.setAccessibleName("Filter by action")
        self.from_filter = _DateFilter("From", self)
        self.to_filter = _DateFilter("To", self)
        self.search_button = QPushButton("Search", self)
        self.search_button.setDefault(True)
        self.search_button.clicked.connect(self.refresh)
        for field in (self.principal_field, self.object_field):
            field.returnPressed.connect(self.refresh)
        filters.addWidget(self.principal_field, 2)
        filters.addWidget(self.object_field, 2)
        filters.addWidget(self.action_combo)
        filters.addWidget(self.from_filter)
        filters.addWidget(self.to_filter)
        filters.addWidget(self.search_button)
        layout.addLayout(filters)

        quick = QHBoxLayout()
        for text, days in (("Today", 0), ("Last 7 days", 7), ("Last 30 days", 30), ("Any time", None)):
            button = QPushButton(text, self)
            button.clicked.connect(lambda _checked=False, d=days: self.set_range(d))
            quick.addWidget(button)
        quick.addStretch(1)
        layout.addLayout(quick)

        self.message = QLabel("", self)
        self.message.setWordWrap(True)
        self.message.setAccessibleName("Audit log status")
        layout.addWidget(self.message)

        self.model = AuditLogModel(self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(Qt.ItemDataRole.UserRole)
        self.table = QTableView(self)
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setWordWrap(False)
        self.table.setAccessibleName("Audit log entries")
        compact_rows(self.table)
        header = self.table.horizontalHeader()
        for column in range(6):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        QShortcut(QKeySequence.StandardKey.Copy, self.table, self.copy_selection)
        layout.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.count_label = QLabel("", self)
        self.export_button = QPushButton("Export…", self)
        self.export_button.setAccessibleName("Export the shown audit entries as CSV")
        self.export_button.clicked.connect(self.export)
        footer.addWidget(self.count_label, 1)
        footer.addWidget(self.export_button)
        layout.addLayout(footer)

        self.set_range(DEFAULT_DAYS, search=False)
        self._update_enabled()
        session.stateChanged.connect(lambda _state: self._update_enabled())

    # --- Filters -------------------------------------------------------------------

    def set_range(self, days: int | None, search: bool = True) -> None:
        """Set From to `days` ago (0 = today, None = no limit) and clear To."""
        if days is None:
            self.from_filter.set_value(None)
        else:
            self.from_filter.set_value(QDate.currentDate().addDays(-days))
        self.to_filter.set_value(None)
        if search:
            self.refresh()

    def set_from_datetime(self, value: datetime) -> None:
        """Show entries from a point in time (used after a commit)."""
        self.principal_field.clear()
        self.object_field.clear()
        self.action_combo.setCurrentIndex(0)
        local = _local(value)
        self.from_filter.set_value(QDate(local.year, local.month, local.day))
        self.to_filter.set_value(None)
        self._from_exact = value
        self.refresh()

    def filters(self) -> dict:
        """Current filters in Session.fetch_audit form (dates as UTC-naive datetimes)."""
        result: dict = {}
        if self.principal_field.text().strip():
            result["affected_user_contains"] = self.principal_field.text().strip()
        if self.object_field.text().strip():
            result["object_search"] = self.object_field.text().strip()
        if self.action_combo.currentIndex() > 0:
            result["action"] = self.action_combo.currentText()
        start = self.from_filter.value()
        if start is not None:
            exact = self._from_exact
            if exact is not None:
                result["start_date"] = exact.astimezone(UTC).replace(tzinfo=None) - timedelta(seconds=1)
            else:
                local = datetime.combine(start.toPython(), time.min).astimezone()
                result["start_date"] = local.astimezone(UTC).replace(tzinfo=None)
        end = self.to_filter.value()
        if end is not None:
            local = datetime.combine(end.toPython(), time.max).astimezone()
            result["end_date"] = local.astimezone(UTC).replace(tzinfo=None)
        return result

    # --- Loading -------------------------------------------------------------------

    def ensure_loaded(self) -> None:
        """Search once the first time the tab is shown."""
        if not self._loaded_once and self.session.connected:
            self.refresh()

    def refresh(self) -> None:
        """Run the search."""
        if not self.session.connected:
            self.message.setText("Connect to a database to see the audit log.")
            return
        filters = self.filters()
        self._from_exact = None
        self._loaded_once = True
        self.message.setText("Searching…")
        self.search_button.setEnabled(False)
        self.session.fetch_audit(filters, self._on_result)

    def _on_result(self, result: AuditResult | None, error: str | None) -> None:
        self.search_button.setEnabled(self.session.connected)
        if error is not None:
            self.message.setText(f"Couldn't load the audit log: {error}")
            return
        self.model.set_entries(result.entries)
        self.table.sortByColumn(0, Qt.SortOrder.DescendingOrder)
        shown = len(result.entries)
        if result.limited:
            self.message.setText(
                f"Showing the newest {shown:,} of {result.total:,} entries. Narrow the filters to see older ones."
            )
        elif shown == 0:
            self.message.setText("No audit entries match these filters.")
        else:
            self.message.setText("")
        self.count_label.setText(f"{shown:,} entries")
        self._update_enabled()

    def _update_enabled(self) -> None:
        connected = self.session.connected
        self.search_button.setEnabled(connected)
        self.export_button.setEnabled(bool(self.model.entries))
        if not connected and not self.model.entries:
            self.message.setText("Connect to a database to see the audit log.")

    # --- Copy and export -----------------------------------------------------------

    def copy_selection(self) -> None:
        """Copy selected rows as tab-separated text."""
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        lines = []
        for row in rows:
            cells = [self.proxy.index(row, c).data() or "" for c in range(self.proxy.columnCount())]
            lines.append("\t".join(str(c) for c in cells))
        if lines:
            QGuiApplication.clipboard().setText("\n".join(lines))

    def export(self) -> None:
        """Save the shown entries as CSV."""
        if not self.model.entries:
            return
        database = self.session.config.database if self.session.config else "database"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export audit log", get_suggested_filename("audit", database), "CSV files (*.csv)"
        )
        if not path:
            return
        entries = list(self.model.entries)

        def done(error: str | None) -> None:
            if error:
                self.message.setText(f"Export failed: {error}")
            else:
                self.message.setText(f"Exported {len(entries):,} entries to {path}")

        self.session.export_audit(path, entries, done)
