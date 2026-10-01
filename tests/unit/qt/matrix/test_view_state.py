"""Remembered view state: round trip, missing entities, search text not restored."""

from PySide6.QtCore import QSettings

from src.qt.views.matrix import view_state
from src.qt.views.matrix.grid_model import GridFilters
from src.qt.views.matrix.matrix_view import MatrixView


def test_round_trip_through_qsettings(tmp_path):
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    state = view_state.ViewState(
        mode="object",
        principal="bob",
        object=("sales", "Customers"),
        lists={"principal": {"types": ["U"], "sort": "grants"}, "object": {"schemas": ["sales"]}},
        grids={"principal": {"segment": "access"}, "object": {"principal_types": ["G"]}},
    )
    view_state.save(settings, state)
    loaded = view_state.load(settings)
    assert loaded.mode == "object" and loaded.principal == "bob" and loaded.object == ("sales", "Customers")
    assert loaded.lists["principal"] == {"types": ["U"], "sort": "grants"}
    assert loaded.grids["object"] == {"principal_types": ["G"]}


def test_bad_values_fall_back_to_defaults(tmp_path):
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    settings.setValue("matrix/mode", "sideways")
    settings.setValue("matrix/list_principal", "{not json")
    loaded = view_state.load(settings)
    assert loaded.mode == "principal" and loaded.lists["principal"] == {} and loaded.object is None


def test_view_restores_mode_filters_and_selection(qtbot, view, session, settings):
    ix = session.matrix.index
    principal = view.panes["principal"]
    principal.left.select_entity(ix.principal_index("bob"))
    principal.left.type_chips["U"].setChecked(True)
    principal.left.search.setText("bo")
    principal.header.set_filters(GridFilters(segment="access", text="cust"))
    principal._on_filters()
    view.set_mode("object", follow=False)
    view.panes["object"].left.select_entity(ix.object_index("sales", "Customers"))
    view.save_state()

    again = MatrixView(session, settings)
    qtbot.addWidget(again)
    assert again.mode == "object"
    assert again.panes["object"].model.entity == ix.object_index("sales", "Customers")
    restored = again.panes["principal"]
    assert restored.left.filters.types == frozenset({"U"})
    assert restored.left.search.text() == ""  # search text isn't remembered
    assert restored.header.filters.segment == "access"
    assert restored.header.filters.text == ""
    again.set_mode("principal", follow=False)
    assert restored.model.entity == ix.principal_index("bob")


def test_missing_entities_are_ignored(qtbot, session, settings):
    view_state.save(settings, view_state.ViewState(principal="ghost", object=("nope", "Gone")))
    view = MatrixView(session, settings)
    qtbot.addWidget(view)
    assert view.pane.model.entity == session.matrix.index.principal_index("alice")
