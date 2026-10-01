"""Tests for Settings, Commit preview, Commit results, Connection lost, Tag manager and the audit view."""

import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMessageBox

from src.models.config import Configuration
from src.qt.dialogs import tag_manager as tag_module
from src.qt.dialogs.commit_preview import CommitPreviewDialog
from src.qt.dialogs.commit_result import CommitSuccessDialog, PartialFailureDialog
from src.qt.dialogs.connection_lost import ConnectionLostDialog
from src.qt.dialogs.settings_dialog import SettingsDialog
from src.qt.dialogs.tag_manager import MemberPickerDialog, TagManagerDialog
from src.qt.session import CommitReport, Session
from src.qt.views.audit_view import AuditView
from tests.unit.qt.conftest import CONFIG, stage


class TestSettings:
    def make(self, qtbot, env, last_test=None, reason=""):
        s = Session()
        s.config = CONFIG
        dialog = SettingsDialog(s, reason, None, last_test)
        qtbot.addWidget(dialog)
        return s, dialog

    def test_prefilled_and_reason_banner(self, qtbot, env):
        _s, dialog = self.make(qtbot, env, reason="Login failed for user")
        assert dialog.server.text() == "sql01" and dialog.database.text() == "FinanceDW"
        assert dialog.reason_label.isVisibleTo(dialog)
        assert "Login failed" in dialog.reason_label.text()

    def test_field_errors(self, qtbot, env):
        _s, dialog = self.make(qtbot, env)
        dialog.server.setText("")
        dialog.port.setText("99999")
        dialog.schema.setText("bad-schema")
        assert dialog.validate() is None
        assert dialog.errors[dialog.server].text().startswith("Enter the server")
        assert "between 1 and 65535" in dialog.errors[dialog.port].text()
        assert dialog.errors[dialog.schema].text()
        assert dialog.port.accessibleDescription() == dialog.errors[dialog.port].text()
        assert dialog.errors[dialog.database].isHidden()

    def test_port_must_be_a_number(self, qtbot, env):
        _s, dialog = self.make(qtbot, env)
        dialog.port.setText("abc")
        assert dialog.validate() is None
        assert dialog.errors[dialog.port].text() == "Port must be a number"

    def test_test_result_only_while_fields_match(self, qtbot, env):
        tested = Configuration(server="sql01", port=1433, database="FinanceDW", schema="dbo")
        _s, dialog = self.make(qtbot, env, last_test=(tested, True, "Connected to sql01/FinanceDW"))
        assert dialog.test_status.text() == "✓ Connected to sql01/FinanceDW"
        dialog.database.setText("Other")
        assert dialog.test_status.text() == "○ Not tested"
        dialog.database.setText("FinanceDW")
        assert dialog.test_status.text().startswith("✓")

    def test_test_connection_runs_in_background(self, qtbot, env, monkeypatch):
        from src.qt import session as session_module

        monkeypatch.setattr(session_module.db_connection, "test_connection", lambda c: (False, "Server not found"))
        _s, dialog = self.make(qtbot, env)
        dialog.test_connection()
        assert not dialog.test_button.isEnabled()
        qtbot.waitUntil(lambda: dialog.test_button.isEnabled(), timeout=2000)
        assert dialog.test_status.text() == "✗ Server not found"

    def test_save_connects_and_cancel_does_not(self, qtbot, env):
        s, dialog = self.make(qtbot, env)
        dialog.reject()
        assert env.saved_configs == []
        s2, dialog2 = self.make(qtbot, env)
        dialog2.server.setText("sql02")
        dialog2.save()
        assert dialog2.result() == QDialog.DialogCode.Accepted
        assert env.saved_configs[0].server == "sql02"
        s2.worker.shutdown(2000)


class TestCommitDialogs:
    def test_preview_lists_filters_and_counts(self, qtbot, session):
        stage(session, 6)
        session.matrix.revert([session.cell_for_change(session.matrix.get_staged_changes()[0])])
        plan = session.matrix.prepare_commit()
        dialog = CommitPreviewDialog(plan, "FinanceDW")
        qtbot.addWidget(dialog)
        assert dialog.proxy.rowCount() == 5
        assert dialog.summary.text() == "5 grants"
        assert dialog.commit_button.text() == "Commit 5"
        dialog.proxy.setFilterFixedString("nobody-matches-this")
        assert dialog.proxy.rowCount() == 0
        dialog.proxy.setFilterFixedString("ALICE")  # case-insensitive, any column
        assert dialog.proxy.rowCount() > 0
        assert dialog.model.data(dialog.model.index(0, 0)) == "GRANT"

    def test_preview_review(self, qtbot, session):
        stage(session, 5)
        dialog = CommitPreviewDialog(session.matrix.prepare_commit(), "FinanceDW")
        qtbot.addWidget(dialog)
        dialog._review()
        assert dialog.review_requested and dialog.result() == QDialog.DialogCode.Rejected

    def report(self, session, failed=0):
        stage(session, 6)
        changes = session.matrix.prepare_commit().changes
        from datetime import UTC, datetime

        return CommitReport(
            succeeded=changes[failed:],
            failed=tuple((c, "Insufficient privileges") for c in changes[:failed]),
            rolled_back=False,
            error=None,
            started_at=datetime.now(UTC),
        )

    def test_success_dialog(self, qtbot, session):
        from PySide6.QtWidgets import QLabel

        dialog = CommitSuccessDialog(self.report(session))
        qtbot.addWidget(dialog)
        texts = [label.text() for label in dialog.findChildren(QLabel)]
        assert "✓ 6 changes applied" in texts
        assert any(text.endswith("and 1 more") for text in texts)

    def test_partial_failure_choices(self, qtbot, session):
        report = self.report(session, failed=2)
        dialog = PartialFailureDialog(report)
        qtbot.addWidget(dialog)
        assert dialog.choice == "keep"
        dialog._choose("discard_failed")
        assert dialog.choice == "discard_failed"
        dialog.reject()
        assert dialog.choice == "keep"
        assert dialog.applied.count() == 4

    def test_connection_lost_choices(self, qtbot):
        dialog = ConnectionLostDialog("sql01/FinanceDW", "Communication link failure", 3)
        qtbot.addWidget(dialog)
        dialog._choose("reconnect")
        assert dialog.choice == "reconnect"
        dialog.reject()
        assert dialog.choice == "offline"


