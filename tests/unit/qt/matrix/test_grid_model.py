"""GridModel: grouping, lookups, flags, roles, change notifications and rebuilds."""

from PySide6.QtCore import Qt

from src.models.permission import STATE_GRANT, PermissionState
from src.qt.views.matrix.grid_model import (
    ApplicableRole,
    CellRole,
    GridFilters,
    GridModel,
    PendingRole,
    StateRole,
)
from tests.unit.qt.matrix.conftest import EXECUTE, INSERT, SELECT, cell


def principal_model(session, login="alice", filters=None):
    model = GridModel(session, "principal")
    if filters is not None:
        model.filters = filters
    model.set_entity(session.matrix.index.principal_index(login))
    return model


def names(model):
    """Table rows as text: "# group" for headers, the item name otherwise."""
    out = []
    for row in range(model.rowCount()):
        g, r = model.locate(row)
        if r < 0:
            out.append(f"# {model.groups[g].label}")
        else:
            out.append(model.data(model.index(row, 0)))
    return out


class TestGrouping:
    def test_by_principal_groups_by_schema(self, session):
        model = principal_model(session)
        assert names(model) == ["# dbo", "Orders", "usp_Close", "# sales", "Customers"]
        assert model.columnCount() == 9

    def test_by_object_groups_by_principal_type(self, session):
        model = GridModel(session, "object")
        model.set_entity(session.matrix.index.object_index("dbo", "Orders"))
        assert names(model) == [
            "# Windows groups",
            "CORP\\team",
            "# Windows users",
            "bob",
            "# SQL users",
            "alice",
        ]

    def test_only_with_access_and_pending(self, session):
        model = principal_model(session, filters=GridFilters(segment="access"))
        assert names(model) == ["# dbo", "Orders"]
        session.matrix.stage([cell(session, "alice", "sales", "Customers", INSERT)], PermissionState.GRANT)
        model.set_filters(GridFilters(segment="pending"))
        assert names(model) == ["# sales", "Customers"]

    def test_text_and_type_filters(self, session):
        from src.models.db_object import ObjectType

        model = principal_model(session, filters=GridFilters(text="cust"))
        assert names(model) == ["# sales", "Customers"]
        model.set_filters(GridFilters(object_types=frozenset({ObjectType.PROCEDURE})))
        assert names(model) == ["# dbo", "usp_Close"]

    def test_object_mode_pending_segment(self, session):
        model = GridModel(session, "object")
        model.filters = GridFilters(segment="pending")
        model.set_entity(session.matrix.index.object_index("dbo", "Orders"))
        assert names(model) == []
        session.matrix.stage([cell(session, "bob", "dbo", "Orders", SELECT)], PermissionState.GRANT)
        model.rebuild()
        assert names(model) == ["# Windows users", "bob"]


class TestLookups:
    def test_cell_round_trip(self, session):
        model = principal_model(session)
        c = cell(session, "alice", "sales", "Customers", INSERT)
        index = model.index_for_cell(c)
        assert index.isValid() and index.row() == 4 and index.column() == INSERT + 1
        assert model.cell_at(index) == c

    def test_cell_at_none_for_names_groups_and_not_applicable(self, session):
        model = principal_model(session)
        assert model.cell_at(model.index(1, 0)) is None  # name
        assert model.cell_at(model.index(0, 1)) is None  # group
        assert model.cell_at(model.index(2, SELECT + 1)) is None  # SELECT on a procedure

    def test_index_for_other_entity_is_invalid(self, session):
        model = principal_model(session)
        assert not model.index_for_cell(cell(session, "bob", "dbo", "Orders", SELECT)).isValid()

    def test_collapse_expand_shifts_rows(self, session):
        model = principal_model(session)
        model.set_collapsed(0, True)
        assert names(model) == ["# dbo", "# sales", "Customers"]
        assert model.pair_at(2) == (model.entity, session.matrix.index.object_index("sales", "Customers"))
        # Finding a cell in a collapsed group expands it
        index = model.index_for_cell(cell(session, "alice", "dbo", "usp_Close", EXECUTE))
        assert index.row() == 2
        assert names(model)[:3] == ["# dbo", "Orders", "usp_Close"]

    def test_collapsed_groups_survive_rebuilds(self, session):
        model = principal_model(session)
        model.set_collapsed(1, True)
        model.set_entity(session.matrix.index.principal_index("bob"))
        assert names(model) == ["# dbo", "Orders", "usp_Close", "# sales"]

    def test_segments(self, session):
        model = principal_model(session)
        assert list(model.segments(0, 4)) == [(0, 0, 1), (1, 0, 0)]
        assert list(model.segments(2, 3)) == [(0, 1, 1)]


