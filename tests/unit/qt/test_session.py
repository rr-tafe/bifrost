"""Tests for Session flows against a FakeConnection."""

import pyodbc
import pytest

from src.db.connection import DatabaseConnectionError, is_connection_error
from src.qt import session as session_module
from src.qt.session import CommitReport, Session, SessionState
from src.services.loader import LoadCancelledError
from src.services.matrix import CommitOutcome, PermissionMatrix
from tests.unit.qt.conftest import stage


def wait_ready(qtbot, s: Session) -> None:
    qtbot.waitUntil(lambda: s.state is SessionState.READY and s.worker.is_idle(), timeout=5000)


class TestStartup:
    def test_missing_config_asks_for_settings(self, qtbot, env):
        env.config_error = "Configuration file not found"
        s = Session()
        with qtbot.waitSignal(s.settingsRequested, timeout=2000) as blocker:
            s.start()
        assert blocker.args == ["Configuration file not found"]
        assert s.state is SessionState.NEEDS_SETTINGS
        assert env.connects == 0

    def test_valid_config_loads(self, qtbot, env):
        s = Session()
        loaded = []
        s.dataLoaded.connect(loaded.append)
        s.start()
        wait_ready(qtbot, s)
        summary = loaded[0]
        assert (summary.principals, summary.objects, summary.grants, summary.denies) == (3, 3, 2, 1)
        assert summary.principals_by_type == {"S": 1, "U": 1, "G": 1}
        assert s.current_user == "CORP\\admin"
        assert s.connected and s.can_edit and not s.busy

    def test_login_failure_fails_and_asks_for_settings(self, qtbot, env):
        env.connect_error = DatabaseConnectionError("Authentication failed. Ensure your Windows account…")
        s = Session()
        with qtbot.waitSignal(s.settingsRequested, timeout=2000):
            s.start()
        assert s.state is SessionState.FAILED
        assert "Authentication failed" in s.last_error

    def test_other_connect_failure_does_not_open_settings(self, qtbot, env):
        env.connect_error = DatabaseConnectionError("Connection timeout")
        s = Session()
        requested = []
        s.settingsRequested.connect(requested.append)
        s.start()
        qtbot.waitUntil(lambda: s.state is SessionState.FAILED, timeout=2000)
        assert requested == []


class TestLoad:
    def test_cancelled_first_load_fails(self, qtbot, env, monkeypatch):
        def cancelled(conn, progress=None, cancel=None):
            raise LoadCancelledError("cancelled")

        monkeypatch.setattr(session_module.loader, "fetch_snapshot", cancelled)
        s = Session()
        s.start()
        qtbot.waitUntil(lambda: s.state is SessionState.FAILED, timeout=2000)
        assert s.last_error == "Loading was cancelled"

    def test_cancelled_refresh_keeps_data(self, qtbot, session, monkeypatch):
        def cancelled(conn, progress=None, cancel=None):
            raise LoadCancelledError("cancelled")

        monkeypatch.setattr(session_module.loader, "fetch_snapshot", cancelled)
        session.refresh()
        wait_ready(qtbot, session)
        assert session.matrix is not None and len(session.matrix.users) == 3

    def test_progress_is_reported(self, qtbot, env):
        s = Session()
        stages = []
        s.loadProgress.connect(lambda p: stages.append(p.stage))
        s.start()
        wait_ready(qtbot, s)
        assert stages[:4] == ["principals", "objects", "permissions", "privileges"]

    def test_refresh_keeps_staged_and_reports_dropped(self, qtbot, session, env):
        stage(session, 3)
        reports = []
        session.restageReport.connect(reports.append)
        env.conn.principals = [p for p in env.conn.principals if p[1] != "alice"]
        session.refresh()
        wait_ready(qtbot, session)
        dropped = len(reports[0].dropped_missing) if reports else 0
        assert session.staged_count == 3 - dropped
        assert dropped > 0

    def test_refresh_when_busy_or_disconnected(self, qtbot, session):
        messages = []
        session.statusMessage.connect(lambda text, _ms: messages.append(text))
        session.disconnect()
        session.refresh()
        assert "Not connected" in messages[-1]
        assert session.state is SessionState.OFFLINE
        assert session.matrix is not None  # data kept


