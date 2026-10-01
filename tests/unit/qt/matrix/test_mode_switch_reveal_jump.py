"""Mode switch carrying the focused cell, pending-tray reveal and the Ctrl+K jump box."""

from src.models.permission import PermissionState
from src.qt.views.matrix.grid_model import GridFilters
from src.qt.views.matrix.jump_dialog import search_jump
from tests.unit.qt.matrix.conftest import INSERT, SELECT, cell


def focus(pane, c):
    pane.grid.setCurrentIndex(pane.model.index_for_cell(c))


class TestModeSwitch:
    def test_focused_cell_carries_over(self, view, session):
        c = cell(session, "alice", "sales", "Customers", INSERT)
        principal = view.panes["principal"]
        focus(principal, c)
        view.set_mode("object")
        pane = view.pane
        assert pane is view.panes["object"]
        assert pane.left.entity == c.o and pane.model.entity == c.o
        assert pane.model.cell_at(pane.grid.currentIndex()) == c
        view.set_mode("principal")
        assert view.pane.model.cell_at(view.pane.grid.currentIndex()) == c

    def test_hidden_row_shows_notice_and_show_it(self, view, session):
        c = cell(session, "alice", "sales", "Customers", INSERT)
        objects = view.panes["object"]
        objects.header.set_filters(GridFilters(principal_types=frozenset({"G"})))
        objects._on_filters()
        focus(view.panes["principal"], c)
        view.set_mode("object")
        assert objects.hidden_notice.isVisibleTo(view)
        assert "alice isn't shown" in objects.hidden_label.text()
        objects.show_it.click()
        assert objects.model.cell_at(objects.grid.currentIndex()) == c
        assert objects.header.filters == GridFilters()

    def test_selection_clears_on_mode_change(self, view, session):
        c = cell(session, "alice", "dbo", "Orders", SELECT)
        principal = view.panes["principal"]
        focus(principal, c)
        principal.grid.selectionModel().select(principal.grid.currentIndex(), principal.grid.selectionModel().SelectionFlag.Select)
        view.set_mode("object")
        assert principal.grid.selected_cells() == []


class TestReveal:
    def test_reveal_clears_only_hiding_filters(self, qtbot, view, session):
        c = cell(session, "bob", "dbo", "Orders", INSERT)
        session.matrix.stage([c], PermissionState.GRANT)
        view.set_mode("object", follow=False)
        principal = view.panes["principal"]
        principal.left.type_chips["S"].setChecked(True)  # hides bob
        principal.header.set_filters(GridFilters(segment="access", text="ord"))
        principal._on_filters()
        session.reveal(session.matrix.get_staged_changes()[0])
        assert view.mode == "principal"
        assert principal.left.entity == c.p
        assert principal.model.cell_at(principal.grid.currentIndex()) == c
        assert principal.grid.selected_cells() == [c]

    def test_reveal_keeps_filters_that_show_the_cell(self, view, session):
        c = cell(session, "alice", "dbo", "Orders", INSERT)
        session.matrix.stage([c], PermissionState.GRANT)
        principal = view.panes["principal"]
        principal.header.set_filters(GridFilters(text="ord"))
        principal._on_filters()
        session.reveal(session.matrix.get_staged_changes()[0])
        assert principal.header.filters.text == "ord"
        assert principal.model.cell_at(principal.grid.currentIndex()) == c


class TestJump:
    def test_ranking_prefix_first_then_shorter(self, big_session):
        ix = big_session.matrix.index
        groups = search_jump(ix, "table0001")
        objects = next(g for g in groups if g.title == "Objects")
        assert objects.results[0].text.split(".")[-1].casefold().startswith("table0001")
        assert len(objects.results) <= 8 and objects.total >= len(objects.results)

    def test_tags_and_limits(self, view, session):
        session.tag_store.add_object_tag("dbo.Orders", "finance")
        session.save_tags()
        groups = search_jump(session.matrix.index, "fin")
        assert [g.title for g in groups] == ["Tags"]
        assert groups[0].results[0].kind == "object_tag"
        assert search_jump(session.matrix.index, "") == []

    def test_jump_to_principal_object_and_tag(self, view, session):
        ix = session.matrix.index
        view.jump_to("object", ix.object_index("sales", "Customers"))
        assert view.mode == "object" and view.pane.model.entity == ix.object_index("sales", "Customers")
        view.jump_to("principal", ix.principal_index("CORP\\team"))
        assert view.mode == "principal" and view.pane.model.entity == ix.principal_index("CORP\\team")
        session.tag_store.add_user_tag("bob", "finance")
        session.save_tags()
        view.jump_to("principal_tag", "finance")
        model = view.pane.left.model
        assert [model.data(model.index(r)) for r in range(model.rowCount())] == ["bob"]

    def test_jump_dialog_enter_opens_first_result(self, qtbot, view, session):
        chosen = []
        view.jump_box.chosen.disconnect()
        view.jump_box.chosen.connect(lambda kind, key: chosen.append((kind, key)))
        view.open_jump()
        view.jump_box.search.setText("custom")
        view.jump_box.update_results()
        view.jump_box._choose_current()
        assert chosen == [("object", session.matrix.index.object_index("sales", "Customers"))]

    def test_show_all_expands_a_group(self, big_session, qtbot, settings):
        from src.qt.views.matrix.matrix_view import MatrixView

        big = MatrixView(big_session, settings)
        qtbot.addWidget(big)
        big.open_jump()
        big.jump_box.search.setText("table")
        big.jump_box.update_results()
        before = big.jump_box.results.count()
        more = next(
            big.jump_box.results.item(r)
            for r in range(big.jump_box.results.count())
            if big.jump_box.results.item(r).text().strip().startswith("Show all")
        )
        big.jump_box._activate(more)
        assert big.jump_box.results.count() > before