class TestFlagsAndRoles:
    def test_flags(self, session):
        model = principal_model(session)
        selectable = Qt.ItemFlag.ItemIsSelectable
        assert not model.flags(model.index(0, 1)) & selectable  # group
        assert not model.flags(model.index(1, 0)) & selectable  # name
        assert model.flags(model.index(1, SELECT + 1)) & selectable
        assert not model.flags(model.index(2, SELECT + 1)) & selectable  # doesn't apply

    def test_roles(self, session):
        model = principal_model(session)
        index = model.index(1, SELECT + 1)  # alice SELECT on Orders: GRANT
        assert model.data(index, StateRole) == STATE_GRANT
        assert model.data(index, ApplicableRole) is True
        assert model.data(index, PendingRole) is False
        assert model.data(index, CellRole) == cell(session, "alice", "dbo", "Orders", SELECT)
        assert model.data(index) == "✓"
        assert model.data(index, Qt.ItemDataRole.AccessibleTextRole) == "SELECT on dbo.Orders: granted"
        assert model.data(model.index(2, SELECT + 1), Qt.ItemDataRole.AccessibleTextRole).endswith("not applicable")
        tip = model.data(index, Qt.ItemDataRole.ToolTipRole)
        assert "GRANT" in tip and "change to DENY" in tip
        assert model.headerData(1, Qt.Orientation.Horizontal) == "SEL"
        assert model.headerData(1, Qt.Orientation.Horizontal, Qt.ItemDataRole.AccessibleTextRole) == "SELECT"

    def test_staged_text(self, session):
        model = principal_model(session)
        c = cell(session, "alice", "dbo", "Orders", SELECT)
        session.matrix.stage([c], PermissionState.DENY)
        index = model.index_for_cell(c)
        assert model.data(index, Qt.ItemDataRole.AccessibleTextRole) == "SELECT on dbo.Orders: denied, staged, was granted"
        assert model.data(index, PendingRole) is True
        assert "1 pending" in model.group_text(0)

    def test_by_object_hides_columns_that_dont_apply(self, session):
        model = GridModel(session, "object")
        model.set_entity(session.matrix.index.object_index("dbo", "usp_Close"))
        mask = model.applicable_mask()
        assert mask & (1 << EXECUTE) and not mask & (1 << SELECT)


class TestChanges:
    def test_data_changed_only_for_affected_rows(self, qtbot, session):
        model = principal_model(session)
        session.matrix.subscribe(model.on_matrix_change)
        emitted = []
        model.dataChanged.connect(lambda tl, br, roles=(): emitted.append((tl.row(), br.row())))
        session.matrix.stage([cell(session, "alice", "sales", "Customers", INSERT)], PermissionState.GRANT)
        assert (4, 4) in emitted  # the row
        assert (3, 3) in emitted  # its group header
        assert all(row in (3, 4) for pair in emitted for row in pair)

    def test_changes_for_other_entities_are_ignored(self, session):
        model = principal_model(session)
        session.matrix.subscribe(model.on_matrix_change)
        emitted = []
        model.dataChanged.connect(lambda *args: emitted.append(args))
        session.matrix.stage([cell(session, "bob", "dbo", "Orders", INSERT)], PermissionState.GRANT)
        assert emitted == []

    def test_rows_stay_visible_and_filter_goes_stale(self, session):
        model = principal_model(session, filters=GridFilters(segment="access"))
        session.matrix.subscribe(model.on_matrix_change)
        stale = []
        model.staleChanged.connect(stale.append)
        orders = cell(session, "alice", "dbo", "Orders", SELECT)
        session.matrix.stage([orders], PermissionState.NONE)  # still "with access" (committed side)
        session.matrix.stage([cell(session, "alice", "sales", "Customers", SELECT)], PermissionState.GRANT)
        assert names(model) == ["# dbo", "Orders"]  # Customers not added while editing
        assert stale == [True] and model.stale
        model.rebuild()
        assert names(model) == ["# dbo", "Orders", "# sales", "Customers"]
        assert model.stale is False

    def test_rebuild_keeps_current_cell_by_natural_key(self, qtbot, view, session):
        pane = view.panes["principal"]
        pane.left.select_entity(session.matrix.index.principal_index("alice"))
        c = cell(session, "alice", "sales", "Customers", INSERT)
        pane.grid.setCurrentIndex(pane.model.index_for_cell(c))
        with qtbot.waitSignal(session.dataLoaded, timeout=3000):
            session.refresh()
        assert pane.model.cell_at(pane.grid.currentIndex()).perm == c.perm
        assert pane.model.pair_for(pane.grid.currentIndex())[1] == c.o
