"""Grid editing with keys, mouse and context menus (spec sections 9.1-9.4)."""

import pytest
from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtGui import QGuiApplication

from tests.unit.qt.matrix.conftest import EXECUTE, INSERT, SELECT, cell, state_name

Select = QItemSelectionModel.SelectionFlag


@pytest.fixture
def pane(view, session):
    pane = view.panes["principal"]
    pane.left.select_entity(session.matrix.index.principal_index("alice"))
    pane.grid.setFocus()
    return pane


def point(grid, index):
    return grid.visualRect(index).center()


def click(qtbot, grid, index, modifier=Qt.KeyboardModifier.NoModifier):
    qtbot.mouseClick(grid.viewport(), Qt.MouseButton.LeftButton, modifier, point(grid, index))


def select(pane, *cells):
    grid = pane.grid
    grid.clearSelection()
    for c in cells:
        grid.selectionModel().select(pane.model.index_for_cell(c), Select.Select)
    grid.selectionModel().setCurrentIndex(pane.model.index_for_cell(cells[-1]), Select.NoUpdate)


class TestMouse:
    def test_click_selects_and_never_changes(self, qtbot, pane, session):
        c = cell(session, "alice", "sales", "Customers", INSERT)
        click(qtbot, pane.grid, pane.model.index_for_cell(c))
        assert pane.grid.selected_cells() == [c]
        assert session.staged_count == 0

    def test_double_click_cycles(self, qtbot, pane, session):
        c = cell(session, "alice", "sales", "Customers", INSERT)
        index = pane.model.index_for_cell(c)
        qtbot.mouseDClick(pane.grid.viewport(), Qt.MouseButton.LeftButton, pos=point(pane.grid, index))
        assert state_name(session, c) == "GRANT"

    def test_click_on_cell_that_doesnt_apply_does_nothing(self, qtbot, pane, session):
        index = pane.model.index(2, SELECT + 1)  # SELECT on usp_Close
        click(qtbot, pane.grid, index)
        assert pane.grid.selected_cells() == []
        assert pane.grid.currentIndex() != index

    def test_name_click_selects_applicable_row_cells(self, qtbot, pane, session):
        click(qtbot, pane.grid, pane.model.index(2, 0))  # usp_Close name
        perms = {c.perm for c in pane.grid.selected_cells()}
        assert EXECUTE in perms and SELECT not in perms and len(perms) == 3

    def test_header_click_selects_column(self, qtbot, pane, session):
        pane.grid._on_header_clicked(SELECT + 1)
        objects = {session.matrix.index.objects[c.o].object_name for c in pane.grid.selected_cells()}
        assert objects == {"Orders", "Customers"}

    def test_group_click_collapses_and_shift_click_selects(self, qtbot, pane, session):
        group = pane.model.group_index(1)  # sales
        click(qtbot, pane.grid, group)
        assert pane.model.is_collapsed(1)
        click(qtbot, pane.grid, pane.model.group_index(1))
        assert not pane.model.is_collapsed(1)
        click(qtbot, pane.grid, pane.model.group_index(1), Qt.KeyboardModifier.ShiftModifier)
        assert {c.o for c in pane.grid.selected_cells()} == {session.matrix.index.object_index("sales", "Customers")}


