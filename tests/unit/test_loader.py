"""Unit tests for fetch_snapshot() and fetch_permission_rows()."""

import threading

import pytest

from src.db.permissions import fetch_permission_rows
from src.models.db_object import ObjectType
from src.models.permission import PERMISSION_INDEX, STATE_DENY, STATE_GRANT, PermissionType
from src.services.loader import LoadCancelledError, fetch_snapshot
from tests.unit.fake_db import FakeConnection


def make_connection(permission_rows: int = 3) -> FakeConnection:
    conn = FakeConnection()
    conn.principals = [(5, "alice", "S "), (6, "bob", "U ")]
    conn.objects = [(100, "dbo", "Orders", "U "), (101, "dbo", "usp_Close", "P ")]
    base = [(5, 100, "SELECT", "G"), (6, 100, "INSERT", "W"), (6, 101, "EXECUTE", "D")]
    conn.permissions = (base * ((permission_rows // 3) + 1))[:permission_rows]
    conn.flags = (0, 1, 0)
    return conn


def test_snapshot_contents():
    snapshot = fetch_snapshot(make_connection())
    assert [u.login_name for u in snapshot.principals] == ["alice", "bob"]
    assert [u.principal_id for u in snapshot.principals] == [5, 6]
    assert snapshot.principals[0].principal_type == "S"
    assert [o.object_id for o in snapshot.objects] == [100, 101]
    assert snapshot.objects[1].object_type == ObjectType.PROCEDURE
    assert snapshot.current_user == "CORP\\admin"
    assert snapshot.privileged is True
    assert set(snapshot.timings) == {"principals", "objects", "permissions", "privileges"}


def test_state_mapping_grant_option_is_grant():
    snapshot = fetch_snapshot(make_connection())
    assert snapshot.permission_rows == (
        (5, 100, PERMISSION_INDEX[PermissionType.SELECT], STATE_GRANT),
        (6, 100, PERMISSION_INDEX[PermissionType.INSERT], STATE_GRANT),
        (6, 101, PERMISSION_INDEX[PermissionType.EXECUTE], STATE_DENY),
    )


def test_unknown_permission_names_are_skipped():
    conn = make_connection()
    conn.permissions.append((5, 100, "CONTROL", "G"))
    assert len(fetch_snapshot(conn).permission_rows) == 3


def test_progress_reports_each_stage_and_batches():
    reports = []
    fetch_snapshot(make_connection(permission_rows=25_000), progress=reports.append)
    stages = [r.stage for r in reports]
    assert stages[0] == "principals"
    assert stages.index("objects") < stages.index("permissions") < stages.index("privileges")
    permission_reports = [r for r in reports if r.stage == "permissions" and r.rows]
    assert [r.rows for r in permission_reports] == [10_000, 20_000]
    assert "20,000 rows" in permission_reports[-1].message
    assert all(r.stage_count == 4 for r in reports)


def test_fetch_permission_rows_uses_fetchmany_batches():
    batches = []
    fetch_permission_rows(make_connection(permission_rows=25), batch_size=10, on_batch=batches.append)
    assert batches == [10, 20, 25]


def test_cancel_before_start():
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(LoadCancelledError):
        fetch_snapshot(make_connection(), cancel=cancel)


def test_cancel_between_permission_batches():
    cancel = threading.Event()

    def on_batch(total):
        cancel.set()

    with pytest.raises(LoadCancelledError):
        fetch_permission_rows(make_connection(permission_rows=30), batch_size=10, on_batch=on_batch, cancel=cancel)
