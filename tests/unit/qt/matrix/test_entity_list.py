"""Left pane: search, chips, sort, tags, pending, selection and schema headers."""


from src.models.permission import PermissionState
from src.qt.views.matrix.entity_list import HeaderRole
from tests.unit.qt.matrix.conftest import INSERT, cell


def logins(pane):
    model = pane.left.model
    return [model.data(model.index(r)) for r in range(model.rowCount())]


def add_tags(session):
    session.tag_store.add_user_tag("alice", "finance")
    session.tag_store.add_user_tag("alice", "reporting")
    session.tag_store.add_user_tag("bob", "finance")
    session.save_tags()


class TestPrincipals:
    def test_initial_list_and_first_selected(self, view, session):
        pane = view.panes["principal"]
        assert logins(pane) == ["alice", "bob", "CORP\\team"]
        assert pane.left.entity == session.matrix.index.principal_index("alice")
        assert pane.model.entity == pane.left.entity
        assert pane.left.footer.text() == "3 principals"

    def test_search_and_footer(self, view):
        pane = view.panes["principal"]
        pane.left.search.setText("bo")
        pane.left.search.returnPressed.emit()
        assert logins(pane) == ["bob"]
        assert pane.left.footer.text() == "1 of 3 principals"

    def test_type_chips(self, view):
        pane = view.panes["principal"]
        pane.left.type_chips["U"].setChecked(True)
        assert logins(pane) == ["bob"]
        assert pane.left.type_chips["U"].accessibleName() == "Users filter, on"
        pane.left.type_chips["G"].setChecked(True)
        assert logins(pane) == ["bob", "CORP\\team"]

    def test_sort_by_grants(self, view, session):
        pane = view.panes["principal"]
        session.matrix.stage([cell(session, "bob", "dbo", "Orders", INSERT)], PermissionState.GRANT)
        pane.left.sort_box.setCurrentIndex(pane.left.sort_box.findData("grants"))
        assert logins(pane)[0] == "bob"

    def test_tags_must_all_match(self, view, session):
        add_tags(session)
        pane = view.panes["principal"]
        keys = {key for key, _label in pane.left.tags_chip._options}
        assert keys == {"finance", "reporting"}
        pane.left.tags_chip.add("finance")
        assert logins(pane) == ["alice", "bob"]
        pane.left.tags_chip.add("reporting")
        assert logins(pane) == ["alice"]

    def test_has_pending_refilters_after_staging(self, qtbot, view, session):
        pane = view.panes["principal"]
        pane.left.pending_chip.setChecked(True)
        assert logins(pane) == []
        assert pane.left.stack.currentWidget() is pane.left.empty
        session.matrix.stage([cell(session, "bob", "dbo", "Orders", INSERT)], PermissionState.GRANT)
        qtbot.waitUntil(lambda: logins(pane) == ["bob"], timeout=1000)

    def test_selection_kept_when_still_matching(self, view, session):
        pane = view.panes["principal"]
        bob = session.matrix.index.principal_index("bob")
        pane.left.select_entity(bob)
        pane.left.type_chips["U"].setChecked(True)
        assert pane.left.entity == bob
        pane.left.type_chips["U"].setChecked(False)
        pane.left.type_chips["G"].setChecked(True)
        assert pane.left.entity == session.matrix.index.principal_index("CORP\\team")
        assert pane.model.entity == pane.left.entity

    def test_clear_filters(self, view):
        pane = view.panes["principal"]
        pane.left.type_chips["S"].setChecked(True)
        pane.left.clear_filters()
        assert len(logins(pane)) == 3
        assert not pane.left.type_chips["S"].isChecked()

    def test_typing_moves_to_search(self, qtbot, view):
        pane = view.panes["principal"]
        pane.left.list.setFocus()
        qtbot.keyClicks(pane.left.list, "b")
        assert pane.left.search.text() == "b"

    def test_pending_role_updates_in_place(self, view, session):
        pane = view.panes["principal"]
        changed = []
        pane.left.model.dataChanged.connect(lambda tl, br, roles=(): changed.append(tl.row()))
        session.matrix.stage([cell(session, "bob", "dbo", "Orders", INSERT)], PermissionState.GRANT)
        assert changed == [1]


class TestObjects:
    def test_schema_headers_and_collapse(self, qtbot, view):
        view.set_mode("object")
        pane = view.panes["object"]
        model = pane.left.model
        rows = [model.data(model.index(r)) for r in range(model.rowCount())]
        assert rows == ["dbo · 2", "Orders", "usp_Close", "sales · 1", "Customers"]
        assert model.data(model.index(0), HeaderRole) == "dbo"
        pane.left._toggle_header("dbo")
        assert [model.data(model.index(r)) for r in range(model.rowCount())] == ["dbo · 2", "sales · 1", "Customers"]

    def test_type_and_pending_filters(self, qtbot, view, session):
        view.set_mode("object")
        pane = view.panes["object"]
        pane.left.type_chips["PROCEDURE"].setChecked(True)
        model = pane.left.model
        assert [model.data(model.index(r)) for r in range(model.rowCount())] == ["dbo · 1", "usp_Close"]
        pane.left.type_chips["PROCEDURE"].setChecked(False)
        pane.left.pending_chip.setChecked(True)
        assert model.rowCount() == 0
        session.matrix.stage([cell(session, "bob", "sales", "Customers", INSERT)], PermissionState.GRANT)
        qtbot.waitUntil(lambda: model.rowCount() == 2, timeout=1000)

    def test_schema_chip(self, view):
        view.set_mode("object")
        pane = view.panes["object"]
        pane.left.schema_chip.add("sales")
        model = pane.left.model
        assert [model.data(model.index(r)) for r in range(model.rowCount())] == ["sales · 1", "Customers"]
