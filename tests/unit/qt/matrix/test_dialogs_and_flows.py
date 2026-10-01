"""Confirm, Make like and description dialogs, plus the view flows that open them."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from src.qt.dialogs import confirm_bulk as confirm_module
from src.qt.dialogs.confirm_bulk import ConfirmBulkDialog
from src.qt.dialogs.edit_description import EditDescriptionDialog
from src.qt.dialogs.make_like import MakeLikeDialog
from src.qt.views.matrix import matrix_view as mv_module
from src.qt.views.matrix.bulk import BulkSummary
from src.qt.views.matrix.grid_model import GridFilters


class TestConfirmBulkDialog:
    def test_text_and_defaults(self, qtbot):
        summary = BulkSummary(changed=231, unchanged=16, skipped=3, grants=231)
        dialog = ConfirmBulkDialog("Grant SELECT on 247 objects in sales for CORP\\jsmith", summary)
        qtbot.addWidget(dialog)
        assert dialog.windowTitle() == "Stage 231 changes?"
        assert dialog.counts.text() == "231 will change · 16 already set · 3 don't apply (skipped)"
        assert dialog.split.isHidden()  # only one kind of change
        assert dialog.cancel_button.isDefault() and not dialog.stage_button.isDefault()
        assert dialog.stage_button.text() == "Stage 231 changes"
        assert not dialog.dont_ask

    def test_split_shown_for_mixed_changes(self, qtbot):
        dialog = ConfirmBulkDialog("Make a like b", BulkSummary(changed=57, grants=52, denies=1, revokes=4))
        qtbot.addWidget(dialog)
        assert not dialog.split.isHidden()
        assert dialog.split.text() == "Changes: 52 grants, 1 deny, 4 revokes"

    def test_confirm_bulk_returns_choice(self, qtbot, monkeypatch):
        def accept(self):
            self.dont_ask_box.setChecked(True)
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(ConfirmBulkDialog, "exec", accept)
        assert confirm_module.confirm_bulk(None, "x", BulkSummary(changed=5)) == (True, True)
        monkeypatch.setattr(ConfirmBulkDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
        assert confirm_module.confirm_bulk(None, "x", BulkSummary(changed=5)) == (False, False)


class TestMakeLike:
    def test_dialog_lists_others_and_filters(self, qtbot, session):
        ix = session.matrix.index
        dialog = MakeLikeDialog(ix, ix.principal_index("alice"), filter_active=False)
        qtbot.addWidget(dialog)
        assert dialog.model.stringList() == ["bob", "CORP\\team"]
        assert not dialog.filtered.isEnabled() and dialog.scope == "all"
        dialog._refilter("team")
        assert dialog.model.stringList() == ["CORP\\team"]
        dialog._accept()
        assert dialog.source == ix.principal_index("CORP\\team")

    def test_filter_scope_is_default_when_filtering(self, qtbot, session):
        ix = session.matrix.index
        dialog = MakeLikeDialog(ix, ix.principal_index("alice"), filter_active=True)
        qtbot.addWidget(dialog)
        assert dialog.scope == "filter"

    def test_flow_from_header_button(self, view, session, monkeypatch, confirmations):
        ix = session.matrix.index

        def run(self):
            self.choose(ix.principal_index("CORP\\team"))
            self._accept()
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(MakeLikeDialog, "exec", run)
        pane = view.panes["principal"]
        pane.header.make_like.click()
        assert session.staged_count == 2  # revoke SELECT on Orders, deny EXECUTE on usp_Close

    def test_filter_scope_only_touches_shown_objects(self, view, session):
        ix = session.matrix.index
        pane = view.panes["principal"]
        pane.header.set_filters(GridFilters(text="usp"))
        pane._on_filters()
        pane.apply_make_like(ix.principal_index("CORP\\team"), "filter")
        assert session.staged_count == 1


class TestDescriptions:
    def test_dialog_counter_and_limit(self, qtbot):
        dialog = EditDescriptionDialog("dbo.Orders", "Orders")
        qtbot.addWidget(dialog)
        assert dialog.counter.text() == "6 of 7,500 characters"
        dialog.editor.setPlainText("x" * 7_501)
        assert not dialog.save_button.isEnabled()

    def test_edit_flow_saves(self, qtbot, view, session, monkeypatch, env):
        def run(self):
            self.editor.setPlainText("Month-end close")
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(EditDescriptionDialog, "exec", run)
        view.set_mode("object", follow=False)
        pane = view.panes["object"]
        pane.left.select_entity(session.matrix.index.object_index("dbo", "usp_Close"))
        pane.edit_description()
        qtbot.waitUntil(lambda: pane.header.description.text() == "Month-end close", timeout=2000)
        assert env.conn.executed[-1][1][2] == "PROCEDURE"

    def test_edit_flow_reports_errors(self, qtbot, view, session, monkeypatch, env):
        errors = []
        def run(self):
            self.editor.setPlainText("New text")
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(EditDescriptionDialog, "exec", run)
        monkeypatch.setattr(mv_module.messages, "show_error", lambda *args: errors.append(args[1]))
        env.conn.fail_on = lambda sql: "extendedproperty" in sql
        view.set_mode("object", follow=False)
        view.panes["object"].edit_description()
        qtbot.waitUntil(lambda: bool(errors), timeout=2000)
        assert errors == ["Couldn't save the description"]


class TestViewFlows:
    def test_banner_and_read_only_when_offline(self, view, session):
        session.disconnect()
        assert view.banner.text() == "Offline. Reconnect to make changes."
        assert not view.banner.isHidden()
        assert view.panes["principal"].grid.cell_delegate.read_only

    def test_empty_states(self, view, session):
        pane = view.panes["principal"]
        pane.header.set_filters(GridFilters(text="zzz"))
        pane._on_filters()
        assert pane.grid_stack.currentWidget() is pane.empty
        assert pane.empty_label.text() == "No objects match the filters."
        pane.empty_button.click()
        assert pane.grid_stack.currentWidget() is pane.grid
        pane.left.select_entity(session.matrix.index.principal_index("bob"))
        pane.header.set_filters(GridFilters(segment="access", text="usp"))
        pane._on_filters()
        assert pane.empty_label.text() == "No objects match the filters."

    def test_no_access_message(self, big_view, big_session):
        ix = big_session.matrix.index
        lonely = next(o for o in ix.object_order if not ix.principals_by_object[o])
        big_view.set_mode("object", follow=False)
        pane = big_view.panes["object"]
        pane.left.select_entity(lonely)
        pane.header.set_filters(GridFilters(segment="access"))
        pane._on_filters()
        assert pane.empty_label.text() == f"{ix.objects[lonely].full_name} has no principals with access."
        assert pane.empty_button.text() == "Show all principals"
        pane.empty_button.click()
        assert pane.grid_stack.currentWidget() is pane.grid

    def test_f6_cycles_focus(self, qtbot, view):
        view.window().activateWindow()
        pane = view.pane
        pane.left.list.setFocus()
        view.cycle_focus()
        assert QApplication.focusWidget() is pane.header.search or not view.isActiveWindow()
        view.cycle_focus()
        view.cycle_focus(-1)

    def test_find_shortcuts_focus_searches(self, view):
        view.focus_list_search()
        view.focus_grid_filter()
        assert view.pane.header.search.hasFocus() or not view.isActiveWindow()

    def test_busy_cursor_follows_privilege_check(self, view, session):
        session.stagingBusyChanged.emit(True)
        assert QApplication.overrideCursor() is not None
        assert QApplication.overrideCursor().shape() == Qt.CursorShape.BusyCursor
        session.stagingBusyChanged.emit(False)
        assert QApplication.overrideCursor() is None

    def test_left_menu(self, view, session):
        pane = view.panes["principal"]
        menu = pane.build_left_menu(session.matrix.index.principal_index("bob"))
        assert [a.text() for a in menu.actions()] == ["Make like…", "Show only this principal's pending changes", "Tags…"]
        assert pane.left.entity == session.matrix.index.principal_index("bob")
        pane._show_only_pending()
        assert pane.header.filters.segment == "pending"

    def test_tags_link_asks_for_tag_manager(self, view, qtbot):
        with qtbot.waitSignal(view.tagsRequested, timeout=500):
            view.pane.header.tags_link.click()

    def test_tag_chip_filters_left_list(self, view, session):
        session.tag_store.add_user_tag("alice", "finance")
        session.save_tags()
        pane = view.panes["principal"]
        pane.header.tagClicked.emit("finance")
        assert pane.left.filters.tags == frozenset({"finance"})

    def test_reduced_motion_is_false_off_windows(self):
        assert mv_module.prefers_reduced_motion() is False
