"""
MatrixView: the Matrix tab.

Shows the status pages (setup, connecting, loading, failed) until data is
loaded, then the split view: a mode switch (By principal / By object) over one
ModePane per mode. Each ModePane is a splitter with the entity list on the left
and the grid header and grid on the right. Both panes stay alive, so switching
modes keeps each one's scroll position and filters.
"""

from __future__ import annotations

import logging
import sys
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QItemSelectionModel, QModelIndex, QSettings, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.qt.dialogs import messages
from src.qt.dialogs.edit_description import EditDescriptionDialog
from src.qt.dialogs.make_like import MakeLikeDialog
from src.qt.session import SessionState
from src.qt.theme import tokens
from src.qt.views.matrix import bulk, view_state
from src.qt.views.matrix.chips import Segmented
from src.qt.views.matrix.editing import MatrixEditor
from src.qt.views.matrix.entity_list import EntityListPane
from src.qt.views.matrix.grid import PermissionGrid
from src.qt.views.matrix.grid_header import GridHeader
from src.qt.views.matrix.grid_model import GridFilters, GridModel
from src.qt.views.matrix.jump_dialog import JumpDialog
from src.qt.views.matrix_placeholder import MatrixPlaceholder
from src.services.matrix import CellRef

if TYPE_CHECKING:
    from src.models.permission import StagedChange
    from src.qt.session import Session
    from src.services.matrix import MatrixChange

logger = logging.getLogger("bifrost.matrix_view")

MODES = (("principal", "By principal"), ("object", "By object"))
LEFT_WIDTH = 300
LEFT_MIN = 220


