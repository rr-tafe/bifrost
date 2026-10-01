"""
Left pane of the split view: a searchable, filterable list of principals (By
principal mode) or objects grouped by schema (By object mode).

The models hold only integer indexes from the PermissionIndex queries; names,
counts and pending dots are read from the index when a row is painted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListView,
    QPushButton,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from src.models.db_object import ObjectType
from src.qt.theme import tokens
from src.qt.views.matrix.chips import ChipButton, MultiSelectChip
from src.qt.views.matrix.grid_model import OBJECT_BADGES, PRINCIPAL_TYPE_NAMES
from src.qt.widgets.search_field import SearchField
from src.services.matrix_index import ObjectQuery, PrincipalQuery

if TYPE_CHECKING:
    from PySide6.QtGui import QKeyEvent

    from src.qt.session import Session
    from src.services.matrix import MatrixChange
    from src.services.matrix_index import PermissionIndex

SELECT_DEBOUNCE_MS = 50  # holding an arrow key doesn't rebuild the grid for every row
REFILTER_DEBOUNCE_MS = 150
ROW_PADDING = 8

IndexRole = Qt.ItemDataRole.UserRole + 1  # p or o, None for headers
PendingRole = Qt.ItemDataRole.UserRole + 2
CountRole = Qt.ItemDataRole.UserRole + 3
TypeRole = Qt.ItemDataRole.UserRole + 4
HeaderRole = Qt.ItemDataRole.UserRole + 5  # schema name for header rows

PRINCIPAL_CHIPS = (("U", "Users", "Windows users"), ("G", "Groups", "Windows groups"), ("S", "SQL users", "SQL users"))
OBJECT_CHIPS = (
    (ObjectType.TABLE, "Tables"),
    (ObjectType.VIEW, "Views"),
    (ObjectType.PROCEDURE, "Procedures"),
    (ObjectType.FUNCTION, "Functions"),
)
SORTS = (("name", "Name"), ("type", "Type"), ("grants", "Most grants"))


@dataclass
class ListFilters:
    """Left-list filters for one mode (search text isn't saved between launches)."""

    text: str = ""
    types: frozenset[str] = frozenset()  # "U"/"G"/"S" or ObjectType values
    tags: frozenset[str] = frozenset()  # casefolded
    schemas: frozenset[str] = frozenset()  # casefolded (objects)
    has_pending: bool = False
    sort: str = "name"
    extra: dict = field(default_factory=dict)

    def active(self) -> bool:
        return bool(self.text.strip() or self.types or self.tags or self.schemas or self.has_pending)


# --- Models ---------------------------------------------------------------------------


class PrincipalListModel(QAbstractListModel):
    """Principals from index.query_principals."""

    def __init__(self, session: Session, parent=None) -> None:
        super().__init__(parent)
        self.session = session
        self.items: list[int] = []
        self.row_of: dict[int, int] = {}

    @property
    def ix(self) -> PermissionIndex:
        return self.session.matrix.index

    def set_items(self, items: list[int]) -> None:
        self.beginResetModel()
        self.items = items
        self.row_of = {p: r for r, p in enumerate(items)}
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.items)

    def entity_at(self, row: int) -> int | None:
        return self.items[row] if 0 <= row < len(self.items) else None

    def row_for(self, entity: int) -> int | None:
        return self.row_of.get(entity)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        p = self.items[index.row()]
        ix = self.ix
        user = ix.principals[p]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.AccessibleTextRole):
            if role == Qt.ItemDataRole.AccessibleTextRole:
                counts = ix.principal_counts(p)
                kind = PRINCIPAL_TYPE_NAMES.get(user.principal_type, user.principal_type)
                text = f"{user.login_name}, {kind}, {counts.grants:,} grants"
                return f"{text}, {counts.pending:,} pending" if counts.pending else text
            return user.login_name
        if role == IndexRole:
            return p
        if role == TypeRole:
            return user.principal_type
        if role == PendingRole:
            return ix.principal_counts(p).pending
        if role == CountRole:
            return ix.principal_counts(p).grants
        if role == Qt.ItemDataRole.ToolTipRole:
            counts = ix.principal_counts(p)
            kind = PRINCIPAL_TYPE_NAMES.get(user.principal_type, user.principal_type)
            tags = f"\nTags: {', '.join(user.tags)}" if user.tags else ""
            return (
                f"{user.login_name}\n{kind}{tags}\n"
                f"{counts.grants:,} grants · {counts.denies:,} denies · {counts.pending:,} pending"
            )
        return None

    def refresh_entities(self, entities: set[int]) -> None:
        for entity in entities:
            row = self.row_of.get(entity)
            if row is not None:
                index = self.index(row)
                self.dataChanged.emit(index, index)


