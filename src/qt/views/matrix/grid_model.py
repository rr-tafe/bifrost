"""
Flat table model behind the permission grid.

Rows are group headers (schemas in By principal mode, principal types in By
object mode) each followed by its objects or principals, unless the group is
collapsed. Column 0 is the name; columns 1-8 are the permissions in PERMS order.

The table is flat on purpose: a QTreeView lays out every row on each rebuild
(~70 ms for 20,000 rows), while a QTableView with fixed row heights only
touches the rows on screen. Groups are contiguous, so a row's group is found
with a bisect over the header positions; there is no per-row list.

The model reads cell states straight from the session's PermissionIndex, so it
holds no copy of permission data: a staged change only needs a dataChanged for
the rows it touched.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, Qt, Signal

from src.models.permission import STATE_DENY, STATE_GRANT, STATE_NONE, PermissionType
from src.services.matrix import CellRef
from src.services.matrix_index import PERM_COUNT, PERMS, ObjectQuery, PrincipalQuery, cell_code

if TYPE_CHECKING:
    from src.models.db_object import ObjectType
    from src.qt.session import Session
    from src.services.matrix import MatrixChange
    from src.services.matrix_index import PermissionIndex

Mode = Literal["principal", "object"]
Segment = Literal["all", "access", "pending"]

COLUMN_COUNT = PERM_COUNT + 1
SHORT_NAMES = {
    PermissionType.SELECT: "SEL",
    PermissionType.INSERT: "INS",
    PermissionType.UPDATE: "UPD",
    PermissionType.DELETE: "DEL",
    PermissionType.EXECUTE: "EXEC",
    PermissionType.ALTER: "ALTER",
    PermissionType.REFERENCES: "REF",
    PermissionType.VIEW_DEFINITION: "VDEF",
}
PRINCIPAL_TYPE_GROUPS = (("G", "Windows groups"), ("U", "Windows users"), ("S", "SQL users"))
PRINCIPAL_TYPE_NAMES = {"G": "Windows group", "U": "Windows user", "S": "SQL user"}
OBJECT_BADGES = {"TABLE": "T", "VIEW": "V", "PROCEDURE": "P", "FUNCTION": "F"}
STATE_WORDS = {STATE_GRANT: "granted", STATE_DENY: "denied", STATE_NONE: "none"}
STATE_NAMES = {STATE_GRANT: "GRANT", STATE_DENY: "DENY", STATE_NONE: "none"}
_NEXT = {STATE_NONE: STATE_GRANT, STATE_GRANT: STATE_DENY, STATE_DENY: STATE_NONE}

# Custom roles
StateRole = Qt.ItemDataRole.UserRole + 1  # effective code
CommittedRole = Qt.ItemDataRole.UserRole + 2  # committed code
PendingRole = Qt.ItemDataRole.UserRole + 3  # bool
ApplicableRole = Qt.ItemDataRole.UserRole + 4  # bool
CellRole = Qt.ItemDataRole.UserRole + 5  # CellRef
BadgeRole = Qt.ItemDataRole.UserRole + 6  # "T", "U", …
IsGroupRole = Qt.ItemDataRole.UserRole + 7  # bool


_GROUP_FLAGS = Qt.ItemFlag.ItemIsEnabled
_ITEM_FLAGS = Qt.ItemFlag.ItemIsEnabled
_CELL_FLAGS = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable


@dataclass(frozen=True)
class GridFilters:
    """
    Grid filters for one mode.

    Attributes:
        text: Search text (object "schema.name" or principal login)
        schemas: Casefolded schemas (By principal)
        object_types: Object types (By principal)
        principal_types: "U", "G", "S" (By object)
        tags: Casefolded tags; rows must have all of them
        segment: "all", "access" (non-empty row) or "pending" (staged cells)
    """

    text: str = ""
    schemas: frozenset[str] = frozenset()
    object_types: frozenset[ObjectType] = frozenset()
    principal_types: frozenset[str] = frozenset()
    tags: frozenset[str] = frozenset()
    segment: Segment = "all"


@dataclass
class Group:
    """One top-level row: label, key (schema or principal type) and its item rows (o or p)."""

    label: str
    key: str
    rows: list[int] = field(default_factory=list)


class GridModel(QAbstractTableModel):
    """
    Model for PermissionGrid.

    Signals:
        staleChanged(bool): a staged change made the current filter out of date
        rebuilt(): groups were rebuilt (entity, filters or reload)
    """

    staleChanged = Signal(bool)
    rebuilt = Signal()

    def __init__(self, session: Session, mode: Mode, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self.mode: Mode = mode
        self.entity: int | None = None
        self.filters = GridFilters()
        self.groups: list[Group] = []
        self.collapsed: set[str] = set()  # group keys; remembered for the session
        self.header_rows: list[int] = []  # table row of each group header
        self.row_of: dict[int, tuple[int, int]] = {}  # o (or p) -> (group, position in group)
        self.stale = False
        self._row_count = 0
        self._group_counts: dict[int, tuple[int, int]] = {}

    # --- Index access ----------------------------------------------------------------

    @property
    def ix(self) -> PermissionIndex:
        return self.session.matrix.index

    def locate(self, row: int) -> tuple[int, int]:
        """(group, position in group) for a table row; position -1 = the group header."""
        g = bisect_right(self.header_rows, row) - 1
        return g, row - self.header_rows[g] - 1

    def pair(self, group: int, position: int) -> tuple[int, int]:
        """(p, o) for an item."""
        other = self.groups[group].rows[position]
        return (self.entity, other) if self.mode == "principal" else (other, self.entity)

    def pair_at(self, row: int) -> tuple[int, int] | None:
        """(p, o) at a table row, None for group headers."""
        g, r = self.locate(row)
        return None if r < 0 else self.pair(g, r)

    def pair_for(self, index: QModelIndex) -> tuple[int, int] | None:
        return self.pair_at(index.row()) if index.isValid() else None

    def is_group(self, index: QModelIndex) -> bool:
        return index.isValid() and self.is_group_row(index.row())

    def is_group_row(self, row: int) -> bool:
        g = bisect_right(self.header_rows, row) - 1
        return g >= 0 and self.header_rows[g] == row

    def group_of(self, index: QModelIndex) -> int:
        return self.locate(index.row())[0]

    def cell_at(self, index: QModelIndex) -> CellRef | None:
        """The cell at index, or None for names, groups and cells that don't apply."""
        if not index.isValid() or index.column() == 0:
            return None
        pair = self.pair_at(index.row())
        if pair is None:
            return None
        p, o = pair
        perm = index.column() - 1
        if not self.ix.object_applicable[o] & (1 << perm):
            return None
        return CellRef(p, o, perm)

    def index_for_cell(self, cell: CellRef) -> QModelIndex:
        """Index of a cell (invalid if its row isn't in the grid). Collapsed groups are expanded."""
        entity = cell.p if self.mode == "principal" else cell.o
        if entity != self.entity:
            return QModelIndex()
        return self.index_for_row(cell.o if self.mode == "principal" else cell.p, cell.perm + 1)

    def index_for_row(self, other: int, column: int = 0) -> QModelIndex:
        """Index of the row for object/principal `other`, expanding its group (invalid if filtered out)."""
        position = self.row_of.get(other)
        if position is None:
            return QModelIndex()
        g, r = position
        if self.groups[g].key in self.collapsed:
            self.set_collapsed(g, False)
        return self.index(self.header_rows[g] + 1 + r, column)

    def group_index(self, g: int) -> QModelIndex:
        return self.index(self.header_rows[g], 0)

    def item_rows(self, g: int) -> tuple[int, int]:
        """First and last table rows of group g's items (last < first when collapsed or empty)."""
        first = self.header_rows[g] + 1
        count = 0 if self.groups[g].key in self.collapsed else len(self.groups[g].rows)
        return first, first + count - 1

    def segments(self, top: int, bottom: int):
        """Yield (group, first position, last position) for the items in table rows top..bottom."""
        if not self.header_rows:
            return
        g = max(bisect_right(self.header_rows, top) - 1, 0)
        while g < len(self.groups):
            first, last = self.item_rows(g)
            if first > bottom:
                return
            lo, hi = max(first, top), min(last, bottom)
            if lo <= hi:
                yield g, lo - first, hi - first
            g += 1

    def item_count(self) -> int:
        return len(self.row_of)

    def is_collapsed(self, g: int) -> bool:
        return self.groups[g].key in self.collapsed

    def set_collapsed(self, g: int, collapsed: bool) -> None:
        """Collapse or expand group g (rows are removed/inserted, so selection elsewhere is kept)."""
        group = self.groups[g]
        if (group.key in self.collapsed) == collapsed or not group.rows:
            if collapsed:
                self.collapsed.add(group.key)
            else:
                self.collapsed.discard(group.key)
            self._emit_group(g)
            return
        first = self.header_rows[g] + 1
        last = first + len(group.rows) - 1
        delta = len(group.rows)
        if collapsed:
            self.beginRemoveRows(QModelIndex(), first, last)
            self.collapsed.add(group.key)
            self._shift(g, -delta)
            self.endRemoveRows()
        else:
            self.beginInsertRows(QModelIndex(), first, last)
            self.collapsed.discard(group.key)
            self._shift(g, delta)
            self.endInsertRows()
        self._emit_group(g)

    def _shift(self, g: int, delta: int) -> None:
        for later in range(g + 1, len(self.header_rows)):
            self.header_rows[later] += delta
        self._row_count += delta

    def _emit_group(self, g: int) -> None:
        index = self.group_index(g)
        self.dataChanged.emit(index, index.siblingAtColumn(COLUMN_COUNT - 1))

    def applicable_mask(self) -> int:
        """Permissions shown as columns: all in By principal; the object's in By object."""
        if self.mode == "object" and self.entity is not None:
            return self.ix.object_applicable[self.entity]
        return (1 << PERM_COUNT) - 1

    # --- Building --------------------------------------------------------------------

    def set_entity(self, entity: int | None) -> None:
        self.entity = entity
        self.rebuild()

    def set_filters(self, filters: GridFilters) -> None:
        self.filters = filters
        self.rebuild()

    def rebuild(self) -> None:
        """Recompute groups from the entity and filters."""
        self.beginResetModel()
        self._group_counts.clear()
        if self.entity is None or self.session.matrix is None:
            self.groups = []
        elif self.mode == "principal":
            self.groups = self._object_groups()
        else:
            self.groups = self._principal_groups()
        row_of: dict[int, tuple[int, int]] = {}
        header_rows: list[int] = []
        row = 0
        for g, group in enumerate(self.groups):
            header_rows.append(row)
            row += 1 if group.key in self.collapsed else 1 + len(group.rows)
            for r, other in enumerate(group.rows):
                row_of[other] = (g, r)
        self.row_of = row_of
        self.header_rows = header_rows
        self._row_count = row
        self.endResetModel()
        self._set_stale(False)
        self.rebuilt.emit()

    def _object_groups(self) -> list[Group]:
        ix = self.ix
        f = self.filters
        p = self.entity
        query = ObjectQuery(
            text=f.text,
            schemas=f.schemas,
            types=f.object_types,
            tags=f.tags,
            with_access_for=p if f.segment == "access" else None,
            pending_for=p if f.segment == "pending" else None,
        )
        objects = ix.query_objects(query)
        return [Group(span.schema, span.schema, objects[span.start : span.end]) for span in ix.group_by_schema(objects)]

    def _principal_groups(self) -> list[Group]:
        ix = self.ix
        f = self.filters
        o = self.entity
        query = PrincipalQuery(
            text=f.text,
            types=f.principal_types,
            tags=f.tags,
            has_access_to_object=o if f.segment != "all" else None,
        )
        principals = ix.query_principals(query)
        if f.segment == "pending":
            pending = ix.pending_mask
            principals = [p for p in principals if pending(p, o)]
        buckets: dict[str, list[int]] = {}
        for p in principals:
            buckets.setdefault(ix.principals[p].principal_type, []).append(p)
        groups = [Group(label, key, buckets.pop(key)) for key, label in PRINCIPAL_TYPE_GROUPS if key in buckets]
        for key in sorted(buckets):
            groups.append(Group(f"Other ({key})", key, buckets[key]))
        return groups

    # --- Changes ---------------------------------------------------------------------

    def on_matrix_change(self, change: MatrixChange) -> None:
        """Repaint affected rows; rebuild on reloads. Rows never vanish while being edited."""
        if self.entity is None:
            return
        if change.rows is None:
            return  # the view rebuilds (keeping the current cell) on reload and tag changes
        principal_mode = self.mode == "principal"
        entity = self.entity
        touched: set[int] = set()
        rows: list[int] = []
        stale = False
        segment = self.filters.segment
        for p, o in change.rows:
            if (p if principal_mode else o) != entity:
                continue
            other = o if principal_mode else p
            position = self.row_of.get(other)
            if position is not None:
                g, r = position
                touched.add(g)
                if self.groups[g].key not in self.collapsed:
                    rows.append(self.header_rows[g] + 1 + r)
            if segment != "all" and not stale:
                stale = (position is not None) != self._passes_segment(p, o)
        last = COLUMN_COUNT - 1
        rows.sort()
        start = 0
        while start < len(rows):
            end = start
            while end + 1 < len(rows) and rows[end + 1] == rows[end] + 1:
                end += 1
            self.dataChanged.emit(self.index(rows[start], 0), self.index(rows[end], last))
            start = end + 1
        for g in touched:
            self._group_counts.pop(g, None)
            self._emit_group(g)
        if stale:
            self._set_stale(True)

    def _passes_segment(self, p: int, o: int) -> bool:
        if self.filters.segment == "access":
            return o in self.ix.objects_by_principal[p]
        return bool(self.ix.pending_mask(p, o))

    def _set_stale(self, stale: bool) -> None:
        if stale != self.stale:
            self.stale = stale
            self.staleChanged.emit(stale)

    def group_counts(self, g: int) -> tuple[int, int]:
        """(rows with access, pending cells) in group g."""
        counts = self._group_counts.get(g)
        if counts is None:
            ix = self.ix
            rows = self.groups[g].rows
            if self.mode == "principal":
                access_set = ix.objects_by_principal[self.entity]
                staged = ix.staged_objects_by_principal[self.entity]
                p = self.entity
                with_access = sum(1 for o in rows if o in access_set)
                pending = sum(ix.pending_mask(p, o).bit_count() for o in rows if o in staged)
            else:
                access_set = ix.principals_by_object[self.entity]
                o = self.entity
                with_access = sum(1 for p in rows if p in access_set)
                pending = sum(ix.pending_mask(p, o).bit_count() for p in rows if p in access_set)
            counts = (with_access, pending)
            self._group_counts[g] = counts
        return counts

    def group_text(self, g: int) -> str:
        group = self.groups[g]
        with_access, pending = self.group_counts(g)
        noun = "objects" if self.mode == "principal" else "principals"
        text = f"{group.label}   {len(group.rows):,} {noun} · {with_access:,} with access"
        if pending:
            text += f" · {pending:,} pending"
        return text

    # --- Qt model API ----------------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else self._row_count

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else COLUMN_COUNT

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        g, r = self.locate(index.row())
        if r < 0:
            return _GROUP_FLAGS
        column = index.column()
        if column == 0:
            return _ITEM_FLAGS
        o = self.pair(g, r)[1]
        if self.ix.object_applicable[o] & (1 << (column - 1)):
            return _CELL_FLAGS
        return _ITEM_FLAGS

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal:
            return None
        if section == 0:
            if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.AccessibleTextRole):
                return "Object" if self.mode == "principal" else "Principal"
            return None
        perm = PERMS[section - 1]
        if role == Qt.ItemDataRole.DisplayRole:
            return SHORT_NAMES[perm]
        if role in (Qt.ItemDataRole.ToolTipRole, Qt.ItemDataRole.AccessibleTextRole):
            return f"{perm.value} (click to select the column)" if role == Qt.ItemDataRole.ToolTipRole else perm.value
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        g, r = self.locate(index.row())
        if r < 0:
            return self._group_data(g, role) if index.column() == 0 else None
        p, o = self.pair(g, r)
        column = index.column()
        if column == 0:
            return self._name_data(p, o, role)
        perm = column - 1
        ix = self.ix
        applicable = bool(ix.object_applicable[o] & (1 << perm))
        if role == ApplicableRole:
            return applicable
        if role == StateRole:
            return cell_code(ix.row_state(p, o), perm)
        if role == CommittedRole:
            return cell_code(ix.committed_row(p, o), perm)
        if role == PendingRole:
            return bool(ix.pending_mask(p, o) & (1 << perm))
        if role == CellRole:
            return CellRef(p, o, perm) if applicable else None
        if role == Qt.ItemDataRole.DisplayRole:
            if not applicable:
                return ""
            return {STATE_GRANT: "✓", STATE_DENY: "✕"}.get(cell_code(ix.row_state(p, o), perm), "·")
        if role == Qt.ItemDataRole.AccessibleTextRole:
            return self.cell_sentence(p, o, perm)
        if role == Qt.ItemDataRole.ToolTipRole:
            return self.cell_tooltip(p, o, perm)
        return None

    def _group_data(self, g: int, role: int):
        if g >= len(self.groups):
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self.group_text(g)
        if role == Qt.ItemDataRole.AccessibleTextRole:
            group = self.groups[g]
            with_access, pending = self.group_counts(g)
            noun = "objects" if self.mode == "principal" else "principals"
            text = f"{group.label} group, {len(group.rows):,} {noun}, {with_access:,} with access"
            if pending:
                text += f", {pending:,} pending"
            return f"{text}, {'collapsed' if group.key in self.collapsed else 'expanded'}"
        if role == IsGroupRole:
            return True
        return None

    def _name_data(self, p: int, o: int, role: int):
        ix = self.ix
        if self.mode == "principal":
            obj = ix.objects[o]
            if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.AccessibleTextRole):
                return obj.object_name
            if role == Qt.ItemDataRole.ToolTipRole:
                tip = f"{obj.full_name} ({obj.object_type.value.lower()})"
                known, text = self.session.cached_description(o)
                return f"{tip}\n{text}" if known and text else tip
            if role == BadgeRole:
                return OBJECT_BADGES.get(obj.object_type.value, "?")
            return None
        user = ix.principals[p]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.AccessibleTextRole):
            return user.login_name
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{user.login_name} ({PRINCIPAL_TYPE_NAMES.get(user.principal_type, user.principal_type)})"
        if role == BadgeRole:
            return user.principal_type
        return None

    # --- Text ------------------------------------------------------------------------

    def cell_sentence(self, p: int, o: int, perm: int) -> str:
        """Screen-reader text, e.g. "SELECT on sales.Orders: granted, staged, was none"."""
        ix = self.ix
        target = ix.objects[o].full_name if self.mode == "principal" else ix.principals[p].login_name
        name = PERMS[perm].value
        if not ix.object_applicable[o] & (1 << perm):
            return f"{name} on {target}: not applicable"
        effective = cell_code(ix.row_state(p, o), perm)
        committed = cell_code(ix.committed_row(p, o), perm)
        text = f"{name} {'on' if self.mode == 'principal' else 'for'} {target}: {STATE_WORDS[effective]}"
        if effective != committed:
            text += f", staged, was {STATE_WORDS[committed]}"
        return text

    def cell_tooltip(self, p: int, o: int, perm: int) -> str:
        """Hover text naming the state, what a double-click does and the keys."""
        ix = self.ix
        obj = ix.objects[o]
        login = ix.principals[p].login_name
        name = PERMS[perm].value
        if not ix.object_applicable[o] & (1 << perm):
            return f"{name} doesn't apply to {obj.object_type.value.lower()}s"
        effective = cell_code(ix.row_state(p, o), perm)
        committed = cell_code(ix.committed_row(p, o), perm)
        state = STATE_NAMES[effective]
        if effective != committed:
            state += f" (staged; was {STATE_NAMES[committed]})"
        return (
            f"{name} on {obj.full_name} for {login} — {state}\n"
            f"Double-click or Space: change to {STATE_NAMES[_NEXT[effective]]}. G grant · D deny · R revoke."
        )
