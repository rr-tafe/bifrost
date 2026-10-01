"""Unit tests for audit query/filter behavior and app fetch mapping."""

from datetime import datetime
from types import SimpleNamespace

import pytest

import src.db.audit as audit_module
import src.ui.app as app_module


class FakeCursor:
    """Test cursor capturing the last query and parameters."""

    def __init__(self):
        self.last_query = ""
        self.last_params = []

    def execute(self, query, params=None):
        self.last_query = query
        self.last_params = list(params or [])

    def fetchall(self):
        return []

    def close(self):
        return None


class FakeConnection:
    """Test connection returning the same fake cursor."""

    def __init__(self):
        self._cursor = FakeCursor()

    def cursor(self):
        return self._cursor


def test_fetch_audit_entries_user_contains_and_action_filter():
    """User contains + action filters should be reflected in SQL and parameters."""
    conn = FakeConnection()

    entries = audit_module.fetch_audit_entries(
        conn,
        schema="dbo",
        affected_user_contains="Ali",
        action="grant",
    )

    assert entries == []
    assert "UPPER(affected_user) LIKE ?" in conn._cursor.last_query
    assert "action = ?" in conn._cursor.last_query
    assert "%ALI%" in conn._cursor.last_params
    assert "GRANT" in conn._cursor.last_params


def test_fetch_audit_entries_object_search_schema_and_object():
    """schema.object search should split and filter both columns."""
    conn = FakeConnection()

    audit_module.fetch_audit_entries(
        conn,
        schema="dbo",
        object_search="dbo.Orders",
    )

    assert "UPPER(schema_name) LIKE ?" in conn._cursor.last_query
    assert "UPPER(object_name) LIKE ?" in conn._cursor.last_query
    assert "%DBO%" in conn._cursor.last_params
    assert "%ORDERS%" in conn._cursor.last_params


def test_fetch_audit_entries_object_search_object_only():
    """Object-only search should match object_name and schema.object text."""
    conn = FakeConnection()

    audit_module.fetch_audit_entries(
        conn,
        schema="dbo",
        object_search="order",
    )

    assert "UPPER(object_name) LIKE ? OR UPPER(schema_name + '.' + object_name) LIKE ?" in conn._cursor.last_query
    # The object-only search adds the same LIKE pattern twice.
    assert conn._cursor.last_params.count("%ORDER%") == 2


def test_fetch_audit_entries_validates_limit_and_action():
    """Invalid action and non-positive limit should raise clear errors."""
    conn = FakeConnection()

    with pytest.raises(ValueError, match="Invalid action filter"):
        audit_module.fetch_audit_entries(conn, action="DROP")

    with pytest.raises(ValueError, match="limit must be greater than zero"):
        audit_module.fetch_audit_entries(conn, limit=0)


def test_app_fetch_audit_entries_maps_filter_keys(monkeypatch):
    """App-level fetch wrapper should map UI filter keys to DB query arguments."""
    captured = {}

    def fake_fetch(_conn, _schema, **kwargs):
        captured.update(kwargs)
        return ["ok"]

    monkeypatch.setattr(audit_module, "fetch_audit_entries", fake_fetch)

    app = object.__new__(app_module.BifrostApp)
    app.connection = object()
    app.config = SimpleNamespace(schema="dbo")

    start = datetime(2026, 9, 1, 0, 0, 0)
    end = datetime(2026, 9, 2, 23, 59, 59)

    result = app_module.BifrostApp._fetch_audit_entries(
        app,
        {
            "user": "ali",
            "object": "dbo.orders",
            "action": "GRANT",
            "from_date": start,
            "to_date": end,
            "limit": 500,
        },
    )

    assert result == ["ok"]
    assert captured["start_date"] == start
    assert captured["end_date"] == end
    assert captured["affected_user_contains"] == "ali"
    assert captured["object_search"] == "dbo.orders"
    assert captured["action"] == "GRANT"
    assert captured["limit"] == 500


def test_app_fetch_audit_entries_surfaces_errors(monkeypatch):
    """App-level fetch wrapper should surface DB failures to the caller."""

    def fake_fetch(_conn, _schema, **_kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(audit_module, "fetch_audit_entries", fake_fetch)

    app = object.__new__(app_module.BifrostApp)
    app.connection = object()
    app.config = SimpleNamespace(schema="dbo")

    with pytest.raises(RuntimeError, match="boom"):
        app_module.BifrostApp._fetch_audit_entries(app, {})