class ObjectListModel(QAbstractListModel):
    """Objects grouped by schema: header rows ("sales · 86") and object rows."""

    def __init__(self, session: Session, parent=None) -> None:
        super().__init__(parent)
        self.session = session
        self.entries: list[tuple] = []  # ("header", schema, count) or ("object", o)
        self.row_of: dict[int, int] = {}
        self.collapsed: set[str] = set()
        self._objects: list[int] = []

    @property
    def ix(self) -> PermissionIndex:
        return self.session.matrix.index

    @property
    def items(self) -> list[int]:
        return self._objects

    def set_items(self, objects: list[int]) -> None:
        self._objects = objects
        self._rebuild_entries()

    def _rebuild_entries(self) -> None:
        self.beginResetModel()
        entries: list[tuple] = []
        objects = self._objects
        for span in self.ix.group_by_schema(objects) if objects else []:
            entries.append(("header", span.schema, span.end - span.start))
            if span.schema not in self.collapsed:
                entries.extend(("object", o) for o in objects[span.start : span.end])
        self.entries = entries
        self.row_of = {entry[1]: r for r, entry in enumerate(entries) if entry[0] == "object"}
        self.endResetModel()

    def toggle(self, schema: str) -> None:
        if schema in self.collapsed:
            self.collapsed.discard(schema)
        else:
            self.collapsed.add(schema)
        self._rebuild_entries()

    def expand_for(self, o: int) -> None:
        schema = self.ix.objects[o].schema_name
        if schema in self.collapsed:
            self.collapsed.discard(schema)
            self._rebuild_entries()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.entries)

    def entity_at(self, row: int) -> int | None:
        if 0 <= row < len(self.entries) and self.entries[row][0] == "object":
            return self.entries[row][1]
        return None

    def row_for(self, entity: int) -> int | None:
        return self.row_of.get(entity)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if index.isValid() and self.entries[index.row()][0] == "header":
            return Qt.ItemFlag.ItemIsEnabled
        return super().flags(index)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        entry = self.entries[index.row()]
        if entry[0] == "header":
            _kind, schema, count = entry
            state = "collapsed" if schema in self.collapsed else "expanded"
            if role == Qt.ItemDataRole.DisplayRole:
                return f"{schema} · {count:,}"
            if role == Qt.ItemDataRole.AccessibleTextRole:
                return f"{schema} schema, {count:,} objects, {state}"
            if role == HeaderRole:
                return schema
            return None
        o = entry[1]
        ix = self.ix
        obj = ix.objects[o]
        if role == Qt.ItemDataRole.DisplayRole:
            return obj.object_name
        if role == Qt.ItemDataRole.AccessibleTextRole:
            count = len(ix.principals_by_object[o])
            return f"{obj.full_name}, {obj.object_type.value.lower()}, {count:,} principals with access"
        if role == IndexRole:
            return o
        if role == TypeRole:
            return OBJECT_BADGES.get(obj.object_type.value, "?")
        if role == PendingRole:
            return ix.object_counts(o).pending
        if role == CountRole:
            return len(ix.principals_by_object[o])
        if role == Qt.ItemDataRole.ToolTipRole:
            counts = ix.object_counts(o)
            tags = f"\nTags: {', '.join(obj.tags)}" if obj.tags else ""
            return (
                f"{obj.full_name}\n{obj.object_type.value.title()}{tags}\n"
                f"{len(ix.principals_by_object[o]):,} principals with access · {counts.pending:,} pending"
            )
        return None

    def refresh_entities(self, entities: set[int]) -> None:
        for entity in entities:
            row = self.row_of.get(entity)
            if row is not None:
                index = self.index(row)
                self.dataChanged.emit(index, index)


# --- Delegate and view -----------------------------------------------------------------


