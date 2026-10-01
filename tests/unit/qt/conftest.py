"""
Fixtures for Qt tests.

`env` patches the database and file layers so a Session runs against a
FakeConnection and never touches the real config.json or tags.json.
"""

from __future__ import annotations

import gc
from dataclasses import dataclass, field

import pytest

from src.models.config import Configuration
from src.qt import session as session_module
from src.qt.session import Session, SessionState
from src.services.tags import TagStore
from tests.unit.fake_db import FakeConnection


@pytest.fixture(autouse=True)
def collect_on_ui_thread():
    """
    Mirror the app's UiThreadGarbageCollector: no automatic GC while a test runs
    (it could collect a QObject on a worker thread), then collect on this thread.
    """
    gc.disable()
    yield
    gc.collect()
    gc.enable()


CONFIG = Configuration(server="sql01", port=1433, database="FinanceDW", schema="dbo")


def seeded_connection() -> FakeConnection:
    """alice, bob, CORP\\team; dbo.Orders, sales.Customers (tables), dbo.usp_Close (procedure)."""
    conn = FakeConnection()
    conn.principals = [(5, "alice", "S"), (6, "bob", "U"), (7, "CORP\\team", "G")]
    conn.objects = [
        (100, "dbo", "Orders", "U"),
        (101, "sales", "Customers", "U"),
        (102, "dbo", "usp_Close", "P"),
    ]
    conn.permissions = [(5, 100, "SELECT", "G"), (6, 101, "SELECT", "G"), (7, 102, "EXECUTE", "D")]
    conn.flags = (0, 1, 0)  # db_owner: privilege checks skipped
    return conn


@dataclass
class Env:
    """Handles for a patched environment."""

    conn: FakeConnection
    config: Configuration | None = field(default_factory=lambda: CONFIG)
    config_error: str | None = None
    connect_error: Exception | None = None
    connects: int = 0
    tag_saves: int = 0
    saved_configs: list[Configuration] = field(default_factory=list)


@pytest.fixture
def env(monkeypatch) -> Env:
    state = Env(conn=seeded_connection())

    def create_connection(config):
        state.connects += 1
        if state.connect_error is not None:
            raise state.connect_error
        return state.conn

    def load_config():
        if state.config_error:
            return Configuration.default(), state.config_error
        return state.config, None

    def save_config(config):
        state.saved_configs.append(config)
        return None

    def save_tags(self, path=None):
        state.tag_saves += 1
        return None

    monkeypatch.setattr(session_module.db_connection, "create_connection", create_connection)
    monkeypatch.setattr(session_module.db_audit, "ensure_audit_log_table", lambda conn, schema: None)
    monkeypatch.setattr(session_module.config_service, "load_config", load_config)
    monkeypatch.setattr(session_module.config_service, "save_config", save_config)
    monkeypatch.setattr(TagStore, "load", classmethod(lambda cls, path=None: cls()))
    monkeypatch.setattr(TagStore, "save", save_tags)
    return state


@pytest.fixture
def session(qtbot, env) -> Session:
    """A Session that has started and loaded the seeded data."""
    s = Session()
    s.start()
    qtbot.waitUntil(lambda: s.state is SessionState.READY, timeout=5000)
    yield s
    s.worker.shutdown(2000)


def stage(session: Session, count: int) -> None:
    """Stage `count` GRANTs that are all new (on applicable cells with no permission)."""
    from src.services.matrix import CellRef
    from src.services.matrix_index import PERMS

    index = session.matrix.index
    cells = []
    for p in range(len(index.principals)):
        for o in range(len(index.objects)):
            for perm in range(len(PERMS)):
                if index.is_applicable(o, perm) and index.cell(p, o, perm).effective.value == "NONE":
                    cells.append(CellRef(p, o, perm))
    from src.models.permission import PermissionState

    session.matrix.stage(cells[:count], PermissionState.GRANT)