def prefers_reduced_motion() -> bool:
    """True if the OS asks for fewer animations (Windows "Show animations" off)."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        value = ctypes.c_bool(True)
        spi_getclientareaanimation = 0x1042
        ctypes.windll.user32.SystemParametersInfoW(spi_getclientareaanimation, 0, ctypes.byref(value), 0)
        return not value.value
    except Exception:  # never let a platform call break the view
        return False


class ModePane(QSplitter):
    """
    Entity list | grid header + grid, for one mode.

    Signals:
        entityShown(object): the grid now shows this p / o (or None)
    """

    entityShown = Signal(object)

    def __init__(self, session: Session, mode: str, editor: MatrixEditor, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.session = session
        self.mode = mode
        self.editor = editor
        self.setObjectName(f"matrix_splitter_{mode}")
        self.setChildrenCollapsible(False)

        self.left = EntityListPane(session, mode, self)
        self.left.setMinimumWidth(LEFT_MIN)
        self.addWidget(self.left)

        right = QWidget(self)
        layout = QVBoxLayout(right)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.header = GridHeader(session, mode, right)
        layout.addWidget(self.header)
        self.hidden_notice = QWidget(right)
        notice_layout = QHBoxLayout(self.hidden_notice)
        notice_layout.setContentsMargins(8, 2, 8, 2)
        self.hidden_label = QLabel("", self.hidden_notice)
        self.show_it = QPushButton("Show it", self.hidden_notice)
        self.show_it.clicked.connect(self._show_hidden)
        notice_layout.addWidget(self.hidden_label, 1)
        notice_layout.addWidget(self.show_it)
        self.hidden_notice.hide()
        self._hidden_cell: CellRef | None = None
        layout.addWidget(self.hidden_notice)

        self.model = GridModel(session, mode, self)
        self.grid = PermissionGrid(self.model, editor, right)
        self.empty = QWidget(right)
        empty_layout = QVBoxLayout(self.empty)
        self.empty_label = QLabel("", self.empty)
        self.empty_label.setWordWrap(True)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_button = QPushButton("", self.empty)
        self.empty_button.clicked.connect(self._empty_action)
        empty_layout.addStretch(1)
        empty_layout.addWidget(self.empty_label)
        empty_layout.addWidget(self.empty_button, 0, Qt.AlignmentFlag.AlignCenter)
        empty_layout.addStretch(2)
        self.grid_stack = QStackedWidget(right)
        self.grid_stack.addWidget(self.grid)
        self.grid_stack.addWidget(self.empty)
        layout.addWidget(self.grid_stack, 1)
        self.selection_label = QLabel("", right)
        self.selection_label.setContentsMargins(8, 2, 8, 2)
        self.selection_label.setAccessibleName("Selected cells")
        layout.addWidget(self.selection_label)
        self.addWidget(right)
        self.setStretchFactor(0, 0)
        self.setStretchFactor(1, 1)
        self.setSizes([LEFT_WIDTH, 900])

        self.left.entityChanged.connect(self.show_entity)
        self.left.focusGridRequested.connect(self.focus_grid)
        self.header.filtersChanged.connect(self._on_filters)
        self.header.tagClicked.connect(self.left.add_tag_filter)
        self.header.refreshListRequested.connect(self.rebuild_keep_current)
        self.header.makeLikeRequested.connect(self.make_like)
        self.header.editDescriptionRequested.connect(self.edit_description)
        self.model.staleChanged.connect(self.header.set_stale)
        self.grid.selectionCountChanged.connect(self._on_selection_count)
        self.left.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.left.list.customContextMenuRequested.connect(self._left_menu)

    # --- Entity ----------------------------------------------------------------------------

    @property
    def entity(self) -> int | None:
        return self.model.entity

    def show_entity(self, entity: int | None) -> None:
        """Show entity's permissions in the grid (selection clears with the model reset)."""
        self.hidden_notice.hide()
        self.model.set_entity(entity)
        self.header.set_entity(entity)
        self._update_empty()
        if entity is not None and self.mode == "object":
            self._load_description(entity)
        if entity is not None:
            self.session.announce.emit(self.summary_sentence())
        self.entityShown.emit(entity)

    def summary_sentence(self) -> str:
        """E.g. "Showing CORP\\jsmith, 2,847 objects, 38 with access"."""
        ix = self.session.matrix.index
        entity = self.model.entity
        if self.mode == "principal":
            name = ix.principals[entity].login_name
            access = len(ix.objects_by_principal[entity])
            noun = "objects"
        else:
            name = ix.objects[entity].full_name
            access = len(ix.principals_by_object[entity])
            noun = "principals"
        return f"Showing {name}, {self.model.item_count():,} {noun}, {access:,} with access"

    def _load_description(self, o: int) -> None:
        def done(text: str | None, error: str | None) -> None:
            if self.model.entity == o and self.mode == "object":
                self.header.set_description(text, loading=False, error=error)

        self.session.load_description(o, done)

    def reload(self) -> None:
        """Data reloaded or tags changed: refresh options, the list and the grid (keeping the current cell)."""
        self.header.refresh_options()
        previous = self.left.entity
        self.left.blockSignals(True)
        self.left.reload()
        self.left.blockSignals(False)
        if self.left.entity != previous or self.model.entity != self.left.entity:
            self.show_entity(self.left.entity)
        else:
            self.rebuild_keep_current()
            self.header.set_entity(self.model.entity)
            if self.model.entity is not None and self.mode == "object":
                self._load_description(self.model.entity)

    def _on_filters(self) -> None:
        self.model.filters = self.header.filters
        self.rebuild_keep_current()

    def rebuild_keep_current(self) -> None:
        current = self.grid.currentIndex()
        cell = self.model.cell_at(current)
        pair = self.model.pair_for(current)
        column = current.column() if current.isValid() else 0
        scroll = self.grid.verticalScrollBar().value()
        self.model.rebuild()
        self._update_empty()
        target = QModelIndex()
        if cell is not None:
            target = self.model.index_for_cell(cell)
        elif pair is not None:
            other = pair[1] if self.mode == "principal" else pair[0]
            target = self.model.index_for_row(other, column)
        if target.isValid():
            self.grid.selectionModel().setCurrentIndex(target, QItemSelectionModel.SelectionFlag.NoUpdate)
            self.grid.verticalScrollBar().setValue(scroll)
            self.grid.scrollTo(target)

    def _update_empty(self) -> None:
        model = self.model
        if model.entity is not None and model.item_count():
            self.grid_stack.setCurrentWidget(self.grid)
            return
        noun = "objects" if self.mode == "principal" else "principals"
        if model.entity is None:
            self.empty_label.setText(f"Select {'a principal' if self.mode == 'principal' else 'an object'} on the left.")
            self.empty_button.hide()
        elif model.filters.segment == "access" and model.filters == GridFilters(segment="access"):
            ix = self.session.matrix.index
            name = ix.principals[model.entity].login_name if self.mode == "principal" else ix.objects[model.entity].full_name
            who = "has no explicit permissions" if self.mode == "principal" else "has no principals with access"
            self.empty_label.setText(f"{name} {who}.")
            self.empty_button.setText(f"Show all {noun}")
            self.empty_button.show()
        else:
            self.empty_label.setText(f"No {noun} match the filters.")
            self.empty_button.setText("Clear filters")
            self.empty_button.show()
        self.grid_stack.setCurrentWidget(self.empty)

    def _empty_action(self) -> None:
        self.header.set_filters(GridFilters())
        self._on_filters()

    # --- Changes -----------------------------------------------------------------------------

    def on_matrix_change(self, change: MatrixChange) -> None:
        if change.rows is None:
            self.reload()
            return
        self.left.on_matrix_change(change)
        self.model.on_matrix_change(change)
        entity = self.model.entity
        if entity is not None and any((p if self.mode == "principal" else o) == entity for p, o in change.rows):
            self.header.update_counts()
        if change.reason in ("commit", "cancel"):
            self.grid.clearSelection()

    def _on_selection_count(self, count: int) -> None:
        if count > bulk.SELECTION_LIMIT:
            self.selection_label.setText(
                f"{count:,} cells selected — select at most {bulk.SELECTION_LIMIT:,}, or use a group action"
            )
        elif count > 1:
            self.selection_label.setText(f"{count:,} cells selected")
        else:
            self.selection_label.setText("")

    # --- Focus, reveal -------------------------------------------------------------------------

    def focus_grid(self) -> None:
        self.grid.setFocus(Qt.FocusReason.OtherFocusReason)
        if not self.grid.currentIndex().isValid() and self.model.groups:
            first = self.model.index(self.model.header_rows[0] + 1, 0)
            target = self.grid._step_in_row(first, +1) if first.isValid() else first
            if target.isValid():
                self.grid.selectionModel().setCurrentIndex(target, QItemSelectionModel.SelectionFlag.ClearAndSelect)

    def focus_cell(self, cell: CellRef, clear_hiding_filters: bool, flash: bool = False) -> bool:
        """
        Select and focus a cell of the current entity.

        Args:
            cell: Cell to show
            clear_hiding_filters: Clear grid filters that hide it (reveal); otherwise show
                the "not shown by the current filter" notice
            flash: Flash its outline (reveal)
        """
        index = self.model.index_for_cell(cell)
        if not index.isValid() and clear_hiding_filters:
            self.header.set_filters(GridFilters())
            self._on_filters()
            index = self.model.index_for_cell(cell)
        if not index.isValid():
            ix = self.session.matrix.index
            name = ix.objects[cell.o].full_name if self.mode == "principal" else ix.principals[cell.p].login_name
            self.hidden_label.setText(f"{name} isn't shown by the current filter.")
            self._hidden_cell = cell
            self.hidden_notice.show()
            return False
        self.hidden_notice.hide()
        self.grid.selectionModel().setCurrentIndex(index, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.grid.scrollTo(index, PermissionGrid.ScrollHint.PositionAtCenter)
        self.grid.setFocus(Qt.FocusReason.OtherFocusReason)
        if flash and not prefers_reduced_motion():
            self.grid.flash(index)
        return True

    def _show_hidden(self) -> None:
        if self._hidden_cell is not None:
            self.focus_cell(self._hidden_cell, clear_hiding_filters=True)

    def current_cell(self) -> tuple[int, int, int] | None:
        """(p, o, perm or -1) at the grid's current index."""
        current = self.grid.currentIndex()
        pair = self.model.pair_for(current)
        if pair is None:
            return None
        return (*pair, current.column() - 1)

    # --- Actions -------------------------------------------------------------------------------

    def make_like(self) -> None:
        if self.mode != "principal" or self.model.entity is None or not self.editor.ensure_editable():
            return
        ix = self.session.matrix.index
        target = self.model.entity
        filter_active = self.model.filters != GridFilters()
        dialog = MakeLikeDialog(ix, target, filter_active, self)
        if dialog.exec() != MakeLikeDialog.DialogCode.Accepted or dialog.source is None:
            return
        self.apply_make_like(dialog.source, dialog.scope)

    def apply_make_like(self, source: int, scope: str) -> None:
        ix = self.session.matrix.index
        target = self.model.entity
        if scope == "filter":
            objects = [o for group in self.model.groups for o in group.rows]
        else:
            objects = list(ix.object_order)
        items = bulk.make_like_items(ix, source, target, objects)
        label = f"Make {ix.principals[target].login_name} like {ix.principals[source].login_name}"
        self.editor.stage(items, label, limited=False)

    def edit_description(self) -> None:
        o = self.model.entity
        if o is None or self.mode != "object":
            return
        obj = self.session.matrix.index.objects[o]
        known, text = self.session.cached_description(o)
        dialog = EditDescriptionDialog(obj.full_name, text if known else None, self)
        if dialog.exec() != EditDescriptionDialog.DialogCode.Accepted:
            return
        new_text = dialog.text

        def done(error: str | None) -> None:
            if error:
                messages.show_error(self, "Couldn't save the description", error)
            elif self.model.entity == o:
                self.header.set_description(new_text.strip() or None)

        self.session.save_description(o, new_text, done)

    def _left_menu(self, position) -> None:
        index = self.left.list.indexAt(position)
        entity = self.left.model.entity_at(index.row()) if index.isValid() else None
        if entity is None:
            return
        menu = self.build_left_menu(entity)
        menu.exec(self.left.list.viewport().mapToGlobal(position))
        menu.deleteLater()

    def build_left_menu(self, entity: int) -> QMenu:
        """Context menu for a left-list entry (selects it first)."""
        if entity != self.left.entity:
            self.left.select_entity(entity, clear_hiding_filters=False)
        menu = QMenu(self)
        if self.mode == "principal":
            make_like = menu.addAction("Make like…")
            make_like.triggered.connect(self.make_like)
        noun = "principal" if self.mode == "principal" else "object"
        pending = menu.addAction(f"Show only this {noun}'s pending changes")
        pending.triggered.connect(self._show_only_pending)
        tags = menu.addAction("Tags…")
        tags.triggered.connect(self.header.tagsRequested)
        return menu

    def _show_only_pending(self) -> None:
        self.header.set_filters(GridFilters(segment="pending"))
        self._on_filters()

    # --- State ---------------------------------------------------------------------------------

    def apply_theme(self) -> None:
        self.grid.cell_delegate.apply_theme(tokens())
        self.left.delegate.apply_theme()
        self.grid.viewport().update()
        self.left.list.viewport().update()


class MatrixView(QWidget):
    """
    The Matrix tab.

    Signals:
        openSettings: a status page asked for connection settings
        tagsRequested: user asked for the tag manager
    """

    openSettings = Signal()
    tagsRequested = Signal()

    def __init__(self, session: Session, settings: QSettings | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self.settings = settings
        self.mode = "principal"
        self.extra_focus_targets: list[QWidget] = []
        self._restored = False
        self._dirty: set[str] = set()  # panes to reload before they're next shown
        self._saved = view_state.load(settings) if settings is not None else view_state.ViewState()

        self.placeholder = MatrixPlaceholder(session, self)
        self.placeholder.openSettings.connect(self.openSettings)
        self.editor = MatrixEditor(session, self)

        self.content = QWidget(self)
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        bar = QHBoxLayout()
        bar.setContentsMargins(8, 6, 8, 2)
        self.mode_switch = Segmented(MODES, "View", self.content)
        self.mode_switch.changed.connect(lambda mode: self.set_mode(mode))
        bar.addWidget(self.mode_switch)
        self.compare_button = QToolButton(self.content)
        self.compare_button.setText("Compare")
        self.compare_button.setEnabled(False)
        self.compare_button.setToolTip("Compare mode arrives in a later update")
        bar.addWidget(self.compare_button)
        bar.addStretch(1)
        content_layout.addLayout(bar)
        self.banner = QLabel("", self.content)
        self.banner.setContentsMargins(10, 4, 10, 4)
        self.banner.setAccessibleName("Editing status")
        self.banner.hide()
        content_layout.addWidget(self.banner)

        self.panes: dict[str, ModePane] = {}
        self.mode_stack = QStackedWidget(self.content)
        for mode, _text in MODES:
            pane = ModePane(session, mode, self.editor, self.mode_stack)
            pane.header.tagsRequested.connect(self.tagsRequested)
            self.panes[mode] = pane
            self.mode_stack.addWidget(pane)
        content_layout.addWidget(self.mode_stack, 1)

        self.stack = QStackedWidget(self)
        self.stack.addWidget(self.placeholder)
        self.stack.addWidget(self.content)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)

        self.jump_box = JumpDialog(lambda: session.matrix.index if session.matrix else None, self)
        self.jump_box.chosen.connect(self.jump_to)

        QShortcut(QKeySequence("F6"), self, self.cycle_focus, context=Qt.ShortcutContext.WindowShortcut)
        QShortcut(QKeySequence("Shift+F6"), self, lambda: self.cycle_focus(-1), context=Qt.ShortcutContext.WindowShortcut)
        QShortcut(QKeySequence.StandardKey.Find, self, self.focus_list_search, context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence("Ctrl+Shift+F"), self, self.focus_grid_filter, context=Qt.ShortcutContext.WidgetWithChildrenShortcut)

        session.stateChanged.connect(lambda _s: self.update_view())
        session.dataLoaded.connect(lambda _summary: self._on_loaded())
        session.matrixChanged.connect(self._on_matrix_change)
        session.stagingDenied.connect(self._on_staging_denied)
        session.stagingBusyChanged.connect(self._on_staging_busy)
        session.revealRequested.connect(self.reveal)
        if session.matrix is not None and session.last_load is not None:
            self._on_loaded()  # created after the data was loaded
        self.update_view()

    # --- State -------------------------------------------------------------------------------

    @property
    def pane(self) -> ModePane:
        return self.panes[self.mode]

    @property
    def showing_data(self) -> bool:
        return self.stack.currentWidget() is self.content

    def update_view(self) -> None:
        """Status pages until data is loaded; afterwards the split view (read-only unless READY)."""
        s = self.session
        has_data = s.matrix is not None and s.last_load is not None
        if not has_data:
            self.stack.setCurrentWidget(self.placeholder)
            self.placeholder.update_view()
            return
        self.stack.setCurrentWidget(self.content)
        read_only = s.state is not SessionState.READY
        reason = s.edit_blocked_reason() if read_only else ""
        self.banner.setText(reason)
        self.banner.setVisible(bool(reason))
        t = tokens()
        self.banner.setStyleSheet(f"background: {t.staged_bg}; color: {t.staged};")
        for pane in self.panes.values():
            pane.grid.set_read_only(read_only)

    def _on_loaded(self) -> None:
        start = time.perf_counter()
        if not self._restored:
            self._restore()
        # Only the visible pane is rebuilt now; the other one on its next mode switch
        self.pane.reload()
        self._dirty = {mode for mode in self.panes if mode != self.mode}
        self.update_view()
        logger.info("Matrix view loaded in %.0f ms", (time.perf_counter() - start) * 1000)

    def _on_matrix_change(self, change: MatrixChange) -> None:
        if change.rows is None and change.reason == "reload":
            return  # dataLoaded follows and reloads the visible pane
        for mode, pane in self.panes.items():
            if mode in self._dirty:
                continue  # reloaded in full when next shown
            if change.rows is None and mode != self.mode:
                self._dirty.add(mode)
                continue
            pane.on_matrix_change(change)

    def _on_staging_denied(self, changes: list[StagedChange]) -> None:
        perms = {c.permission_type.value for c in changes}
        perm = next(iter(perms)) if len(perms) == 1 else "these permissions"
        objects = {(c.schema_name, c.object_name) for c in changes}
        target = (
            f"{changes[0].schema_name}.{changes[0].object_name}" if len(objects) == 1 else f"{len(objects):,} objects"
        )
        lines = [
            f"{c.permission_type.value} on {c.schema_name}.{c.object_name} for {c.user_login}" for c in changes[:50]
        ]
        if len(changes) > 50:
            lines.append(f"…and {len(changes) - 50:,} more")
        messages.show_error(
            self,
            "Some grants weren't staged",
            f"You can't grant {perm} on {target} because you don't hold those permissions yourself. "
            "Contact a database owner or sysadmin. The other changes were staged.",
            "\n".join(lines),
        )

    def _on_staging_busy(self, busy: bool) -> None:
        if busy:
            QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        else:
            QApplication.restoreOverrideCursor()

    def apply_theme(self) -> None:
        for pane in self.panes.values():
            pane.apply_theme()
        self.update_view()

    # --- Modes ---------------------------------------------------------------------------------

    def set_mode(self, mode: str, follow: bool = True) -> None:
        """
        Switch modes. With follow, the focused cell carries over: its object (or
        principal) becomes the left selection and the same cell is focused.
        """
        if mode == self.mode:
            self.mode_switch.set_value(mode)
            return
        previous = self.pane
        carried = previous.current_cell() if follow and self.showing_data else None
        previous.grid.clearSelection()
        self.mode = mode
        self.mode_switch.set_value(mode)
        if mode in self._dirty:
            self._dirty.discard(mode)
            self.pane.reload()
        self.mode_stack.setCurrentWidget(self.pane)
        self.pane.grid.clearSelection()
        if carried is not None:
            p, o, perm = carried
            entity, other = (p, o) if mode == "principal" else (o, p)
            if self.pane.left.select_entity(entity) and self.pane.model.entity != entity:
                self.pane.show_entity(entity)
            if perm >= 0 and self.session.matrix.index.is_applicable(o, perm):
                self.pane.focus_cell(CellRef(p, o, perm), clear_hiding_filters=False)
            else:
                index = self.pane.model.index_for_row(other)
                if index.isValid():
                    self.pane.grid.setCurrentIndex(index)
                    self.pane.grid.scrollTo(index)
        self.session.announce.emit(f"{dict(MODES)[mode]} mode")

    def reveal(self, cell: CellRef) -> None:
        """Pending tray: show a staged cell in By principal mode, flashing it."""
        if not self.showing_data:
            return
        self.set_mode("principal", follow=False)
        pane = self.pane
        if not pane.left.select_entity(cell.p):
            return
        if pane.model.entity != cell.p:
            pane.show_entity(cell.p)
        pane.focus_cell(cell, clear_hiding_filters=True, flash=True)

    def open_jump(self) -> None:
        if self.session.matrix is None:
            return
        self.jump_box.open_box()

    def jump_to(self, kind: str, key) -> None:
        if kind == "principal":
            self.set_mode("principal", follow=False)
        elif kind == "object":
            self.set_mode("object", follow=False)
        elif kind == "principal_tag":
            self.set_mode("principal", follow=False)
            self.pane.left.add_tag_filter(key)
            self.pane.left.focus_list()
            return
        elif kind == "object_tag":
            self.set_mode("object", follow=False)
            self.pane.left.add_tag_filter(key)
            self.pane.left.focus_list()
            return
        pane = self.pane
        if pane.left.select_entity(key) and pane.model.entity != key:
            pane.show_entity(key)
        pane.focus_grid()

    # --- Focus ---------------------------------------------------------------------------------

    def focus_targets(self) -> list[QWidget]:
        pane = self.pane
        targets: list[QWidget] = [pane.left.list, pane.header.search, pane.grid]
        targets += [w for w in self.extra_focus_targets if w.isVisible()]
        return targets

    def cycle_focus(self, step: int = 1) -> None:
        """F6 / Shift+F6: left list → grid filter → grid → pending tray."""
        if not self.showing_data:
            return
        targets = self.focus_targets()
        focused = QApplication.focusWidget()
        position = -1
        for i, target in enumerate(targets):
            if focused is not None and (focused is target or target.isAncestorOf(focused)):
                position = i
                break
        target = targets[(position + step) % len(targets)]
        if target is self.pane.grid:
            self.pane.focus_grid()
        else:
            target.setFocus(Qt.FocusReason.TabFocusReason)

    def focus_list_search(self) -> None:
        self.pane.left.search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.pane.left.search.selectAll()

    def focus_grid_filter(self) -> None:
        self.pane.header.search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.pane.header.search.selectAll()

    # --- Saved state -----------------------------------------------------------------------------

    def _restore(self) -> None:
        """Apply the saved state once the first data is loaded (entities must exist)."""
        self._restored = True
        saved = self._saved
        ix = self.session.matrix.index
        selected = {
            "principal": ix.principal_index(saved.principal) if saved.principal else None,
            "object": ix.object_index(*saved.object) if saved.object else None,
        }
        for mode, pane in self.panes.items():
            pane.header.refresh_options()
            pane.header.set_state(saved.grids.get(mode, {}))
            pane.model.filters = pane.header.filters
            pane.left.restore(saved.lists.get(mode, {}), selected[mode])
            if saved.splitter is not None:
                pane.restoreState(saved.splitter)
        self.mode = saved.mode
        self.mode_switch.set_value(saved.mode)
        self.mode_stack.setCurrentWidget(self.pane)

    def save_state(self) -> None:
        if self.settings is None:
            return
        state = view_state.ViewState(mode=self.mode, splitter=self.pane.saveState())
        if self.session.matrix is not None:
            ix = self.session.matrix.index
            p = self.panes["principal"].model.entity
            o = self.panes["object"].model.entity
            state.principal = ix.principals[p].login_name if p is not None else ""
            state.object = (ix.objects[o].schema_name, ix.objects[o].object_name) if o is not None else None
        elif self._saved:
            state.principal, state.object = self._saved.principal, self._saved.object
        for mode, pane in self.panes.items():
            state.lists[mode] = pane.left.get_state() if self._restored else self._saved.lists.get(mode, {})
            state.grids[mode] = pane.header.get_state() if self._restored else self._saved.grids.get(mode, {})
        view_state.save(self.settings, state)
