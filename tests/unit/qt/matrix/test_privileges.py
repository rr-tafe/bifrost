"""FR-017a at staging time: Session.check_then_stage and the denial message."""

import pytest

from src.models.permission import PermissionState
from src.qt.dialogs import messages
from src.qt.session import Session, SessionState
from src.qt.views.matrix.matrix_view import MatrixView
from tests.unit.qt.matrix.conftest import INSERT, SELECT, cell, state_name

GRANT = PermissionState.GRANT


@pytest.fixture
def limited(qtbot, env):
    """A session whose admin isn't privileged and holds only INSERT on dbo.Orders."""
    env.conn.flags = (0, 0, 0)
    env.conn.held = {("dbo", "Orders", "INSERT")}
    s = Session()
    s.start()
    qtbot.waitUntil(lambda: s.state is SessionState.READY, timeout=5000)
    yield s
    s.worker.shutdown(2000)


def checks(env):
    return [sql for sql, _ in env.conn.executed if "HAS_PERMS_BY_NAME(QUOTENAME" in sql]


def test_privileged_skips_the_check(session, env):
    session.check_then_stage([(cell(session, "bob", "dbo", "Orders", INSERT), GRANT)])
    assert session.staged_count == 1
    assert checks(env) == []


def test_unknown_cells_checked_in_one_query(qtbot, limited, env):
    allowed = cell(limited, "bob", "dbo", "Orders", INSERT)
    denied = cell(limited, "bob", "sales", "Customers", INSERT)
    reported = []
    limited.stagingDenied.connect(reported.append)
    busy = []
    limited.stagingBusyChanged.connect(busy.append)
    limited.check_then_stage([(allowed, GRANT), (denied, GRANT)], label="Grant INSERT")
    assert limited.staging_busy and not limited.can_edit  # edits ignored while checking
    qtbot.waitUntil(lambda: not limited.staging_busy, timeout=2000)
    assert busy == [True, False]
    assert len(checks(env)) == 1
    assert state_name(limited, allowed) == "GRANT"
    assert state_name(limited, denied) == "NONE"
    assert [(c.object_name, c.permission_type.value) for c in reported[0]] == [("Customers", "INSERT")]
    limited.undo()
    assert limited.staged_count == 0  # allowed cells were one undo step


def test_cached_answers_need_no_query(qtbot, limited, env):
    c = cell(limited, "bob", "dbo", "Orders", INSERT)
    limited.check_then_stage([(c, GRANT)])
    qtbot.waitUntil(lambda: limited.staged_count == 1, timeout=2000)
    limited.undo()
    other = cell(limited, "CORP\\team", "dbo", "Orders", INSERT)  # same object and permission
    limited.check_then_stage([(other, GRANT)])
    assert limited.staged_count == 1  # staged immediately from the cache
    assert len(checks(env)) == 1


def test_cells_already_granted_and_non_grants_skip_the_check(limited, env):
    already = cell(limited, "alice", "dbo", "Orders", SELECT)  # committed GRANT
    deny = cell(limited, "bob", "sales", "Customers", SELECT)
    limited.check_then_stage([(already, GRANT), (deny, PermissionState.DENY)])
    assert checks(env) == []
    assert limited.staged_count == 1


def test_view_reports_denied_grants(qtbot, limited, settings, monkeypatch):
    errors = []
    monkeypatch.setattr(messages, "show_error", lambda parent, title, text, details="": errors.append((title, text)))
    view = MatrixView(limited, settings)
    qtbot.addWidget(view)
    view.editor.set_state([cell(limited, "bob", "sales", "Customers", INSERT)], GRANT)
    qtbot.waitUntil(lambda: bool(errors), timeout=2000)
    title, text = errors[0]
    assert title == "Some grants weren't staged"
    assert "You can't grant INSERT on sales.Customers" in text
    assert limited.staged_count == 0
