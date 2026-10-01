"""Pick the principal to copy permissions from ("Make like…")."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QStringListModel, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListView,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from src.qt.widgets.search_field import SearchField
from src.services.matrix_index import PrincipalQuery

if TYPE_CHECKING:
    from src.services.matrix_index import PermissionIndex


class MakeLikeDialog(QDialog):
    """
    After exec(): source is the chosen principal index (or None) and
    scope is "all" or "filter".
    """

    def __init__(
        self, ix: PermissionIndex, target: int, filter_active: bool, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.ix = ix
        self.target = target
        self.source: int | None = None
        login = ix.principals[target].login_name
        self.setWindowTitle(f"Make {login} like…")
        self.setMinimumSize(460, 480)
        layout = QVBoxLayout(self)
        intro = QLabel(
            f"Give {login} the same permissions as another principal. Each permission is set to the other "
            "principal's GRANT, DENY or none, so this can also revoke and deny.",
            self,
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.search = SearchField("Search principals…", "Search principals to copy from", self)
        self.search.searchChanged.connect(self._refilter)
        layout.addWidget(self.search)
        self.model = QStringListModel(self)
        self.list = QListView(self)
        self.list.setModel(self.model)
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list.setAccessibleName("Principal to copy from")
        self.list.doubleClicked.connect(lambda _i: self._accept())
        layout.addWidget(self.list, 1)
        self.all_objects = QRadioButton("All objects", self)
        self.filtered = QRadioButton("Only objects shown by the current filter", self)
        (self.filtered if filter_active else self.all_objects).setChecked(True)
        self.filtered.setEnabled(filter_active)
        layout.addWidget(self.all_objects)
        layout.addWidget(self.filtered)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self)
        self.ok = buttons.addButton("Continue…", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._items: list[int] = []
        self._refilter("")
        self.search.setFocus()

    @property
    def scope(self) -> str:
        return "filter" if self.filtered.isChecked() else "all"

    def _refilter(self, text: str) -> None:
        items = [p for p in self.ix.query_principals(PrincipalQuery(text=text)) if p != self.target]
        self._items = items
        self.model.setStringList([self.ix.principals[p].login_name for p in items])
        if items:
            self.list.setCurrentIndex(self.model.index(0))
        self.ok.setEnabled(bool(items))

    def choose(self, p: int) -> None:
        """Select principal p in the list (for tests and keyboard users)."""
        if p in self._items:
            self.list.setCurrentIndex(self.model.index(self._items.index(p)))

    def _accept(self) -> None:
        index = self.list.currentIndex()
        if not index.isValid():
            return
        self.source = self._items[index.row()]
        self.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self.search.hasFocus():
            self.list.setFocus()
            self.list.keyPressEvent(event)
            return
        super().keyPressEvent(event)
