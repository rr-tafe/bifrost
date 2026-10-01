"""FR-023 object descriptions: the level1type fix, Session load/save and the header."""

import pytest

from src.db import objects as db_objects
from src.models.db_object import ObjectType
from src.qt import session as session_module
from tests.unit.fake_db import FakeConnection


@pytest.mark.parametrize("object_type", list(ObjectType))
def test_add_uses_the_objects_level1type(object_type):
    conn = FakeConnection()
    db_objects.save_object_description(conn, "dbo", "Thing", "Text", object_type)
    sql, params = conn.executed[-1]
    assert "sp_addextendedproperty" in sql and "@level1type = ?" in sql
    assert params == ("Text", "dbo", object_type.value, "Thing")


@pytest.mark.parametrize("object_type", [ObjectType.VIEW, ObjectType.PROCEDURE])
def test_update_and_drop_use_the_objects_level1type(monkeypatch, object_type):
    conn = FakeConnection()
    monkeypatch.setattr(db_objects, "load_object_description", lambda *_args: "old")
    db_objects.save_object_description(conn, "dbo", "Thing", "New", object_type)
    assert conn.executed[-1][1] == ("New", "dbo", object_type.value, "Thing")
    db_objects.save_object_description(conn, "dbo", "Thing", None, object_type)
    sql, params = conn.executed[-1]
    assert "sp_dropextendedproperty" in sql and params == ("dbo", object_type.value, "Thing")


def test_default_type_is_table():
    conn = FakeConnection()
    db_objects.save_object_description(conn, "dbo", "Orders", "Text")
    assert conn.executed[-1][1][2] == "TABLE"


class TestSession:
    def test_load_is_cached(self, qtbot, session, monkeypatch):
        calls = []

        def load(conn, schema, name):
            calls.append((schema, name))
            return "Customer orders"

        monkeypatch.setattr(session_module.db_objects, "load_object_description", load)
        o = session.matrix.index.object_index("dbo", "Orders")
        results = []
        session.load_description(o, lambda text, error: results.append((text, error)))
        qtbot.waitUntil(lambda: bool(results), timeout=2000)
        session.load_description(o, lambda text, error: results.append((text, error)))
        assert results == [("Customer orders", None), ("Customer orders", None)]
        assert calls == [("dbo", "Orders")]
        assert session.cached_description(o) == (True, "Customer orders")

    def test_save_passes_object_type_and_commits(self, qtbot, session, env):
        o = session.matrix.index.object_index("dbo", "usp_Close")
        errors = []
        commits = env.conn.commits
        session.save_description(o, "Closes the month", errors.append)
        qtbot.waitUntil(lambda: bool(errors), timeout=2000)
        assert errors == [None]
        assert env.conn.commits == commits + 1
        sql, params = env.conn.executed[-1]
        assert params == ("Closes the month", "dbo", "PROCEDURE", "usp_Close")
        assert session.cached_description(o) == (True, "Closes the month")

    def test_save_rejects_too_long(self, session):
        errors = []
        session.save_description(0, "x" * 7_501, errors.append)
        assert errors and "7500" in errors[0].replace(",", "")

    def test_save_needs_connection(self, session):
        session.disconnect()
        errors = []
        session.save_description(0, "text", errors.append)
        assert errors[0].startswith("Not connected")


def test_header_shows_description(qtbot, view, session, monkeypatch):
    monkeypatch.setattr(session_module.db_objects, "load_object_description", lambda *_a: "Line one\nLine two")
    view.set_mode("object", follow=False)
    pane = view.panes["object"]
    pane.left.select_entity(session.matrix.index.object_index("sales", "Customers"))
    qtbot.waitUntil(lambda: pane.header.description.text() == "Line one\nLine two", timeout=2000)
    assert pane.header.description_box.isVisibleTo(view)
    assert view.panes["principal"].header.description_box.isHidden()
