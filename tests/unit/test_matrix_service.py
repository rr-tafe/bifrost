"""Unit tests for PermissionMatrix: staging, undo/redo, events, reload, commit and legacy API."""

import pyodbc
import pytest

from src.models.permission import PermissionState, PermissionType
from src.services import matrix as matrix_module
from src.services.loader import MatrixSnapshot
from src.services.matrix import CellRef, CommitOutcome, PermissionMatrix
from src.services.matrix_index import PERM_INDEX
from src.services.tags import TagStore
from tests.unit.fake_db import FakeConnection
from tests.unit.test_matrix_index import small_snapshot

SELECT = PERM_INDEX[PermissionType.SELECT]
INSERT = PERM_INDEX[PermissionType.INSERT]
UPDATE = PERM_INDEX[PermissionType.UPDATE]
GRANT, DENY, NONE = PermissionState.GRANT, PermissionState.DENY, PermissionState.NONE


@pytest.fixture
def matrix() -> PermissionMatrix:
    m = PermissionMatrix(None)
    m.apply_snapshot(small_snapshot())
    return m


def ids(m: PermissionMatrix):
    """(alice, bob, team, orders, customers, usp) indexes."""
    i = m.index
    return (
        i.principal_index("alice"),
        i.principal_index("bob"),
        i.principal_index("CORP\\team"),
        i.object_index("dbo", "Orders"),
        i.object_index("sales", "Customers"),
        i.object_index("dbo", "usp_Close"),
    )


class TestStaging:
    def test_stage_is_one_undo_group(self, matrix):
        alice, bob, _team, orders, customers, _usp = ids(matrix)
        result = matrix.stage(
            [CellRef(bob, orders, SELECT), CellRef(bob, customers, INSERT), CellRef(bob, orders, UPDATE)], GRANT
        )
        assert result.changed == 3
        assert result.group is not None
        assert matrix.can_undo()
        assert matrix.get_staged_change_count() == 3
        matrix.undo()
        assert matrix.get_staged_change_count() == 0
        assert not matrix.can_undo()

    def test_stage_counts_unchanged_and_skipped(self, matrix):
        alice, _bob, _team, orders, _customers, usp = ids(matrix)
        result = matrix.stage([CellRef(alice, orders, SELECT), CellRef(alice, usp, SELECT)], GRANT)
        assert (result.changed, result.unchanged, result.skipped_not_applicable) == (0, 1, 1)
        assert result.group is None
        assert not matrix.can_undo()

    def test_labels(self, matrix):
        _alice, bob, team, orders, customers, _usp = ids(matrix)
        one = matrix.stage([CellRef(bob, orders, SELECT)], GRANT)
        assert one.group.label == "Grant SELECT on dbo.Orders for bob"
        many = matrix.stage([CellRef(bob, orders, UPDATE), CellRef(bob, customers, UPDATE)], DENY)
        assert many.group.label == "Deny UPDATE on 2 objects for bob"
        cells = matrix.stage([CellRef(team, orders, INSERT), CellRef(bob, orders, INSERT)], GRANT)
        assert cells.group.label == "Grant INSERT on 2 cells"
        assert matrix.stage([CellRef(team, orders, UPDATE)], NONE).group is None  # already NONE

    def test_stage_cycle(self, matrix):
        _alice, bob, _team, orders, _customers, _usp = ids(matrix)
        cell = CellRef(bob, orders, SELECT)
        states = []
        for _ in range(3):
            matrix.stage_cycle(cell)
            states.append(matrix.index.cell(bob, orders, SELECT).effective)
        assert states == [GRANT, DENY, NONE]

    def test_revert(self, matrix):
        alice, _bob, _team, orders, _customers, _usp = ids(matrix)
        matrix.stage([CellRef(alice, orders, SELECT), CellRef(alice, orders, UPDATE)], DENY)
        result = matrix.revert([CellRef(alice, orders, SELECT), CellRef(alice, orders, UPDATE)])
        assert result.changed == 2
        assert matrix.get_staged_change_count() == 0

    def test_redo_cleared_by_new_stage(self, matrix):
        _alice, bob, _team, orders, _customers, _usp = ids(matrix)
        matrix.stage([CellRef(bob, orders, SELECT)], GRANT)
        matrix.undo()
        assert matrix.can_redo()
        matrix.stage([CellRef(bob, orders, INSERT)], GRANT)
        assert not matrix.can_redo()

    def test_undo_restores_effective_states_in_reverse(self, matrix):
        _alice, bob, _team, orders, _customers, _usp = ids(matrix)
        cell = CellRef(bob, orders, SELECT)
        matrix.stage([cell], GRANT)
        matrix.stage([cell], DENY)
        matrix.undo()
        assert matrix.index.cell(bob, orders, SELECT).effective == GRANT
        matrix.undo()
        assert matrix.index.cell(bob, orders, SELECT).effective == NONE
        assert matrix.undo() is None
        matrix.redo()
        matrix.redo()
        assert matrix.index.cell(bob, orders, SELECT).effective == DENY

    def test_undo_limit(self, matrix):
        _alice, bob, _team, orders, _customers, _usp = ids(matrix)
        cell = CellRef(bob, orders, SELECT)
        for i in range(60):
            matrix.stage([cell], GRANT if i % 2 == 0 else NONE)
        undone = 0
        while matrix.undo():
            undone += 1
        assert undone == PermissionMatrix.MAX_UNDO_GROUPS

    def test_cancel_clears_everything(self, matrix):
        _alice, bob, _team, orders, _customers, _usp = ids(matrix)
        matrix.stage([CellRef(bob, orders, SELECT)], GRANT)
        matrix.cancel()
        assert not matrix.has_staged_changes()
        assert not matrix.can_undo()


