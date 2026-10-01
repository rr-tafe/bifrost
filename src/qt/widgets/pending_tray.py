"""
Pending changes tray: a dock listing every staged change as a sentence.

Each row can be undone on its own (button or Delete key) or revealed in the
matrix (double-click or Enter; handled by the matrix view from step 3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    QTimer,
)
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDockWidget,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from src.qt.session import describe_change
from src.qt.widgets.search_field import SearchField
from src.qt.widgets.tables import compact_rows

if TYPE_CHECKING:
    from src.models.permission import StagedChange
    from src.qt.session import Session

REBUILD_DEBOUNCE_MS = 100


class StagedChangesModel(QAbstractTableModel):
    """Table model over a list of StagedChange: Change, Was, Principal, Object."""

    HEADERS = ("Change", "Was", "Principal", "Object")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._changes: list[StagedChange] = []

    def set_changes(self, changes: list[StagedChange]) -> None:
        self.beginResetModel()
        self._changes = list(changes)
        self.endResetModel()

    def change_at(self, row: int) -> StagedChange:
        return self._changes[row]

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008, N802 - Qt API
        return 0 if parent.isValid() else len(self._changes)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008, N802 - Qt API
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        change = self._changes[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            column = index.column()
            if column == 0:
                return describe_change(change)
            if column == 1:
                return change.previous_state.value.title() if change.previous_state.value != "NONE" else "none"
            if column == 2:
                return change.user_login
            return f"{change.schema_name}.{change.object_name}"
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None


class PendingTray(QDockWidget):
    """Bottom dock listing staged changes."""

    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__("Pending changes", parent)
        self.setObjectName("pending_tray")
        self.session = session
        self.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.TopDockWidgetArea)

        self.model = StagedChangesModel(self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterKeyColumn(-1)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        body = QWidget(self)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(8, 4, 8, 8)

        top = QHBoxLayout()
        self.filter_field = SearchField("Filter pending changes…", "Filter pending changes", body)
        self.filter_field.searchChanged.connect(self.proxy.setFilterFixedString)
        self.count_label = QLabel("", body)
        self.undo_button = QPushButton("Undo selected change", body)
        self.undo_button.setAccessibleName("Undo the selected staged change")
        self.undo_button.clicked.connect(self.undo_selected)
        top.addWidget(self.filter_field, 1)
        top.addWidget(self.count_label)
        top.addWidget(self.undo_button)
        layout.addLayout(top)

        self.table = QTableView(body)
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setWordWrap(False)
        self.table.setAccessibleName("Staged changes")
        compact_rows(self.table)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.doubleClicked.connect(self._reveal)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self.table, self.undo_selected)
        QShortcut(QKeySequence(Qt.Key.Key_Return), self.table, self._reveal_current)

        self.empty_label = QLabel(
            "No pending changes. Changes you make in the matrix appear here until you commit them.", body
        )
        self.empty_label.setWordWrap(True)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.stack = QStackedWidget(body)
        self.stack.addWidget(self.empty_label)
        self.stack.addWidget(self.table)
        layout.addWidget(self.stack, 1)
        self.setWidget(body)

        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(REBUILD_DEBOUNCE_MS)
        self._rebuild_timer.timeout.connect(self.rebuild)
        session.matrixChanged.connect(lambda _change: self._rebuild_timer.start())
        session.stateChanged.connect(lambda _state: self._update_buttons())
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._update_buttons())
        self.rebuild()

    def rebuild(self) -> None:
        """Reload the list from the matrix."""
        changes = self.session.matrix.get_staged_changes() if self.session.matrix else []
        self.model.set_changes(changes)
        self.table.sortByColumn(-1, Qt.SortOrder.AscendingOrder)  # keep the matrix order until the user sorts
        count = len(changes)
        self.count_label.setText(f"{count:,} pending" if count else "")
        self.stack.setCurrentIndex(1 if count else 0)
        self._update_buttons()

    def _update_buttons(self) -> None:
        has_selection = bool(self.table.selectionModel().selectedRows())
        self.undo_button.setEnabled(has_selection and not self.session.commit_running)

    def selected_changes(self) -> list[StagedChange]:
        rows = sorted({self.proxy.mapToSource(i).row() for i in self.table.selectionModel().selectedRows()})
        return [self.model.change_at(r) for r in rows]

    def undo_selected(self) -> None:
        """Undo the selected staged changes (one undo step)."""
        changes = self.selected_changes()
        if not changes:
            return
        if len(changes) == 1:
            self.session.revert_change(changes[0])
        else:
            self.session.revert_changes(changes, f"Undo {len(changes):,} staged changes")

    def _reveal(self, index: QModelIndex) -> None:
        if index.isValid():
            self.session.reveal(self.model.change_at(self.proxy.mapToSource(index).row()))

    def _reveal_current(self) -> None:
        self._reveal(self.table.currentIndex())