class TestCommit:
    def test_small_commit_goes_straight_through(self, qtbot, session, env):
        stage(session, 2)
        previews = []
        session.commitPreviewRequested.connect(previews.append)
        with qtbot.waitSignal(session.commitFinished, timeout=3000) as blocker:
            session.request_commit()
        report: CommitReport = blocker.args[0]
        assert report.all_succeeded and len(report.succeeded) == 2
        assert previews == []
        assert len(env.conn.statements("GRANT")) == 2
        assert session.staged_count == 0
        assert session.state is SessionState.READY

    def test_five_or_more_asks_for_preview(self, qtbot, session, env):
        stage(session, 5)
        with qtbot.waitSignal(session.commitPreviewRequested, timeout=1000) as blocker:
            session.request_commit()
        assert env.conn.statements("GRANT") == []
        with qtbot.waitSignal(session.commitFinished, timeout=3000):
            session.confirm_commit(blocker.args[0])
        assert len(env.conn.statements("GRANT")) == 5

    def test_review_preview_for_small_commit(self, qtbot, session):
        stage(session, 1)
        with qtbot.waitSignal(session.commitPreviewRequested, timeout=1000):
            session.request_commit(always_preview=True)

    def test_privilege_denial_unstages_only_failing_grants(self, qtbot, env):
        env.conn.flags = (0, 0, 0)
        s = Session()
        s.start()
        wait_ready(qtbot, s)
        stage(s, 3)
        plan = s.matrix.prepare_commit()
        allowed = plan.changes[0]
        env.conn.held = {(allowed.schema_name, allowed.object_name, allowed.permission_type.value)}
        with qtbot.waitSignal(s.privilegeDenied, timeout=3000) as blocker:
            s.request_commit()
        assert len(blocker.args[0]) == 2
        assert s.staged_count == 1
        assert env.conn.statements("GRANT") == []
        assert s.state is SessionState.READY
        # The allowed one now commits without another check
        with qtbot.waitSignal(s.commitFinished, timeout=3000):
            s.request_commit()
        assert len(env.conn.statements("GRANT")) == 1
        s.worker.shutdown(2000)

    def test_partial_failure_keeps_failed_staged(self, qtbot, session, env):
        stage(session, 2)
        first = session.matrix.prepare_commit().changes[0]
        target = f"GRANT {first.permission_type.value} ON [{first.schema_name}].[{first.object_name}]"
        env.conn.fail_on = lambda sql: sql.startswith(target)
        with qtbot.waitSignal(session.commitFinished, timeout=3000) as blocker:
            session.request_commit()
        report = blocker.args[0]
        assert len(report.failed) == 1 and len(report.succeeded) == 1
        assert session.staged_count == 1

    def test_rollback_keeps_everything_staged(self, qtbot, session, env):
        stage(session, 2)
        env.conn.fail_on = lambda sql: sql.strip().startswith("INSERT INTO")
        with qtbot.waitSignal(session.commitFinished, timeout=3000) as blocker:
            session.request_commit()
        assert blocker.args[0].rolled_back
        assert session.staged_count == 2
        assert session.state is SessionState.READY

    def test_connection_lost_during_commit(self, qtbot, session, monkeypatch):
        stage(session, 2)

        def lost(conn, plan, admin):
            return CommitOutcome(
                tuple((c, "lost") for c in plan.changes), 0, True, "Nothing was committed: [08S01] Communication link failure"
            )

        monkeypatch.setattr(PermissionMatrix, "execute_commit", staticmethod(lost))
        with qtbot.waitSignal(session.connectionLost, timeout=3000) as blocker:
            session.request_commit()
        assert blocker.args[1] == 2
        assert session.state is SessionState.OFFLINE
        assert not session.can_edit
        assert session.staged_count == 2

    def test_editing_disabled_while_committing(self, qtbot, session, monkeypatch):
        import threading

        gate = threading.Event()
        real = PermissionMatrix.execute_commit

        def slow(conn, plan, admin):
            gate.wait(2)
            return real(conn, plan, admin)

        monkeypatch.setattr(PermissionMatrix, "execute_commit", staticmethod(slow))
        stage(session, 1)
        session.request_commit()
        qtbot.waitUntil(lambda: session.state is SessionState.COMMITTING, timeout=2000)
        assert not session.can_edit and not session.can_commit and not session.can_undo
        session.discard_all()
        assert session.staged_count == 1  # can't discard mid-commit
        gate.set()
        wait_ready(qtbot, session)

    def test_nothing_to_commit(self, qtbot, session):
        messages = []
        session.statusMessage.connect(lambda text, _ms: messages.append(text))
        session.request_commit()
        assert messages == ["Nothing to commit"]


class TestEditing:
    def test_discard_confirmation_threshold(self, qtbot, session):
        stage(session, 5)
        with qtbot.waitSignal(session.discardConfirmationRequested, timeout=1000) as blocker:
            session.discard_all()
        assert blocker.args == [5]
        assert session.staged_count == 5
        session.discard_all(confirmed=True)
        assert session.staged_count == 0

    def test_small_discard_needs_no_confirmation(self, session):
        stage(session, 2)
        session.discard_all()
        assert session.staged_count == 0

    def test_undo_redo_announce(self, qtbot, session):
        stage(session, 2)
        announced = []
        session.announce.connect(announced.append)
        session.undo()
        assert session.staged_count == 0
        assert announced[-1].startswith("Undone: ")
        session.redo()
        assert session.staged_count == 2
        assert announced[-1].startswith("Redone: ")

    def test_signals_on_stage(self, qtbot, session):
        counts, undo_states = [], []
        session.stagedCountChanged.connect(counts.append)
        session.undoStateChanged.connect(lambda u, r: undo_states.append((u, r)))
        stage(session, 3)
        assert counts == [3]
        assert undo_states[-1] == (True, False)
        with qtbot.waitSignal(session.announce, timeout=2000) as blocker:
            pass
        assert blocker.args == ["3 changes staged"]

    def test_revert_change_and_reveal(self, qtbot, session):
        stage(session, 2)
        change = session.matrix.get_staged_changes()[0]
        with qtbot.waitSignal(session.revealRequested, timeout=1000):
            session.reveal(change)
        session.revert_change(change)
        assert session.staged_count == 1
        session.undo()
        assert session.staged_count == 2


