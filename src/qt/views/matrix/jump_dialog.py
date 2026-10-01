"""
Ctrl+K jump box: find a principal, object or tag by typing.

search_jump() is plain Python over the index's search keys, so a keystroke
stays well under the 30 ms budget at 20,000 objects.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QDialog, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from src.qt.widgets.search_field import SearchField

if TYPE_CHECKING:
    from PySide6.QtGui import QKeyEvent

    from src.services.matrix_index import PermissionIndex

GROUP_LIMIT = 8
KindRole = Qt.ItemDataRole.UserRole + 1
KeyRole = Qt.ItemDataRole.UserRole + 2


@dataclass(frozen=True)
class JumpResult:
    """One hit: kind is "principal", "object", "principal_tag" or "object_tag"."""

    kind: str
    key: object  # p, o or casefolded tag
    text: str


@dataclass(frozen=True)
class JumpGroup:
    title: str
    results: tuple[JumpResult, ...]
    total: int


def _rank(keys: list[str], tokens: list[str], limit: int | None) -> tuple[list[int], int]:
    """Positions whose key contains every token: prefix matches first, then shorter keys."""
    first = tokens[0]
    if len(tokens) == 1:
        hits = [i for i, key in enumerate(keys) if first in key]
    else:
        hits = [i for i, key in enumerate(keys) if all(t in key for t in tokens)]

    def order(i: int) -> tuple[bool, int, str]:
        key = keys[i]
        prefix = key.startswith(first) or key.rsplit("\\", 1)[-1].startswith(first) or key.rsplit(".", 1)[-1].startswith(first)
        return (not prefix, len(key), key)

    best = sorted(hits, key=order) if limit is None else heapq.nsmallest(limit, hits, key=order)
    return best, len(hits)


def search_jump(ix: PermissionIndex, text: str, limit: int | None = GROUP_LIMIT, only: str | None = None) -> list[JumpGroup]:
    """
    Search principals, objects and tags.

    Args:
        ix: Index to search
        text: Whitespace-separated tokens (all must match, case-insensitive)
        limit: Results per group (None = all)
        only: Return just this group title ("Principals", "Objects", "Tags")

    Returns:
        list[JumpGroup]: Non-empty groups in order Principals, Objects, Tags
    """
    tokens = text.casefold().split()
    if not tokens:
        return []
    groups: list[JumpGroup] = []
    if only in (None, "Principals"):
        hits, total = _rank(ix.principal_search_key, tokens, limit)
        if total:
            results = tuple(JumpResult("principal", p, ix.principals[p].login_name) for p in hits)
            groups.append(JumpGroup("Principals", results, total))
    if only in (None, "Objects"):
        hits, total = _rank(ix.object_search_key, tokens, limit)
        if total:
            results = tuple(JumpResult("object", o, ix.objects[o].full_name) for o in hits)
            groups.append(JumpGroup("Objects", results, total))
    if only in (None, "Tags"):
        tags: dict[tuple[str, str], str] = {}
        for kind, entities in (("principal_tag", ix.principals), ("object_tag", ix.objects)):
            for entity in entities:
                for tag in entity.tags:
                    tags.setdefault((kind, tag.casefold()), tag)
        names = list(tags)
        keys = [key for _kind, key in names]
        hits, total = _rank(keys, tokens, limit)
        if total:
            results = tuple(
                JumpResult(
                    names[i][0],
                    names[i][1],
                    f"{tags[names[i]]} ({'principals' if names[i][0] == 'principal_tag' else 'objects'})",
                )
                for i in hits
            )
            groups.append(JumpGroup("Tags", results, total))
    return groups


class JumpDialog(QDialog):
    """
    Popup with a search field and grouped results.

    Signals:
        chosen(str, object): kind and key of the picked result
    """

    chosen = Signal(str, object)

    def __init__(self, ix_provider, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ix_provider = ix_provider
        self._expanded: set[str] = set()
        self.setWindowTitle("Jump to")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        self.search = SearchField("Jump to a principal, object or tag…", "Jump to", self)
        self.search.textChanged.connect(lambda _t: self._timer.start())
        self.search.returnPressed.connect(self._choose_current)
        self.search.installEventFilter(self)
        layout.addWidget(self.search)
        self.results = QListWidget(self)
        self.results.setAccessibleName("Jump results")
        self.results.itemActivated.connect(self._activate)
        layout.addWidget(self.results, 1)
        self.hint = QLabel("Enter opens the result. Esc closes.", self)
        layout.addWidget(self.hint)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self.update_results)

    def open_box(self) -> None:
        self.search.clear()
        self.results.clear()
        self._expanded.clear()
        self.show()
        self.raise_()
        self.activateWindow()
        self.search.setFocus()

    def update_results(self) -> None:
        self.results.clear()
        ix = self._ix_provider()
        if ix is None:
            return
        text = self.search.text()
        groups = search_jump(ix, text)
        for group in groups:
            if group.title in self._expanded:
                group = search_jump(ix, text, limit=None, only=group.title)[0]
            header = QListWidgetItem(f"{group.title} · {group.total:,}")
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            font = header.font()
            font.setBold(True)
            header.setFont(font)
            self.results.addItem(header)
            for result in group.results:
                item = QListWidgetItem(f"   {result.text}")
                item.setData(KindRole, result.kind)
                item.setData(KeyRole, result.key)
                self.results.addItem(item)
            if len(group.results) < group.total:
                more = QListWidgetItem(f"   Show all {group.total:,}")
                more.setData(KindRole, "more")
                more.setData(KeyRole, group.title)
                self.results.addItem(more)
        for row in range(self.results.count()):
            if self.results.item(row).flags() & Qt.ItemFlag.ItemIsSelectable:
                self.results.setCurrentRow(row)
                break

    def eventFilter(self, watched, event) -> bool:
        if watched is self.search and event.type() == event.Type.KeyPress:
            key_event: QKeyEvent = event
            if key_event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_PageDown, Qt.Key.Key_PageUp):
                self.results.keyPressEvent(key_event)
                return True
        return super().eventFilter(watched, event)

    def _choose_current(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self.update_results()
        item = self.results.currentItem()
        if item is not None:
            self._activate(item)

    def _activate(self, item: QListWidgetItem) -> None:
        kind = item.data(KindRole)
        if kind is None:
            return
        if kind == "more":
            self._expanded.add(item.data(KeyRole))
            self.update_results()
            return
        self.hide()
        self.chosen.emit(kind, item.data(KeyRole))