class TestKeys:
    def test_g_d_r_u_on_selection(self, qtbot, pane, session):
        a = cell(session, "alice", "dbo", "Orders", INSERT)
        b = cell(session, "alice", "sales", "Customers", INSERT)
        select(pane, a, b)
        qtbot.keyClick(pane.grid, Qt.Key.Key_G)
        assert state_name(session, a) == state_name(session, b) == "GRANT"
        qtbot.keyClick(pane.grid, Qt.Key.Key_D)
        assert state_name(session, a) == "DENY"
        qtbot.keyClick(pane.grid, Qt.Key.Key_R)
        assert state_name(session, a) == "NONE" and session.staged_count == 0
        qtbot.keyClick(pane.grid, Qt.Key.Key_G)
        qtbot.keyClick(pane.grid, Qt.Key.Key_U)
        assert session.staged_count == 0

    def test_delete_revokes(self, qtbot, pane, session):
        c = cell(session, "alice", "dbo", "Orders", SELECT)
        select(pane, c)
        qtbot.keyClick(pane.grid, Qt.Key.Key_Delete)
        assert state_name(session, c) == "NONE"

    def test_space_cycles_one_and_opens_menu_for_many(self, qtbot, pane, session, monkeypatch):
        c = cell(session, "alice", "sales", "Customers", INSERT)
        select(pane, c)
        qtbot.keyClick(pane.grid, Qt.Key.Key_Space)
        assert state_name(session, c) == "GRANT"
        menus = []
        monkeypatch.setattr(pane.grid, "_show_menu", lambda index, pos: menus.append(index))
        select(pane, c, cell(session, "alice", "dbo", "Orders", INSERT))
        qtbot.keyClick(pane.grid, Qt.Key.Key_Space)
        assert len(menus) == 1 and session.staged_count == 1

    def test_escape_clears_selection_only(self, qtbot, pane, session):
        c = cell(session, "alice", "sales", "Customers", INSERT)
        select(pane, c)
        qtbot.keyClick(pane.grid, Qt.Key.Key_G)
        qtbot.keyClick(pane.grid, Qt.Key.Key_Escape)
        assert pane.grid.selected_cells() == []
        assert session.staged_count == 1

    def test_keys_ignored_when_offline(self, qtbot, pane, session):
        messages = []
        session.statusMessage.connect(lambda text, _ms: messages.append(text))
        session.disconnect()
        c = cell(session, "alice", "sales", "Customers", INSERT)
        select(pane, c)
        qtbot.keyClick(pane.grid, Qt.Key.Key_G)
        qtbot.keyClick(pane.grid, Qt.Key.Key_Space)
        assert session.staged_count == 0
        assert "Offline. Reconnect to make changes." in messages
        assert pane.grid.cell_delegate.read_only

    def test_arrows_skip_cells_that_dont_apply_and_groups(self, qtbot, pane, session):
        start = cell(session, "alice", "dbo", "Orders", SELECT)
        pane.grid.setCurrentIndex(pane.model.index_for_cell(start))
        qtbot.keyClick(pane.grid, Qt.Key.Key_Down)
        # usp_Close has no SELECT and the sales header is skipped
        assert pane.model.cell_at(pane.grid.currentIndex()) == cell(session, "alice", "sales", "Customers", SELECT)
        pane.grid.setCurrentIndex(pane.model.index_for_cell(cell(session, "alice", "dbo", "usp_Close", EXECUTE)))
        qtbot.keyClick(pane.grid, Qt.Key.Key_Left)
        assert pane.grid.currentIndex().column() == 0  # nothing applicable to the left: the name
        qtbot.keyClick(pane.grid, Qt.Key.Key_Right)
        assert pane.model.cell_at(pane.grid.currentIndex()).perm == EXECUTE

    def test_home_end(self, qtbot, pane, session):
        pane.grid.setCurrentIndex(pane.model.index_for_cell(cell(session, "alice", "dbo", "usp_Close", EXECUTE)))
        qtbot.keyClick(pane.grid, Qt.Key.Key_End)
        last = pane.model.cell_at(pane.grid.currentIndex())
        qtbot.keyClick(pane.grid, Qt.Key.Key_Home)
        first = pane.model.cell_at(pane.grid.currentIndex())
        assert first.perm == EXECUTE and last.perm > EXECUTE

    def test_ctrl_a_selects_every_applicable_cell(self, qtbot, pane, session):
        qtbot.keyClick(pane.grid, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        assert pane.grid.selection_count() == 7 + 3 + 7
        assert len(pane.grid.selected_cells()) == 17

    def test_enter_on_group_toggles(self, qtbot, pane):
        pane.grid.setCurrentIndex(pane.model.group_index(0))
        qtbot.keyClick(pane.grid, Qt.Key.Key_Return)
        assert pane.model.is_collapsed(0)

    def test_copy(self, qtbot, pane, session):
        select(pane, cell(session, "alice", "dbo", "Orders", SELECT))
        pane.grid.copy_selection()
        text = QGuiApplication.clipboard().text()
        assert text.splitlines()[1].startswith("dbo.Orders\tGRANT")


class TestMenus:
    def test_selection_menu_describes_action(self, pane, session):
        select(pane, cell(session, "alice", "dbo", "Orders", INSERT), cell(session, "alice", "sales", "Customers", INSERT))
        menu = pane.grid.build_menu(pane.grid.currentIndex())
        texts = [a.text() for a in menu.actions()]
        assert texts[0] == "Grant INSERT on 2 objects for alice\tG"
        assert "Revert to committed\tU" not in texts

    def test_group_action_stages_whole_group(self, pane, session, confirmations):
        menu = pane.grid.build_menu(pane.model.group_index(0))  # dbo
        grant = next(a for a in menu.actions() if a.text() == "Grant").menu()
        action = next(a for a in grant.actions() if a.text().startswith("VIEW DEFINITION"))
        assert "on all 2 objects in dbo for alice" in action.text()
        action.trigger()
        assert session.staged_count == 2

    def test_preset_from_menu(self, pane, session):
        select(pane, cell(session, "alice", "sales", "Customers", INSERT))
        pane.grid.apply_preset("Read/write")
        assert session.staged_count == 4  # SELECT, INSERT, UPDATE, DELETE on Customers

    def test_selection_count_label(self, qtbot, pane, session):
        pane.grid._on_header_clicked(SELECT + 1)
        qtbot.waitUntil(lambda: pane.selection_label.text() == "2 cells selected", timeout=1000)

    def test_entity_change_clears_selection(self, pane, session):
        select(pane, cell(session, "alice", "dbo", "Orders", SELECT))
        pane.left.select_entity(session.matrix.index.principal_index("bob"))
        assert pane.grid.selected_cells() == []