class TestConnectionHealth:
    def test_heartbeat_skipped_while_busy(self, qtbot, session, monkeypatch):
        import threading

        gate = threading.Event()
        session.worker.submit("block", lambda _ctx: gate.wait(2))
        before = len(session.worker._queued)
        session._on_heartbeat()
        assert len(session.worker._queued) == before
        gate.set()

    def test_heartbeat_detects_loss_once(self, qtbot, session, env):
        env.conn.fail_on = lambda sql: sql == "SELECT 1"
        env.conn.fail_error = ("08S01", "[08S01] Communication link failure")
        lost = []
        session.connectionLost.connect(lambda error, staged: lost.append(error))
        session._on_heartbeat()
        qtbot.waitUntil(lambda: bool(lost), timeout=2000)
        session._connection_lost(RuntimeError("again"))
        assert len(lost) == 1
        assert session.state is SessionState.OFFLINE

    def test_reconnect_keeps_staged(self, qtbot, session, env):
        stage(session, 2)
        session._connection_lost(RuntimeError("gone"))
        session.reconnect()
        wait_ready(qtbot, session)
        assert session.staged_count == 2
        assert env.connects == 2


@pytest.mark.parametrize(
    "error,expected",
    [
        (pyodbc.Error("08S01", "[08S01] Communication link failure"), True),
        (pyodbc.Error("08001", "cannot open"), True),
        (pyodbc.Error("HYT00", "timeout"), True),
        (pyodbc.Error("42000", "[42000] TCP Provider: An existing connection was forcibly closed"), True),
        (pyodbc.Error("42000", "[42000] Cannot find the user 'x'"), False),
        (ValueError("08S01"), False),
    ],
)
def test_is_connection_error(error, expected):
    assert is_connection_error(error) is expected


class TestSettingsAuditExportTags:
    def test_save_settings_validates_and_connects(self, qtbot, env):
        from src.models.config import Configuration

        s = Session()
        assert "server" in s.save_settings(Configuration(server="", database="x"))
        assert env.saved_configs == []
        assert s.save_settings(Configuration(server="sql02", database="Other")) is None
        wait_ready(qtbot, s)
        assert env.saved_configs[0].server == "sql02"
        s.worker.shutdown(2000)

    def test_test_connection_callback(self, qtbot, env, monkeypatch):
        from src.models.config import Configuration

        monkeypatch.setattr(session_module.db_connection, "test_connection", lambda config: (True, "Connected to x/y"))
        s = Session()
        results = []
        s.test_connection(Configuration(server="x", database="y"), lambda ok, msg: results.append((ok, msg)))
        qtbot.waitUntil(lambda: bool(results), timeout=2000)
        assert results == [(True, "Connected to x/y")]

    def test_fetch_audit(self, qtbot, session, env):
        results = []
        session.fetch_audit({"action": "GRANT", "ignored": 1}, lambda r, e: results.append((r, e)))
        qtbot.waitUntil(lambda: bool(results), timeout=2000)
        result, error = results[0]
        assert error is None and result.entries == [] and not result.limited
        sql, params = env.conn.executed[-1]
        assert "action = ?" in sql and params == ["GRANT"]

    def test_fetch_audit_when_offline(self, session):
        session.disconnect()
        results = []
        session.fetch_audit({}, lambda r, e: results.append((r, e)))
        assert results == [(None, "Not connected")]

    def test_export_permissions(self, qtbot, session, tmp_path):
        stage(session, 1)
        done = []
        path = tmp_path / "perms.csv"
        assert session.estimate_export_rows(False) == 4
        session.export_permissions(str(path), False, done.append)
        qtbot.waitUntil(lambda: bool(done), timeout=3000)
        assert done == [None]
        assert len(path.read_text(encoding="utf-8").splitlines()) == 5

    def test_save_tags_updates_matrix(self, qtbot, session, env):
        session.tag_store.add_user_tag("bob", "finance")
        with qtbot.waitSignal(session.tagsChanged, timeout=1000):
            assert session.save_tags() is None
        assert env.tag_saves == 1
        bob = session.matrix.users[session.matrix.index.principal_index("bob")]
        assert bob.has_tag("finance")

    def test_close_saves_tags_and_stops(self, qtbot, session, env):
        assert session.close(2000) is None
        assert env.tag_saves == 1
        errors = []
        session.worker.submit("after-close", lambda _ctx: None, on_error=errors.append)
        qtbot.waitUntil(lambda: bool(errors), timeout=2000)  # worker refuses new jobs
