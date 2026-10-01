"""
Fixtures for the matrix view tests.

Seeded data (from tests/unit/qt/conftest.py):
    principals: alice (SQL user), bob (Windows user), CORP\\team (Windows group)
    objects:    dbo.Orders (table), sales.Customers (table), dbo.usp_Close (procedure)
    explicit:   alice SELECT GRANT on dbo.Orders; bob SELECT GRANT on sales.Customers;
                CORP\\team EXECUTE DENY on dbo.usp_Close
"""

from __future__ import annotations

import dataclasses

import pytest
from PySide6.QtCore import QSettings

from src.models.permission import PermissionType
from src.qt.session import Session, SessionState
from src.qt.views.matrix.matrix_view import MatrixView
from src.services.matrix import CellRef
from src.services.matrix_index import PERM_INDEX
from tests.perf.synthetic import make_snapshot

SELECT = PERM_INDEX[PermissionType.SELECT]
INSERT = PERM_INDEX[PermissionType.INSERT]
EXECUTE = PERM_INDEX[PermissionType.EXECUTE]
DELETE = PERM_INDEX[PermissionType.DELETE]


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "view.ini"), QSettings.Format.IniFormat)


class Confirmations:
    """Stands in for ConfirmBulkDialog: records each request and answers with `answer`."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.answer = (True, False)

    def __call__(self, sentence, summary):
        self.calls.append((sentence, summary))
        return self.answer


@pytest.fixture
def confirmations() -> Confirmations:
    return Confirmations()


@pytest.fixture
def view(qtbot, session, settings, confirmations) -> MatrixView:
    v = MatrixView(session, settings)
    qtbot.addWidget(v)
    v.resize(1200, 700)
    v.show()
    v.editor.confirm = confirmations
    return v


def cell(session: Session, login: str, schema: str, name: str, perm: int) -> CellRef:
    ix = session.matrix.index
    return CellRef(ix.principal_index(login), ix.object_index(schema, name), perm)


def state_name(session: Session, c: CellRef) -> str:
    return session.matrix.index.cell(c.p, c.o, c.perm).effective.value


@pytest.fixture
def big_session(qtbot) -> Session:
    """No database: 40 principals, 2,000 objects, privileged (no grant checks needed)."""
    s = Session()
    snapshot = dataclasses.replace(make_snapshot(40, 2000, 3000), privileged=True)
    s.apply_snapshot(snapshot)
    assert s.state is SessionState.READY
    yield s
    s.worker.shutdown(1000)


@pytest.fixture
def big_view(qtbot, big_session, settings, confirmations) -> MatrixView:
    v = MatrixView(big_session, settings)
    qtbot.addWidget(v)
    v.resize(1200, 700)
    v.show()
    v.editor.confirm = confirmations
    return v