class TestEvents:
    def test_one_event_per_call_with_rows(self, matrix):
        events = []
        matrix.subscribe(events.append)
        _alice, bob, _team, orders, customers, _usp = ids(matrix)
        matrix.stage([CellRef(bob, orders, SELECT), CellRef(bob, orders, INSERT), CellRef(bob, customers, SELECT)], DENY)
        assert len(events) == 1
        assert events[0].reason == "stage"
        assert events[0].rows == frozenset({(bob, orders), (bob, customers)})
        assert events[0].staged_count == 3
        matrix.undo()
        matrix.cancel()
        assert [e.reason for e in events] == ["stage", "undo", "cancel"]

    def test_no_event_when_nothing_changes(self, matrix):
        events = []
        matrix.subscribe(events.append)
        alice, _bob, _team, orders, _customers, _usp = ids(matrix)
        matrix.stage([CellRef(alice, orders, SELECT)], GRANT)  # already GRANT
        assert events == []

    def test_failing_listener_does_not_stop_others(self, matrix):
        seen = []

        def broken(_change):
            raise RuntimeError("boom")

        matrix.subscribe(broken)
        matrix.subscribe(seen.append)
        _alice, bob, _team, orders, _customers, _usp = ids(matrix)
        matrix.stage([CellRef(bob, orders, SELECT)], GRANT)
        assert len(seen) == 1
        assert matrix.get_staged_change_count() == 1

    def test_unsubscribe_and_legacy_callback(self, matrix):
        calls = []
        unsubscribe = matrix.subscribe(calls.append)
        unsubscribe()
        legacy = []
        matrix.set_on_change_callback(lambda: legacy.append(1))
        matrix.set_on_change_callback(lambda: legacy.append(2))  # replaces the first
        _alice, bob, _team, orders, _customers, _usp = ids(matrix)
        matrix.stage([CellRef(bob, orders, SELECT)], GRANT)
        assert calls == []
        assert legacy == [2]