class EntityDelegate(QStyledItemDelegate):
    """Row: type badge, name (elided), pending dot, count right-aligned. Headers in bold."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.elide = Qt.TextElideMode.ElideMiddle
        self.row_height = 22
        self.apply_theme()

    def apply_theme(self) -> None:
        t = tokens()
        self.staged = QBrush(QColor(t.staged))
        self.badge_bg = QColor(t.surface_2)
        self.muted = QColor(t.muted)

    def sizeHint(self, option, index) -> QSize:
        return QSize(100, self.row_height)

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        self.initStyleOption(option, index)
        style = option.widget.style() if option.widget else QApplication.style()
        text = option.text
        option.text = ""
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, option, painter, option.widget)
        painter.save()
        try:
            rect = option.rect.adjusted(4, 0, -6, 0)
            selected = bool(option.state & QStyle.StateFlag.State_Selected)
            fg = option.palette.highlightedText().color() if selected else option.palette.text().color()
            if index.data(HeaderRole) is not None:
                font = QFont(option.font)
                font.setBold(True)
                painter.setFont(font)
                painter.setPen(fg)
                schema = index.data(HeaderRole)
                arrow = "▸" if schema in getattr(index.model(), "collapsed", ()) else "▾"
                painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, f"{arrow} {text}")
                return
            size = rect.height() - 8
            badge = QRect(rect.left(), rect.top() + 4, size + 4, size)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.badge_bg)
            painter.drawRoundedRect(badge, 3, 3)
            small = QFont(option.font)
            small.setPointSizeF(max(option.font.pointSizeF() * 0.8, 6))
            small.setBold(True)
            painter.setFont(small)
            painter.setPen(self.muted)
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(index.data(TypeRole) or ""))
            painter.setFont(option.font)
            count = index.data(CountRole) or 0
            count_text = f"{count:,}"
            metrics = option.fontMetrics
            count_width = metrics.horizontalAdvance(count_text)
            painter.setPen(fg if selected else self.muted)
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, count_text)
            right = rect.right() - count_width - 8
            if index.data(PendingRole):
                dot = QRect(right - 6, rect.center().y() - 3, 6, 6)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(self.staged)
                painter.drawEllipse(dot)
                right = dot.left() - 6
            name_rect = QRect(badge.right() + 6, rect.top(), max(right - badge.right() - 6, 10), rect.height())
            painter.setPen(fg)
            painter.drawText(
                name_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                metrics.elidedText(text, self.elide, name_rect.width()),
            )
        finally:
            painter.restore()


class EntityListView(QListView):
    """
    QListView with the list keys from spec section 9.2.

    Signals:
        focusGridRequested: Enter or Right on an entity
        typed(str): a printable key was pressed (moves to the search box)
        headerToggled(str): Enter/Left/Right or a click on a schema header
    """

    focusGridRequested = Signal()
    typed = Signal(str)
    headerToggled = Signal(str)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        index = self.currentIndex()
        schema = index.data(HeaderRole) if index.isValid() else None
        if schema is not None and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Left, Qt.Key.Key_Right):
            collapsed = schema in getattr(self.model(), "collapsed", ())
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) or (key == Qt.Key.Key_Left) != collapsed:
                self.headerToggled.emit(schema)
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Right):
            self.focusGridRequested.emit()
            return
        text = event.text()
        if text and text.isprintable() and not text.isspace() and not (
            event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
        ):
            self.typed.emit(text)
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        index = self.indexAt(event.position().toPoint())
        schema = index.data(HeaderRole) if index.isValid() else None
        if schema is not None and event.button() == Qt.MouseButton.LeftButton:
            self.setCurrentIndex(index)
            self.headerToggled.emit(schema)
            return
        super().mousePressEvent(event)


# --- Pane --------------------------------------------------------------------------------


class EntityListPane(QWidget):
    """
    Search, chips, sort, list and footer for one mode.

    Signals:
        entityChanged(object): selected p / o (or None), debounced
        focusGridRequested: user pressed Enter/Right in the list
        filtersChanged: any filter changed (for saving view state)
    """

    entityChanged = Signal(object)
    focusGridRequested = Signal()
    filtersChanged = Signal()

    def __init__(self, session: Session, mode: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self.mode = mode
        self.filters = ListFilters()
        self._entity: int | None = None
        self._pending_entity: int | None = None  # chosen in the list, shown after the debounce
        principal = mode == "principal"
        noun = "principals" if principal else "objects"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        self.search = SearchField(f"Search {noun}…", f"Search {noun}", self)
        self.search.searchChanged.connect(self._on_search)
        layout.addWidget(self.search)

        chips = QHBoxLayout()
        chips.setSpacing(4)
        self.type_chips: dict[str, ChipButton] = {}
        if principal:
            for key, text, tip in PRINCIPAL_CHIPS:
                chip = ChipButton(text, text, tip, self)
                self.type_chips[key] = chip
        else:
            for object_type, text in OBJECT_CHIPS:
                chip = ChipButton(text, text, parent=self)
                self.type_chips[object_type.value] = chip
        for chip in self.type_chips.values():
            chip.toggled.connect(lambda _checked: self._on_chips())
            chips.addWidget(chip)
        chips.addStretch(1)
        layout.addLayout(chips)

        row = QHBoxLayout()
        row.setSpacing(4)
        self.pending_chip = ChipButton("Has pending", "Has pending", f"Only {noun} with staged changes", self)
        self.pending_chip.toggled.connect(lambda _checked: self._on_chips())
        row.addWidget(self.pending_chip)
        self.tags_chip = MultiSelectChip("Tags", self)
        self.tags_chip.changed.connect(lambda _keys: self._on_chips())
        row.addWidget(self.tags_chip)
        self.schema_chip: MultiSelectChip | None = None
        self.sort_box: QComboBox | None = None
        if principal:
            self.sort_box = QComboBox(self)
            self.sort_box.setAccessibleName("Sort principals")
            for key, text in SORTS:
                self.sort_box.addItem(f"Sort: {text}", key)
            self.sort_box.currentIndexChanged.connect(lambda _i: self._on_chips())
            row.addWidget(self.sort_box)
        else:
            self.schema_chip = MultiSelectChip("Schema", self)
            self.schema_chip.changed.connect(lambda _keys: self._on_chips())
            row.addWidget(self.schema_chip)
        row.addStretch(1)
        layout.addLayout(row)

        self.model = PrincipalListModel(session, self) if principal else ObjectListModel(session, self)
        self.list = EntityListView(self)
        self.list.setModel(self.model)
        self.list.setUniformItemSizes(True)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list.setAccessibleName("Principals" if principal else "Objects")
        self.delegate = EntityDelegate(self.list)
        self.delegate.elide = Qt.TextElideMode.ElideMiddle if principal else Qt.TextElideMode.ElideRight
        self.delegate.row_height = self.list.fontMetrics().height() + ROW_PADDING
        self.list.setItemDelegate(self.delegate)
        self.list.selectionModel().currentChanged.connect(lambda current, _prev: self._on_current(current))
        self.list.focusGridRequested.connect(self.focusGridRequested)
        self.list.typed.connect(self._type_into_search)
        self.list.headerToggled.connect(self._toggle_header)

        self.empty = QWidget(self)
        empty_layout = QVBoxLayout(self.empty)
        self.empty_label = QLabel(f"No {noun} match.", self.empty)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        clear = QPushButton("Clear filters", self.empty)
        clear.clicked.connect(self.clear_filters)
        empty_layout.addStretch(1)
        empty_layout.addWidget(self.empty_label)
        empty_layout.addWidget(clear, 0, Qt.AlignmentFlag.AlignCenter)
        empty_layout.addStretch(2)
        self.stack = QStackedWidget(self)
        self.stack.addWidget(self.list)
        self.stack.addWidget(self.empty)
        layout.addWidget(self.stack, 1)

        self.footer = QLabel("", self)
        self.footer.setAccessibleName(f"{noun.title()} count")
        layout.addWidget(self.footer)

        self._select_timer = QTimer(self)
        self._select_timer.setSingleShot(True)
        self._select_timer.setInterval(SELECT_DEBOUNCE_MS)
        self._select_timer.timeout.connect(self._emit_entity)
        self._refilter_timer = QTimer(self)
        self._refilter_timer.setSingleShot(True)
        self._refilter_timer.setInterval(REFILTER_DEBOUNCE_MS)
        self._refilter_timer.timeout.connect(self.refresh)

    # --- Public ------------------------------------------------------------------------

    @property
    def entity(self) -> int | None:
        return self._entity

    def reload(self) -> None:
        """Data was (re)loaded or tags changed: refresh tag/schema options and the list."""
        if self.session.matrix is None:
            return
        self._refresh_options()
        self.refresh()

    def refresh(self) -> None:
        """Re-run the query, keeping the selected entity if it still matches."""
        if self.session.matrix is None:
            return
        ix = self.session.matrix.index
        f = self.filters
        if self.mode == "principal":
            items = ix.query_principals(
                PrincipalQuery(text=f.text, types=f.types, tags=f.tags, has_pending=f.has_pending, sort=f.sort)
            )
            total = len(ix.principals)
        else:
            items = ix.query_objects(
                ObjectQuery(
                    text=f.text,
                    schemas=f.schemas,
                    types=frozenset(ObjectType(t) for t in f.types),
                    tags=f.tags,
                )
            )
            if f.has_pending:
                pending = ix.object_pending
                items = [o for o in items if pending(o)]
            total = len(ix.objects)
        keep = self._entity
        self.model.set_items(items)
        noun = "principals" if self.mode == "principal" else "objects"
        shown = len(items)
        self.footer.setText(f"{total:,} {noun}" if shown == total else f"{shown:,} of {total:,} {noun}")
        self.search.setPlaceholderText(f"Search {total:,} {noun}…")
        self.stack.setCurrentWidget(self.list if items else self.empty)
        if keep is not None and keep in set(items) and self.model.row_for(keep) is not None:
            self._select_row(keep, emit=False)
        elif items:
            self._select_row(items[0] if self.mode == "principal" else self._first_entity(), emit=True)
        else:
            self._set_entity(None)

    def select_entity(self, entity: int, clear_hiding_filters: bool = True) -> bool:
        """Select an entity, clearing left-list filters only if they hide it. Returns True if shown."""
        if entity not in set(self.model.items) and clear_hiding_filters:
            self.clear_filters(refresh=False)
            self.refresh()
        if isinstance(self.model, ObjectListModel):
            self.model.expand_for(entity)
        if self.model.row_for(entity) is None:
            return False
        self._select_row(entity, emit=False)
        self._set_entity(entity)
        return True

    def clear_filters(self, refresh: bool = True) -> None:
        self.filters = ListFilters(sort=self.filters.sort)
        self._sync_controls()
        if refresh:
            self.refresh()
        self.filtersChanged.emit()

    def add_tag_filter(self, tag: str) -> None:
        self.tags_chip.add(tag.casefold())

    def on_matrix_change(self, change: MatrixChange) -> None:
        if change.rows is None:
            self.reload()
            return
        entities = {p for p, _o in change.rows} if self.mode == "principal" else {o for _p, o in change.rows}
        self.model.refresh_entities(entities)
        if self.filters.has_pending:
            self._refilter_timer.start()

    def focus_list(self) -> None:
        self.list.setFocus(Qt.FocusReason.OtherFocusReason)

    # --- Saved state ---------------------------------------------------------------------

    def get_state(self) -> dict:
        f = self.filters
        return {
            "types": sorted(f.types),
            "tags": sorted(f.tags),
            "schemas": sorted(f.schemas),
            "has_pending": f.has_pending,
            "sort": f.sort,
        }

    def restore(self, state: dict, entity: int | None) -> None:
        """Apply saved filters and the entity to select on the next refresh (after data loads)."""
        self._refresh_options()
        self.set_state(state)
        self._refresh_options()  # drops saved tags/schemas that no longer exist
        if entity is not None:
            self._entity = entity

    def set_state(self, state: dict) -> None:
        sort = state.get("sort", "name")
        self.filters = ListFilters(
            types=frozenset(state.get("types", ())) & frozenset(self.type_chips),
            tags=frozenset(state.get("tags", ())),
            schemas=frozenset(state.get("schemas", ())),
            has_pending=bool(state.get("has_pending", False)),
            sort=sort if sort in {k for k, _ in SORTS} else "name",
        )
        self._sync_controls()

    # --- Internals ---------------------------------------------------------------------

    def _first_entity(self) -> int | None:
        for row in range(self.model.rowCount()):
            entity = self.model.entity_at(row)
            if entity is not None:
                return entity
        return None

    def _select_row(self, entity: int | None, emit: bool) -> None:
        if entity is None:
            return
        row = self.model.row_for(entity)
        if row is None:
            return
        index = self.model.index(row)
        selection = self.list.selectionModel()
        selection.blockSignals(True)
        selection.setCurrentIndex(index, selection.SelectionFlag.ClearAndSelect)
        selection.blockSignals(False)
        self.list.viewport().update()
        self.list.scrollTo(index)
        if emit:
            self._set_entity(entity)

    def _on_current(self, current: QModelIndex) -> None:
        entity = self.model.entity_at(current.row()) if current.isValid() else None
        if entity is None:
            return  # a header row: keep the grid on the previous entity
        self._pending_entity = entity
        self._select_timer.start()

    def _emit_entity(self) -> None:
        self._set_entity(self._pending_entity)

    def _set_entity(self, entity: int | None) -> None:
        self._select_timer.stop()
        if entity != self._entity:
            self._entity = entity
            self.entityChanged.emit(entity)

    def _type_into_search(self, text: str) -> None:
        self.search.setFocus(Qt.FocusReason.OtherFocusReason)
        self.search.insert(text)

    def _toggle_header(self, schema: str) -> None:
        if isinstance(self.model, ObjectListModel):
            self.model.toggle(schema)
            for row, entry in enumerate(self.model.entries):
                if entry[0] == "header" and entry[1] == schema:
                    self.list.setCurrentIndex(self.model.index(row))
                    break
            entity = self._entity
            if entity is not None and self.model.row_for(entity) is not None:
                selection = self.list.selectionModel()
                selection.select(self.model.index(self.model.row_for(entity)), selection.SelectionFlag.Select)

    def _on_search(self, text: str) -> None:
        self.filters.text = text
        self.refresh()

    def _on_chips(self) -> None:
        f = self.filters
        f.types = frozenset(k for k, chip in self.type_chips.items() if chip.isChecked())
        f.has_pending = self.pending_chip.isChecked()
        f.tags = self.tags_chip.selected
        if self.schema_chip is not None:
            f.schemas = self.schema_chip.selected
        if self.sort_box is not None:
            f.sort = self.sort_box.currentData() or "name"
        self.refresh()
        self.filtersChanged.emit()

    def _sync_controls(self) -> None:
        f = self.filters
        for key, chip in self.type_chips.items():
            chip.set_checked_quietly(key in f.types)
        self.pending_chip.set_checked_quietly(f.has_pending)
        self.tags_chip.set_selected(f.tags)
        if self.schema_chip is not None:
            self.schema_chip.set_selected(f.schemas)
        if self.sort_box is not None:
            self.sort_box.blockSignals(True)
            row = self.sort_box.findData(f.sort)
            self.sort_box.setCurrentIndex(max(row, 0))
            self.sort_box.blockSignals(False)
        self.search.blockSignals(True)
        self.search.setText(f.text)
        self.search.blockSignals(False)

    def _refresh_options(self) -> None:
        ix = self.session.matrix.index
        self.tags_chip.set_options(tag_options(ix, self.mode))
        if self.schema_chip is not None:
            schemas: dict[str, tuple[str, int]] = {}
            for span in ix.schema_spans:
                key = span.schema.casefold()
                name, count = schemas.get(key, (span.schema, 0))
                schemas[key] = (name, count + span.end - span.start)
            self.schema_chip.set_options((key, f"{name} ({count:,})") for key, (name, count) in schemas.items())
        # Selected keys that no longer exist were dropped by set_options
        self.filters.tags = self.tags_chip.selected
        if self.schema_chip is not None:
            self.filters.schemas = self.schema_chip.selected


def tag_options(ix: PermissionIndex, mode: str) -> list[tuple[str, str]]:
    """(casefolded tag, "Label (count)") for principals or objects, sorted by name."""
    counts: dict[str, list] = {}
    entities = ix.principals if mode == "principal" else ix.objects
    for entity in entities:
        for tag in entity.tags:
            key = tag.casefold()
            entry = counts.setdefault(key, [tag, 0])
            entry[1] += 1
    return [(key, f"{name} ({count:,})") for key, (name, count) in sorted(counts.items())]
