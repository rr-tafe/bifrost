"""
PermissionGrid: the right-hand grid of the split view.

A QTableView over the flat GridModel (group headers are spanned rows). Click selects (it never changes a cell); double-click
or Space cycles one cell; G / D / R / U set the selection. Every edit goes
through MatrixEditor, which applies the selection limit, FR-030 confirmation and
the FR-017a privilege check.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    QPoint,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMenu,
    QStyle,
    QStyleOptionHeader,
    QTableView,
    QWidget,
)

from src.models.permission import PermissionState
from src.qt.views.matrix import bulk
from src.qt.views.matrix.cell_delegate import ROW_PADDING, CellDelegate
from src.qt.views.matrix.grid_model import COLUMN_COUNT, SHORT_NAMES, STATE_NAMES, GridModel
from src.services.matrix import CellRef
from src.services.matrix_index import PERM_COUNT, PERMS, cell_code

if TYPE_CHECKING:
    from PySide6.QtGui import QContextMenuEvent, QKeyEvent, QMouseEvent

    from src.qt.views.matrix.editing import MatrixEditor

CELL_WIDTH = 52
FLASH_MS = 160
Select = QItemSelectionModel.SelectionFlag

_STATE_KEYS = {
    Qt.Key.Key_G: PermissionState.GRANT,
    Qt.Key.Key_D: PermissionState.DENY,
    Qt.Key.Key_R: PermissionState.NONE,
    Qt.Key.Key_Delete: PermissionState.NONE,
    Qt.Key.Key_Backspace: PermissionState.NONE,
}
_VERBS = ((PermissionState.GRANT, "Grant", "G"), (PermissionState.DENY, "Deny", "D"), (PermissionState.NONE, "Revoke", "R"))


class GridHeaderView(QHeaderView):
    """
    Column header that paints sections without asking about selection.

    QHeaderView.paintSection checks whether the neighbouring columns are fully
    selected, which scans every row through the model (~50 ms at 20,000 rows)
    on each header repaint. The grid never shows column selection in the header,
    so this paints the section from its text alone.
    """

    def paintSection(self, painter, rect, logical_index: int) -> None:
        if not rect.isValid():
            return
        option = QStyleOptionHeader()
        self.initStyleOption(option)
        option.rect = rect
        option.section = logical_index
        option.text = str(self.model().headerData(logical_index, self.orientation()) or "")
        option.textAlignment = Qt.AlignmentFlag.AlignCenter if logical_index else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        option.state |= QStyle.StateFlag.State_Enabled
        option.position = QStyleOptionHeader.SectionPosition.Middle
        self.style().drawControl(QStyle.ControlElement.CE_Header, option, painter, self)


class PermissionGrid(QTableView):
    """
    Grid of one principal's (or object's) permissions.

    Signals:
        selectionCountChanged(int): applicable cells selected (debounced)
    """

    selectionCountChanged = Signal(int)

    def __init__(self, model: GridModel, editor: MatrixEditor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.grid_model = model
        self.editor = editor
        self.cell_delegate = CellDelegate(self)
        self.setModel(model)
        self.setItemDelegate(self.cell_delegate)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setCornerButtonEnabled(False)
        self.setAlternatingRowColors(False)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSortingEnabled(False)
        self.setTabKeyNavigation(False)
        self.setAccessibleName("Permissions grid")
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        self.verticalHeader().hide()
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        # Highlighting makes the header ask whether the whole row is selected each time the
        # current cell moves, which calls flags() for every row (~50 ms at 20,000 rows).
        self.verticalHeader().setHighlightSections(False)
        self.apply_font()

        self.setHorizontalHeader(GridHeaderView(Qt.Orientation.Horizontal, self))
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionsClickable(True)
        header.setSectionsMovable(False)
        header.setHighlightSections(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setMinimumSectionSize(40)
        metrics = header.fontMetrics()
        for column in range(1, COLUMN_COUNT):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            width = max(CELL_WIDTH, metrics.horizontalAdvance(SHORT_NAMES[PERMS[column - 1]]) + 16)
            header.resizeSection(column, width)
        header.sectionClicked.connect(self._on_header_clicked)

        model.rebuilt.connect(self._after_rebuild)
        model.rowsInserted.connect(lambda *_: self._apply_spans())
        model.rowsRemoved.connect(lambda *_: self._apply_spans())

        self._count_timer = QTimer(self)
        self._count_timer.setSingleShot(True)
        self._count_timer.setInterval(80)
        self._count_timer.timeout.connect(lambda: self.selectionCountChanged.emit(self.selection_count()))
        self._flash_timer = QTimer(self)
        self._flash_timer.setInterval(FLASH_MS)
        self._flash_timer.timeout.connect(self._flash_step)
        self._flash_steps = 0
        self.selectionModel().selectionChanged.connect(lambda *_: self._count_timer.start())

    # --- Setup -----------------------------------------------------------------------

    def apply_font(self) -> None:
        height = self.fontMetrics().height() + ROW_PADDING
        self.cell_delegate.set_font(self.font(), height)
        self.verticalHeader().setDefaultSectionSize(height)
        self.verticalHeader().setMinimumSectionSize(height)

    def set_read_only(self, read_only: bool) -> None:
        if self.cell_delegate.read_only != read_only:
            self.cell_delegate.read_only = read_only
            self.viewport().update()

    def _after_rebuild(self) -> None:
        """Span group rows and hide columns that don't apply."""
        self._apply_spans()
        mask = self.grid_model.applicable_mask()
        for column in range(1, COLUMN_COUNT):
            self.setColumnHidden(column, not mask & (1 << (column - 1)))

    def _apply_spans(self) -> None:
        self.clearSpans()
        for row in self.grid_model.header_rows:
            self.setSpan(row, 0, 1, COLUMN_COUNT)

    # --- Selection -------------------------------------------------------------------

    def _ranges(self):
        """(group, first position, last position, left, right) for each selected item run."""
        model = self.grid_model
        for rng in self.selectionModel().selection():
            left, right = max(rng.left(), 1), rng.right()
            if right < left:
                continue
            for g, first, last in model.segments(rng.top(), rng.bottom()):
                yield g, first, last, left, right

    def selection_count(self) -> int:
        """Applicable cells selected (no allocation per cell)."""
        model = self.grid_model
        if model.entity is None:
            return 0
        applicable = model.ix.object_applicable
        total = 0
        for g, top, bottom, left, right in self._ranges():
            columns = sum(1 << (c - 1) for c in range(left, right + 1))
            rows = model.groups[g].rows
            if model.mode == "object":
                total += (bottom - top + 1) * (applicable[model.entity] & columns).bit_count()
            else:
                total += sum((applicable[rows[r]] & columns).bit_count() for r in range(top, bottom + 1))
        return total

    def selected_cells(self) -> list[CellRef]:
        """Applicable selected cells, in grid order, without duplicates."""
        model = self.grid_model
        if model.entity is None:
            return []
        applicable = model.ix.object_applicable
        cells: dict[CellRef, None] = {}
        for g, top, bottom, left, right in sorted(self._ranges()):
            for r in range(top, bottom + 1):
                p, o = model.pair(g, r)
                mask = applicable[o]
                for column in range(left, right + 1):
                    if mask & (1 << (column - 1)):
                        cells[CellRef(p, o, column - 1)] = None
        return list(cells)

    def selected_rows(self) -> list[tuple[int, int]]:
        """(p, o) of every row with a selected cell."""
        rows: dict[tuple[int, int], None] = {}
        for g, top, bottom, _left, _right in sorted(self._ranges()):
            for r in range(top, bottom + 1):
                rows[self.grid_model.pair(g, r)] = None
        return list(rows)

    def _select(self, ranges: list[tuple[int, int, int, int]], add: bool = False) -> None:
        """Select (top row, bottom row, left column, right column) ranges of table rows."""
        model = self.grid_model
        selection = QItemSelection()
        for top, bottom, left, right in ranges:
            if bottom >= top:
                selection.select(model.index(top, left), model.index(bottom, right))
        flags = Select.Select if add else Select.ClearAndSelect
        self.selectionModel().select(selection, flags)

    def _item_ranges(self, left: int, right: int) -> list[tuple[int, int, int, int]]:
        """One range per expanded group, so group header rows aren't included."""
        model = self.grid_model
        return [(first, last, left, right) for first, last in (model.item_rows(g) for g in range(len(model.groups)))]

    def select_column(self, column: int) -> None:
        """Select a permission column for every visible row (collapsed groups excluded)."""
        self._select(self._item_ranges(column, column))
        first = self._first_applicable_in_column(column)
        if first.isValid():
            self.selectionModel().setCurrentIndex(first, Select.NoUpdate)

    def select_all_cells(self) -> None:
        """Ctrl+A: every applicable cell in visible rows."""
        self._select(self._item_ranges(1, PERM_COUNT))

    def select_row(self, index: QModelIndex, add: bool = False) -> None:
        row = index.row()
        self._select([(row, row, 1, PERM_COUNT)], add)
        first = self._step_in_row(index.siblingAtColumn(0), +1)
        if first.isValid():
            self.selectionModel().setCurrentIndex(first, Select.NoUpdate)

    def select_group(self, g: int) -> None:
        first, last = self.grid_model.item_rows(g)
        self._select([(first, last, 1, PERM_COUNT)])

    def _first_applicable_in_column(self, column: int) -> QModelIndex:
        model = self.grid_model
        applicable = model.ix.object_applicable
        for g in range(len(model.groups)):
            first, last = model.item_rows(g)
            for row in range(first, last + 1):
                if applicable[model.pair(g, row - first)[1]] & (1 << (column - 1)):
                    return model.index(row, column)
        return QModelIndex()

    # --- Keyboard navigation ---------------------------------------------------------

    def _applicable(self, index: QModelIndex) -> bool:
        return self.grid_model.cell_at(index) is not None

    def _step_in_row(self, index: QModelIndex, step: int, start: int | None = None) -> QModelIndex:
        """Next applicable, visible cell left (-1) or right (+1) in the same row, from column `start`."""
        column = (index.column() if start is None else start) + step
        while 1 <= column < COLUMN_COUNT:
            candidate = self.grid_model.index(index.row(), column)
            if not self.isColumnHidden(column) and self._applicable(candidate):
                return candidate
            column += step
        return QModelIndex()

    def _step_vertical(self, index: QModelIndex, step: int) -> QModelIndex:
        """Next row up/down. Cell columns skip group rows and cells that don't apply."""
        column = index.column()
        model = self.grid_model
        row = index.row()
        rows = model.rowCount()
        while True:
            row += step
            if not 0 <= row < rows:
                return QModelIndex()
            if column == 0:
                return model.index(row, 0)
            if model.is_group_row(row):
                continue
            candidate = model.index(row, column)
            if self._applicable(candidate):
                return candidate

    def _settle(self, index: QModelIndex, column: int, step: int) -> QModelIndex:
        """Move index to an applicable cell in `column`, searching rows in direction step."""
        if not index.isValid():
            return index
        if column == 0:
            return index.siblingAtColumn(0)
        if self.grid_model.is_group(index) or not self._applicable(index.siblingAtColumn(column)):
            moved = self._step_vertical(index.siblingAtColumn(column), step)
            return moved if moved.isValid() else self._step_vertical(index.siblingAtColumn(column), -step)
        return index.siblingAtColumn(column)

    def moveCursor(self, action: QAbstractItemView.CursorAction, modifiers: Qt.KeyboardModifier) -> QModelIndex:
        current = self.currentIndex()
        A = QAbstractItemView.CursorAction  # noqa: N806 - short alias for readability
        if not current.isValid():
            return super().moveCursor(action, modifiers)
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        column = current.column()
        on_group = self.grid_model.is_group(current)
        if action in (A.MoveLeft, A.MoveRight):
            if on_group:
                return current
            step = -1 if action == A.MoveLeft else 1
            target = self._step_in_row(current, step)
            if not target.isValid() and step < 0:
                return current.siblingAtColumn(0)
            return target if target.isValid() else current
        if action in (A.MoveUp, A.MoveDown):
            target = self._step_vertical(current, -1 if action == A.MoveUp else 1)
            return target if target.isValid() else current
        if action in (A.MoveHome, A.MoveEnd) and not ctrl:
            if on_group:
                return current
            if action == A.MoveHome:
                target = self._step_in_row(current, +1, start=0)
            else:
                target = self._step_in_row(current, -1, start=COLUMN_COUNT)
            return target if target.isValid() else current
        if action in (A.MoveHome, A.MoveEnd, A.MovePageUp, A.MovePageDown):
            target = super().moveCursor(action, modifiers)
            step = -1 if action in (A.MoveEnd, A.MovePageUp) else 1
            settled = self._settle(target, column if not on_group else 0, step)
            return settled if settled.isValid() else current
        return super().moveCursor(action, modifiers)

    # --- Keys ------------------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        modifiers = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        plain = modifiers in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier)
        if key in _STATE_KEYS and plain and not (key == Qt.Key.Key_R and modifiers):
            self.editor.set_state(self.selected_cells(), _STATE_KEYS[key])
            return
        if key == Qt.Key.Key_U and modifiers == Qt.KeyboardModifier.NoModifier:
            self.editor.revert(self.selected_cells())
            return
        if key == Qt.Key.Key_Space and modifiers == Qt.KeyboardModifier.NoModifier:
            self._space()
            return
        if key == Qt.Key.Key_Escape and modifiers == Qt.KeyboardModifier.NoModifier:
            self.clearSelection()  # never discards anything
            return
        if event.matches(QKeySequence.StandardKey.SelectAll):
            self.select_all_cells()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.grid_model.is_group(self.currentIndex()):
            self._toggle_group(self.currentIndex())
            return
        if key == Qt.Key.Key_Menu or (key == Qt.Key.Key_F10 and modifiers == Qt.KeyboardModifier.ShiftModifier):
            self._menu_at_current()
            return
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_selection()
            return
        super().keyPressEvent(event)

    def _space(self) -> None:
        cells = self.selected_cells()
        current = self.grid_model.cell_at(self.currentIndex())
        if len(cells) > 1:
            self._menu_at_current()
        elif cells:
            self.editor.cycle(cells[0])
        elif current is not None:
            self.editor.cycle(current)

    def _menu_at_current(self) -> None:
        index = self.currentIndex()
        rect = self.visualRect(index) if index.isValid() else self.viewport().rect()
        self._show_menu(index, self.viewport().mapToGlobal(rect.center()))

    # --- Mouse -----------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        index = self.indexAt(event.position().toPoint())
        if event.button() != Qt.MouseButton.LeftButton or not index.isValid():
            super().mousePressEvent(event)
            return
        model = self.grid_model
        modifiers = event.modifiers()
        if model.is_group(index):
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.selectionModel().setCurrentIndex(index.siblingAtColumn(0), Select.NoUpdate)
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                self.select_group(model.group_of(index))
            else:
                self._toggle_group(index)
            return
        if index.column() == 0:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.select_row(index, add=bool(modifiers & Qt.KeyboardModifier.ControlModifier))
            return
        if not self._applicable(index):
            return  # cells that don't apply can't be selected or focused
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        index = self.indexAt(event.position().toPoint())
        cell = self.grid_model.cell_at(index)
        if event.button() == Qt.MouseButton.LeftButton and cell is not None:
            self.editor.cycle(cell)
            return
        if self.grid_model.is_group(index):
            return  # the press already toggled it
        super().mouseDoubleClickEvent(event)

    def _toggle_group(self, index: QModelIndex) -> None:
        model = self.grid_model
        g = model.group_of(index)
        model.set_collapsed(g, not model.is_collapsed(g))
        self.selectionModel().setCurrentIndex(model.group_index(g), Select.NoUpdate)

    def _on_header_clicked(self, column: int) -> None:
        if column >= 1:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.select_column(column)

    # --- Context menu ----------------------------------------------------------------

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        index = self.indexAt(event.pos())
        if index.isValid() and self._applicable(index) and not self.selectionModel().isSelected(index):
            self.selectionModel().setCurrentIndex(index, Select.ClearAndSelect)
        self._show_menu(index if index.isValid() else self.currentIndex(), event.globalPos())

    def build_menu(self, index: QModelIndex) -> QMenu:
        """Context menu for a group row or for the selection."""
        if self.grid_model.is_group(index):
            return self._group_menu(self.grid_model.group_of(index))
        return self._selection_menu()

    def _show_menu(self, index: QModelIndex, position: QPoint) -> None:
        menu = self.build_menu(index)
        menu.exec(position)
        menu.deleteLater()

    def _selection_menu(self) -> QMenu:
        menu = QMenu(self)
        cells = self.selected_cells()
        ix = self.grid_model.ix if self.grid_model.entity is not None else None
        editable = self.editor.session.can_edit and bool(cells)
        for state, verb, key in _VERBS:
            text = verb
            if cells and ix is not None:
                text = bulk.describe_action(ix, bulk.items_for(cells, state))
            action = menu.addAction(f"{text}\t{key}")
            action.setEnabled(editable)
            action.triggered.connect(lambda _=False, s=state, c=cells: self.editor.set_state(c, s))
        if cells and ix is not None and any(ix.pending_mask(c.p, c.o) & (1 << c.perm) for c in cells):
            revert = menu.addAction("Revert to committed\tU")
            revert.setEnabled(editable)
            revert.triggered.connect(lambda _=False, c=cells: self.editor.revert(c))
        menu.addSeparator()
        presets = menu.addMenu("Apply preset")
        presets.setEnabled(editable)
        for name in bulk.PRESETS:
            action = presets.addAction(name)
            action.triggered.connect(lambda _=False, n=name: self.apply_preset(n))
        menu.addSeparator()
        current = self.currentIndex()
        select_row = menu.addAction("Select row")
        select_row.setEnabled(current.isValid() and not self.grid_model.is_group(current))
        select_row.triggered.connect(lambda: self.select_row(self.currentIndex()))
        select_column = menu.addAction("Select column")
        select_column.setEnabled(current.isValid() and current.column() >= 1)
        select_column.triggered.connect(lambda: self.select_column(self.currentIndex().column()))
        select_group = menu.addAction("Select group")
        select_group.setEnabled(current.isValid() and not self.grid_model.is_group(current))
        select_group.triggered.connect(lambda: self.select_group(self.grid_model.group_of(self.currentIndex())))
        menu.addSeparator()
        copy = menu.addAction("Copy")
        copy.setShortcut(QKeySequence.StandardKey.Copy)
        copy.setEnabled(bool(cells))
        copy.triggered.connect(self.copy_selection)
        return menu

    def _group_menu(self, g: int) -> QMenu:
        model = self.grid_model
        group = model.groups[g]
        menu = QMenu(self)
        editable = self.editor.session.can_edit
        mask = model.applicable_mask()
        for state, verb, _key in _VERBS:
            sub = menu.addMenu(verb)
            sub.setEnabled(editable)
            for perm in range(PERM_COUNT):
                if not mask & (1 << perm):
                    continue
                cells = self.group_cells(g, perm)
                if not cells:
                    continue
                label = self.group_action_label(g, state, perm, len(cells))
                action = sub.addAction(f"{PERMS[perm].value} — {label}")
                action.triggered.connect(
                    lambda _=False, c=cells, s=state, lbl=label: self.editor.set_state(c, s, lbl, limited=False)
                )
        menu.addSeparator()
        expanded = not model.is_collapsed(g)
        toggle = menu.addAction("Collapse" if expanded else "Expand")
        toggle.triggered.connect(lambda: self._toggle_group(model.group_index(g)))
        select = menu.addAction("Select group")
        select.setEnabled(bool(group.rows))
        select.triggered.connect(lambda: self.select_group(g))
        return menu

    def group_cells(self, g: int, perm: int) -> list[CellRef]:
        """Applicable cells for one permission across a group (current filter)."""
        model = self.grid_model
        applicable = model.ix.object_applicable
        bit = 1 << perm
        cells = []
        for r in range(len(model.groups[g].rows)):
            p, o = model.pair(g, r)
            if applicable[o] & bit:
                cells.append(CellRef(p, o, perm))
        return cells

    def group_action_label(self, g: int, state: PermissionState, perm: int, count: int) -> str:
        """E.g. "Grant SELECT on all 86 objects in sales for CORP\\jsmith"."""
        model = self.grid_model
        verb = {PermissionState.GRANT: "Grant", PermissionState.DENY: "Deny", PermissionState.NONE: "Revoke"}[state]
        group = model.groups[g]
        name = PERMS[perm].value
        if model.mode == "principal":
            login = model.ix.principals[model.entity].login_name
            return f"{verb} {name} on all {count:,} objects in {group.label} for {login}"
        target = model.ix.objects[model.entity].full_name
        return f"{verb} {name} on {target} for all {count:,} {group.label.lower()}"

    def apply_preset(self, name: str) -> None:
        rows = self.selected_rows()
        if not rows:
            return
        items = bulk.preset_items(self.grid_model.ix, rows, name)
        label = f"Apply the {name} preset to {len(rows):,} rows"
        self.editor.stage(items, label)

    # --- Copy and flash --------------------------------------------------------------

    def copy_selection(self) -> None:
        """Copy selected rows as tab-separated text: name, then the 8 permission states."""
        rows = self.selected_rows()
        if not rows:
            return
        model = self.grid_model
        ix = model.ix
        lines = ["\t".join(["Name", *(p.value for p in PERMS)])]
        for p, o in rows:
            name = ix.objects[o].full_name if model.mode == "principal" else ix.principals[p].login_name
            packed = ix.row_state(p, o)
            states = [
                STATE_NAMES[cell_code(packed, perm)] if ix.object_applicable[o] & (1 << perm) else ""
                for perm in range(PERM_COUNT)
            ]
            lines.append("\t".join([name, *states]))
        QGuiApplication.clipboard().setText("\n".join(lines))
        self.editor.session.statusMessage.emit(f"Copied {len(rows):,} rows", 3000)

    def flash(self, index: QModelIndex) -> None:
        """Flash a cell's outline twice (reveal)."""
        self.cell_delegate.flash = (index, True)
        self._flash_steps = 4
        self._flash_timer.start()
        self.viewport().update(self.visualRect(index))

    def _flash_step(self) -> None:
        self._flash_steps -= 1
        flash = self.cell_delegate.flash
        if flash is None or self._flash_steps <= 0:
            self.cell_delegate.flash = None
            self._flash_timer.stop()
        else:
            self.cell_delegate.flash = (flash[0], not flash[1])
        if flash is not None:
            self.viewport().update(self.visualRect(flash[0]))