class TestTagManager:
    @pytest.fixture
    def dialog(self, qtbot, session):
        d = TagManagerDialog(session)
        qtbot.addWidget(d)
        return d

    def names(self, dialog):
        return [dialog.tag_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(dialog.tag_list.count())]

    def test_create_validates(self, dialog):
        dialog.new_name.setText("bad name")
        dialog.create_tag()
        assert not dialog.new_error.isHidden()
        assert self.names(dialog) == []
        dialog.new_name.setText("finance")
        dialog.create_tag()
        assert self.names(dialog) == ["finance"]
        assert dialog.current_tag() == "finance"
        dialog.new_name.setText("Finance")
        dialog.create_tag()
        assert "already exists" in dialog.new_error.text()

    def test_add_members_saves(self, dialog, session, env, monkeypatch):
        dialog.new_name.setText("finance")
        dialog.create_tag()

        def pick(self):
            self.chosen = ["alice", "bob"]
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(tag_module.MemberPickerDialog, "exec", pick)
        dialog.add_members("principals")
        assert env.tag_saves == 1
        assert sorted(session.tag_store.get_users_with_tag("finance")) == ["alice", "bob"]
        assert dialog.principals.model.stringList() == ["alice", "bob"]
        assert "finance" not in dialog._new_tags  # now a real tag
        dialog.principals.list.selectAll()
        dialog.remove_members("principals")
        assert session.tag_store.get_users_with_tag("finance") == []

    def test_rename_merges(self, dialog, session, monkeypatch):
        store = session.tag_store
        store.add_user_tag("alice", "fin")
        store.add_user_tag("bob", "finance")
        store.add_user_tag("alice", "finance")
        dialog.refresh(select="fin")
        monkeypatch.setattr(tag_module.QInputDialog, "getText", lambda *a, **k: ("FINANCE", True))
        monkeypatch.setattr(tag_module.QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
        dialog.rename_tag()
        assert store.get_user_tags("alice") == ["finance"]  # merged, no duplicate
        assert sorted(store.get_users_with_tag("finance")) == ["alice", "bob"]

    def test_delete(self, dialog, session, monkeypatch):
        session.tag_store.add_object_tag("dbo.Orders", "pii")
        dialog.refresh(select="pii")
        monkeypatch.setattr(tag_module.QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
        dialog.delete_tag()
        assert session.tag_store.get_objects_with_tag("pii") == ["dbo.Orders"]
        monkeypatch.setattr(tag_module.QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
        dialog.delete_tag()
        assert session.tag_store.get_objects_with_tag("pii") == []


def test_member_picker_filters_large_lists(qtbot):
    items = [(f"sch{i % 20:02d}.Table{i:06d}", "Table") for i in range(20_000)]
    started = time.perf_counter()
    picker = MemberPickerDialog("Add objects", items, exclude={items[0][0]})
    qtbot.addWidget(picker)
    assert picker.model.rowCount() == 19_999
    picker._filter("Table00012")
    assert picker.proxy.rowCount() == 10
    picker._set_shown(Qt.CheckState.Checked)
    assert len(picker.checked_keys()) == 10
    assert picker.add_button.text() == "Add 10"
    picker._accept()
    assert len(picker.chosen) == 10
    assert time.perf_counter() - started < 5


class TestAuditView:
    def test_filters_and_range(self, qtbot, session):
        view = AuditView(session)
        qtbot.addWidget(view)
        view.principal_field.setText("jsmith")
        view.action_combo.setCurrentIndex(2)
        filters = view.filters()
        assert filters["affected_user_contains"] == "jsmith" and filters["action"] == "DENY"
        assert "start_date" in filters and "end_date" not in filters
        view.set_range(None, search=False)
        assert "start_date" not in view.filters()

    def test_search_shows_empty_state(self, qtbot, session):
        view = AuditView(session)
        qtbot.addWidget(view)
        view.refresh()
        qtbot.waitUntil(lambda: view.message.text() == "No audit entries match these filters.", timeout=2000)
        assert not view.export_button.isEnabled()

    def test_disconnected_message(self, qtbot, session):
        session.disconnect()
        view = AuditView(session)
        qtbot.addWidget(view)
        view.refresh()
        assert view.message.text() == "Connect to a database to see the audit log."