class TestReload:
    def test_staged_none_to_grant_survives_reload(self, matrix):
        """Regression (P3): refresh used to drop staged changes on cells with no committed permission."""
        _alice, bob, _team, orders, _customers, _usp = ids(matrix)
        matrix.stage([CellRef(bob, orders, SELECT)], GRANT)
        report = matrix.apply_snapshot(small_snapshot())
        assert len(report.kept) == 1
        assert matrix.get_staged_change_count() == 1
        assert not matrix.can_undo()  # history cleared on reload

    def test_report_dropped_and_already_applied(self, matrix):
        alice, bob, team, orders, customers, _usp = ids(matrix)
        matrix.stage([CellRef(bob, orders, SELECT), CellRef(team, customers, SELECT), CellRef(alice, orders, UPDATE)], GRANT)
        snapshot = small_snapshot()
        principals = tuple(u for u in snapshot.principals if u.login_name != "CORP\\team")
        rows = snapshot.permission_rows + ((5, 100, UPDATE, 1),)  # someone else granted alice UPDATE
        report = matrix.apply_snapshot(MatrixSnapshot(principals, snapshot.objects, rows))
        assert [c.user_login for c in report.kept] == ["bob"]
        assert [c.user_login for c in report.dropped_missing] == ["CORP\\team"]
        assert [c.user_login for c in report.already_applied] == ["alice"]
        assert matrix.get_staged_change_count() == 1

    def test_reload_event(self, matrix):
        events = []
        matrix.subscribe(events.append)
        matrix.apply_snapshot(small_snapshot())
        assert events[-1].reason == "reload"
        assert events[-1].rows is None


def staged_matrix_with_conn(conn: FakeConnection) -> PermissionMatrix:
    m = PermissionMatrix(conn, schema="dbo")
    m.apply_snapshot(small_snapshot())
    _alice, bob, _team, orders, customers, _usp = ids(m)
    m.stage([CellRef(bob, orders, SELECT), CellRef(bob, customers, INSERT)], GRANT)
    return m


class TestCommit:
    def test_prepare_commit_orders_changes(self, matrix):
        alice, bob, _team, orders, customers, _usp = ids(matrix)
        matrix.stage([CellRef(bob, customers, SELECT)], DENY)
        matrix.stage([CellRef(alice, orders, UPDATE)], GRANT)
        plan = matrix.prepare_commit()
        assert [(c.user_login, c.object_name) for c in plan.changes] == [("alice", "Orders"), ("bob", "Customers")]
        assert plan.cells[0] == CellRef(alice, orders, UPDATE)

    def test_all_succeed(self):
        conn = FakeConnection()
        m = staged_matrix_with_conn(conn)
        plan = m.prepare_commit()
        outcome = PermissionMatrix.execute_commit(conn, plan, "CORP\\admin")
        assert outcome.rolled_back is False
        assert outcome.audit_written == 2
        assert conn.commits == 1
        assert len(conn.statements("GRANT")) == 2
        assert len(conn.statements("INSERT INTO")) == 2
        m.apply_commit_results(plan, outcome)
        assert m.get_staged_change_count() == 0
        _alice, bob, _team, orders, _customers, _usp = ids(m)
        assert m.index.cell(bob, orders, SELECT).committed == GRANT

    def test_partial_failure_keeps_failed_staged(self):
        conn = FakeConnection()
        conn.fail_on = lambda sql: sql.startswith("GRANT INSERT")
        m = staged_matrix_with_conn(conn)
        plan = m.prepare_commit()
        outcome = PermissionMatrix.execute_commit(conn, plan, "CORP\\admin")
        assert outcome.rolled_back is False
        errors = [e for _c, e in outcome.results if e]
        assert len(errors) == 1
        assert outcome.audit_written == 1
        m.apply_commit_results(plan, outcome)
        remaining = m.get_staged_changes()
        assert [(c.object_name, c.permission_type) for c in remaining] == [("Customers", PermissionType.INSERT)]

    def test_audit_failure_rolls_back_everything(self):
        conn = FakeConnection()
        conn.fail_on = lambda sql: sql.strip().startswith("INSERT INTO")
        m = staged_matrix_with_conn(conn)
        plan = m.prepare_commit()
        outcome = PermissionMatrix.execute_commit(conn, plan, "CORP\\admin")
        assert outcome.rolled_back is True
        assert conn.rollbacks == 1 and conn.commits == 0
        assert "audit log" in outcome.error
        assert all(error for _c, error in outcome.results)
        m.apply_commit_results(plan, outcome)
        assert m.get_staged_change_count() == 2

    def test_whole_batch_error_rolls_back(self, monkeypatch):
        conn = FakeConnection()
        m = staged_matrix_with_conn(conn)

        def broken(_conn, _changes):
            raise pyodbc.Error("08S01", "Communication link failure")

        monkeypatch.setattr(matrix_module.db_permissions, "apply_permission_changes", broken)
        outcome = PermissionMatrix.execute_commit(conn, m.prepare_commit(), "CORP\\admin")
        assert outcome.rolled_back is True
        assert "Communication link failure" in outcome.error

    def test_empty_plan(self, matrix):
        outcome = PermissionMatrix.execute_commit(FakeConnection(), matrix.prepare_commit(), "x")
        assert outcome.results == () and not outcome.rolled_back

    def test_apply_results_after_reload_uses_names(self):
        conn = FakeConnection()
        m = staged_matrix_with_conn(conn)
        plan = m.prepare_commit()
        outcome = PermissionMatrix.execute_commit(conn, plan, "CORP\\admin")
        m.apply_snapshot(small_snapshot())  # reload while the commit was running
        m.apply_commit_results(plan, outcome)
        assert m.get_staged_change_count() == 0

    def test_apply_results_rolled_back_changes_nothing(self, matrix):
        _alice, bob, _team, orders, _customers, _usp = ids(matrix)
        matrix.stage([CellRef(bob, orders, SELECT)], GRANT)
        plan = matrix.prepare_commit()
        matrix.apply_commit_results(plan, CommitOutcome(tuple((c, "x") for c in plan.changes), 0, True, "x"))
        assert matrix.get_staged_change_count() == 1
        assert matrix.can_undo()


