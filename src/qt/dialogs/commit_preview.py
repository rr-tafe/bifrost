"""
Commit preview (FR-026): shown before committing 5 or more changes.

Lists every change in a sortable, filterable table with counts by action.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from src.qt.theme import tokens
from src.qt.widgets.search_field import SearchField
from src.qt.widgets.tables import compact_rows

if TYPE_CHECKING:
    from src.models.permission import StagedChange
    from src.services.matrix import CommitPlan


class ChangeTableModel(QAbstractTableModel):
    """Action, Permission, Object, Principal, Was (and an optional Reason column)."""

    def __init__(self, changes: list[StagedChange], reasons: list[str] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.changes = list(changes)
        self.reasons = reasons
        self.headers = ["Action", "Permission", "Object", "Principal", "Was"] + (["Reason"] if reasons else [])

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008, N802 - Qt API
        return 0 if parent.isValid() else len(self.changes)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008, N802 - Qt API
        return 0 if parent.isValid() else len(self.headers)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        change = self.changes[index.row()]
        column = index.column()
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            values = [
                change.action,
                change.permission_type.value,
                f"{change.schema_name}.{change.object_name}",
                change.user_login,
                "none" if change.previous_state.value == "NONE" else change.previous_state.value,
            ]
            if self.reasons:
                values.append(self.reasons[index.row()])
            return values[column]
        if role == Qt.ItemDataRole.ForegroundRole and column == 0:
            t = tokens()
            return QColor({"GRANT": t.grant, "DENY": t.deny}.get(change.action, t.fg))
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]
        return None


def make_change_table(model: ChangeTableModel, parent: QWidget, name: str) -> tuple[QTableView, QSortFilterProxyModel]:
    """A read-only, sortable table over model."""
    proxy = QSortFilterProxyModel(parent)
    proxy.setSourceModel(model)
    proxy.setFilterKeyColumn(-1)
    proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    table = QTableView(parent)
    table.setModel(proxy)
    table.setSortingEnabled(True)
    table.sortByColumn(-1, Qt.SortOrder.AscendingOrder)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().hide()
    table.setWordWrap(False)
    table.setAccessibleName(name)
    compact_rows(table)
    header = table.horizontalHeader()
    for column in range(model.columnCount()):
        header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
    header.setStretchLastSection(True)
    return table, proxy


class CommitPreviewDialog(QDialog):
    """
    Review staged changes before committing.

    Result: exec() returns Accepted to commit. If the user clicks "Review in matrix",
    exec() returns Rejected and review_requested is True.
    """

    def __init__(self, plan: CommitPlan, database: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.plan = plan
        self.review_requested = False
        count = len(plan.changes)
        self.setWindowTitle(f"Review {count:,} changes")
        self.resize(860, 520)

        layout = QVBoxLayout(self)
        intro = QLabel(
            f"These changes will be applied to {database} and written to the audit log.", self
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        top = QHBoxLayout()
        self.filter_field = SearchField("Filter changes…", "Filter changes", self)
        actions = [c.action for c in plan.changes]
        parts = [
            f"{actions.count(a):,} {label}"
            for a, label in (("GRANT", "grants"), ("DENY", "denies"), ("REVOKE", "revokes"))
            if actions.count(a)
        ]
        self.summary = QLabel(" · ".join(parts), self)
        top.addWidget(self.filter_field, 1)
        top.addWidget(self.summary)
        layout.addLayout(top)

        self.model = ChangeTableModel(list(plan.changes), parent=self)
        self.table, self.proxy = make_change_table(self.model, self, "Changes to commit")
        self.filter_field.searchChanged.connect(self.proxy.setFilterFixedString)
        layout.addWidget(self.table, 1)

        buttons = QDialogButtonBox(self)
        review = buttons.addButton("Review in matrix", QDialogButtonBox.ButtonRole.ResetRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.commit_button = buttons.addButton(f"Commit {count:,}", QDialogButtonBox.ButtonRole.AcceptRole)
        self.commit_button.setDefault(True)
        self.commit_button.setAutoDefault(True)
        review.clicked.connect(self._review)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.commit_button.setFocus()

    def _review(self) -> None:
        self.review_requested = True
        self.reject()