class TestLegacyApi:
    def test_load_and_refresh_with_connection(self):
        conn = FakeConnection()
        conn.principals = [(5, "alice", "S"), (6, "bob", "U")]
        conn.objects = [(100, "dbo", "Orders", "U")]
        conn.permissions = [(5, 100, "SELECT", "G")]
        m = PermissionMatrix(conn)
        m.load()
        assert [u.login_name for u in m.users] == ["alice", "bob"]
        assert m.current_user == "CORP\\admin"
        assert m.stage_change("bob", "dbo", "Orders", PermissionType.SELECT, GRANT) is None
        m.refresh()
        assert m.get_staged_change_count() == 1
        m.load()
        assert m.get_staged_change_count() == 0

    def test_stage_change_and_toggle_errors(self, matrix):
        assert "Unknown" in matrix.stage_change("nobody", "dbo", "Orders", PermissionType.SELECT, GRANT)
        assert "does not apply" in matrix.stage_change("alice", "dbo", "usp_Close", PermissionType.SELECT, GRANT)
        assert "Unknown" in matrix.toggle_cell("nobody", "dbo", "Orders", PermissionType.SELECT)
        assert matrix.toggle_cell("bob", "dbo", "Orders", PermissionType.SELECT) is None
        assert matrix.get_assignment("bob", "dbo", "Orders", PermissionType.SELECT).effective_state == GRANT

    def test_stage_change_without_undo(self, matrix):
        matrix.stage_change("bob", "dbo", "Orders", PermissionType.SELECT, GRANT, add_to_undo=False)
        assert matrix.has_staged_changes()
        assert not matrix.can_undo()

    def test_get_assignment(self, matrix):
        matrix.stage_change("alice", "dbo", "Orders", PermissionType.SELECT, DENY)
        a = matrix.get_assignment("alice", "dbo", "Orders", PermissionType.SELECT)
        assert (a.committed_state, a.staged_state, a.has_pending_change) == (GRANT, DENY, True)
        unknown = matrix.get_assignment("nobody", "dbo", "Orders", PermissionType.SELECT)
        assert unknown.effective_state == NONE

    def test_assignments_property(self, matrix):
        matrix.stage_change("bob", "dbo", "Orders", PermissionType.SELECT, GRANT)
        assignments = matrix.assignments
        assert len(assignments) == 5
        staged = assignments[("bob", "dbo", "Orders", PermissionType.SELECT)]
        assert staged.committed_state == NONE and staged.staged_state == GRANT
        committed = assignments[("alice", "dbo", "Orders", PermissionType.SELECT)]
        assert committed.staged_state is None

    def test_legacy_commit(self):
        conn = FakeConnection()
        m = staged_matrix_with_conn(conn)
        m.current_user = None  # falls back to SYSTEM_USER
        results = m.commit()
        assert len(results) == 2 and all(e is None for _c, e in results)
        assert m.commit() == []

    def test_legacy_commit_raises_on_whole_batch_failure(self):
        conn = FakeConnection()
        conn.fail_on = lambda sql: sql.strip().startswith("INSERT INTO")
        m = staged_matrix_with_conn(conn)
        with pytest.raises(RuntimeError):
            m.commit()
        assert m.get_staged_change_count() == 2

    def test_undo_return_is_truthy(self, matrix):
        matrix.stage_change("bob", "dbo", "Orders", PermissionType.SELECT, GRANT)
        assert matrix.undo()
        assert matrix.redo()
        matrix.cancel()
        assert not matrix.undo()
        assert not matrix.redo()

    def test_filtered_users_with_tag(self):
        """Regression (P4): tag filters never matched because tags were never applied."""
        store = TagStore()
        store.add_user_tag("bob", "finance")
        store.add_object_tag("sales.Customers", "pii")
        m = PermissionMatrix(None, tag_store=store)
        m.apply_snapshot(small_snapshot())
        m.set_filter("user_tag", "Finance")
        assert [u.login_name for u in m.get_filtered_users()] == ["bob"]
        m.set_filter("object_tag", "pii")
        assert [o.full_name for o in m.get_filtered_objects()] == ["sales.Customers"]
        m.clear_all_filters()
        m.set_sort("user_name", ascending=False)
        assert [u.login_name for u in m.get_filtered_users()][0] == "CORP\\team"
        m.set_search_term("cust")
        assert [o.full_name for o in m.get_filtered_objects()] == ["sales.Customers"]

    def test_set_tag_store_updates_tags(self, matrix):
        events = []
        matrix.subscribe(events.append)
        store = TagStore()
        store.add_user_tag("alice", "audit")
        matrix.set_tag_store(store)
        matrix.set_filter("user_tag", "audit")
        assert [u.login_name for u in matrix.get_filtered_users()] == ["alice"]
        assert events[-1].reason == "tags"

    def test_performance_info(self, matrix):
        assert matrix.get_performance_info().is_large is False


class TestPrivileges:
    def test_privileged_account_skips_checks(self):
        conn = FakeConnection()
        m = PermissionMatrix(conn)
        snapshot = small_snapshot()
        m.apply_snapshot(MatrixSnapshot(snapshot.principals, snapshot.objects, snapshot.permission_rows, privileged=True))
        assert m.validate_grant_privilege("dbo", "Orders", PermissionType.SELECT) is None
        assert m.known_grant_privilege(CellRef(0, 0, SELECT)) is True
        assert conn.executed == []

    def test_check_is_cached(self):
        conn = FakeConnection()
        conn.held = {("dbo", "Orders", "SELECT")}
        m = PermissionMatrix(conn)
        m.apply_snapshot(small_snapshot())
        orders = m.index.object_index("dbo", "Orders")
        assert m.known_grant_privilege(CellRef(0, orders, SELECT)) is None
        assert m.validate_grant_privilege("dbo", "Orders", PermissionType.SELECT) is None
        message = m.validate_grant_privilege("dbo", "Orders", PermissionType.INSERT)
        assert "You cannot grant INSERT on dbo.Orders" in message
        m.validate_grant_privilege("dbo", "Orders", PermissionType.SELECT)
        assert len(conn.executed) == 2  # cached after first check of each
        assert m.known_grant_privilege(CellRef(0, orders, SELECT)) is True
        assert m.known_grant_privilege(CellRef(1, orders, INSERT)) is False
